import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import { projectKey, runtimeBaseDir } from './project-key.js';
import { BrokerError } from './errors.js';

type Lease = { pid: number; id: string };

function alive(pid: number) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function safeName(name: string) {
  return name.replace(/[^A-Za-z0-9_.-]/g, '_');
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export class FileLock {
  constructor(
    private readonly baseDir: string,
    private readonly waitMs = 5000,
    private readonly busyCode = 'LOCK_BUSY',
    private readonly staleCode = 'LOCK_STALE',
    private readonly pollMs = 25
  ) {}

  private lockPath(name: string) { return path.join(this.baseDir, safeName(name) + '.lock'); }

  private async readOwner(file: string): Promise<Lease | null> {
    return await fs.readFile(file, 'utf8').then(value => JSON.parse(value) as Lease).catch(() => null);
  }

  private async probe(file: string): Promise<{ exists: boolean; owner: Lease | null }> {
    try {
      const stat = await fs.stat(file);
      if (!stat.isFile()) return { exists: true, owner: null };
    } catch {
      return { exists: false, owner: null };
    }
    let text: string;
    try {
      text = await fs.readFile(file, 'utf8');
    } catch (error: any) {
      // The holder released between stat and read.
      if (error?.code === 'ENOENT') return { exists: false, owner: null };
      return { exists: true, owner: null };
    }
    try {
      return { exists: true, owner: JSON.parse(text) as Lease };
    } catch {
      return { exists: true, owner: null };
    }
  }

  // Publishes the lease atomically: a fully written temp file is hard-linked
  // into place, so the lock artifact never exists without its complete owner.
  // There is therefore no "initializing" window another process could reclaim.
  private async publish(target: string, lease: Lease): Promise<boolean> {
    const temp = target + '.' + crypto.randomUUID() + '.tmp';
    await fs.writeFile(temp, JSON.stringify(lease), { encoding: 'utf8', mode: 0o600 });
    try {
      await fs.link(temp, target);
      return true;
    } catch (error: any) {
      if (error?.code === 'EEXIST') return false;
      throw error;
    } finally {
      await fs.rm(temp, { force: true }).catch(() => undefined);
    }
  }

  private async waitOrFail(deadline: number, message: string): Promise<void> {
    if (Date.now() >= deadline) throw new BrokerError(this.busyCode, message);
    await sleep(this.pollMs);
  }

  async withLock<T>(name: string, fn: () => Promise<T>): Promise<T> {
    const target = this.lockPath(name);
    const id = crypto.randomUUID();
    const lease: Lease = { pid: process.pid, id };
    await fs.mkdir(this.baseDir, { recursive: true });
    const deadline = Date.now() + this.waitMs;
    let spins = 0;
    for (;;) {
      if (++spins > 5000) throw new BrokerError(this.busyCode, 'Lock could not be acquired');
      if (await this.publish(target, lease)) {
        try { return await fn(); }
        finally {
          const owner = await this.readOwner(target);
          if (owner?.id === id) await fs.rm(target, { force: true }).catch(() => undefined);
        }
      }
      const observed = await this.probe(target);
      if (!observed.exists) continue;
      if (observed.owner && alive(observed.owner.pid)) {
        await this.waitOrFail(deadline, 'Lock is held by another process');
        continue;
      }
      // A holder is dead or the artifact is unreadable. Reclaiming it cannot be
      // made race-free with the available primitives, so fail closed instead of
      // ever deleting a lock that another process may have just acquired.
      throw new BrokerError(this.staleCode, 'Stale lock detected; remove it manually: ' + target +
        (observed.owner?.pid ? ' (holder pid ' + observed.owner.pid + ' is not running)' : ' (unreadable owner)'));
    }
  }
}

export class ProjectFileLock {
  private readonly inner: FileLock;
  constructor(baseDir = path.join(runtimeBaseDir(), 'locks')) {
    this.inner = new FileLock(baseDir, 0, 'PROJECT_LOCK_BUSY', 'PROJECT_LOCK_STALE');
  }

  withLock<T>(root: string, fn: () => Promise<T>): Promise<T> {
    return this.inner.withLock(projectKey(root).slice('sha256:'.length), fn);
  }
}

export class SessionFileLock {
  private readonly inner: FileLock;
  constructor(baseDir = path.join(runtimeBaseDir(), 'session-locks'), waitMs = 60000) {
    this.inner = new FileLock(baseDir, waitMs, 'SESSION_LOCK_BUSY', 'SESSION_LOCK_STALE');
  }

  withLock<T>(root: string, sessionId: string, fn: () => Promise<T>): Promise<T> {
    return this.inner.withLock(projectKey(root).slice('sha256:'.length) + '-' + sessionId, fn);
  }
}
