import test from 'node:test';
import assert from 'node:assert/strict';
import { SessionManager } from '../dist/session-manager.js';
import { SessionStateStore } from '../dist/runtime-store.js';
import { canonicalRoot, projectKey } from '../dist/project-key.js';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

test('send is asynchronous and wait timeout is not success', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-session-test-'));
  const runtime = { schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root), host: '127.0.0.1', port: 1, username: 'opencode', password: 'x', instanceId: 'ocs_test', pid: process.pid, opencodeVersion: 'test', startedAt: '', updatedAt: '' };
  let status = 'running';
  const client = { create: async () => 's1', send: async () => ({ accepted: true }), status: async () => ({ id: 's1', status }), events: async () => new Response('') };
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  assert.deepEqual(await manager.create(runtime, { change: 'AR-001-test', agent: 'ar-worker', access: 'workspace-write' }), { sessionId: 's1', change: 'AR-001-test', agent: 'ar-worker', access: 'workspace-write', status: 'ready', revision: 0 });
  assert.equal((await manager.send(runtime, 's1', 'AR-001-test', 'all', 'do it', 0)).accepted, true);
  const timeout = await manager.wait(runtime, 's1', 1, 1000); assert.equal(timeout.changed, false); assert.equal(timeout.status, 'running');
  status = 'completed'; const done = await manager.wait(runtime, 's1', 1, 1000); assert.equal(done.status, 'completed');
});

test('unknown status fails closed', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-session-test-'));
  const runtime = { schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root), host: '127.0.0.1', port: 1, username: 'opencode', password: 'x', instanceId: 'ocs_test', pid: process.pid, opencodeVersion: 'test', startedAt: '', updatedAt: '' };
  const client = { create: async () => 's2', status: async () => ({ id: 's2', status: 'unknown' }), events: async () => new Response('') };
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state'))); await manager.create(runtime, { change: 'AR-002-test', agent: 'ar-worker', access: 'workspace-write' });
  await assert.rejects(() => manager.result(runtime, 's2'), { code: 'SESSION_NOT_TERMINAL' });
});
