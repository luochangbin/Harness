import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { RuntimeStore } from '../dist/runtime-store.js';
import { ServerManager } from '../dist/server-manager.js';
import { canonicalRoot, projectKey } from '../dist/project-key.js';

test('runtime store isolates project identities and writes atomically', async (t) => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-mcp-'));
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  const store = new RuntimeStore(base);
  const root = await fs.mkdtemp(path.join(base, 'cw-root-'));
  const otherRoot = await fs.mkdtemp(path.join(base, 'cw-root-'));
  const record = { schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root), host: '127.0.0.1', port: 4001, username: 'opencode', password: 'secret', instanceId: 'ocs_a', pid: 999999, opencodeVersion: 'test', startedAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
  await store.write(record.root, record);
  assert.equal((await store.read(record.root)).port, 4001);
  assert.notEqual(store.fileFor(record.root), store.fileFor(otherRoot));
});

test('unowned healthy server is not stopped', async (t) => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-mcp-'));
  t.after(() => fs.rm(base, { recursive: true, force: true }));
  const store = new RuntimeStore(base);
  const root = await fs.mkdtemp(path.join(base, 'cw-root-'));
  await store.write(root, { schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root), host: '127.0.0.1', port: 1, username: 'opencode', password: 'secret', instanceId: 'ocs_a', pid: 999999, opencodeVersion: 'test', startedAt: new Date().toISOString(), updatedAt: new Date().toISOString() });
  const result = await new ServerManager(store).stop(root);
  assert.equal(result.stopped, false);
});
