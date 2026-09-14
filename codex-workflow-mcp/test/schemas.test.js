import test from 'node:test';
import assert from 'node:assert/strict';
import { redactSecrets, toolDefinitions } from '../dist/schemas.js';

test('tool contract exposes only high-level broker tools', () => {
  const names = toolDefinitions.map((tool) => tool.name);
  assert.deepEqual(names, [
    'opencode_project_probe', 'opencode_project_start',
    'opencode_session_create', 'opencode_session_send',
    'opencode_session_send_bound',
    'opencode_session_binding',
    'opencode_session_replace',
    'opencode_session_wait', 'opencode_permission_respond',
    'opencode_session_abort', 'opencode_session_result',
    'opencode_project_stop'
  ]);
});

test('sensitive fields are never exposed', () => {
  const value = redactSecrets({ password: 'secret', token: 'token', pid: 42, port: 4096, ok: true });
  assert.deepEqual(value, { ok: true });
});
