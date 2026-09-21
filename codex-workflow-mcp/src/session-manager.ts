import crypto from 'node:crypto';
import path from 'node:path';
import { BrokerError } from './errors.js';
import { waitForEvent, ServerEvent } from './event-stream.js';
import { OpenCodeClient, OpenCodeStatus, SessionInfo, messageId } from './opencode-client.js';
import { PermissionBridge, PermissionResponse, automaticPermissionResponse } from './permissions.js';
import { RuntimeRecord, SessionStateRecord, SessionStateStore } from './runtime-store.js';
import { SessionFileLock } from './project-lock.js';
import { PhaseBatchMode, resolvePhaseBatch } from './phase-batch.js';
import { buildBoundWorkerPrompt, buildOrdinaryWorkerPrompt, validateWorkerPrompt } from './worker-prompt.js';

const terminal = new Set<OpenCodeStatus>(['completed', 'failed', 'interrupted']);
const active = new Set(['sending', 'ready', 'running', 'awaiting_permission']);
const changePattern = /^[A-Za-z0-9_-]{1,256}$/;
const ordinaryRunKeyPattern = /^ordinary:([A-Za-z0-9_.-]{1,256})$/;
const ordinaryChangePattern = /^[A-Za-z0-9_.-]{1,256}$/;

export type SessionNamespace = 'ar' | 'ordinary';

export type SessionCreateOptions = {
  change: string;
  namespace?: SessionNamespace;
  runKey?: string;
  agent: string;
  access: 'read-only' | 'workspace-write';
  title?: string;
};

function isAssistant(item: any) {
  return item?.info?.role === 'assistant' || item?.role === 'assistant';
}

function assistantInfo(item: any) {
  return item?.info ?? item;
}

function assistantCompleted(item: any): boolean {
  const info = assistantInfo(item);
  return (info?.time?.completed !== undefined && info?.time?.completed !== null) || info?.completed === true;
}

function assistantParentId(item: any): string | undefined {
  return item?.info?.parentID ?? item?.info?.parentId ?? item?.parentID ?? item?.parentId;
}

function latestTurnAssistant(messages: any[], userMessageId?: string) {
  const assistants = messages.filter(isAssistant);
  if (!assistants.length) return undefined;
  if (userMessageId) {
    const linked = [...assistants].reverse().find(item => assistantParentId(item) === userMessageId);
    if (linked) return linked;
    if (assistants.some(item => assistantParentId(item) !== undefined)) return undefined;
  }
  return assistants[assistants.length - 1];
}

export class SessionManager {
  private sessions = new Map<string, SessionStateRecord>();
  private permissionQuerySupported: boolean | undefined;

  constructor(
    private readonly client: OpenCodeClient,
    private readonly store = new SessionStateStore(),
    private readonly permissions?: PermissionBridge,
    private readonly watchdogMs = 30 * 60 * 1000,
    private readonly lock = new SessionFileLock()
  ) {}

  private async remoteSessionByTitle(runtime: RuntimeRecord, title: string): Promise<string | null> {
    const list = (this.client as any).listSessions;
    if (typeof list !== 'function') {
      throw new BrokerError(
        'SESSION_CREATE_UNCERTAIN',
        'Cannot reconcile a persisted Session creation intent'
      );
    }
    const sessions = await list.call(this.client, runtime) as Array<{ id?: string; title?: string }>;
    const matches = sessions.filter(item => item?.title === title && typeof item?.id === 'string');
    if (matches.length > 1) {
      throw new BrokerError(
        'SESSION_CREATE_AMBIGUOUS',
        'Multiple OpenCode Sessions match the persisted creation marker'
      );
    }
    return matches[0]?.id ?? null;
  }

  private markedTitle(options: SessionCreateOptions, requestId: string) {
    const base = options.title?.includes(options.change) ?
      options.title : options.change + ' implementation';
    return base + ' [cw:' + requestId + ']';
  }
  async create(runtime: RuntimeRecord, options: SessionCreateOptions) {
    const namespace = options.namespace ?? 'ar';
    const validChange = namespace === 'ordinary' ? ordinaryChangePattern : changePattern;
    if (!validChange.test(options.change)) {
      throw new BrokerError('INVALID_CHANGE', 'Invalid AR change name');
    }
    return await this.withSessionLock(
      runtime,
      'create-' + options.change,
      async () => await this.createUnlocked(runtime, options)
    );
  }

  private async createUnlocked(runtime: RuntimeRecord, options: SessionCreateOptions) {
    const namespace = options.namespace ?? 'ar';
    const validChange = namespace === 'ordinary' ? ordinaryChangePattern : changePattern;
    if (!validChange.test(options.change)) throw new BrokerError('INVALID_CHANGE', 'Invalid Session name');
    if (!options.agent || !/^[A-Za-z0-9_.-]{1,128}$/.test(options.agent)) {
      throw new BrokerError('INVALID_AGENT', 'Invalid OpenCode agent');
    }
    if (namespace === 'ordinary' && (!options.runKey || options.runKey !== 'ordinary:' + options.change || !ordinaryRunKeyPattern.test(options.runKey))) {
      throw new BrokerError('INVALID_RUN_KEY', 'Ordinary Session requires runKey ordinary:<suffix>');
    }
    const existing = await this.store.findByChange(runtime.root, options.change, namespace);
    if (existing) {
      if (existing.agent === options.agent && existing.access === options.access) {
        this.sessions.set(existing.sessionId, existing);
        await this.store.removeCreation(runtime.root, options.change, namespace).catch(() => undefined);
        return {
          sessionId: existing.sessionId, change: existing.change,
          agent: existing.agent, access: existing.access,
          status: existing.status, revision: existing.revision, recovered: true
        };
      }
      throw new BrokerError('SESSION_ALREADY_BOUND', 'AR already has a bound Session');
    }
    if ('agentExists' in this.client && typeof (this.client as any).agentExists === 'function') {
      if (!await (this.client as any).agentExists(runtime, options.agent)) {
        throw new BrokerError('INVALID_AGENT', 'OpenCode agent does not exist: ' + options.agent);
      }
    }

    let intent = await this.store.readCreation(runtime.root, options.change, namespace);
    const recovering = intent !== null;
    if (intent) {
      if ((intent.namespace ?? 'ar') !== namespace || intent.agent !== options.agent || intent.access !== options.access) {
        throw new BrokerError(
          'SESSION_CREATE_CONFLICT',
          'Persisted Session creation intent uses a different agent or access mode'
        );
      }
    } else {
      const requestId = crypto.randomUUID().replace(/-/g, '');
      intent = {
        schemaVersion: 1,
        projectKey: runtime.projectKey,
        root: runtime.root,
        change: options.change,
        namespace,
        ...(options.runKey ? { runKey: options.runKey } : {}),
        requestId,
        title: this.markedTitle(options, requestId),
        agent: options.agent,
        access: options.access,
        updatedAt: new Date().toISOString()
      };
      await this.store.writeCreation(runtime.root, intent);
    }

    let id = recovering ? await this.remoteSessionByTitle(runtime, intent.title) : null;
    if (!id) {
      id = await this.client.create(runtime, {
        title: intent.title, agent: intent.agent, access: intent.access
      });
    }
    const state: SessionStateRecord = {
      schemaVersion: 1,
      namespace,
      ...(options.runKey ? { runKey: options.runKey } : {}),
      projectKey: runtime.projectKey,
      root: runtime.root,
      sessionId: id,
      change: options.change,
      agent: intent.agent,
      access: intent.access,
      revision: 0,
      status: 'ready',
      updatedAt: new Date().toISOString()
    };
    await this.store.write(runtime.root, state);
    let cleanupPending = false;
    try {
      await this.store.removeCreation(runtime.root, options.change, namespace);
    } catch {
      cleanupPending = true;
    }
    this.sessions.set(id, state);
    return {
      sessionId: id, change: options.change, agent: intent.agent, access: intent.access,
      status: 'ready', revision: 0,
      ...(recovering ? { recovered: true } : {}),
      ...(cleanupPending ? { cleanupPending: true } : {})
    };
  }
  async replace(runtime: RuntimeRecord, previousSessionId: string, options: SessionCreateOptions, expectedRevision: number) {
    return await this.withSessionLock(runtime, previousSessionId, async () => {
      const existing = await this.require(runtime, previousSessionId);
      const current = await this.store.findByChange(runtime.root, options.change);
      if (!current || current.sessionId !== previousSessionId) {
        throw new BrokerError(
          'SESSION_BINDING_CONFLICT',
          'Session is not the current AR binding'
        );
      }
      if (existing.change !== options.change) throw new BrokerError('PROJECT_SESSION_MISMATCH', 'Session is bound to another AR');
      if (existing.revision !== expectedRevision) throw new BrokerError('REVISION_CONFLICT', 'Session revision has changed');
      if (active.has(existing.status)) throw new BrokerError('SESSION_BUSY', 'Cannot replace an active Session');
      if (!options.agent || !/^[A-Za-z0-9_.-]{1,128}$/.test(options.agent)) {
        throw new BrokerError('INVALID_AGENT', 'Invalid OpenCode agent');
      }
      if ('agentExists' in this.client && typeof (this.client as any).agentExists === 'function' &&
          !await (this.client as any).agentExists(runtime, options.agent)) {
        throw new BrokerError('INVALID_AGENT', 'OpenCode agent does not exist: ' + options.agent);
      }

      let intent = await this.store.readReplacement(runtime.root, options.change);
      let recovering = false;
      if (intent?.phase === 'creating' && intent.requestId && intent.title &&
          intent.agent && intent.access) {
        if (intent.previousSessionId !== previousSessionId ||
            intent.agent !== options.agent || intent.access !== options.access) {
          throw new BrokerError(
            'SESSION_CREATE_CONFLICT',
            'Persisted Session replacement intent does not match this request'
          );
        }
        recovering = true;
      } else {
        if (intent) {
          // Legacy creating intents have no remote reconciliation marker.
          await this.store.removeReplacement(runtime.root, options.change);
        }
        const requestId = crypto.randomUUID().replace(/-/g, '');
        intent = {
          schemaVersion: 1,
          projectKey: runtime.projectKey,
          root: runtime.root,
          change: options.change,
          previousSessionId,
          requestId,
          title: this.markedTitle(options, requestId),
          agent: options.agent,
          access: options.access,
          phase: 'creating',
          updatedAt: new Date().toISOString()
        };
        await this.store.writeReplacement(runtime.root, intent);
      }

      let sessionId = recovering ?
        await this.remoteSessionByTitle(runtime, intent.title!) : null;
      if (!sessionId) {
        sessionId = await this.client.create(runtime, {
          title: intent.title!, agent: intent.agent!, access: intent.access!
        });
      }
      const state: SessionStateRecord = {
        schemaVersion: 1,
        projectKey: runtime.projectKey,
        root: runtime.root,
        sessionId,
        change: options.change,
        agent: intent.agent!,
        access: intent.access!,
        revision: 0,
        status: 'ready',
        updatedAt: new Date().toISOString()
      };
      await this.store.writeReplacement(runtime.root, {
        ...intent,
        newSessionId: sessionId,
        pendingState: state,
        phase: 'created',
        updatedAt: new Date().toISOString()
      });
      await this.store.write(runtime.root, state);
      let cleanupPending = false;
      try {
        await this.store.remove(runtime.root, previousSessionId);
      } catch {
        cleanupPending = true;
      }
      if (!cleanupPending) {
        try {
          await this.store.removeReplacement(runtime.root, options.change);
        } catch {
          cleanupPending = true;
        }
      }
      this.sessions.delete(previousSessionId);
      this.sessions.set(sessionId, state);
      return {
        sessionId, change: options.change, agent: state.agent, access: state.access,
        status: 'ready', revision: 0, replacedSessionId: previousSessionId,
        cleanupPending, ...(recovering ? { recovered: true } : {})
      };
    });
  }
  async binding(runtime: RuntimeRecord, change: string, namespace: SessionNamespace = 'ar') {
    return await this.store.findByChange(runtime.root, change, namespace);
  }

  async sendBound(runtime: RuntimeRecord, change: string, phaseId: string, prompt: string, expectedRevision: number, batchMode: PhaseBatchMode = 'implementation', codespecSnapshotPath: string, workspaceSnapshotPath: string) {
    const state = await this.store.findByChange(runtime.root, change);
    if (!state) throw new BrokerError('SESSION_NOT_FOUND', 'No active Session is bound to this AR');
    if (!codespecSnapshotPath || !workspaceSnapshotPath) {
      throw new BrokerError('INVALID_SNAPSHOT_PATH', 'Bound sends require both codespec and workspace snapshot paths');
    }
    const batch = await resolvePhaseBatch(runtime.root, change, phaseId, batchMode);
    const boundPrompt = buildBoundWorkerPrompt(change, batch.phaseId, batch.taskBatch, prompt, batchMode);
    return await this.send(runtime, state.sessionId, change, batch.taskBatch, boundPrompt, expectedRevision, codespecSnapshotPath, workspaceSnapshotPath);
  }

  async sendOrdinary(runtime: RuntimeRecord, sessionId: string, runKey: string, taskBatch: string, prompt: string, expectedRevision: number, codespecSnapshotPath: string, workspaceSnapshotPath: string) {
    validateWorkerPrompt(prompt);
    const match = ordinaryRunKeyPattern.exec(runKey);
    if (!match) throw new BrokerError('INVALID_RUN_KEY', 'Ordinary runKey must be ordinary:<suffix>');
    const suffix = match[1];
    if (!codespecSnapshotPath || !workspaceSnapshotPath) {
      throw new BrokerError('INVALID_SNAPSHOT_PATH', 'Ordinary sends require both snapshot paths');
    }
    const state = await this.store.findByChange(runtime.root, suffix, 'ordinary');
    if (!state || state.sessionId !== sessionId) throw new BrokerError('SESSION_NOT_FOUND', 'Ordinary Session not found');
    const ordinaryPrompt = buildOrdinaryWorkerPrompt(runKey, taskBatch, prompt);
    return await this.send(runtime, sessionId, suffix, taskBatch, ordinaryPrompt, expectedRevision, codespecSnapshotPath, workspaceSnapshotPath, 'ordinary');
  }

  async hasActiveSessions(root: string) {
    const states = await this.store.list(root);
    return states.some(state => active.has(state.status));
  }

  async access(runtime: RuntimeRecord, sessionId: string) {
    return (await this.require(runtime, sessionId)).access;
  }

  async isActive(runtime: RuntimeRecord, sessionId: string) {
    return active.has((await this.require(runtime, sessionId)).status);
  }

  async send(runtime: RuntimeRecord, sessionId: string, change: string, taskBatch: string, prompt: string, expectedRevision: number, codespecSnapshotPath?: string, workspaceSnapshotPath?: string, namespace: SessionNamespace = 'ar') {
    validateWorkerPrompt(prompt);
    return await this.withSessionLock(runtime, sessionId, async () => {
      let state = await this.require(runtime, sessionId);
      if (state.status === 'sending') {
        state = await this.reconcileSend(runtime, state);
        if (state.status === 'sending') {
          throw new BrokerError('SEND_UNCERTAIN', 'Previous send outcome is not confirmed; refusing to resend');
        }
      }
      if (state.change !== change || (state.namespace ?? 'ar') !== namespace) throw new BrokerError('PROJECT_SESSION_MISMATCH', 'Session is bound to another namespace');
      if (state.revision !== expectedRevision) throw new BrokerError('REVISION_CONFLICT', 'Session revision has changed');
      if (state.status === 'running' || state.status === 'awaiting_permission' || state.status === 'sending') {
        throw new BrokerError('SESSION_BUSY', 'Session already has an active message');
      }
      if (state.access === 'read-only') {
        throw new BrokerError('READ_ONLY_SESSION', 'OpenCode read-only execution is not enforceable by this adapter');
      }
      if (codespecSnapshotPath && !path.isAbsolute(codespecSnapshotPath)) {
        throw new BrokerError('INVALID_SNAPSHOT_PATH', 'Codespec snapshot path must be absolute');
      }
      if (workspaceSnapshotPath && !path.isAbsolute(workspaceSnapshotPath)) {
        throw new BrokerError('INVALID_SNAPSHOT_PATH', 'Workspace snapshot path must be absolute');
      }
      if (codespecSnapshotPath === undefined && workspaceSnapshotPath !== undefined) {
        throw new BrokerError('INVALID_SNAPSHOT_PATH', 'Codespec and workspace snapshot paths must be supplied together');
      }
      if (!/^(all|[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)$/.test(taskBatch)) {
        throw new BrokerError('INVALID_TASK_BATCH', 'Invalid task batch');
      }
      if (!prompt.trim()) throw new BrokerError('INVALID_PROMPT', 'Prompt must not be empty');
      let baseline: { messageCount?: number; assistantId?: string } | undefined;
      if ('messages' in this.client && typeof (this.client as any).messages === 'function') {
        const messages = await (this.client as any).messages(runtime, sessionId) as any[];
        const assistants = messages.filter(isAssistant);
        const latest = assistants[assistants.length - 1];
        baseline = { messageCount: messages.length, assistantId: latest?.info?.id ?? latest?.id };
      }
      // Persist the send intent before the HTTP call so a lost response cannot
      // be mistaken for "not sent": the messageID is reconciled on retry.
      const messageIdValue = 'msg_' + crypto.randomBytes(12).toString('hex');
      state.status = 'sending';
      state.pendingMessageId = messageIdValue;
      state.lastMessageId = messageIdValue;
      state.baselineMessageCount = baseline?.messageCount;
      state.baselineAssistantId = baseline?.assistantId;
      state.codespecSnapshotPath = codespecSnapshotPath;
      state.workspaceSnapshotPath = workspaceSnapshotPath;
      state.turnStartedAt = new Date().toISOString();
      state.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, state);
      await this.client.send(runtime, sessionId, prompt, state.agent, messageIdValue);
      state.status = 'running';
      state.pendingMessageId = undefined;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, state);
      return { accepted: true, sessionId, status: 'running', revision: state.revision };
    });
  }

  private async reconcileSend(runtime: RuntimeRecord, state: SessionStateRecord) {
    const pending = state.pendingMessageId;
    if (!pending) return state;
    if (!('messages' in this.client) || typeof (this.client as any).messages !== 'function') return state;
    let messages: any[];
    try {
      messages = await (this.client as any).messages(runtime, state.sessionId) as any[];
    } catch {
      return state;
    }
    if (!messages.some(item => messageId(item) === pending)) return state;
    state.status = 'running';
    state.pendingMessageId = undefined;
    state.revision++;
    state.updatedAt = new Date().toISOString();
    await this.store.write(runtime.root, state);
    return state;
  }

  async wait(runtime: RuntimeRecord, sessionId: string, afterRevision: number, timeoutMs = 30000) {
    let state = await this.require(runtime, sessionId);
    if (!Number.isInteger(afterRevision) || afterRevision < 0) throw new BrokerError('INVALID_REVISION', 'Invalid afterRevision');
    const bounded = Math.min(Math.max(timeoutMs, 1000), 120000);

    if (state.status === 'sending') {
      state = await this.withSessionLock(runtime, sessionId, async () => this.reconcileSend(runtime, await this.require(runtime, sessionId)));
    }
    if (!terminal.has(state.status as OpenCodeStatus)) {
      const permissionState = await this.reconcilePermissions(runtime, sessionId);
      if (permissionState.supported && permissionState.pending.length) {
        state = await this.applyPendingPermissions(runtime, sessionId, permissionState.pending, permissionState.expectedRevision, permissionState.expectedInteractionId);
      }
    }
    if (state.status === 'awaiting_permission' && state.revision > afterRevision) return this.snapshot(state, true);
    if (terminal.has(state.status as OpenCodeStatus)) return this.snapshot(state, state.revision > afterRevision);
    await this.enforceWatchdog(runtime, state);

    const deadline = Date.now() + bounded;
    const initial = await this.withSessionLock(runtime, sessionId, async () => {
      state = await this.require(runtime, sessionId);
      if (terminal.has(state.status as OpenCodeStatus)) return { changed: state.revision > afterRevision, info: { id: sessionId, status: state.status } as SessionInfo };
      return this.updateFromServer(runtime, state);
    });
    if (state.revision > afterRevision || initial.changed) return this.snapshot(state, true);

    const authoritativeSnapshot = async () => {
      await this.reconcileSessionPermissions(runtime, sessionId);
      return await this.withSessionLock(runtime, sessionId, async () => {
        state = await this.require(runtime, sessionId);
        const refreshed = await this.updateFromServer(runtime, state);
        return this.snapshot(state, refreshed.changed || state.revision > afterRevision);
      });
    };

    let reconnects = 0;
    while (Date.now() < deadline) {
      const controller = new AbortController();
      let endReason: 'eof' | 'timeout' | undefined;
      try {
        const response = await this.client.events(runtime, controller.signal);
        await this.reconcileSessionPermissions(runtime, sessionId);
        state = await this.require(runtime, sessionId);
        if (state.status === 'awaiting_permission' || terminal.has(state.status as OpenCodeStatus)) {
          controller.abort();
          await response.body?.cancel().catch(() => undefined);
          return this.snapshot(state, true);
        }
        const event = await waitForEvent(
          response,
          deadline - Date.now(),
          controller.signal,
          async item => {
            await this.withSessionLock(runtime, sessionId, async () => {
              const current = await this.require(runtime, sessionId);
              state = current;
              if (terminal.has(current.status as OpenCodeStatus)) return;
              const changed = this.consumeEvent(runtime, current, item);
              if (changed) await this.store.write(runtime.root, current);
            });
          },
          item => this.isSessionEvent(item, state.sessionId),
          reason => { endReason = reason; }
        );
        if (!event) {
          if (endReason === 'timeout') break;
          reconnects++;
          if (reconnects > 2) return await authoritativeSnapshot();
          await new Promise(resolve => setTimeout(resolve, reconnects * 100));
          continue;
        }
        reconnects = 0;
        if (state.status === 'awaiting_permission') {
          state = await this.autoApprovePermission(runtime, sessionId);
        }
         if (state.status === 'awaiting_permission' || terminal.has(state.status as OpenCodeStatus)) return this.snapshot(state, true);
        const updated = await this.withSessionLock(runtime, sessionId, async () => {
          state = await this.require(runtime, sessionId);
          if (terminal.has(state.status as OpenCodeStatus)) return { changed: state.revision > afterRevision, info: { id: sessionId, status: state.status } as SessionInfo };
          return this.updateFromServer(runtime, state);
        });
        if (state.revision > afterRevision || updated.changed) return this.snapshot(state, true);
      } catch (error) {
        reconnects++;
        if (reconnects > 2) return await authoritativeSnapshot();
        await new Promise(resolve => setTimeout(resolve, reconnects * 100));
      }
    }
    await this.reconcileSessionPermissions(runtime, sessionId);
    state = await this.require(runtime, sessionId);
    if (state.status === 'awaiting_permission') return this.snapshot(state, true);
    return this.snapshot(state, false);
  }

  async result(runtime: RuntimeRecord, sessionId: string) {
    const state = await this.require(runtime, sessionId);
    if (state.status !== 'completed') throw new BrokerError('SESSION_NOT_TERMINAL', 'Session is not completed');
    const raw = await this.client.result(runtime, sessionId) as any;
    const messages = Array.isArray(raw) ? raw : Array.isArray(raw?.messages) ? raw.messages : [];
    const assistant = latestTurnAssistant(messages, state.lastMessageId) ?? [...messages].reverse().find(isAssistant) ?? {};
    const info = assistant.info ?? assistant;
    const parts = Array.isArray(assistant.parts) ? assistant.parts : [];
    const finalMessage = raw?.finalMessage ??
      (parts.filter((part: any) => typeof part?.text === 'string').map((part: any) => part.text).join('\n') || '');
    const turn = messages.slice(state.baselineMessageCount ?? 0).filter(isAssistant);
    const usage = this.aggregateUsage(turn.length ? turn : [assistant]);
    return {
      sessionId,
      status: state.status,
      revision: state.revision,
      finalMessage,
      codespecSnapshotPath: state.codespecSnapshotPath ?? null,
      workspaceSnapshotPath: state.workspaceSnapshotPath ?? null,
      usage: usage ?? raw?.usage ?? info.usage ?? null,
      diff: raw?.diff ?? null
    };
  }

  private aggregateUsage(items: any[]) {
    let seen = false;
    let hasCache = false;
    const usage: Record<string, number | string> = { input: 0, output: 0, reasoning: 0, cost: 0 };
    for (const item of items) {
      const info = item?.info ?? item;
      const tokens = info?.tokens;
      if (!tokens && info?.cost === undefined) continue;
      seen = true;
      usage.input = (usage.input as number) + (tokens?.input ?? 0);
      usage.output = (usage.output as number) + (tokens?.output ?? 0);
      usage.reasoning = (usage.reasoning as number) + (tokens?.reasoning ?? 0);
      usage.cost = (usage.cost as number) + (info?.cost ?? 0);
      if (tokens?.cache !== undefined) {
        hasCache = true;
        usage.cacheRead = ((usage.cacheRead as number) ?? 0) + (tokens.cache?.read ?? 0);
        usage.cacheWrite = ((usage.cacheWrite as number) ?? 0) + (tokens.cache?.write ?? 0);
      }
    }
    if (!seen) return null;
    usage.cacheStatus = hasCache ? 'supported' : 'unsupported';
    return usage;
  }

  async abort(runtime: RuntimeRecord, sessionId: string) {
    return await this.withSessionLock(runtime, sessionId, async () => {
      const state = await this.require(runtime, sessionId);
      if (terminal.has(state.status as OpenCodeStatus)) return { sessionId, status: 'already_terminal' };
      try {
        await this.client.abort(runtime, sessionId);
      } catch (error) {
        if (error instanceof BrokerError && error.code === 'SERVER_HTTP_ERROR') {
          throw new BrokerError('SERVER_UNREACHABLE', error.message);
        }
        throw new BrokerError('ABORT_FAILED', error instanceof Error ? error.message : String(error));
      }
      state.status = 'interrupted';
      state.pendingMessageId = undefined;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, state);
      return { sessionId, status: 'interrupted', revision: state.revision };
    });
  }

  private async enforceWatchdog(runtime: RuntimeRecord, state: SessionStateRecord) {
    if ((state.status !== 'running' && state.status !== 'sending') || !state.turnStartedAt) return;
    if (Date.now() - Date.parse(state.turnStartedAt) < this.watchdogMs) return;
    try {
      await this.abort(runtime, state.sessionId);
    } catch {
      throw new BrokerError('ABORT_FAILED', 'Workflow watchdog reached but the Session could not be aborted');
    }
    throw new BrokerError('WORKFLOW_TIMEOUT', 'Workflow watchdog reached; Session was aborted');
  }

  async permission(runtime: RuntimeRecord, sessionId: string, permissionId: string, response: PermissionResponse) {
    return await this.withSessionLock(runtime, sessionId, async () => {
      const state = await this.require(runtime, sessionId);
      this.permissions?.validate(runtime.projectKey, sessionId, permissionId, response);
      await this.client.permission(runtime, sessionId, permissionId, response);
      const permission = this.permissions?.respond(runtime.projectKey, sessionId, permissionId, response) ?? null;
      state.status = 'running';
      state.interaction = null;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, state);
      return { sessionId, revision: state.revision, accepted: true, permission };
    });
  }

  async recoverActive(runtime: RuntimeRecord) {
    const states = await this.store.list(runtime.root);
    const activeSessions: SessionStateRecord[] = [];
    for (let state of states) {
      const cached = this.sessions.get(state.sessionId);
      if (!cached || state.revision >= cached.revision) this.sessions.set(state.sessionId, state);
      if (!active.has(state.status)) continue;
      if (state.status === 'awaiting_permission') {
        await this.withSessionLock(runtime, state.sessionId, async () => {
          const current = await this.require(runtime, state.sessionId);
          if (current.status !== 'awaiting_permission') {
            const staleId = (state.interaction as any)?.id;
            if (staleId) this.permissions?.discard(String(staleId));
            return;
          }
          const restored = this.permissions?.restore(current.interaction);
          if (restored) {
            current.interaction = restored;
            current.updatedAt = new Date().toISOString();
            await this.store.write(runtime.root, current);
          }
        });
        state = await this.require(runtime, state.sessionId);
        if (state.status === 'awaiting_permission') {
          const { supported, pending, expectedRevision, expectedInteractionId } = await this.reconcilePermissions(runtime, state.sessionId);
          if (supported) {
            if (pending.length) {
              await this.applyPendingPermissions(runtime, state.sessionId, pending, expectedRevision, expectedInteractionId);
            } else {
              await this.withSessionLock(runtime, state.sessionId, async () => {
                const current = await this.require(runtime, state.sessionId);
                const currentInteractionId = (current.interaction as any)?.id == null ? null : String((current.interaction as any).id);
                if (current.status === 'awaiting_permission' && current.revision === expectedRevision && currentInteractionId === expectedInteractionId) {
                  const id = (current.interaction as any)?.id;
                  if (id) this.permissions?.discard(String(id));
                  current.status = 'running';
                  current.interaction = null;
                  current.revision++;
                  current.updatedAt = new Date().toISOString();
                  await this.store.write(runtime.root, current);
                } else if (expectedInteractionId !== null && currentInteractionId !== expectedInteractionId) {
                  this.permissions?.discard(expectedInteractionId);
                }
              });
            }
          }
        }
      }
      if (state.status === 'running' || state.status === 'sending') {
        await this.withSessionLock(runtime, state.sessionId, async () => {
          const current = await this.require(runtime, state.sessionId);
          if (current.status === 'sending') {
            await this.reconcileSend(runtime, current);
          } else {
            await this.updateFromServer(runtime, current);
          }
        });
        await this.reconcileSessionPermissions(runtime, state.sessionId);
      }
      const current = await this.require(runtime, state.sessionId);
      if (active.has(current.status)) activeSessions.push(current);
    }
    return activeSessions;
  }

  async recoverWriter(runtime: RuntimeRecord) {
    const writers = (await this.recoverActive(runtime)).filter(state => state.access === 'workspace-write');
    if (writers.length > 1) throw new BrokerError('PROJECT_WRITER_BUSY', 'Multiple active write Sessions found for this project');
    return writers[0] ?? null;
  }

  private async require(runtime: RuntimeRecord, sessionId: string) {
    const cached = this.sessions.get(sessionId);
    const persisted = await this.store.read(runtime.root, sessionId);
    const state = persisted && (!cached || persisted.revision >= cached.revision) ? persisted : cached;
    if (!state) throw new BrokerError('SESSION_NOT_FOUND', 'Session is not persisted for this project');
    if (state.projectKey !== runtime.projectKey) throw new BrokerError('PROJECT_SESSION_MISMATCH', 'Session belongs to another project');
    this.sessions.set(sessionId, state);
    return state;
  }

  private async updateFromServer(runtime: RuntimeRecord, state: SessionStateRecord): Promise<{ changed: boolean; info: SessionInfo }> {
    let info = await (this.client as any).status(runtime, state.sessionId, {
      messageCount: state.baselineMessageCount,
      assistantId: state.baselineAssistantId,
      userMessageId: state.lastMessageId
    }) as SessionInfo;
    if (info.status === 'completed' && 'messages' in this.client && typeof (this.client as any).messages === 'function') {
      const messages = await (this.client as any).messages(runtime, state.sessionId) as any[];
      const latest = latestTurnAssistant(messages, state.lastMessageId);
      const latestId = latest?.info?.id ?? latest?.id;
      const isNew = Boolean(latest) && (state.baselineAssistantId === undefined || latestId !== state.baselineAssistantId);
      const error = latest?.info?.error ?? latest?.error;
      if (error) {
        info = { ...info, status: 'failed', progress: String(error.data?.message ?? error.message ?? error.name ?? error) };
      } else if (!isNew || !assistantCompleted(latest)) {
        info = { ...info, status: 'running' };
      }
    }
    // A terminal result must never be downgraded by a later server observation.
    if (terminal.has(state.status as OpenCodeStatus)) return { changed: false, info };
    // The send intent owns its own running transition.
    if (state.status === 'sending') return { changed: false, info };
    // A pending permission stays pending only while the authoritative list
    // still contains it; otherwise it was resolved or expired.
    if (state.status === 'awaiting_permission' && state.interaction) {
      const id = (state.interaction as any)?.id;
      const stillPending = id ? await this.permissionStillPending(runtime, state.sessionId, id) : undefined;
      if (stillPending !== false) return { changed: false, info };
      if (id) this.permissions?.discard(String(id));
      state.interaction = null;
    }
    const changed = state.status !== info.status || state.progress !== info.progress ||
      JSON.stringify(state.interaction ?? null) !== JSON.stringify(info.interaction ?? null);
    if (changed) {
      state.status = info.status;
      state.progress = info.progress;
      state.interaction = info.interaction ?? null;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, state);
    }
    return { changed, info };
  }

  private async permissionList(runtime: RuntimeRecord): Promise<any[] | null | undefined> {
    if (typeof (this.client as any).permissionList !== 'function') return undefined;
    try {
      const list = await (this.client as any).permissionList(runtime) as any[] | null;
      this.permissionQuerySupported = list !== null;
      return list;
    } catch {
      return undefined;
    }
  }

  private async reconcilePermissions(runtime: RuntimeRecord, sessionId: string): Promise<{ supported: boolean; pending: any[]; expectedRevision: number; expectedInteractionId: string | null }> {
    const baseline = await this.require(runtime, sessionId);
    const expectedInteractionId = (baseline.interaction as any)?.id == null ? null : String((baseline.interaction as any).id);
    const list = await this.permissionList(runtime);
    if (list === undefined || list === null) return { supported: false, pending: [], expectedRevision: baseline.revision, expectedInteractionId };
    const mine = list.filter(item => (item?.sessionID ?? item?.sessionId ?? item?.session?.id) === sessionId);
    return { supported: true, pending: mine, expectedRevision: baseline.revision, expectedInteractionId };
  }

  private async reconcileSessionPermissions(runtime: RuntimeRecord, sessionId: string): Promise<void> {
    await this.autoApprovePermission(runtime, sessionId);
    const permissionState = await this.reconcilePermissions(runtime, sessionId);
    if (permissionState.supported && permissionState.pending.length) {
      await this.applyPendingPermissions(runtime, sessionId, permissionState.pending, permissionState.expectedRevision, permissionState.expectedInteractionId);
    }
  }

  private async autoApprovePermissionUnlocked(runtime: RuntimeRecord, state: SessionStateRecord) {
    if (state.status !== 'awaiting_permission' || !state.interaction || !this.permissions) return state;
    const interaction = state.interaction as any;
    const id = typeof interaction.id === 'string' ? interaction.id : undefined;
    const response = id ? automaticPermissionResponse(interaction) : null;
    if (!id || !response) return state;
    if (typeof (this.client as any).permission !== 'function') return state;
    await this.client.permission(runtime, state.sessionId, id, response);
    this.permissions.respond(runtime.projectKey, state.sessionId, id, response);
    state.status = 'running';
    state.interaction = null;
    state.revision++;
    state.updatedAt = new Date().toISOString();
    await this.store.write(runtime.root, state);
    return state;
  }

  private async autoApprovePermission(runtime: RuntimeRecord, sessionId: string) {
    return await this.withSessionLock(runtime, sessionId, async () => {
      return await this.autoApprovePermissionUnlocked(runtime, await this.require(runtime, sessionId));
    });
  }
  private async applyPendingPermissions(runtime: RuntimeRecord, sessionId: string, pending: any[], expectedRevision?: number, expectedInteractionId?: string | null) {
    return await this.withSessionLock(runtime, sessionId, async () => {
      const current = await this.require(runtime, sessionId);
      const currentInteractionId = (current.interaction as any)?.id == null ? null : String((current.interaction as any).id);
      if ((expectedRevision !== undefined && current.revision !== expectedRevision) ||
          (expectedInteractionId !== undefined && currentInteractionId !== expectedInteractionId)) {
        if (expectedInteractionId !== undefined && expectedInteractionId !== null && currentInteractionId !== expectedInteractionId) {
          this.permissions?.discard(expectedInteractionId);
        }
        return current;
      }
      if (terminal.has(current.status as OpenCodeStatus) || current.status === 'awaiting_permission') return current;
      const mapped = this.permissionFrom(runtime, sessionId, pending[0]);
      if (!mapped.id || !this.permissions) return current;
      current.status = 'awaiting_permission';
      current.interaction = this.permissions.add({ ...mapped.request, id: mapped.id });
      current.revision++;
      current.updatedAt = new Date().toISOString();
      await this.store.write(runtime.root, current);
      return await this.autoApprovePermissionUnlocked(runtime, current);
    });
  }

  private async permissionStillPending(runtime: RuntimeRecord, sessionId: string, id: string): Promise<boolean | undefined> {
    const list = await this.permissionList(runtime);
    if (list === undefined || list === null) return undefined;
    return list.some(item => String(item?.id ?? item?.permissionID ?? item?.permissionId) === id);
  }

  private isSessionEvent(event: ServerEvent, sessionId: string) {
    const data = event.data as any;
    const properties = data?.properties ?? data;
    if (event.event === 'server.connected' || data?.type === 'server.connected') return false;
    const eventSessionId = properties?.sessionID ?? properties?.sessionId ?? properties?.session?.id;
    return eventSessionId === sessionId;
  }

  private consumeEvent(runtime: RuntimeRecord, state: SessionStateRecord, event: ServerEvent) {
    if (!this.isSessionEvent(event, state.sessionId)) return false;
    const data = event.data as any;
    const properties = data?.properties ?? data;
    const sessionId = properties?.sessionID ?? properties?.sessionId ?? properties?.session?.id;
    if (sessionId && sessionId !== state.sessionId) return false;
    const eventType = data?.type ?? event.event;
    if (eventType === 'session.error' || event.event === 'session.error') {
      state.status = 'failed';
      state.progress = String(properties?.message ?? properties?.error ?? 'OpenCode Session failed');
      state.interaction = null;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      return true;
    }
    const raw = properties?.permission !== undefined ? { permission: properties.permission, ...properties } : properties;
    const mapped = this.permissionFrom(runtime, state.sessionId, raw);
    const isPermissionEvent = eventType === 'permission.updated' || eventType === 'permission.requested' ||
      eventType === 'permission.asked' || Boolean(raw?.permission);
    if (mapped.id && this.permissions && isPermissionEvent) {
      const item = this.permissions.add({ ...mapped.request, id: mapped.id });
      state.status = 'awaiting_permission';
      state.interaction = item;
      state.revision++;
      state.updatedAt = new Date().toISOString();
      return true;
    }
    return false;
  }

  private permissionFrom(runtime: RuntimeRecord, sessionId: string, source: any) {
    const permission = source?.permission;
    const id = source?.permissionID ?? source?.permissionId ??
      (typeof permission === 'object' && permission ? permission.id : undefined) ?? source?.id;
    const rawType = source?.type;
    const eventLikeType = typeof rawType === 'string' && rawType.startsWith('permission.');
    const type = (typeof permission === 'string' ? permission : permission?.type ?? permission?.title) ??
      (!eventLikeType ? rawType : undefined) ?? source?.title ?? 'unknown';
    const requestValues = (typeof permission === 'object' && permission
      ? permission.patterns ?? permission.paths ?? permission.metadata?.patterns ?? [permission.path ?? permission.target ?? permission.pattern]
      : undefined) ?? source?.patterns ?? source?.paths ?? [source?.path ?? source?.target ?? source?.pattern];
    const alwaysValues = (typeof permission === 'object' && permission
      ? permission.always ?? permission.metadata?.always
      : undefined) ?? source?.always;
    const request = this.classifyScope(requestValues, runtime.root);
    const always = this.classifyScope(alwaysValues, runtime.root);
    const operation = (typeof source?.tool === 'string' ? source.tool : source?.tool?.name) ??
      (typeof permission === 'object' && permission ? permission.tool : undefined) ??
      source?.metadata?.tool ?? source?.metadata?.operation ?? source?.operation;
    return {
      id: id === undefined || id === null ? undefined : String(id),
      request: {
        id: id === undefined || id === null ? undefined : String(id),
        projectKey: runtime.projectKey,
        sessionId,
        permission: String(type),
        type: String(type),
        operation: operation === undefined || operation === null ? undefined : String(operation),
        target: request.targets.length ? request.targets.join(', ') : undefined,
        outside: request.outside,
        unknownScope: request.unknown,
        alwaysOutside: always.outside,
        alwaysUnknown: always.unknown,
        alwaysTargets: always.targets.length ? always.targets : undefined
      } as const
    };
  }

  private classifyScope(values: unknown, root: string) {
    const texts = (Array.isArray(values) ? values : [values])
      .filter(value => value !== undefined && value !== null && value !== '')
      .map(value => String(value));
    if (texts.length === 0) return { targets: [], outside: false, unknown: true };
    const rootAbs = path.resolve(root);
    let outside = false;
    let unknown = false;
    for (const text of texts) {
      if (/[*?[\]{}]/.test(text)) unknown = true;
      const stripped = text.replace(/[*?[\]{}].*$/, '');
      const resolved = path.resolve(rootAbs, stripped);
      const rel = path.relative(rootAbs, resolved);
      if (rel !== '' && (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel))) outside = true;
    }
    return { targets: texts, outside, unknown };
  }

  private async withSessionLock<T>(runtime: RuntimeRecord, sessionId: string, fn: () => Promise<T>): Promise<T> {
    return await this.lock.withLock(runtime.root, sessionId, fn);
  }

  private snapshot(state: SessionStateRecord, changed: boolean) {
    return {
      sessionId: state.sessionId,
      status: state.status,
      revision: state.revision,
      changed,
      progress: state.progress ?? null,
      interaction: state.interaction ?? null,
      finalMessageAvailable: state.status === 'completed',
      codespecSnapshotPath: state.codespecSnapshotPath ?? null,
      workspaceSnapshotPath: state.workspaceSnapshotPath ?? null,
      ...(this.permissionQuerySupported === false ? { permissionQuery: 'unsupported' as const } : {})
    };
  }
}
