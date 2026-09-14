import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

export type Executable = { file: string; args: string[]; entryType?: 'exe' | 'cmd' | 'ps1' | 'unknown' };

export function resolveOpenCodeExecutable(file = 'opencode'): Executable {
  if (process.platform === 'win32' && !path.extname(file)) {
    const found = spawnSync('where.exe', [file], { encoding: 'utf8' }).stdout?.split(/\r?\n/).find(Boolean);
    if (found) {
      const base = found.trim();
      for (const candidate of [base + '.ps1', base + '.cmd', base + '.exe', base]) {
        if (fs.existsSync(candidate)) return resolveOpenCodeExecutable(candidate);
      }
    }
  }
  const lower = file.toLowerCase();
  if (lower.endsWith('.ps1')) return { file: 'pwsh.exe', args: ['-NoLogo', '-NoProfile', '-NonInteractive', '-File', path.resolve(file)], entryType: 'ps1' };
  if (lower.endsWith('.cmd')) return { file: 'cmd.exe', args: ['/d', '/s', '/c', 'call', path.resolve(file)], entryType: 'cmd' };
  if (lower.endsWith('.exe') || fs.existsSync(file)) return { file: path.resolve(file), args: [], entryType: 'exe' };
  return { file, args: [], entryType: 'unknown' };
}
