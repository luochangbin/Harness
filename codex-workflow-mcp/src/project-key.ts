import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { BrokerError } from './errors.js';

function reject(message: string): never {
  throw new BrokerError('INVALID_ROOT', message);
}

export function canonicalRoot(input: string): string {
  if (typeof input !== 'string' || !input.trim()) reject('Project root must not be empty');
  const resolved = path.resolve(input);
  let real: string;
  try {
    real = fs.realpathSync.native(resolved);
  } catch {
    reject('Project root does not exist: ' + input);
  }
  let normalized = path.normalize(real);
  if (process.platform === 'win32') {
    normalized = normalized.replace(/^\\\\\?\\/, '').toLowerCase();
  }
  const stat = fs.statSync(normalized);
  if (!stat.isDirectory()) reject('Project root must be a directory');
  const parsed = path.parse(normalized);
  const home = path.normalize(os.homedir()).toLowerCase();
  if (normalized === parsed.root.toLowerCase() || normalized === home) {
    reject('Project root must not be a filesystem root or user home');
  }
  return normalized;
}

export function projectKey(root: string): string {
  return 'sha256:' + crypto.createHash('sha256').update(canonicalRoot(root), 'utf8').digest('hex');
}

export function runtimeBaseDir(): string {
  if (process.platform === 'win32') return path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'codex-workflow', 'opencode');
  if (process.platform === 'darwin') return path.join(os.homedir(), 'Library', 'Application Support', 'codex-workflow', 'opencode');
  return path.join(process.env.XDG_STATE_HOME ?? path.join(os.homedir(), '.local', 'state'), 'codex-workflow', 'opencode');
}
