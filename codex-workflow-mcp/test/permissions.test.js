import test from 'node:test';
import assert from 'node:assert/strict';
import { PermissionBridge, ProjectWriteLock } from '../dist/permissions.js';

test('permission response is project scoped', () => {
  const bridge = new PermissionBridge(); const request = bridge.add({ id: 'p1', projectKey: 'a', sessionId: 's1', permission: 'write' });
  assert.equal(request.status, 'pending'); assert.throws(() => bridge.respond('b', 's1', 'p1', 'once'), { code: 'PROJECT_PERMISSION_MISMATCH' });
  assert.equal(bridge.respond('a', 's1', 'p1', 'once').status, 'once');
});

test('high-risk permissions cannot be permanently approved', () => {
  const bridge = new PermissionBridge();
  bridge.add({ id: 'p2', projectKey: 'a', sessionId: 's1', permission: 'api_key_access' });
  assert.throws(() => bridge.respond('a', 's1', 'p2', 'always'), { code: 'PERMISSION_REQUIRED' });
});

test('permission interaction advertises whether always is available', () => {
  const bridge = new PermissionBridge();
  const safe = bridge.add({ id: 'p-safe', projectKey: 'a', sessionId: 's1', permission: 'read', type: 'read', target: 'src/app.ts' });
  const risky = bridge.add({ id: 'p-risky', projectKey: 'a', sessionId: 's1', permission: 'write', type: 'write' });
  assert.deepEqual(safe.allowedResponses, ['once', 'always', 'reject']);
  assert.deepEqual(risky.allowedResponses, ['once', 'reject']);
});

test('always is refused when the permanent read scope contains a high-risk target', () => {
  const bridge = new PermissionBridge();
  const request = bridge.add({
    id: 'p-secret-scope',
    projectKey: 'a',
    sessionId: 's1',
    permission: 'read',
    type: 'read',
    target: 'src/app.ts',
    alwaysTargets: ['secrets/api-token.txt']
  });
  assert.deepEqual(request.allowedResponses, ['once', 'reject']);
  assert.throws(() => bridge.respond('a', 's1', 'p-secret-scope', 'always'), { code: 'PERMISSION_REQUIRED' });
});
test('one writer per project but independent projects proceed', () => {
  const lock = new ProjectWriteLock(); lock.acquire('a', 's1', 'workspace-write'); assert.throws(() => lock.acquire('a', 's2', 'workspace-write'), { code: 'PROJECT_WRITER_BUSY' });
  assert.equal(lock.acquire('b', 's2', 'workspace-write').acquired, true); lock.release('a', 's1'); assert.equal(lock.acquire('a', 's2', 'workspace-write').acquired, true);
});

test('replacement refuses to overwrite another active project writer', () => {
  const lock = new ProjectWriteLock();
  lock.acquire('a', 's1', 'workspace-write', 'running');
  assert.throws(() => lock.assertReplaceAllowed('a', 's2'), { code: 'PROJECT_WRITER_BUSY' });
  assert.doesNotThrow(() => lock.assertReplaceAllowed('a', 's1'));
});

test('unscoped read permissions cannot be permanently approved', () => {
  const bridge = new PermissionBridge();
  const request = bridge.add({ id: 'p-unscoped', projectKey: 'a', sessionId: 's1', permission: 'read', type: 'read' });
  assert.deepEqual(request.allowedResponses, ['once', 'reject']);
  assert.throws(() => bridge.respond('a', 's1', 'p-unscoped', 'always'), { code: 'PERMISSION_REQUIRED' });
});

test('sensitive read targets cannot be permanently approved', () => {
  const bridge = new PermissionBridge();
  const request = bridge.add({ id: 'p-env', projectKey: 'a', sessionId: 's1', permission: 'read', type: 'read', target: '.env' });
  assert.deepEqual(request.allowedResponses, ['once', 'reject']);
});
