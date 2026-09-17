import fs from 'node:fs/promises';
import path from 'node:path';
import { BrokerError } from './errors.js';
import { canonicalRoot, projectKey, runtimeBaseDir } from './project-key.js';

export type RuntimeRecord = {
  schemaVersion: 1;
  projectKey: string;
  root: string;
  host: '127.0.0.1';
  port: number;
  username: string;
  password: string;
  instanceId: string;
  pid: number;
  opencodeVersion: string;
  startedAt: string;
  updatedAt: string;
};

export type SessionCreationRecord = {
  schemaVersion: 1;
  namespace?: 'ar' | 'ordinary';
  runKey?: string;
  projectKey: string;
  root: string;
  change: string;
  requestId: string;
  title: string;
  agent: string;
  access: 'read-only' | 'workspace-write';
  updatedAt: string;
};
export type SessionReplacementRecord = {
  schemaVersion: 1;
  projectKey: string;
  root: string;
  change: string;
  previousSessionId: string;
  requestId?: string;
  title?: string;
  agent?: string;
  access?: 'read-only' | 'workspace-write';
  newSessionId?: string;
  pendingState?: SessionStateRecord;
  phase: 'creating' | 'created';
  updatedAt: string;
};

export type SessionStateRecord = {
  schemaVersion: 1;
  namespace?: 'ar' | 'ordinary';
  runKey?: string;
  projectKey: string;
  root: string;
  sessionId: string;
  change: string;
  agent: string;
  access: 'read-only' | 'workspace-write';
  revision: number;
  status: string;
  progress?: string;
  interaction?: unknown;
  baselineMessageCount?: number;
  baselineAssistantId?: string;
  pendingMessageId?: string;
  lastMessageId?: string;
  turnStartedAt?: string;
  codespecSnapshotPath?: string;
  workspaceSnapshotPath?: string;
  updatedAt: string;
};

function corrupt(message: string): never {
  throw new BrokerError('RUNTIME_CORRUPT', message);
}

async function atomicWrite(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = file + '.' + process.pid + '.' + Date.now() + '.tmp';
  try {
    await fs.writeFile(temp, JSON.stringify(value, null, 2) + '\n', { encoding: 'utf8', mode: 0o600 });
    await fs.rename(temp, file);
    await fs.chmod(file, 0o600).catch(() => undefined);
  } catch (error) {
    await fs.rm(temp, { force: true }).catch(() => undefined);
    throw error;
  }
}

export class RuntimeStore {
  constructor(readonly baseDir = runtimeBaseDir()) {}
  fileFor(root: string) { return path.join(this.baseDir, projectKey(root).slice('sha256:'.length), 'runtime.json'); }

  async read(root: string): Promise<RuntimeRecord | null> {
    const normalized = canonicalRoot(root);
    try {
      const value = JSON.parse(await fs.readFile(this.fileFor(normalized), 'utf8')) as Partial<RuntimeRecord>;
      if (value.schemaVersion !== 1 || value.projectKey !== projectKey(normalized) ||
          value.root !== normalized || value.host !== '127.0.0.1' ||
          typeof value.port !== 'number' || typeof value.pid !== 'number' ||
          typeof value.password !== 'string' || typeof value.instanceId !== 'string' ||
          typeof value.opencodeVersion !== 'string') {
        corrupt('Runtime identity or schema is invalid');
      }
      return value as RuntimeRecord;
    } catch (error: any) {
      if (error?.code === 'ENOENT') return null;
      if (error instanceof BrokerError) throw error;
      corrupt('Runtime state is unreadable');
    }
  }

  async write(root: string, record: RuntimeRecord): Promise<void> {
    const normalized = canonicalRoot(root);
    if (record.projectKey !== projectKey(normalized) || record.root !== normalized) {
      corrupt('Runtime identity does not match project root');
    }
    await atomicWrite(this.fileFor(normalized), { ...record, root: normalized });
  }

  async remove(root: string) { await fs.rm(this.fileFor(root), { force: true }); }
}

export class SessionStateStore {
  constructor(private readonly baseDir = runtimeBaseDir()) {}

  fileFor(root: string, sessionId: string) {
    if (!/^[A-Za-z0-9_-]{1,256}$/.test(sessionId)) corrupt('Invalid Session ID');
    return path.join(this.baseDir, projectKey(root).slice('sha256:'.length), 'sessions', sessionId + '.json');
  }

  async read(root: string, sessionId: string): Promise<SessionStateRecord | null> {
    try {
      const value = JSON.parse(await fs.readFile(this.fileFor(root, sessionId), 'utf8')) as Partial<SessionStateRecord>;
      if (value.schemaVersion !== 1 || value.projectKey !== projectKey(root) ||
          value.sessionId !== sessionId || typeof value.revision !== 'number' ||
          (value.namespace !== undefined && !['ar', 'ordinary'].includes(value.namespace)) ||
          (value.runKey !== undefined && typeof value.runKey !== 'string')) {
        corrupt('Session state is invalid');
      }
      return value as SessionStateRecord;
    } catch (error: any) {
      if (error?.code === 'ENOENT') return null;
      if (error instanceof BrokerError) throw error;
      corrupt('Session state is unreadable');
    }
  }

  async write(root: string, state: SessionStateRecord): Promise<void> {
    await atomicWrite(this.fileFor(root, state.sessionId), state);
  }

  async remove(root: string, sessionId: string) {
    await fs.rm(this.fileFor(root, sessionId), { force: true });
  }

  creationFileFor(root: string, change: string, namespace: 'ar' | 'ordinary' = 'ar') {
    const pattern = namespace === 'ordinary' ? /^[A-Za-z0-9_.-]{1,256}$/ : /^[A-Za-z0-9_-]{1,256}$/;
    if (!pattern.test(change)) corrupt('Invalid Session key');
    return path.join(this.baseDir, projectKey(root).slice('sha256:'.length), 'creations', namespace, change + '.json');
  }

  async readCreation(root: string, change: string, namespace: 'ar' | 'ordinary' = 'ar'): Promise<SessionCreationRecord | null> {
    try {
      const value = JSON.parse(await fs.readFile(this.creationFileFor(root, change, namespace), 'utf8')) as Partial<SessionCreationRecord>;
      if (value.schemaVersion !== 1 || value.projectKey !== projectKey(root) ||
          value.root !== canonicalRoot(root) || value.change !== change ||
          (value.namespace ?? 'ar') !== namespace ||
          typeof value.requestId !== 'string' ||
          !/^[A-Za-z0-9_-]{16,128}$/.test(value.requestId) ||
          typeof value.title !== 'string' || !value.title.includes(value.requestId) ||
          typeof value.agent !== 'string' ||
          !['read-only', 'workspace-write'].includes(value.access ?? '') ||
          typeof value.updatedAt !== 'string') {
        corrupt('Session creation state is invalid');
      }
      return value as SessionCreationRecord;
    } catch (error: any) {
      if (error?.code === 'ENOENT') return null;
      if (error instanceof BrokerError) throw error;
      corrupt('Session creation state is unreadable');
    }
  }

  async writeCreation(root: string, record: SessionCreationRecord): Promise<void> {
    const normalized = canonicalRoot(root);
    const namespace = record.namespace ?? 'ar';
    const changePattern = namespace === 'ordinary' ? /^[A-Za-z0-9_.-]{1,256}$/ : /^[A-Za-z0-9_-]{1,256}$/;
    if (record.projectKey !== projectKey(normalized) || record.root !== normalized ||
        record.change === '' || !changePattern.test(record.change) ||
        !/^[A-Za-z0-9_-]{16,128}$/.test(record.requestId) ||
        !record.title.includes(record.requestId) ||
        !record.agent || !['read-only', 'workspace-write'].includes(record.access) ||
        (namespace === 'ordinary' && record.runKey !== 'ordinary:' + record.change)) {
      corrupt('Session creation identity is invalid');
    }
    await atomicWrite(this.creationFileFor(normalized, record.change, namespace), { ...record, namespace, root: normalized });
  }

  async removeCreation(root: string, change: string, namespace: 'ar' | 'ordinary' = 'ar') {
    await fs.rm(this.creationFileFor(root, change, namespace), { force: true });
  }
  replacementFileFor(root: string, change: string) {
    if (!/^[A-Za-z0-9_-]{1,256}$/.test(change)) corrupt('Invalid AR change');
    return path.join(this.baseDir, projectKey(root).slice('sha256:'.length), 'replacements', change + '.json');
  }

  async readReplacement(root: string, change: string): Promise<SessionReplacementRecord | null> {
    try {
      const value = JSON.parse(await fs.readFile(this.replacementFileFor(root, change), 'utf8')) as Partial<SessionReplacementRecord>;
      if (value.schemaVersion !== 1 || value.projectKey !== projectKey(root) ||
          value.root !== canonicalRoot(root) || value.change !== change ||
          typeof value.previousSessionId !== 'string' ||
          (value.requestId !== undefined &&
           (typeof value.requestId !== 'string' ||
            !/^[A-Za-z0-9_-]{16,128}$/.test(value.requestId))) ||
          (value.title !== undefined && typeof value.title !== 'string') ||
          (value.agent !== undefined && typeof value.agent !== 'string') ||
          (value.access !== undefined &&
           !['read-only', 'workspace-write'].includes(value.access)) ||
          (value.newSessionId !== undefined && typeof value.newSessionId !== 'string') ||
          !['creating', 'created'].includes(value.phase ?? '') ||
          typeof value.updatedAt !== 'string') {
        corrupt('Session replacement state is invalid');
      }
      const markerFields = [value.requestId, value.title, value.agent, value.access];
      if (markerFields.some(item => item !== undefined) &&
          markerFields.some(item => item === undefined)) {
        corrupt('Session replacement creation marker is incomplete');
      }
      if (value.requestId !== undefined && !value.title?.includes(value.requestId)) {
        corrupt('Session replacement title does not contain its request marker');
      }
      const pending = value.pendingState as Partial<SessionStateRecord> | undefined;
      if (pending !== undefined && (
          pending.schemaVersion !== 1 ||
          pending.projectKey !== projectKey(root) ||
          pending.root !== canonicalRoot(root) ||
          pending.sessionId !== value.newSessionId ||
          pending.change !== change ||
          typeof pending.agent !== 'string' ||
          !['read-only', 'workspace-write'].includes(pending.access ?? '') ||
          typeof pending.revision !== 'number' ||
          typeof pending.status !== 'string' ||
          typeof pending.updatedAt !== 'string')) {
        corrupt('Session replacement pending state is invalid');
      }
      if (value.phase === 'created' &&
          (!value.newSessionId || !pending)) {
        corrupt('Created Session replacement is missing its pending state');
      }
      return value as SessionReplacementRecord;
    } catch (error: any) {
      if (error?.code === 'ENOENT') return null;
      if (error instanceof BrokerError) throw error;
      corrupt('Session replacement state is unreadable');
    }
  }

  async writeReplacement(root: string, record: SessionReplacementRecord): Promise<void> {
    const normalized = canonicalRoot(root);
    if (record.projectKey !== projectKey(normalized) || record.root !== normalized ||
        record.change === '' || !/^[A-Za-z0-9_-]{1,256}$/.test(record.change)) {
      corrupt('Session replacement identity is invalid');
    }
    const markerFields = [record.requestId, record.title, record.agent, record.access];
    if (markerFields.some(item => item !== undefined) &&
        markerFields.some(item => item === undefined)) {
      corrupt('Session replacement creation marker is incomplete');
    }
    if (record.requestId !== undefined &&
        (!/^[A-Za-z0-9_-]{16,128}$/.test(record.requestId) ||
         !record.title?.includes(record.requestId))) {
      corrupt('Session replacement creation marker is invalid');
    }
    this.fileFor(normalized, record.previousSessionId);
    if (record.newSessionId !== undefined) this.fileFor(normalized, record.newSessionId);
    if (record.newSessionId !== undefined && record.newSessionId === record.previousSessionId) {
      corrupt('Session replacement cannot reuse the previous Session');
    }
    if (record.phase === 'created' &&
        (!record.newSessionId || !record.pendingState ||
         record.pendingState.sessionId !== record.newSessionId ||
         record.pendingState.change !== record.change)) {
      corrupt('Created Session replacement is missing its pending state');
    }
    await atomicWrite(this.replacementFileFor(normalized, record.change), { ...record, root: normalized });
  }

  async removeReplacement(root: string, change: string) {
    await fs.rm(this.replacementFileFor(root, change), { force: true });
  }

  private async recoverReplacement(root: string, change: string): Promise<SessionStateRecord | null> {
    const intent = await this.readReplacement(root, change);
    if (!intent) return null;
    if (!intent.newSessionId) {
      // A creating intent may represent a remote Session whose response was lost.
      // Keep it until SessionManager reconciles the unique title marker.
      return null;
    }
    let next = await this.read(root, intent.newSessionId);
    if (!next) {
      if (!intent.pendingState) corrupt('Replacement intent cannot reconstruct the new Session');
      await this.write(root, intent.pendingState);
      next = await this.read(root, intent.newSessionId);
      if (!next) corrupt('Replacement recovery did not persist the new Session');
    }
    try {
      await this.remove(root, intent.previousSessionId);
      await this.removeReplacement(root, change);
    } catch {
      // The new state is already authoritative; keep the intent for the next recovery pass.
    }
    return next;
  }

  private async recoverReplacements(root: string): Promise<void> {
    const dir = path.dirname(this.replacementFileFor(root, 'placeholder'));
    let files: string[];
    try { files = await fs.readdir(dir); } catch (error: any) {
      if (error?.code === 'ENOENT') return;
      throw error;
    }
    for (const file of files.filter(item => item.endsWith('.json'))) {
      await this.recoverReplacement(root, file.slice(0, -5));
    }
  }

  async list(root: string): Promise<SessionStateRecord[]> {
    await this.recoverReplacements(root);
    const dir = path.dirname(this.fileFor(root, 'placeholder'));
    let files: string[];
    try { files = await fs.readdir(dir); } catch (error: any) {
      if (error?.code === 'ENOENT') return [];
      throw error;
    }
    const states: SessionStateRecord[] = [];
    for (const file of files.filter(item => item.endsWith('.json'))) {
      const state = await this.read(root, file.slice(0, -5));
      if (state) states.push(state);
    }
    return states;
  }

  async findByChange(root: string, change: string, namespace: 'ar' | 'ordinary' = 'ar'): Promise<SessionStateRecord | null> {
    const recovered = namespace === 'ar' ? await this.recoverReplacement(root, change) : null;
    if (recovered && (recovered.namespace ?? 'ar') === namespace) return recovered;
    const matches = (await this.list(root))
      .filter(state => state.change === change && (state.namespace ?? 'ar') === namespace)
      .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
    return matches.find(state => !['completed', 'failed', 'interrupted'].includes(state.status)) ?? matches[0] ?? null;
  }
}
