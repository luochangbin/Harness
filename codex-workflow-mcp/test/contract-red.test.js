import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { canonicalRoot, projectKey } from '../dist/project-key.js';
import { SessionManager } from '../dist/session-manager.js';
import { PermissionBridge } from '../dist/permissions.js';
import { OpenCodeClient } from '../dist/opencode-client.js';
import { waitForEvent } from '../dist/event-stream.js';
import { ProjectWriteLock } from '../dist/permissions.js';
import { ProjectFileLock } from '../dist/project-lock.js';

test('project keys use the prefixed hash and reject missing roots', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-contract-'));
  assert.equal(canonicalRoot(root), (await fs.realpath(root)).toLowerCase());
  assert.match(projectKey(root), /^sha256:[a-f0-9]{64}$/);
  assert.throws(() => canonicalRoot(path.join(root, 'missing')), { code: 'INVALID_ROOT' });
});

test('a new Session starts at revision zero and send enforces expectedRevision', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-session-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test',
    startedAt: '', updatedAt: ''
  };
  const client = {
    create: async () => 'ses_contract',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_contract', status: 'running' }),
    events: async () => new Response(''),
  };
  const manager = new SessionManager(client);
  assert.equal((await manager.create(runtime, {
    change: 'AR-001-test', agent: 'ar-worker', access: 'workspace-write'
  })).revision, 0);
  await assert.rejects(
    () => manager.send(runtime, 'ses_contract', 'AR-001-test', 'all', 'do it', 1),
    { code: 'REVISION_CONFLICT' }
  );
});

test('permission responses accept only once/always/reject and consume a known request once', () => {
  const bridge = new PermissionBridge();
  bridge.add({ id: 'perm_1', projectKey: 'sha256:' + 'a'.repeat(64), sessionId: 'ses_1', permission: 'read' });
  assert.equal(bridge.respond('sha256:' + 'a'.repeat(64), 'ses_1', 'perm_1', 'once').status, 'once');
  assert.throws(
    () => bridge.respond('sha256:' + 'a'.repeat(64), 'ses_1', 'perm_1', 'always'),
    { code: 'PERMISSION_NOT_FOUND' }
  );
});

test('OpenCode status uses the documented type envelope and result reads messages', async () => {
  const calls = [];
  const server = {
    requestJson: async (_runtime, endpoint) => {
      calls.push(endpoint);
      if (endpoint === '/session/status') return { s1: { type: 'busy' } };
      if (endpoint === '/session/s1/message') return [
        { info: { role: 'assistant', id: 'm1', usage: { input: 1 } }, parts: [{ type: 'text', text: 'done' }] }
      ];
      if (endpoint === '/session/s1/diff') return [{ path: 'src/a.ts' }];
      throw new Error('unexpected endpoint ' + endpoint);
    }
  };
  const client = new OpenCodeClient(server);
  const runtime = {};
  assert.equal((await client.status(runtime, 's1')).status, 'running');
  const result = await client.result(runtime, 's1');
  assert.equal(result.messages[0].parts[0].text, 'done');
  assert.deepEqual(result.diff, [{ path: 'src/a.ts' }]);
  assert.deepEqual(calls, ['/session/status', '/session/s1/message', '/session/s1/diff']);
});

test('OpenCode Session listing uses GET /session and normalizes the response', async () => {
  const calls = [];
  const server = {
    requestJson: async (_runtime, endpoint) => {
      calls.push(endpoint);
      return { sessions: [
        { id: 'ses_1', title: 'AR-001 [cw:marker]' },
        { sessionID: 'ses_2', title: 'AR-002 [cw:marker]' }
      ] };
    }
  };
  const client = new OpenCodeClient(server);
  assert.deepEqual(await client.listSessions({}), [
    { id: 'ses_1', title: 'AR-001 [cw:marker]' },
    { id: 'ses_2', title: 'AR-002 [cw:marker]' }
  ]);
  assert.deepEqual(calls, ['/session']);
});
test('completed Session accepts a later repair message in the same Session', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-repair-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  let status = 'running';
  let sends = 0;
  const client = {
    create: async () => 'ses_repair',
    send: async () => { sends++; return { accepted: true }; },
    status: async () => ({ id: 'ses_repair', status }),
    events: async () => new Response('')
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-repair', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_repair', 'AR-001-repair', 'all', 'first', 0);
  status = 'completed';
  const done = await manager.wait(runtime, 'ses_repair', 1, 1000);
  assert.equal(done.status, 'completed');
  const repaired = await manager.send(runtime, 'ses_repair', 'AR-001-repair', 'all', 'repair', done.revision);
  assert.equal(repaired.status, 'running');
  assert.equal(sends, 2);
});

test('two sends with the same revision serialize and only one is accepted', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-send-race-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  const client = {
    create: async () => 'ses_race',
    send: async () => { await new Promise(resolve => setTimeout(resolve, 25)); return { accepted: true }; },
    status: async () => ({ id: 'ses_race', status: 'running' }),
    events: async () => new Response('')
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-race', agent: 'ar-worker', access: 'workspace-write' });
  const results = await Promise.allSettled([
    manager.send(runtime, 'ses_race', 'AR-001-race', 'all', 'one', 0),
    manager.send(runtime, 'ses_race', 'AR-001-race', 'all', 'two', 0)
  ]);
  assert.equal(results.filter(item => item.status === 'fulfilled').length, 1);
  assert.equal(results.filter(item => item.status === 'rejected' && item.reason.code === 'REVISION_CONFLICT').length, 1);
});

test('permission event reads the documented properties envelope', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-event-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  const bridge = new PermissionBridge();
  const sse = 'data: ' + JSON.stringify({ type: 'permission.updated', properties: { id: 'perm_1', sessionID: 'ses_perm', type: 'file.write', title: 'Write file' } }) + '\n\n';
  const client = {
    create: async () => 'ses_perm',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_perm', status: 'running' }),
    events: async () => new Response(sse)
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-perm', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_perm', 'AR-001-perm', 'all', 'run', 0);
  const snapshot = await manager.wait(runtime, 'ses_perm', 1, 1000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.equal(snapshot.interaction.id, 'perm_1');
});

test('idle Session status is confirmed through the Session endpoint', async () => {
  const server = {
    requestJson: async (_runtime, endpoint) => {
      if (endpoint === '/session/status') return {};
      if (endpoint === '/session/s1') return { id: 's1', title: 'AR-001' };
      if (endpoint === '/session/s1/message') return [{ info: { role: 'assistant', time: { created: 1, completed: 2 } } }];
      throw new Error('unexpected endpoint ' + endpoint);
    }
  };
  const client = new OpenCodeClient(server);
  assert.equal((await client.status({}, 's1')).status, 'completed');
});

test('SSE wait ignores server handshake and keeps the stream until the target Session event', async () => {
  const sse = [
    'event: server.connected\ndata: {}\n\n',
    'data: ' + JSON.stringify({ type: 'session.status', properties: { sessionID: 's1', status: 'busy' } }) + '\n\n'
  ].join('');
  const events = [];
  const event = await waitForEvent(
    new Response(sse),
    1000,
    undefined,
    item => { events.push(item.event); },
    item => item.event !== 'server.connected' && item.data?.properties?.sessionID === 's1'
  );
  assert.equal(event?.data?.properties?.sessionID, 's1');
  assert.deepEqual(events, ['server.connected', 'message']);
});

test('permission requests can be restored after the broker restarts', () => {
  const bridge = new PermissionBridge();
  const restored = bridge.restore({ id: 'perm_restore', projectKey: 'sha256:' + 'b'.repeat(64), sessionId: 'ses_restore', permission: 'read', type: 'read', target: 'src/app.ts', alwaysTargets: ['secret/token.txt'], status: 'pending' });
  assert.deepEqual(restored.allowedResponses, ['once', 'reject']);
  assert.equal(bridge.pending('sha256:' + 'b'.repeat(64), 'ses_restore')?.id, 'perm_restore');
});

test('project write lock rejects a repair while another Session owns the project', () => {
  const locks = new ProjectWriteLock();
  locks.acquire('sha256:' + 'c'.repeat(64), 'ses_a', 'workspace-write', 'running');
  assert.throws(
    () => locks.acquire('sha256:' + 'c'.repeat(64), 'ses_b', 'workspace-write', 'ready'),
    { code: 'PROJECT_WRITER_BUSY' }
  );
});

test('recovery refreshes the cached Session revision from disk', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-recovery-cache-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  const { SessionStateStore } = await import('../dist/runtime-store.js');
  const store = new SessionStateStore(path.join(root, '.state'));
  let sends = 0;
  const client = {
    create: async () => 'ses_cache',
    send: async () => { sends++; return { accepted: true }; },
    status: async () => ({ id: 'ses_cache', status: 'completed' }),
    events: async () => new Response('')
  };
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-cache', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_cache', 'AR-001-cache', 'all', 'run', 0);
  const persisted = await store.read(root, 'ses_cache');
  persisted.status = 'completed';
  persisted.revision = 2;
  await store.write(root, persisted);
  await manager.recoverWriter(runtime);
  const result = await manager.send(runtime, 'ses_cache', 'AR-001-cache', 'all', 'repair', 2);
  assert.equal(result.revision, 3);
  assert.equal(sends, 2);
});

test('recovery preserves persisted permission interaction and restores its bridge entry', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-recovery-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  const { SessionStateStore } = await import('../dist/runtime-store.js');
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const client = {
    create: async () => 'ses_perm_recovery',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_perm_recovery', status: 'running' }),
    events: async () => new Response('')
  };
  const manager = new SessionManager(client, store, bridge);
  await manager.create(runtime, { change: 'AR-001-perm-recovery', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_perm_recovery');
  state.status = 'awaiting_permission';
  state.revision = 1;
  state.interaction = { id: 'perm_recovery', projectKey: runtime.projectKey, sessionId: 'ses_perm_recovery', permission: 'file.write', status: 'pending' };
  await store.write(root, state);
  const recovered = await manager.recoverWriter(runtime);
  assert.equal(recovered.status, 'awaiting_permission');
  assert.equal(bridge.pending(runtime.projectKey, 'ses_perm_recovery')?.id, 'perm_recovery');
});
test('an existing but empty Session is not reported completed', async () => {
  const server = {
    requestJson: async (_runtime, endpoint) => {
      if (endpoint === '/session/status') return {};
      if (endpoint === '/session/s1') return { id: 's1' };
      if (endpoint === '/session/s1/message') return [];
      throw new Error('unexpected endpoint ' + endpoint);
    }
  };
  const client = new OpenCodeClient(server);
  assert.notEqual((await client.status({}, 's1')).status, 'completed');
});

test('an empty SSE stream is bounded and does not reconnect in a tight loop', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-sse-eof-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  let calls = 0;
  const client = {
    create: async () => 'ses_eof',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_eof', status: 'running' }),
    events: async () => { calls++; return new Response(''); }
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-eof', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_eof', 'AR-001-eof', 'all', 'run', 0);
  await manager.wait(runtime, 'ses_eof', 1, 1000);
  assert.ok(calls <= 4, 'SSE EOF reconnects were not bounded: ' + calls);
});

test('a stale wait cannot overwrite an abort result', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-wait-abort-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  let streamController;
  let streamReady;
  const ready = new Promise(resolve => { streamReady = resolve; });
  const client = {
    create: async () => 'ses_abort_race',
    send: async () => ({ accepted: true }),
    abort: async () => ({ status: 'interrupted' }),
    status: async () => ({ id: 'ses_abort_race', status: 'running' }),
    events: async () => new Response(new ReadableStream({ start(controller) { streamController = controller; streamReady(); } }))
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')), new PermissionBridge());
  await manager.create(runtime, { change: 'AR-001-abort-race', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_abort_race', 'AR-001-abort-race', 'all', 'run', 0);
  const waiting = manager.wait(runtime, 'ses_abort_race', 1, 1000);
  await ready;
  await manager.abort(runtime, 'ses_abort_race');
  streamController.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({ type: 'permission.updated', properties: { sessionID: 'ses_abort_race', id: 'perm_stale', type: 'read' } }) + '\n\n'));
  const result = await waiting;
  assert.equal(result.status, 'interrupted');
});

test('permission restoration applies to read-only Sessions too', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-readonly-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  const { SessionStateStore } = await import('../dist/runtime-store.js');
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const client = { create: async () => 'ses_ro_permission', status: async () => ({ id: 'ses_ro_permission', status: 'running' }), events: async () => new Response('') };
  const manager = new SessionManager(client, store, bridge);
  await manager.create(runtime, { change: 'AR-001-ro-permission', agent: 'ar-worker', access: 'read-only' });
  const state = await store.read(root, 'ses_ro_permission');
  state.status = 'awaiting_permission';
  state.interaction = { id: 'perm_ro', projectKey: runtime.projectKey, sessionId: 'ses_ro_permission', permission: 'read', status: 'pending' };
  await store.write(root, state);
  await manager.recoverWriter(runtime);
  assert.equal(bridge.pending(runtime.projectKey, 'ses_ro_permission')?.id, 'perm_ro');
});
test('project file lock serializes independent Broker instances', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-project-lock-'));
  const lockDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-lock-root-'));
  const first = new ProjectFileLock(lockDir);
  const second = new ProjectFileLock(lockDir);
  let release;
  const held = first.withLock(root, () => new Promise(resolve => { release = resolve; }));
  await new Promise(resolve => setTimeout(resolve, 25));
  await assert.rejects(() => second.withLock(root, async () => undefined), { code: 'PROJECT_LOCK_BUSY' });
  release();
  await held;
});
test('read-only Session refuses execution when the adapter cannot enforce a filesystem sandbox', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-readonly-send-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  let sends = 0;
  const client = { create: async () => 'ses_readonly_send', send: async () => { sends++; }, status: async () => ({ id: 'ses_readonly_send', status: 'ready' }), events: async () => new Response('') };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-readonly-send', agent: 'ar-worker', access: 'read-only' });
  await assert.rejects(() => manager.send(runtime, 'ses_readonly_send', 'AR-001-readonly-send', 'all', 'run', 0), { code: 'READ_ONLY_SESSION' });
  assert.equal(sends, 0);
});
test('idle status without an assistant message is not completion evidence', async () => {
  const server = {
    requestJson: async (_runtime, endpoint) => {
      if (endpoint === '/session/status') return { s_idle: { type: 'idle' } };
      if (endpoint === '/session/s_idle/message') return [];
      throw new Error('unexpected endpoint ' + endpoint);
    }
  };
  const client = new OpenCodeClient(server);
  assert.notEqual((await client.status({}, 's_idle')).status, 'completed');
});
test('a repair wait does not complete from the previous assistant message', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-old-assistant-'));
  const runtime = {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
  let messages = [{ info: { role: 'assistant', id: 'old' }, parts: [{ text: 'old result' }] }];
  const client = {
    create: async () => 'ses_old_assistant',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_old_assistant', status: 'completed' }),
    messages: async () => messages,
    events: async () => new Response('')
  };
  const manager = new SessionManager(client, new (await import('../dist/runtime-store.js')).SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-old-assistant', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_old_assistant', 'AR-001-old-assistant', 'all', 'first', 0);
  messages = [{ info: { role: 'assistant', id: 'old' }, parts: [{ text: 'old result' }] }];
  const beforeNewMessage = await manager.wait(runtime, 'ses_old_assistant', 1, 1000);
  assert.equal(beforeNewMessage.status, 'running');
  messages.push({ info: { role: 'assistant', id: 'new', time: { created: 3, completed: 4 } }, parts: [{ text: 'new result' }] });
  const afterNewMessage = await manager.wait(runtime, 'ses_old_assistant', beforeNewMessage.revision, 1000);
  assert.equal(afterNewMessage.status, 'completed');
});