import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { canonicalRoot, projectKey } from '../dist/project-key.js';

test('canonical root is stable and project keys are distinct', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-key-'));
  const a = canonicalRoot(await fs.mkdtemp(path.join(base, 'todo-')));
  const b = canonicalRoot(await fs.mkdtemp(path.join(base, 'other-')));
  assert.notEqual(a, b);
  assert.match(projectKey(a), /^sha256:[a-f0-9]{64}$/);
  assert.notEqual(projectKey(a), projectKey(b));
});

test('project key normalizes Windows case', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-case-'));
  assert.equal(projectKey(root), projectKey(root.toUpperCase()));
});
