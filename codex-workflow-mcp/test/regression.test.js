import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { SessionManager } from '../dist/session-manager.js';
import { OpenCodeClient } from '../dist/opencode-client.js';
import { SessionStateStore, RuntimeStore } from '../dist/runtime-store.js';
import { PermissionBridge } from '../dist/permissions.js';
import { ProjectFileLock, SessionFileLock } from '../dist/project-lock.js';
import { ServerManager } from '../dist/server-manager.js';
import { waitForEvent } from '../dist/event-stream.js';
import { canonicalRoot, projectKey } from '../dist/project-key.js';
import { BrokerError } from '../dist/errors.js';

async function runtimeFor(root) {
  return {
    schemaVersion: 1, projectKey: projectKey(root), root: canonicalRoot(root),
    host: '127.0.0.1', port: 1, username: 'opencode', password: 'x',
    instanceId: 'ocs_test', pid: 1, opencodeVersion: 'test', startedAt: '', updatedAt: ''
  };
}

function fakeClient(overrides = {}) {
  return {
    create: async () => 'ses_test',
    send: async () => ({ accepted: true }),
    status: async () => ({ id: 'ses_test', status: 'running' }),
    messages: async () => [],
    events: async () => new Response(''),
    ...overrides
  };
}

test('a new user message does not turn an old assistant reply into completion', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-user-'));
  const runtime = await runtimeFor(root);
  let messages = [{ info: { role: 'assistant', id: 'old' }, parts: [{ text: 'old' }] }];
  let status = 'completed';
  const manager = new SessionManager(fakeClient({ status: async () => ({ id: 'ses_test', status }), messages: async () => messages }), new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-user', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-user', 'all', 'go', 0);
  messages = [{ info: { role: 'assistant', id: 'old' }, parts: [{ text: 'old' }] }, { info: { role: 'user', id: 'u1' } }];
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'running');
});

test('an assistant error is surfaced as failed, not completed', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-error-'));
  const runtime = await runtimeFor(root);
  let messages = [{ info: { role: 'assistant', id: 'old' } }];
  const client = fakeClient({ status: async () => ({ id: 'ses_test', status: 'completed' }), messages: async () => messages });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-error', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-error', 'all', 'go', 0);
  messages = [
    { info: { role: 'assistant', id: 'old' } },
    { info: { role: 'user', id: 'u1' } },
    { info: { role: 'assistant', id: 'new', error: { name: 'APIError', data: { message: 'boom' } } } }
  ];
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'failed');
  assert.match(String(snapshot.progress), /boom/);
});

test('create is idempotent for the same agent and access, and rejects a different binding', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-idem-'));
  const runtime = await runtimeFor(root);
  const manager = new SessionManager(fakeClient(), new SessionStateStore(path.join(root, '.state')));
  const first = await manager.create(runtime, { change: 'AR-001-idem', agent: 'ar-worker', access: 'workspace-write' });
  const second = await manager.create(runtime, { change: 'AR-001-idem', agent: 'ar-worker', access: 'workspace-write' });
  assert.equal(second.sessionId, first.sessionId);
  assert.equal(second.recovered, true);
  await assert.rejects(
    () => manager.create(runtime, { change: 'AR-001-idem', agent: 'ar-worker', access: 'read-only' }),
    { code: 'SESSION_ALREADY_BOUND' }
  );
});

test('concurrent creates for one AR share one remote Session', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-create-race-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  let createCalls = 0;
  const client = fakeClient({
    create: async () => {
      createCalls += 1;
      await new Promise(resolve => setTimeout(resolve, 75));
      return 'ses_one';
    }
  });
  const firstManager = new SessionManager(client, store);
  const secondManager = new SessionManager(client, store);
  const [first, second] = await Promise.all([
    firstManager.create(runtime, {
      change: 'AR-001-create-race', agent: 'ar-worker', access: 'workspace-write'
    }),
    secondManager.create(runtime, {
      change: 'AR-001-create-race', agent: 'ar-worker', access: 'workspace-write'
    })
  ]);
  assert.equal(first.sessionId, 'ses_one');
  assert.equal(second.sessionId, 'ses_one');
  assert.equal(createCalls, 1);
});
test('create recovers a remote Session after the create response is lost', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-create-lost-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const remote = [];
  let createCalls = 0;
  const client = fakeClient({
    listSessions: async () => remote,
    create: async (_runtime, options) => {
      createCalls += 1;
      remote.push({ id: 'ses_created', title: options.title });
      throw new Error('response lost');
    }
  });
  const manager = new SessionManager(client, store);

  await assert.rejects(
    () => manager.create(runtime, {
      change: 'AR-001-create-lost', agent: 'ar-worker', access: 'workspace-write'
    }),
    /response lost/
  );
  const recovered = await manager.create(runtime, {
    change: 'AR-001-create-lost', agent: 'ar-worker', access: 'workspace-write'
  });

  assert.equal(recovered.sessionId, 'ses_created');
  assert.equal(recovered.recovered, true);
  assert.equal(createCalls, 1);
  assert.equal(await store.readCreation(root, 'AR-001-create-lost'), null);
});

test('replacement recovers a remote Session after the create response is lost', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-lost-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const remote = [];
  let createCalls = 0;
  const client = fakeClient({
    listSessions: async () => remote,
    create: async (_runtime, options) => {
      createCalls += 1;
      const id = createCalls === 1 ? 'ses_old' : 'ses_new';
      remote.push({ id, title: options.title });
      if (id === 'ses_new') throw new Error('response lost');
      return id;
    }
  });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, {
    change: 'AR-001-replace-lost', agent: 'old-agent', access: 'workspace-write'
  });
  const old = await store.read(root, 'ses_old');
  old.status = 'completed';
  await store.write(root, old);

  await assert.rejects(
    () => manager.replace(runtime, 'ses_old', {
      change: 'AR-001-replace-lost', agent: 'new-agent', access: 'workspace-write'
    }, 0),
    /response lost/
  );
  const recovered = await manager.replace(runtime, 'ses_old', {
    change: 'AR-001-replace-lost', agent: 'new-agent', access: 'workspace-write'
  }, 0);

  assert.equal(recovered.sessionId, 'ses_new');
  assert.equal(createCalls, 2);
  assert.equal(await store.read(root, 'ses_old'), null);
  assert.equal((await store.read(root, 'ses_new')).agent, 'new-agent');
});

test('create fails closed when the recovery marker matches multiple remote Sessions', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-create-ambiguous-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const remote = [];
  let createCalls = 0;
  const client = fakeClient({
    listSessions: async () => remote,
    create: async (_runtime, options) => {
      createCalls += 1;
      remote.push({ id: 'ses_a', title: options.title }, { id: 'ses_b', title: options.title });
      throw new Error('response lost');
    }
  });
  const manager = new SessionManager(client, store);
  await assert.rejects(
    () => manager.create(runtime, {
      change: 'AR-001-create-ambiguous', agent: 'ar-worker', access: 'workspace-write'
    }),
    /response lost/
  );
  await assert.rejects(
    () => manager.create(runtime, {
      change: 'AR-001-create-ambiguous', agent: 'ar-worker', access: 'workspace-write'
    }),
    { code: 'SESSION_CREATE_AMBIGUOUS' }
  );
  assert.equal(createCalls, 1);
});
test('an explicit replacement creates a new bound Session after the old one is terminal', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-'));
  const runtime = await runtimeFor(root);
  const ids = ['ses_old', 'ses_new'];
  const store = new SessionStateStore(path.join(root, '.state'));
  const client = fakeClient({ create: async () => ids.shift() });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-replace', agent: 'old-agent', access: 'workspace-write' });
  const old = await store.read(root, 'ses_old');
  old.status = 'completed';
  await store.write(root, old);

  const result = await manager.replace(runtime, 'ses_old', {
    change: 'AR-001-replace', agent: 'new-agent', access: 'workspace-write'
  }, 0);

  assert.equal(result.sessionId, 'ses_new');
  assert.equal(result.agent, 'new-agent');
  assert.equal(await store.read(root, 'ses_old'), null);
  assert.equal((await store.read(root, 'ses_new')).change, 'AR-001-replace');
});

test('replacement recovery reconstructs a persisted new state when its file is missing', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-pending-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const old = {
    schemaVersion: 1, projectKey: runtime.projectKey, root: runtime.root,
    sessionId: 'ses_old', change: 'AR-001-replace-pending', agent: 'old-agent',
    access: 'workspace-write', revision: 0, status: 'completed',
    updatedAt: new Date().toISOString()
  };
  const pending = {
    schemaVersion: 1, projectKey: runtime.projectKey, root: runtime.root,
    sessionId: 'ses_new', change: 'AR-001-replace-pending', agent: 'new-agent',
    access: 'workspace-write', revision: 0, status: 'ready',
    updatedAt: new Date().toISOString()
  };
  await store.write(root, old);
  await store.writeReplacement(root, {
    schemaVersion: 1, projectKey: runtime.projectKey, root: runtime.root,
    change: 'AR-001-replace-pending', previousSessionId: 'ses_old',
    newSessionId: 'ses_new', phase: 'created', pendingState: pending,
    updatedAt: new Date().toISOString()
  });
  const manager = new SessionManager(fakeClient(), store);
  const binding = await manager.binding(runtime, 'AR-001-replace-pending');
  assert.equal(binding.sessionId, 'ses_new');
  assert.equal((await store.read(root, 'ses_new')).agent, 'new-agent');
  assert.equal(await store.read(root, 'ses_old'), null);
  assert.equal(await store.readReplacement(root, 'AR-001-replace-pending'), null);
});

test('replacement recovery makes the new binding authoritative after cleanup failure', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-recover-'));
  const runtime = await runtimeFor(root);
  const ids = ['ses_old', 'ses_new'];
  class CleanupFailStore extends SessionStateStore {
    failed = false;
    async remove(removeRoot, sessionId) {
      if (sessionId === 'ses_old' && !this.failed) {
        this.failed = true;
        throw new Error('simulated cleanup failure');
      }
      return await super.remove(removeRoot, sessionId);
    }
  }
  const store = new CleanupFailStore(path.join(root, '.state'));
  const client = fakeClient({ create: async () => ids.shift() });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-replace-recover', agent: 'old-agent', access: 'workspace-write' });
  const old = await store.read(root, 'ses_old');
  old.status = 'completed';
  await store.write(root, old);

  const result = await manager.replace(runtime, 'ses_old', {
    change: 'AR-001-replace-recover', agent: 'new-agent', access: 'workspace-write'
  }, 0);

  assert.equal(result.sessionId, 'ses_new');
  assert.equal(result.cleanupPending, true);
  assert.equal((await manager.binding(runtime, 'AR-001-replace-recover')).sessionId, 'ses_new');
  assert.equal(await store.read(root, 'ses_old'), null);
  assert.equal(await store.readReplacement(root, 'AR-001-replace-recover'), null);
});

test('replacement reports success when only intent cleanup fails after commit', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-intent-'));
  const runtime = await runtimeFor(root);
  const ids = ['ses_old', 'ses_new'];
  class IntentCleanupFailStore extends SessionStateStore {
    failed = false;
    async removeReplacement(removeRoot, change) {
      if (!this.failed) {
        this.failed = true;
        throw new Error('simulated intent cleanup failure');
      }
      return await super.removeReplacement(removeRoot, change);
    }
  }
  const store = new IntentCleanupFailStore(path.join(root, '.state'));
  const client = fakeClient({ create: async () => ids.shift() });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-replace-intent', agent: 'old-agent', access: 'workspace-write' });
  const old = await store.read(root, 'ses_old');
  old.status = 'completed';
  await store.write(root, old);

  const result = await manager.replace(runtime, 'ses_old', {
    change: 'AR-001-replace-intent', agent: 'new-agent', access: 'workspace-write'
  }, 0);

  assert.equal(result.sessionId, 'ses_new');
  assert.equal(result.cleanupPending, true);
  assert.equal((await manager.binding(runtime, 'AR-001-replace-intent')).sessionId, 'ses_new');
});

test('replacement rejects a terminal Session that is no longer the current AR binding', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-replace-stale-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const manager = new SessionManager(fakeClient(), store);
  await manager.create(runtime, { change: 'AR-001-replace-stale', agent: 'old-agent', access: 'workspace-write' });
  const old = await store.read(root, 'ses_test');
  old.status = 'completed';
  await store.write(root, old);
  await store.write(root, { ...old, sessionId: 'ses_active', status: 'running', revision: 0 });

  await assert.rejects(
    () => manager.replace(runtime, 'ses_test', {
      change: 'AR-001-replace-stale', agent: 'new-agent', access: 'workspace-write'
    }, 0),
    { code: 'SESSION_BINDING_CONFLICT' }
  );
});

test('a bound send resolves the AR session but still enforces the caller revision', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-bound-send-'));
  const runtime = await runtimeFor(root);
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-bound');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '## 实施 Phases\n\n### Phase 1：实现\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '## Phase 1：实现\n\n- [ ] 1.1 完成实现\n', 'utf8');
  let sent = 0;
  let sentPrompt = '';
  const client = fakeClient({
    send: async (_runtime, _sessionId, prompt) => { sentPrompt = prompt; sent++; return { accepted: true }; }
  });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-bound', agent: 'ar-worker', access: 'workspace-write' });
  const result = await manager.sendBound(runtime, 'AR-001-bound', '1', '本次任务批次是：9.9\nfix issue', 0, 'implementation', path.join(root, 'codespec-snapshot.json'), path.join(root, 'workspace-snapshot.json'));
  assert.equal(result.accepted, true);
  assert.equal(result.sessionId, 'ses_test');
  assert.equal(sent, 1);
  assert.match(sentPrompt, /Task batch: 1\.1/);
  assert.match(sentPrompt, /authoritative Broker batch/i);
  assert.match(sentPrompt, /fix issue/);
  assert.match(sentPrompt, /WORKER_EXTERNAL_PATH_REQUIRED/);
  assert.match(sentPrompt, /WORKER_SKILL_UNAVAILABLE/);
  assert.match(sentPrompt, /Do not.*commit.*push/i);
  assert.equal((sentPrompt.match(/Task batch:/g) || []).length, 1);
  assert.doesNotMatch(sentPrompt, /本次任务批次是：9\.9/);
});

test('a bound send persists the workspace snapshot path for recovery', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-bound-snapshot-'));
  const runtime = await runtimeFor(root);
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-snapshot');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '### Phase 1：实现\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '## Phase 1：实现\n\n- [ ] 1.1 完成实现\n', 'utf8');
  const store = new SessionStateStore(path.join(root, '.state'));
  const manager = new SessionManager(fakeClient(), store);
  await manager.create(runtime, { change: 'AR-001-snapshot', agent: 'ar-worker', access: 'workspace-write' });
  const codespecSnapshotPath = path.join(root, 'codespec-snapshot.json');
  const workspaceSnapshotPath = path.join(root, 'workspace-snapshot.json');
  await manager.sendBound(runtime, 'AR-001-snapshot', '1', 'repair', 0, 'repair', codespecSnapshotPath, workspaceSnapshotPath);
  const persisted = await store.read(root, 'ses_test');
  assert.equal(persisted.codespecSnapshotPath, codespecSnapshotPath);
  assert.equal(persisted.workspaceSnapshotPath, workspaceSnapshotPath);
});
test('a bound send rejects a stale revision after an intervening Session update', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-bound-revision-'));
  const runtime = await runtimeFor(root);
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-bound-revision');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '## 实施 Phases\n\n### Phase 1：实现\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '## Phase 1：实现\n\n- [ ] 1.1 完成实现\n', 'utf8');
  const store = new SessionStateStore(path.join(root, '.state'));
  const manager = new SessionManager(fakeClient(), store);
  await manager.create(runtime, { change: 'AR-001-bound-revision', agent: 'ar-worker', access: 'workspace-write' });
  const state = await manager.binding(runtime, 'AR-001-bound-revision');
  state.revision = 1;
  await store.write(root, state);

  await assert.rejects(
    () => manager.sendBound(runtime, 'AR-001-bound-revision', '1', 'go', 0, 'implementation', path.join(root, 'codespec-snapshot.json'), path.join(root, 'workspace-snapshot.json')),
    { code: 'REVISION_CONFLICT' }
  );
});

test('a lost send response is reconciled through the message id instead of resending', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-send-'));
  const runtime = await runtimeFor(root);
  const sent = [];
  const client = fakeClient({
    send: async (_runtime, _sessionId, _prompt, _agent, messageId) => {
      sent.push(messageId);
      throw new BrokerError('SERVER_TIMEOUT', 'response lost after acceptance');
    },
    messages: async () => [{ info: { role: 'user', id: sent[0] } }]
  });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-send', agent: 'ar-worker', access: 'workspace-write' });
  await assert.rejects(() => manager.send(runtime, 'ses_test', 'AR-001-send', 'all', 'go', 0), { code: 'SERVER_TIMEOUT' });
  await assert.rejects(() => manager.send(runtime, 'ses_test', 'AR-001-send', 'all', 'go', 0), { code: 'REVISION_CONFLICT' });
  assert.equal(sent.length, 1);
});

test('a terminal abort cannot be downgraded by another broker observation', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-term-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const client = fakeClient({ abort: async () => ({ status: 'interrupted' }) });
  const a = new SessionManager(client, store);
  const b = new SessionManager(client, store);
  await a.create(runtime, { change: 'AR-001-term', agent: 'ar-worker', access: 'workspace-write' });
  await a.send(runtime, 'ses_test', 'AR-001-term', 'all', 'go', 0);
  await b.abort(runtime, 'ses_test');
  const snapshot = await a.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'interrupted');
});

test('usage aggregates assistant tokens, cache and cost for the turn', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-usage-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const client = fakeClient({
    result: async () => ({
      messages: [
        { info: { role: 'assistant', id: 'a0', tokens: { input: 1 } } },
        { info: { role: 'user', id: 'u1' } },
        { info: { role: 'assistant', id: 'a1', tokens: { input: 10, output: 20, reasoning: 3, cache: { read: 5, write: 2 } }, cost: 0.01 }, parts: [{ type: 'text', text: 'done' }] }
      ],
      diff: []
    })
  });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-usage', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'completed';
  state.baselineMessageCount = 2;
  await store.write(root, state);
  const result = await manager.result(runtime, 'ses_test');
  assert.equal(result.usage.input, 10);
  assert.equal(result.usage.output, 20);
  assert.equal(result.usage.reasoning, 3);
  assert.equal(result.usage.cacheRead, 5);
  assert.equal(result.usage.cacheWrite, 2);
  assert.equal(result.usage.cost, 0.01);
  assert.equal(result.usage.cacheStatus, 'supported');
});

test('usage reports unsupported cache instead of zero when the provider omits it', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-cache-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const client = fakeClient({
    result: async () => ({
      messages: [{ info: { role: 'assistant', id: 'a1', tokens: { input: 3, output: 4 }, cost: 0.02 }, parts: [{ type: 'text', text: 'ok' }] }],
      diff: []
    })
  });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-cache', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'completed';
  state.baselineMessageCount = 0;
  await store.write(root, state);
  const result = await manager.result(runtime, 'ses_test');
  assert.equal(result.usage.cacheStatus, 'unsupported');
  assert.equal(result.usage.cacheRead, undefined);
  assert.equal(result.usage.cacheWrite, undefined);
});

test('always is refused for external or unknown permissions but allowed for reads', () => {
  const bridge = new PermissionBridge();
  bridge.add({ id: 'pe', projectKey: 'a', sessionId: 's', permission: 'external_directory', type: 'external_directory', target: 'C:\\outside' });
  assert.throws(() => bridge.respond('a', 's', 'pe', 'always'), { code: 'PERMISSION_REQUIRED' });
  bridge.add({ id: 'pm', projectKey: 'a', sessionId: 's', permission: 'weird' });
  assert.throws(() => bridge.respond('a', 's', 'pm', 'always'), { code: 'PERMISSION_REQUIRED' });
  bridge.add({ id: 'po', projectKey: 'a', sessionId: 's', permission: 'read', type: 'read', target: 'C:\\private\\.env', outside: true });
  assert.throws(() => bridge.respond('a', 's', 'po', 'always'), { code: 'PERMISSION_REQUIRED' });
  bridge.add({ id: 'pr', projectKey: 'a', sessionId: 's', permission: 'read', type: 'read', target: 'src/app.ts' });
  assert.equal(bridge.respond('a', 's', 'pr', 'always').status, 'always');
});

test('permission events preserve patterns and mark out-of-workspace targets', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-perm-'));
  const runtime = await runtimeFor(root);
  const bridge = new PermissionBridge();
  const sse = 'data: ' + JSON.stringify({ type: 'permission.asked', properties: { id: 'perm_1', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts', 'C:\\private\\.env'] } }) + '\n\n';
  const client = fakeClient({ events: async () => new Response(sse) });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-perm', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-perm', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.match(snapshot.interaction.target, /private/);
  assert.equal(snapshot.interaction.outside, true);
});

test('a quiet SSE read reports timeout, not EOF', async () => {
  let endReason;
  const stream = new ReadableStream({ start() {} });
  const event = await waitForEvent(new Response(stream), 100, undefined, undefined, undefined, reason => { endReason = reason; });
  assert.equal(event, null);
  assert.equal(endReason, 'timeout');
});

test('a stalled response body is bounded by the request timeout', async () => {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.flushHeaders();
    response.write('{"partial":');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-body-'));
  const manager = new ServerManager(new RuntimeStore(path.join(root, '.store')));
  const runtime = { host: '127.0.0.1', port, username: 'opencode', password: 'x' };
  try {
    await assert.rejects(() => manager.requestJson(runtime, '/slow', { timeoutMs: 300 }), { code: 'SERVER_TIMEOUT' });
  } finally {
    server.closeAllConnections?.();
    await new Promise(resolve => server.close(resolve));
  }
});

test('a stale project lock fails closed instead of being reclaimed', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lock-'));
  const lockDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lockdir-'));
  const lockFile = path.join(lockDir, projectKey(root).slice('sha256:'.length) + '.lock');
  await fs.writeFile(lockFile, JSON.stringify({ pid: 999999, id: 'dead' }));
  const lock = new ProjectFileLock(lockDir);
  await assert.rejects(() => lock.withLock(root, async () => 'x'), { code: 'PROJECT_LOCK_STALE' });
  assert.equal(await fs.readFile(lockFile, 'utf8'), JSON.stringify({ pid: 999999, id: 'dead' }));
});

test('session locks never admit two critical sections concurrently', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lockcs-'));
  const lock = new SessionFileLock(await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lockcsdir-')), 5000);
  let active = 0;
  let max = 0;
  const worker = () => lock.withLock(root, 'ses_cs', async () => {
    active++;
    max = Math.max(max, active);
    await new Promise(resolve => setTimeout(resolve, 30));
    active--;
  });
  await Promise.all([worker(), worker(), worker()]);
  assert.equal(max, 1);
});

test('pending permissions are recovered through the authoritative query', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permq-'));
  const runtime = await runtimeFor(root);
  const bridge = new PermissionBridge();
  const client = fakeClient({
    permissionList: async () => [{ id: 'perm_q', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts'] }]
  });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-permq', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-permq', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.equal(snapshot.interaction.id, 'perm_q');
  assert.equal(bridge.pending(runtime.projectKey, 'ses_test').id, 'perm_q');
});

test('a permission resolved outside the broker no longer sticks', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permr-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const client = fakeClient({ permissionList: async () => [] });
  const manager = new SessionManager(client, store, bridge);
  await manager.create(runtime, { change: 'AR-001-permr', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'awaiting_permission';
  state.interaction = { id: 'perm_gone', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', status: 'pending' };
  await store.write(root, state);
  const active = await manager.recoverActive(runtime);
  assert.equal(active.length, 1);
  assert.equal(active[0].status, 'running');
  assert.equal((await store.read(root, 'ses_test')).status, 'running');
  assert.equal(bridge.pending(runtime.projectKey, 'ses_test'), undefined);
});

test('relative and escaped permission paths are outside the workspace', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permp-'));
  const runtime = await runtimeFor(root);
  const bridge = new PermissionBridge();
  const patterns = ['../private/file.txt', root + path.sep + '..' + path.sep + 'private' + path.sep + 'file.txt'];
  const sse = 'data: ' + JSON.stringify({ type: 'permission.asked', properties: { id: 'perm_p', sessionID: 'ses_test', permission: 'read', patterns, always: ['../private/file.txt'] } }) + '\n\n';
  const client = fakeClient({ events: async () => new Response(sse) });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-permp', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-permp', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.equal(snapshot.interaction.outside, true);
  assert.equal(snapshot.interaction.alwaysOutside, true);
  assert.throws(() => bridge.respond(runtime.projectKey, 'ses_test', 'perm_p', 'always'), { code: 'PERMISSION_REQUIRED' });
});

test('a stale session lock fails closed with a clear error', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lockstale-'));
  const lockDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-lockstaledir-'));
  const lock = new SessionFileLock(lockDir, 5000);
  const lockFile = path.join(lockDir, projectKey(root).slice('sha256:'.length) + '-ses_stale.lock');
  await fs.writeFile(lockFile, JSON.stringify({ pid: 999999, id: 'dead' }));
  await assert.rejects(() => lock.withLock(root, 'ses_stale', async () => 'x'), { code: 'SESSION_LOCK_STALE' });
});

test('an unsupported permission query is reported, not silently ignored', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permu-'));
  const runtime = await runtimeFor(root);
  const client = fakeClient({ permissionList: async () => null });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-permu', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-permu', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.permissionQuery, 'unsupported');
});

test('permission replies use the field each endpoint expects', async () => {
  const calls = [];
  const server = {
    requestJson: async (_runtime, endpoint, init) => {
      calls.push({ endpoint, body: init?.body ? JSON.parse(init.body) : undefined });
      if (endpoint.includes('/permissions/')) throw new BrokerError('SERVER_HTTP_ERROR', 'OpenCode Server returned HTTP 404');
      return {};
    }
  };
  const client = new OpenCodeClient(server);
  await client.permission({}, 'ses_1', 'perm_new', 'reject');
  assert.match(calls[1].endpoint, /\/permission\/perm_new\/reply$/);
  assert.deepEqual(calls[1].body, { reply: 'reject' });
});

test('the legacy permission endpoint uses the response field', async () => {
  const calls = [];
  const server = {
    requestJson: async (_runtime, endpoint, init) => {
      calls.push({ endpoint, body: init?.body ? JSON.parse(init.body) : undefined });
      return {};
    }
  };
  const client = new OpenCodeClient(server);
  await client.permission({}, 'ses_1', 'perm_old', 'once');
  assert.match(calls[0].endpoint, /\/session\/ses_1\/permissions\/perm_old$/);
  assert.deepEqual(calls[0].body, { response: 'once' });
});

test('a reconnect snapshot reconciles permissions lost during the disconnect', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permdc-'));
  const runtime = await runtimeFor(root);
  const bridge = new PermissionBridge();
  let listCalls = 0;
  const client = fakeClient({
    permissionList: async () => {
      listCalls++;
      return listCalls === 1 ? [] : [{ id: 'perm_dc', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts'] }];
    },
    events: async () => new Response('')
  });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-permdc', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-permdc', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 2000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.ok(listCalls >= 2, 'reconnect did not re-query permissions: ' + listCalls);
});

test('a successful reconnect reconciles permissions without further events', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permrc-'));
  const runtime = await runtimeFor(root);
  const bridge = new PermissionBridge();
  let connections = 0;
  let listCalls = 0;
  const client = fakeClient({
    permissionList: async () => {
      listCalls++;
      return listCalls >= 3 ? [{ id: 'perm_rc', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts'] }] : [];
    },
    events: async () => {
      connections++;
      if (connections === 1) return new Response('');
      return new Response(new ReadableStream({ start() {} }));
    }
  });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')), bridge);
  await manager.create(runtime, { change: 'AR-001-permrc', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-permrc', 'all', 'go', 0);
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 3000);
  assert.equal(snapshot.status, 'awaiting_permission');
  assert.ok(connections >= 2, 'did not reconnect: ' + connections);
  assert.ok(listCalls >= 3, 'reconnect did not re-query permissions: ' + listCalls);
});

test('broker recovery reconciles permissions for a running session', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-permrec-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const client = fakeClient({
    permissionList: async () => [{ id: 'perm_rec', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts'] }]
  });
  const manager = new SessionManager(client, store, bridge);
  await manager.create(runtime, { change: 'AR-001-permrec', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'running';
  await store.write(root, state);
  await manager.recoverActive(runtime);
  assert.equal((await store.read(root, 'ses_test')).status, 'awaiting_permission');
  assert.equal(bridge.pending(runtime.projectKey, 'ses_test').id, 'perm_rec');
});

test('graceful stop refuses to terminate a busy project inside the stop transaction', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-stop-'));
  const manager = new ServerManager(new RuntimeStore(path.join(root, '.store')));
  await assert.rejects(() => manager.stop(root, 'graceful', () => true), { code: 'PROJECT_BUSY' });
});

test('the workflow watchdog aborts a turn that exceeds its budget', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-watchdog-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const client = fakeClient({ abort: async () => ({ status: 'interrupted' }) });
  const manager = new SessionManager(client, store, undefined, 1);
  await manager.create(runtime, { change: 'AR-001-watchdog', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-watchdog', 'all', 'go', 0);
  await assert.rejects(() => manager.wait(runtime, 'ses_test', 1, 1000), { code: 'WORKFLOW_TIMEOUT' });
  assert.equal((await store.read(root, 'ses_test')).status, 'interrupted');
});

test('an assistant without a completion timestamp is not completion evidence', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-partial-'));
  const runtime = await runtimeFor(root);
  let messages = [{ info: { role: 'assistant', id: 'old' } }];
  const client = fakeClient({ status: async () => ({ id: 'ses_test', status: 'completed' }), messages: async () => messages });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-partial', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-partial', 'all', 'go', 0);
  messages = [
    { info: { role: 'assistant', id: 'old' } },
    { info: { role: 'user', id: 'u1' } },
    { info: { role: 'assistant', id: 'new', time: { created: 3 } } }
  ];
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 1000);
  assert.equal(snapshot.status, 'running');
});

test('an invisible message keeps the send uncertain instead of resending', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-uncertain-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const sent = [];
  const client = fakeClient({
    send: async (_runtime, _sessionId, _prompt, _agent, messageId) => { sent.push(messageId); throw new BrokerError('SERVER_TIMEOUT', 'lost'); },
    messages: async () => []
  });
  const manager = new SessionManager(client, store);
  await manager.create(runtime, { change: 'AR-001-uncertain', agent: 'ar-worker', access: 'workspace-write' });
  await assert.rejects(() => manager.send(runtime, 'ses_test', 'AR-001-uncertain', 'all', 'go', 0), { code: 'SERVER_TIMEOUT' });
  await assert.rejects(() => manager.send(runtime, 'ses_test', 'AR-001-uncertain', 'all', 'go', 0), { code: 'SEND_UNCERTAIN' });
  assert.equal(sent.length, 1);
  assert.equal((await store.read(root, 'ses_test')).status, 'sending');
  const active = await manager.recoverActive(runtime);
  assert.equal(active.length, 1);
  assert.equal(await manager.hasActiveSessions(root), true);
});

test('a concurrent abort cannot be overwritten by an in-flight wait observation', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-race-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  let releaseStatus;
  let statusEnteredResolve;
  const statusEntered = new Promise(resolve => { statusEnteredResolve = resolve; });
  const gate = new Promise(resolve => { releaseStatus = resolve; });
  let first = true;
  let messages = [];
  const client = fakeClient({
    messages: async () => messages,
    status: async () => {
      statusEnteredResolve();
      if (first) { first = false; await gate; }
      return { id: 'ses_test', status: 'completed' };
    },
    abort: async () => ({ status: 'interrupted' })
  });
  const a = new SessionManager(client, store);
  const b = new SessionManager(client, store);
  await a.create(runtime, { change: 'AR-001-race', agent: 'ar-worker', access: 'workspace-write' });
  await a.send(runtime, 'ses_test', 'AR-001-race', 'all', 'go', 0);
  messages = [{ info: { role: 'assistant', id: 'a1', time: { created: 1, completed: 2 } } }];
  const waiting = a.wait(runtime, 'ses_test', 1, 2000);
  await statusEntered;
  const aborting = b.abort(runtime, 'ses_test');
  releaseStatus();
  const [snapshot, abortResult] = await Promise.all([waiting, aborting]);
  assert.equal(abortResult.status, 'already_terminal');
  assert.equal(snapshot.status, 'completed');
});

test('wait honors the full timeout beyond the old five second cap', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-reg-longwait-'));
  const runtime = await runtimeFor(root);
  const client = fakeClient({ events: async () => new Response(new ReadableStream({ start() {} })) });
  const manager = new SessionManager(client, new SessionStateStore(path.join(root, '.state')));
  await manager.create(runtime, { change: 'AR-001-longwait', agent: 'ar-worker', access: 'workspace-write' });
  await manager.send(runtime, 'ses_test', 'AR-001-longwait', 'all', 'go', 0);
  const started = Date.now();
  const snapshot = await manager.wait(runtime, 'ses_test', 1, 6000);
  const elapsed = Date.now() - started;
  assert.equal(snapshot.changed, false);
  assert.ok(elapsed >= 5500, 'wait returned too early: ' + elapsed + 'ms');
});

test('permission recovery persists the normalized allowed response set', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-recovery-normalized-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const manager = new SessionManager(fakeClient({ permissionList: async () => null }), store, bridge);
  await manager.create(runtime, { change: 'AR-001-perm-normalized', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'awaiting_permission';
  state.revision = 1;
  state.interaction = { id: 'perm_normalized', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', target: 'src/app.ts', alwaysTargets: ['secret/token.txt'], status: 'pending' };
  await store.write(root, state);

  const recovered = await manager.recoverWriter(runtime);
  assert.deepEqual(recovered.interaction.allowedResponses, ['once', 'reject']);
  assert.deepEqual((await store.read(root, 'ses_test')).interaction.allowedResponses, ['once', 'reject']);
});
test('permission recovery cannot overwrite a concurrent response', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-recovery-race-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  const manager = new SessionManager(fakeClient({ permissionList: async () => null, permission: async () => ({ accepted: true }) }), store, bridge);
  await manager.create(runtime, { change: 'AR-001-perm-race', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'awaiting_permission';
  state.revision = 0;
  state.interaction = { id: 'perm_race', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', target: 'src/app.ts', status: 'pending' };
  await store.write(root, state);
  bridge.restore(state.interaction);

  const originalList = store.list.bind(store);
  let entered;
  let release;
  const enteredPromise = new Promise(resolve => { entered = resolve; });
  const releasePromise = new Promise(resolve => { release = resolve; });
  store.list = async rootPath => {
    const states = await originalList(rootPath);
    entered();
    await releasePromise;
    return states;
  };

  const recovery = manager.recoverActive(runtime);
  await enteredPromise;
  await manager.permission(runtime, 'ses_test', 'perm_race', 'once');
  release();
  await recovery;

  const finalState = await store.read(root, 'ses_test');
  assert.equal(finalState.status, 'running');
  assert.equal(finalState.revision, 1);
  assert.equal(finalState.interaction, null);
});

test('permission reconciliation does not reinsert a permission resolved during the query', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-query-race-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  let entered;
  let release;
  const enteredPromise = new Promise(resolve => { entered = resolve; });
  const releasePromise = new Promise(resolve => { release = resolve; });
  const manager = new SessionManager(fakeClient({
    permissionList: async () => {
      entered();
      await releasePromise;
      return [{ id: 'perm_stale', sessionID: 'ses_test', permission: 'read', patterns: [root + '\\src\\a.ts'] }];
    },
    permission: async () => ({ accepted: true })
  }), store, bridge);
  await manager.create(runtime, { change: 'AR-001-perm-query-race', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'awaiting_permission';
  state.interaction = { id: 'perm_stale', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', target: 'src/a.ts', status: 'pending' };
  await store.write(root, state);
  bridge.restore(state.interaction);

  const recovery = manager.recoverActive(runtime);
  await enteredPromise;
  await manager.permission(runtime, 'ses_test', 'perm_stale', 'once');
  release();
  await recovery;

  const finalState = await store.read(root, 'ses_test');
  assert.equal(finalState.status, 'running');
  assert.equal(finalState.interaction, null);
  assert.equal(bridge.pending(runtime.projectKey, 'ses_test'), undefined);
});

test('permission reconciliation does not clear a newer permission after an empty query', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-permission-query-newer-'));
  const runtime = await runtimeFor(root);
  const store = new SessionStateStore(path.join(root, '.state'));
  const bridge = new PermissionBridge();
  let entered;
  let release;
  const enteredPromise = new Promise(resolve => { entered = resolve; });
  const releasePromise = new Promise(resolve => { release = resolve; });
  const manager = new SessionManager(fakeClient({
    permissionList: async () => {
      entered();
      await releasePromise;
      return [];
    }
  }), store, bridge);
  await manager.create(runtime, { change: 'AR-001-perm-query-newer', agent: 'ar-worker', access: 'workspace-write' });
  const state = await store.read(root, 'ses_test');
  state.status = 'awaiting_permission';
  state.interaction = { id: 'perm_old', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', target: 'src/a.ts', status: 'pending' };
  await store.write(root, state);
  bridge.restore(state.interaction);

  const recovery = manager.recoverActive(runtime);
  await enteredPromise;
  state.status = 'awaiting_permission';
  state.revision++;
  state.interaction = { id: 'perm_new', projectKey: runtime.projectKey, sessionId: 'ses_test', permission: 'read', type: 'read', target: 'src/b.ts', status: 'pending' };
  await store.write(root, state);
  bridge.restore(state.interaction);
  release();
  await recovery;

  const finalState = await store.read(root, 'ses_test');
  assert.equal(finalState.status, 'awaiting_permission');
  assert.equal(finalState.interaction.id, 'perm_new');
  assert.equal(bridge.pending(runtime.projectKey, 'ses_test').id, 'perm_new');
});