#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { ServerManager } from './server-manager.js';
import { OpenCodeClient } from './opencode-client.js';
import { SessionManager } from './session-manager.js';
import { PermissionBridge, ProjectWriteLock } from './permissions.js';
import { BrokerError, errorResult } from './errors.js';
import { redactSecrets } from './schemas.js';
import { projectKey } from './project-key.js';
import { ProjectFileLock } from './project-lock.js';
import { registerOrdinaryTools } from './ordinary-tools.js';

const serverManager = new ServerManager();
const permissions = new PermissionBridge();
const sessionManager = new SessionManager(new OpenCodeClient(serverManager), undefined, permissions);
const locks = new ProjectWriteLock();
const recoveries = new Map<string, Promise<void>>();
const projectFileLock = new ProjectFileLock();
serverManager.setBusyChecker(async root => {
  if (locks.isBusy(projectKey(root))) return true;
  return await sessionManager.hasActiveSessions(root);
});
const server = new McpServer({ name: 'codex-workflow-opencode-broker', version: '1.0.0' });

const rootInput = { root: z.string().min(1) };
const sessionInput = { ...rootInput, sessionId: z.string().min(1) };
const change = z.string().regex(/^[A-Za-z0-9_-]{1,256}$/);
const runKey = z.string().regex(/^ordinary:[A-Za-z0-9_.-]{1,256}$/);
const taskBatch = z.string().regex(/^(all|[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)$/);
const access = z.enum(['read-only', 'workspace-write']);

function reply(value: unknown) {
  const safe = redactSecrets(value);
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(safe) }],
    structuredContent: safe as Record<string, unknown>
  };
}

function fail(error: unknown) {
  const value = errorResult(error);
  return { ...reply(value), isError: true };
}

async function safeCall(fn: () => Promise<unknown>) {
  try { return reply(await fn()); } catch (error) { return fail(error); }
}

async function synchronizeWriter(runtime: Awaited<ReturnType<ServerManager['start']>>) {
  const previous = recoveries.get(runtime.projectKey) ?? Promise.resolve();
  const recovery = previous.then(async () => {
    const activeSessions = await sessionManager.recoverActive(runtime);
    if (activeSessions.length > 1) throw new BrokerError('PROJECT_WRITER_BUSY', 'Multiple active Sessions found for this project');
    const activeSession = activeSessions[0];
    if (activeSession) {
      locks.restore(runtime.projectKey, activeSession.sessionId, activeSession.access, activeSession.status);
    } else {
      const owner = locks.owner(runtime.projectKey);
      if (owner && !owner.sessionId.startsWith('pending-') && !await sessionManager.isActive(runtime, owner.sessionId)) {
        locks.clear(runtime.projectKey);
      }
    }
  });
  recoveries.set(runtime.projectKey, recovery);
  try { await recovery; } finally {
    if (recoveries.get(runtime.projectKey) === recovery) recoveries.delete(runtime.projectKey);
  }
}

async function startProject(root: string) {
  const runtime = await serverManager.start(root);
  await projectFileLock.withLock(root, () => synchronizeWriter(runtime));
  return runtime;
}

async function recoverProject(root: string) {
  const runtime = await serverManager.recover(root);
  if (runtime) await projectFileLock.withLock(root, () => synchronizeWriter(runtime));
  return runtime;
}

server.registerTool('opencode_project_probe', {
  description: 'Probe project root, OpenCode capability and owned Server state',
  inputSchema: rootInput
}, async ({ root }) => safeCall(async () => serverManager.probe(root)));

server.registerTool('opencode_project_start', {
  description: 'Start or recover the project OpenCode Server',
  inputSchema: rootInput
}, async ({ root }) => safeCall(async () => {
  const runtime = await startProject(root);
  return {
    ok: true,
    projectKey: runtime.projectKey,
    root: runtime.root,
    server: {
      status: 'ready',
      instanceId: runtime.instanceId,
      pid: runtime.pid,
      port: runtime.port,
      version: runtime.opencodeVersion,
      reused: false
    }
  };
}));

server.registerTool('opencode_session_create', {
  description: 'Create one AR-scoped OpenCode Session without sending work',
  inputSchema: {
    ...rootInput,
    change,
    agent: z.string().regex(/^[A-Za-z0-9_.-]{1,128}$/),
    access,
    title: z.string().optional()
  }
}, async ({ root, change, agent, access, title }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const existing = await sessionManager.binding(runtime, change);
    const owner = locks.owner(runtime.projectKey);
    const busy = Boolean(owner && ['ready', 'running', 'awaiting_permission', 'sending'].includes(owner.status));
    if (busy && owner!.sessionId !== existing?.sessionId) {
      throw new BrokerError('PROJECT_WRITER_BUSY', 'Another active Session is operating this project');
    }
    const result = await sessionManager.create(runtime, { change, agent, access, title });
    locks.restore(runtime.projectKey, result.sessionId, access, result.status);
    return { ok: true, projectKey: runtime.projectKey, ...result };
  });
}));

server.registerTool('opencode_session_send', {
  description: 'Asynchronously send a self-contained AR task',
  inputSchema: {
    ...sessionInput,
    change,
    taskBatch: z.string().regex(/^(all|[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)$/),
    prompt: z.string().min(1),
    expectedRevision: z.number().int().min(0)
  }
}, async ({ root, sessionId, change, taskBatch, prompt, expectedRevision }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const sessionAccess = await sessionManager.access(runtime, sessionId);
    let claimed = false;
    if (sessionAccess === 'workspace-write') {
      const owner = locks.owner(runtime.projectKey);
      if (!owner || owner.sessionId !== sessionId) {
        locks.acquire(runtime.projectKey, sessionId, sessionAccess, 'ready');
        claimed = true;
      }
    }
    try {
      const result = await sessionManager.send(runtime, sessionId, change, taskBatch, prompt, expectedRevision);
      locks.update(runtime.projectKey, sessionId, 'running');
      return result;
    } catch (error) {
      if (claimed) locks.release(runtime.projectKey, sessionId);
      throw error;
    }
  });
}));


registerOrdinaryTools(server as any, { startProject, synchronizeWriter, projectFileLock, sessionManager, locks });
server.registerTool('opencode_session_send_bound', {
  description: 'Asynchronously send an implementation or repair batch using the persisted AR Session binding; batchMode selects the deterministic Phase scope, both codespecSnapshotPath and workspaceSnapshotPath are persisted for recovery, and prompt is supplemental review context',
  inputSchema: {
    ...rootInput,
    change,
    phaseId: z.string().regex(/^(implicit|(?:Phase\s+)?[A-Za-z0-9_.-]+)$/i),
    prompt: z.string().min(1),
    batchMode: z.enum(['implementation', 'repair']).default('implementation'),
    codespecSnapshotPath: z.string().min(1),
    workspaceSnapshotPath: z.string().min(1),
    expectedRevision: z.number().int().min(0)
  }
}, async ({ root, change, phaseId, prompt, batchMode, codespecSnapshotPath, workspaceSnapshotPath, expectedRevision }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const binding = await sessionManager.binding(runtime, change);
    if (!binding) throw new BrokerError('SESSION_NOT_FOUND', 'No active Session is bound to this AR');
    const sessionAccess = await sessionManager.access(runtime, binding.sessionId);
    let claimed = false;
    if (sessionAccess === 'workspace-write') {
      const owner = locks.owner(runtime.projectKey);
      if (!owner || owner.sessionId !== binding.sessionId) {
        locks.acquire(runtime.projectKey, binding.sessionId, sessionAccess, 'ready');
        claimed = true;
      }
    }
    try {
      const result = await sessionManager.sendBound(runtime, change, phaseId, prompt, expectedRevision, batchMode, codespecSnapshotPath, workspaceSnapshotPath);
      locks.update(runtime.projectKey, binding.sessionId, 'running');
      return result;
    } catch (error) {
      if (claimed) locks.release(runtime.projectKey, binding.sessionId);
      throw error;
    }
  });
}));

server.registerTool('opencode_session_replace', {
  description: 'Explicitly replace a terminal AR Session binding with a new agent Session',
  inputSchema: {
    ...rootInput,
    change,
    previousSessionId: z.string().min(1),
    expectedRevision: z.number().int().min(0),
    agent: z.string().regex(/^[A-Za-z0-9_.-]{1,128}$/),
    access,
    title: z.string().optional()
  }
}, async ({ root, change, previousSessionId, expectedRevision, agent, access, title }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const binding = await sessionManager.binding(runtime, change);
    if (!binding || binding.sessionId !== previousSessionId) {
      throw new BrokerError('SESSION_BINDING_CONFLICT', 'Session is not the current AR binding');
    }
    locks.assertReplaceAllowed(runtime.projectKey, previousSessionId);
    const result = await sessionManager.replace(runtime, previousSessionId,
      { change, agent, access, title }, expectedRevision);
    locks.restore(runtime.projectKey, result.sessionId, access, result.status);
    return { ok: true, projectKey: runtime.projectKey, ...result };
  });
}));

server.registerTool('opencode_session_binding', {
  description: 'Read the authoritative Broker Session binding for an AR',
  inputSchema: { ...rootInput, change }
}, async ({ root, change }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const binding = await sessionManager.binding(runtime, change);
    return {
      ok: true,
      projectKey: runtime.projectKey,
      change,
      binding: binding ? {
        sessionId: binding.sessionId,
        agent: binding.agent,
        access: binding.access,
        status: binding.status,
        revision: binding.revision
      } : null
    };
  });
}));

server.registerTool('opencode_session_wait', {
  description: 'Wait for a revision change using SSE and authoritative status',
  inputSchema: {
    ...sessionInput,
    afterRevision: z.number().int().min(0),
    timeoutMs: z.number().int().min(1000).max(120000).optional()
  }
}, async ({ root, sessionId, afterRevision, timeoutMs }) => safeCall(async () => {
  const runtime = await startProject(root);
  const result = await sessionManager.wait(runtime, sessionId, afterRevision, timeoutMs);
  locks.update(runtime.projectKey, sessionId, result.status);
  if (['completed', 'failed', 'interrupted'].includes(result.status)) locks.release(runtime.projectKey, sessionId);
  return result;
}));

server.registerTool('opencode_permission_respond', {
  description: 'Respond once to a known OpenCode permission request',
  inputSchema: {
    ...rootInput,
    sessionId: z.string().min(1),
    permissionId: z.string().min(1),
    response: z.enum(['once', 'always', 'reject'])
  }
}, async ({ root, sessionId, permissionId, response }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    return await sessionManager.permission(runtime, sessionId, permissionId, response);
  });
}));

server.registerTool('opencode_session_abort', {
  description: 'Abort a Session without stopping the project Server',
  inputSchema: sessionInput
}, async ({ root, sessionId }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await projectFileLock.withLock(root, async () => {
    await synchronizeWriter(runtime);
    const result = await sessionManager.abort(runtime, sessionId);
    locks.release(runtime.projectKey, sessionId);
    return result;
  });
}));

server.registerTool('opencode_session_result', {
  description: 'Read final message and usage from a completed Session',
  inputSchema: sessionInput
}, async ({ root, sessionId }) => safeCall(async () => {
  const runtime = await startProject(root);
  return await sessionManager.result(runtime, sessionId);
}));

server.registerTool('opencode_project_stop', {
  description: 'Stop the project OpenCode Server',
  inputSchema: { ...rootInput, mode: z.enum(['graceful', 'force']) }
}, async ({ root, mode }) => safeCall(async () => {
  const key = projectKey(root);
  return await serverManager.stop(root, mode, async () => {
    const runtime = await serverManager.recover(root);
    if (runtime) await synchronizeWriter(runtime);
    return locks.isBusy(runtime?.projectKey ?? key);
  });
}));

const transport = new StdioServerTransport();
server.connect(transport).catch(error => { console.error(error); process.exitCode = 1; });
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.once(signal, async () => {
    await serverManager.stopAll();
    process.exit(0);
  });
}
