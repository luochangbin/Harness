import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { resolvePhaseBatch } from '../dist/phase-batch.js';

test('phase batch resolver returns all incomplete tasks from the declared phase', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), [
    '## 实施 Phases', '', '### Phase 1：基础', '', '### Phase 2：交付', ''
  ].join('\n'), 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), [
    '## Phase 1：基础', '', '- [x] 1.1 已完成', '- [ ] 1.2 待实现', '',
    '## Phase 2：交付', '', '- [ ] 2.1 待实现', ''
  ].join('\n'), 'utf8');

  const result = await resolvePhaseBatch(root, 'AR-001-phase', '1');
  assert.equal(result.taskBatch, '1.2');
  assert.deepEqual(result.taskIds, ['1.2']);
});

test('phase batch resolver canonicalizes a display label such as Phase 1', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-label-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '### Phase 1: base\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '## Phase 1: base\n\n- [ ] 1.1 pending\n', 'utf8');

  const result = await resolvePhaseBatch(root, 'AR-001-phase', 'Phase 1');
  assert.equal(result.phaseId, '1');
  assert.equal(result.taskBatch, '1.1');
});

test('phase batch resolver returns a complete Phase scope for repair mode', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-repair-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '### Phase 1：基础\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), [
    '## Phase 1：基础', '', '- [x] 1.1 已完成', '- [x] 1.2 已完成', ''
  ].join('\n'), 'utf8');

  const result = await resolvePhaseBatch(root, 'AR-001-phase', '1', 'repair');
  assert.equal(result.taskBatch, '1.1,1.2');
  assert.deepEqual(result.taskIds, ['1.1', '1.2']);
});
test('phase batch resolver rejects an undeclared phase', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-invalid-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '## 实施 Phases\n\n### Phase 1：基础\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '## Phase 1：基础\n\n- [ ] 1.1 待实现\n', 'utf8');

  await assert.rejects(
    () => resolvePhaseBatch(root, 'AR-001-phase', '2'),
    { code: 'PHASE_NOT_DECLARED' }
  );
});

test('phase batch resolver treats a legacy AR without Phase headings as one implicit Phase', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-implicit-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '# Legacy design\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '- [ ] 1.1 旧任务\n- [x] 1.2 已完成\n', 'utf8');

  const result = await resolvePhaseBatch(root, 'AR-001-phase', 'implicit');
  assert.equal(result.taskBatch, '1.1');
});

test('phase batch resolver rejects duplicate task IDs across phases', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-duplicate-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '### Phase 1：基础\n\n### Phase 2：交付\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), [
    '## Phase 1：基础', '', '- [ ] 1.1 重复任务', '',
    '## Phase 2：交付', '', '- [ ] 1.1 重复任务', ''
  ].join('\n'), 'utf8');

  await assert.rejects(
    () => resolvePhaseBatch(root, 'AR-001-phase', '1'),
    { code: 'INVALID_PHASE_MAPPING' }
  );
});

test('phase batch resolver rejects duplicate Phase headings in tasks', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-duplicate-heading-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '### Phase 1：基础\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), [
    '## Phase 1：基础', '', '- [ ] 1.1 第一段', '',
    '## Phase 1：基础', '', '- [ ] 1.2 第二段', ''
  ].join('\n'), 'utf8');

  await assert.rejects(
    () => resolvePhaseBatch(root, 'AR-001-phase', '1'),
    { code: 'INVALID_PHASE_MAPPING' }
  );
});


test('phase batch resolver includes completed tasks for repair in an implicit Phase', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'cw-phase-batch-implicit-repair-'));
  const changeDir = path.join(root, 'codespec', 'changes', 'AR-001-phase');
  await fs.mkdir(changeDir, { recursive: true });
  await fs.writeFile(path.join(changeDir, 'design.md'), '# Legacy design\n', 'utf8');
  await fs.writeFile(path.join(changeDir, 'tasks.md'), '- [x] 1.1 已完成\n- [x] 1.2 已完成\n', 'utf8');

  const result = await resolvePhaseBatch(root, 'AR-001-phase', 'implicit', 'repair');
  assert.deepEqual(result.taskIds, ['1.1', '1.2']);
  assert.equal(result.taskBatch, '1.1,1.2');
});
