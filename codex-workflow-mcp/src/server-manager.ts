import { spawn, spawnSync, ChildProcess } from 'node:child_process';
import net from 'node:net';
import crypto from 'node:crypto';
import { canonicalRoot, projectKey } from './project-key.js';
import { BrokerError } from './errors.js';
import { Executable, resolveOpenCodeExecutable } from './executable.js';
import { RuntimeRecord, RuntimeStore } from './runtime-store.js';
import { ProjectFileLock } from './project-lock.js';

type Managed = { runtime: RuntimeRecord; child?: ChildProcess };

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.once('error', reject);
    socket.listen(0, '127.0.0.1', () => {
      const address = socket.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      socket.close(() => resolve(port));
    });
  });
}

function processAlive(pid: number) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch { return false; }
}

export class ServerManager {
  private readonly active = new Map<string, Managed>();
  private readonly starts = new Map<string, Promise<RuntimeRecord>>();
  private readonly idleTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly projectLock = new ProjectFileLock();
  private busyChecker: (root: string) => boolean | Promise<boolean> = () => false;
  constructor(
    private readonly store = new RuntimeStore(),
    private readonly executable: Executable = resolveOpenCodeExecutable()
  ) {}

  setBusyChecker(checker: (root: string) => boolean | Promise<boolean>) {
    this.busyChecker = checker;
  }

  async probe(root: string) {
    const normalized = canonicalRoot(root);
    const version = this.version();
    const existing = await this.store.read(normalized);
    if (!existing) {
      return {
        ok: true,
        projectKey: projectKey(normalized),
        root: normalized,
        opencode: { available: version !== null, version, entryType: this.executable.entryType ?? 'unknown' },
        server: { status: 'stopped', owned: false }
      };
    }
    const healthy = await this.isHealthy(existing);
    return {
      ok: true,
      projectKey: existing.projectKey,
      root: normalized,
      opencode: { available: version !== null, version: version ?? existing.opencodeVersion, entryType: this.executable.entryType ?? 'unknown' },
      server: { status: healthy ? 'ready' : 'unhealthy', owned: Boolean(this.active.get(normalized)?.child) }
    };
  }

  async recover(root: string): Promise<RuntimeRecord | null> {
    const normalized = canonicalRoot(root);
    const current = this.active.get(normalized);
    if (current && await this.isHealthy(current.runtime)) return current.runtime;
    const persisted = await this.store.read(normalized);
    if (!persisted || !await this.isHealthy(persisted)) return null;
    this.active.set(normalized, { runtime: persisted });
    this.scheduleIdle(normalized);
    return persisted;
  }

  async start(root: string): Promise<RuntimeRecord> {
    const normalized = canonicalRoot(root);
    const existingStart = this.starts.get(normalized);
    if (existingStart) return await existingStart;
    const task = this.startInternal(normalized);
    this.starts.set(normalized, task);
    try { return await task; } finally { this.starts.delete(normalized); }
  }

  private async startInternal(normalized: string): Promise<RuntimeRecord> {
    return await this.projectLock.withLock(normalized, () => this.startUnlocked(normalized));
  }

  private async startUnlocked(normalized: string): Promise<RuntimeRecord> {
    const current = this.active.get(normalized);
    if (current && await this.isHealthy(current.runtime)) {
      this.scheduleIdle(normalized);
      return current.runtime;
    }
    const persisted = await this.store.read(normalized);
    if (persisted && await this.isHealthy(persisted)) {
      this.active.set(normalized, { runtime: persisted });
      this.scheduleIdle(normalized);
      return persisted;
    }

    let lastError: unknown = undefined;
    for (let attempt = 0; attempt < 3; attempt++) {
      const port = await freePort();
      const password = crypto.randomBytes(32).toString('base64url');
      const args = [...this.executable.args, 'serve', '--hostname', '127.0.0.1', '--port', String(port)];
      let stderr = '';
      const child = spawn(this.executable.file, args, {
        cwd: normalized,
        env: {
          ...process.env,
          OPENCODE_SERVER_PASSWORD: password,
          OPENCODE_SERVER_USERNAME: 'opencode'
        },
        stdio: ['ignore', 'ignore', 'pipe'],
        windowsHide: true
      });
      child.stderr?.on('data', chunk => {
        stderr = (stderr + String(chunk)).slice(-4000);
        child.stderr?.resume();
      });
      child.stderr?.resume();
      child.once('error', error => { lastError = new BrokerError('SERVER_START_FAILED', error.message); });
      const now = new Date().toISOString();
      const runtime: RuntimeRecord = {
        schemaVersion: 1,
        projectKey: projectKey(normalized),
        root: normalized,
        host: '127.0.0.1',
        port,
        username: 'opencode',
        password,
        instanceId: 'ocs_' + crypto.randomBytes(12).toString('hex'),
        pid: child.pid ?? -1,
        opencodeVersion: this.version() ?? 'unknown',
        startedAt: now,
        updatedAt: now
      };
      try {
        await this.waitHealthy(runtime, child);
        await this.store.write(normalized, runtime);
        this.active.set(normalized, { runtime, child });
        this.scheduleIdle(normalized);
        return runtime;
      } catch (error) {
        const detail = stderr.replace(password, '<redacted>').trim().slice(-800);
        if (error instanceof BrokerError) {
          lastError = detail ? new BrokerError(error.code, error.message + ' | stderr: ' + detail) : error;
        } else {
          lastError = new BrokerError('SERVER_START_FAILED', (error instanceof Error ? error.message : String(error)) + (detail ? ' | stderr: ' + detail : ''));
        }
        if (child.pid) await this.terminate(child.pid, true);
      }
    }
    if (lastError instanceof BrokerError) throw lastError;
    throw new BrokerError('SERVER_START_FAILED', 'OpenCode Server failed to start');
  }

  async stop(root: string, mode: 'graceful' | 'force' = 'graceful', busyCheck?: () => boolean | Promise<boolean>) {
    const normalized = canonicalRoot(root);
    return await this.projectLock.withLock(normalized, async () => {
      const check = busyCheck ?? (() => this.busyChecker(normalized));
      if (mode === 'graceful' && await check()) {
        throw new BrokerError('PROJECT_BUSY', 'Project has a running or awaiting-permission Session');
      }
      const managed = this.active.get(normalized);
      const runtime = managed?.runtime ?? await this.store.read(normalized);
      if (!runtime) return { stopped: false, status: 'already_stopped' };
      const healthy = await this.isHealthy(runtime);
      if (!healthy && processAlive(runtime.pid)) {
        throw new BrokerError('SERVER_UNHEALTHY', 'Server identity or health could not be verified');
      }
      if (!healthy) {
        await this.store.remove(normalized);
        this.active.delete(normalized);
        this.clearIdle(normalized);
        return { stopped: false, status: 'already_stopped' };
      }
      if (mode === 'graceful' && !managed?.child) {
        throw new BrokerError('SERVER_NOT_OWNED', 'Server is healthy but not owned by this Broker');
      }
      await this.terminate(runtime.pid, mode === 'force');
      if (processAlive(runtime.pid)) throw new BrokerError('SERVER_STOP_FAILED', 'OpenCode Server did not exit');
      await this.store.remove(normalized);
      this.active.delete(normalized);
      this.clearIdle(normalized);
      return { stopped: true, status: 'stopped' };
    });
  }

  async stopAll() {
    for (const root of [...this.active.keys()]) {
      await this.stop(root, 'graceful', async () => await this.busyChecker(root)).catch(() => undefined);
    }
  }

  async request(runtime: RuntimeRecord, endpoint: string, init?: RequestInit & { timeoutMs?: number }): Promise<Response> {
    return await this.execute(runtime, endpoint, init, async response => response);
  }

  async requestJson<T = unknown>(runtime: RuntimeRecord, endpoint: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
    return await this.execute(runtime, endpoint, init, async response => {
      const text = await response.text();
      if (!text) return undefined as T;
      try { return JSON.parse(text) as T; }
      catch { throw new BrokerError('PROTOCOL_ERROR', 'OpenCode Server returned invalid JSON'); }
    });
  }

  private async execute<T>(runtime: RuntimeRecord, endpoint: string, init: (RequestInit & { timeoutMs?: number }) | undefined, consume: (response: Response) => Promise<T>): Promise<T> {
    const url = 'http://' + runtime.host + ':' + runtime.port + endpoint;
    const controller = new AbortController();
    const timeoutMs = init?.timeoutMs ?? 30000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const cancel = () => controller.abort(init?.signal?.reason);
    init?.signal?.addEventListener('abort', cancel, { once: true });
    try {
      const { timeoutMs: _timeoutMs, ...fetchInit } = init ?? {};
      const response = await fetch(url, {
        ...fetchInit,
        signal: controller.signal,
        headers: {
          authorization: 'Basic ' + Buffer.from(runtime.username + ':' + runtime.password).toString('base64'),
          ...(init?.headers ?? {})
        }
      });
      if (!response.ok) throw new BrokerError('SERVER_HTTP_ERROR', 'OpenCode Server returned HTTP ' + response.status);
      return await consume(response);
    } catch (error) {
      if (error instanceof BrokerError) throw error;
      if (error instanceof Error && error.name === 'AbortError') throw new BrokerError('SERVER_TIMEOUT', 'OpenCode Server request timed out');
      throw new BrokerError('SERVER_UNREACHABLE', error instanceof Error ? error.message : String(error));
    } finally {
      clearTimeout(timer);
      init?.signal?.removeEventListener('abort', cancel);
    }
  }

  private version(): string | null {
    try {
      const result = spawnSync(this.executable.file, [...this.executable.args, '--version'], {
        encoding: 'utf8', windowsHide: true, timeout: 5000
      });
      if (result.status !== 0) return null;
      const value = String(result.stdout ?? '').trim();
      return value || null;
    } catch { return null; }
  }

  private async isHealthy(runtime: RuntimeRecord, timeoutMs = 30000) {
    if (!processAlive(runtime.pid)) return false;
    try {
      await this.requestJson(runtime, '/global/health', { timeoutMs });
      const body = await this.requestJson<{ path?: string; directory?: string }>(runtime, '/path', { timeoutMs });
      return canonicalRoot(body.path ?? body.directory ?? '') === canonicalRoot(runtime.root);
    } catch { return false; }
  }

  private async waitHealthy(runtime: RuntimeRecord, child: ChildProcess) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new BrokerError('SERVER_START_FAILED', 'OpenCode exited with code ' + child.exitCode);
      if (await this.isHealthy(runtime, 1000)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new BrokerError('SERVER_START_TIMEOUT', 'OpenCode Server health check timed out');
  }

  private async terminate(pid: number, force: boolean) {
    if (!processAlive(pid)) return;
    if (process.platform === 'win32') {
      const args = ['/PID', String(pid), '/T'];
      if (force) args.push('/F');
      spawnSync('taskkill.exe', args, { encoding: 'utf8', windowsHide: true });
      return;
    }
    try { process.kill(pid, force ? 'SIGKILL' : 'SIGTERM'); } catch { /* already exited */ }
  }

  private scheduleIdle(root: string) {
    this.clearIdle(root);
    const timer = setTimeout(async () => {
      if (await this.busyChecker(root)) {
        this.scheduleIdle(root);
        return;
      }
      await this.stop(root, 'graceful', async () => await this.busyChecker(root)).catch(() => this.scheduleIdle(root));
    }, 20 * 60 * 1000);
    this.idleTimers.set(root, timer);
  }

  private clearIdle(root: string) {
    const timer = this.idleTimers.get(root);
    if (timer) clearTimeout(timer);
    this.idleTimers.delete(root);
  }
}
