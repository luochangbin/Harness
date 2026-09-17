import { z } from 'zod';
import { BrokerError, errorResult } from './errors.js';
import { redactSecrets } from './schemas.js';

const rootInput = { root: z.string().min(1) };
const runKey = z.string().regex(/^ordinary:[A-Za-z0-9_.-]{1,256}$/);
const taskBatch = z.string().regex(/^(all|[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)$/);
const access = z.enum(['read-only', 'workspace-write']);

function reply(value: unknown) {
  const safe = redactSecrets(value);
  return { content: [{ type: 'text' as const, text: JSON.stringify(safe) }], structuredContent: safe as Record<string, unknown> };
}

async function safeCall(fn: () => Promise<unknown>) {
  try { return reply(await fn()); }
  catch (error) { return { ...reply(errorResult(error)), isError: true }; }
}

export function registerOrdinaryTools(server: any, deps: any) {
  const { startProject, synchronizeWriter, projectFileLock, sessionManager, locks } = deps;
  server.registerTool('opencode_run', {
    description: 'Send an ordinary non-AR OpenCode task using a stable runKey and explicit task batch',
    inputSchema: {
      ...rootInput, runKey, taskBatch, prompt: z.string().min(1),
      agent: z.string().regex(/^[A-Za-z0-9_.-]{1,128}$/), access,
      expectedRevision: z.number().int().min(0),
      codespecSnapshotPath: z.string().min(1), workspaceSnapshotPath: z.string().min(1),
      title: z.string().optional()
    }
  }, async ({ root, runKey, taskBatch, prompt, agent, access, expectedRevision, codespecSnapshotPath, workspaceSnapshotPath, title }: any) => safeCall(async () => {
    const runtime = await startProject(root);
    return await projectFileLock.withLock(root, async () => {
      await synchronizeWriter(runtime);
      const suffix = runKey.slice('ordinary:'.length);
      const existing = await sessionManager.binding(runtime, suffix, 'ordinary');
      const owner = locks.owner(runtime.projectKey);
      const busy = Boolean(owner && ['ready', 'running', 'awaiting_permission', 'sending'].includes(owner.status));
      if (busy && owner.sessionId !== existing?.sessionId) {
        throw new BrokerError('PROJECT_WRITER_BUSY', 'Another active Session is operating this project');
      }
      const created = await sessionManager.create(runtime, { change: suffix, namespace: 'ordinary', runKey, agent, access, title });
      locks.restore(runtime.projectKey, created.sessionId, access, created.status);
      const result = await sessionManager.sendOrdinary(runtime, created.sessionId, runKey, taskBatch, prompt, expectedRevision, codespecSnapshotPath, workspaceSnapshotPath);
      locks.update(runtime.projectKey, created.sessionId, 'running');
      return { ...result, namespace: 'ordinary', runKey, taskBatch };
    });
  }));

  server.registerTool('opencode_run_binding', {
    description: 'Read the authoritative ordinary OpenCode Session binding by runKey without creating or sending work',
    inputSchema: { ...rootInput, runKey }
  }, async ({ root, runKey }: any) => safeCall(async () => {
    const runtime = await startProject(root);
    return await projectFileLock.withLock(root, async () => {
      await synchronizeWriter(runtime);
      const suffix = runKey.slice('ordinary:'.length);
      const binding = await sessionManager.binding(runtime, suffix, 'ordinary');
      if (!binding) return { ok: true, projectKey: runtime.projectKey, runKey, binding: null };
      if (binding.runKey !== runKey) throw new BrokerError('RUN_KEY_BINDING_MISMATCH', 'Stored ordinary binding does not match runKey');
      return {
        ok: true, projectKey: runtime.projectKey, runKey,
        binding: {
          sessionId: binding.sessionId, agent: binding.agent, access: binding.access,
          status: binding.status, revision: binding.revision,
          namespace: 'ordinary', runKey
        }
      };
    });
  }));
}
