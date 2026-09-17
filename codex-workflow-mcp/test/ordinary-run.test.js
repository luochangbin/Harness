import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { SessionManager } from '../dist/session-manager.js';
import { SessionStateStore } from '../dist/runtime-store.js';
import { canonicalRoot, projectKey } from '../dist/project-key.js';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { registerOrdinaryTools } from '../dist/ordinary-tools.js';

function runtimeFor(root) {
  return {
    schemaVersion: 1,
    projectKey: projectKey(root),
    root: canonicalRoot(root),
    host: '127.0.0.1',
    port: 1,
    username: 'opencode',
    password: 'x',
    instanceId: 'ocs_test',
    pid: process.pid,
    opencodeVersion: 'test',
    startedAt: '',
    updatedAt: ''
  };
}

function fakeClient() {
  const calls = [];
  let nextSession = 0;
  return {
    calls,
    create: async () => 'ordinary_session_' + (++nextSession),
    send: async (_runtime, sessionId, prompt) => {
      calls.push({ sessionId, prompt });
      return { accepted: true };
    },
    messages: async () => [],
    status: async (_runtime, sessionId) => ({ id: sessionId, status: 'running' }),
    events: async () => new Response('')
  };
}

async function managerFor() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-ordinary-run-'));
  const client = fakeClient();
  const store = new SessionStateStore(path.join(root, '.state'));
  const manager = new SessionManager(client, store);
  return { root, runtime: runtimeFor(root), client, manager, store };
}

test('ordinary namespace cannot resolve as an AR binding or phase batch', async () => {
  const { root, runtime, manager } = await managerFor();
  await manager.create(runtime, {
    change: 'shared-name',
    namespace: 'ordinary',
    runKey: 'ordinary:shared-name',
    agent: 'ar-worker',
    access: 'workspace-write'
  });

  assert.equal(await manager.binding(runtime, 'shared-name'), null);
  const ordinary = await manager.binding(runtime, 'shared-name', 'ordinary');
  assert.equal(ordinary.namespace, 'ordinary');
  assert.equal(ordinary.runKey, 'ordinary:shared-name');
  await assert.rejects(
    () => manager.sendBound(runtime, 'shared-name', '1', 'must not resolve', 0, 'implementation', 'C:\\snapshot', 'C:\\workspace'),
    { code: 'SESSION_NOT_FOUND' }
  );
});

test('ordinary dot suffix is accepted through creation intent and runtime paths', async () => {
  const { root, runtime, manager, store } = await managerFor();
  const created = await manager.create(runtime, {
    change: 'fix.login',
    namespace: 'ordinary',
    runKey: 'ordinary:fix.login',
    agent: 'ar-worker',
    access: 'workspace-write'
  });
  const binding = await manager.binding(runtime, 'fix.login', 'ordinary');
  assert.equal(binding.sessionId, created.sessionId);
  assert.equal(binding.runKey, 'ordinary:fix.login');
  assert.equal(await store.readCreation(root, 'fix.login', 'ordinary'), null);
});

test('ordinary public tools/call query returns binding without creating or sending', async () => {
  const root = 'C:\\repo';
  const runtime = { projectKey: 'sha256:test', root };
  const calls = { create: 0, send: 0 };
  const binding = { sessionId: 'ordinary_session_1', agent: 'ar-worker', access: 'workspace-write', status: 'running', revision: 3, namespace: 'ordinary', runKey: 'ordinary:fix.login' };
  const fakeManager = {
    binding: async (_runtime, suffix, namespace) => namespace === 'ordinary' && suffix === 'fix.login' ? binding : null,
    create: async () => { calls.create++; return binding; },
    sendOrdinary: async () => { calls.send++; return { accepted: true, sessionId: binding.sessionId, status: 'running', revision: 4 }; }
  };
  const server = new McpServer({ name: 'test', version: '1' });
  const locks = { owner: () => null, restore: () => {}, update: () => {} };
  registerOrdinaryTools(server, {
    startProject: async () => runtime,
    synchronizeWriter: async () => {},
    projectFileLock: { withLock: async (_root, fn) => fn() },
    sessionManager: fakeManager,
    locks
  });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'test-client', version: '1' }, { capabilities: {} });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const response = await client.callTool({ name: 'opencode_run_binding', arguments: { root, runKey: 'ordinary:fix.login' } });
  const value = JSON.parse(response.content[0].text);
  assert.deepEqual(value.binding, binding);
  assert.deepEqual(calls, { create: 0, send: 0 });
  const missing = await client.callTool({ name: 'opencode_run_binding', arguments: { root, runKey: 'ordinary:missing' } });
  assert.equal(JSON.parse(missing.content[0].text).binding, null);
  await client.close();
});

test('ordinary public tools/call supports dot suffix first send and same-session repair', async () => {
  const root = 'C:\\repo';
  const runtime = { projectKey: 'sha256:test', root };
  const calls = { create: 0, send: 0, namespaces: [] };
  let state = null;
  const fakeManager = {
    binding: async (_runtime, suffix, namespace) => {
      calls.namespaces.push(namespace);
      return namespace === 'ordinary' && suffix === 'fix.login' ? state : null;
    },
    create: async (_runtime, options) => {
      calls.create++;
      state ??= { sessionId: 'ordinary_session_1', agent: options.agent, access: options.access, status: 'ready', revision: 0, namespace: 'ordinary', runKey: options.runKey };
      return state;
    },
    sendOrdinary: async (_runtime, sessionId, runKey, _batch, _prompt, expectedRevision) => {
      calls.send++;
      assert.equal(sessionId, 'ordinary_session_1');
      assert.equal(runKey, 'ordinary:fix.login');
      assert.equal(expectedRevision, state.revision);
      state = { ...state, status: 'running', revision: state.revision + 1 };
      return { accepted: true, sessionId, status: 'running', revision: state.revision };
    }
  };
  const server = new McpServer({ name: 'test', version: '1' });
  const locks = { owner: () => null, restore: () => {}, update: () => {} };
  registerOrdinaryTools(server, {
    startProject: async () => runtime,
    synchronizeWriter: async () => {},
    projectFileLock: { withLock: async (_root, fn) => fn() },
    sessionManager: fakeManager,
    locks
  });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'test-client', version: '1' }, { capabilities: {} });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const args = { root, runKey: 'ordinary:fix.login', taskBatch: 'all', prompt: 'fix', agent: 'ar-worker', access: 'workspace-write', expectedRevision: 0, codespecSnapshotPath: 'C:\\snap', workspaceSnapshotPath: 'C:\\workspace' };
  const first = await client.callTool({ name: 'opencode_run', arguments: args });
  assert.equal(JSON.parse(first.content[0].text).sessionId, 'ordinary_session_1');
  const second = await client.callTool({ name: 'opencode_run', arguments: { ...args, prompt: 'repair', expectedRevision: 1 } });
  assert.equal(JSON.parse(second.content[0].text).revision, 2);
  assert.equal(calls.send, 2);
  assert.ok(calls.namespaces.every(namespace => namespace === 'ordinary'));
  await client.close();
});

test('ordinary runKey cannot bind to a same-suffix full AR Session', async () => {
  const { runtime, manager } = await managerFor();
  const ar = await manager.create(runtime, {
    change: 'collision',
    agent: 'ar-worker',
    access: 'workspace-write'
  });
  const ordinary = await manager.create(runtime, {
    change: 'collision',
    namespace: 'ordinary',
    runKey: 'ordinary:collision',
    agent: 'ar-worker',
    access: 'workspace-write'
  });

  assert.notEqual(ordinary.sessionId, ar.sessionId);
  assert.equal((await manager.binding(runtime, 'collision')).sessionId, ar.sessionId);
  assert.equal((await manager.binding(runtime, 'collision', 'ordinary')).sessionId, ordinary.sessionId);
  await assert.rejects(
    () => manager.sendOrdinary(runtime, ar.sessionId, 'ordinary:collision', '1.1', 'must not cross bind', 0, 'C:\\snapshot', 'C:\\workspace'),
    { code: 'SESSION_NOT_FOUND' }
  );
});

test('ordinary run keeps one Session across first send and repair', async () => {
  const { root, runtime, manager, client, store } = await managerFor();
  const created = await manager.create(runtime, {
    change: 'machine-42',
    namespace: 'ordinary',
    runKey: 'ordinary:machine-42',
    agent: 'ar-worker',
    access: 'workspace-write'
  });
  const first = await manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-42', '1.1', 'first task', 0, 'C:\\snapshot', 'C:\\workspace');
  const state = await manager.binding(runtime, 'machine-42', 'ordinary');
  state.status = 'completed';
  await store.write(root, state);
  const repaired = await manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-42', '1.1', 'repair task', first.revision, 'C:\\snapshot', 'C:\\workspace');

  assert.equal(repaired.sessionId, created.sessionId);
  assert.equal(client.calls.length, 2);
  assert.match(client.calls[0].prompt, /Ordinary OpenCode run: ordinary:machine-42/);
  assert.doesNotMatch(client.calls[0].prompt, /ordinary:ordinary:/);
  assert.match(client.calls[0].prompt, /Task batch: 1\.1/);
  assert.match(client.calls[1].prompt, /repair task/);
});

test('ordinary sends serialize and reject stale revisions', async () => {
  const { runtime, manager } = await managerFor();
  const created = await manager.create(runtime, {
    change: 'machine-race',
    namespace: 'ordinary',
    runKey: 'ordinary:machine-race',
    agent: 'ar-worker',
    access: 'workspace-write'
  });
  const results = await Promise.allSettled([
    manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-race', '1.1', 'one', 0, 'C:\\snapshot', 'C:\\workspace'),
    manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-race', '1.1', 'two', 0, 'C:\\snapshot', 'C:\\workspace')
  ]);
  assert.equal(results.filter(item => item.status === 'fulfilled').length, 1);
  assert.equal(results.filter(item => item.status === 'rejected' && item.reason.code === 'REVISION_CONFLICT').length, 1);
});

test('ordinary send preserves snapshot safety checks', async () => {
  const { runtime, manager } = await managerFor();
  const created = await manager.create(runtime, {
    change: 'machine-snapshot',
    namespace: 'ordinary',
    runKey: 'ordinary:machine-snapshot',
    agent: 'ar-worker',
    access: 'workspace-write'
  });
  await assert.rejects(
    () => manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-snapshot', 'all', 'task', 0, 'relative', 'C:\\workspace'),
    { code: 'INVALID_SNAPSHOT_PATH' }
  );
  await assert.rejects(
    () => manager.sendOrdinary(runtime, created.sessionId, 'ordinary:machine-snapshot', 'all', 'task', 0, 'C:\\snapshot', undefined),
    { code: 'INVALID_SNAPSHOT_PATH' }
  );
});
