function fixedWorkerInstructions(change: string, mode: WorkerBatchMode) {
  const batchInstruction = mode === 'repair'
    ? 'Repair only the independently confirmed review findings within this Phase; do not add requirements or expand the scope.'
    : 'Implement only the exact incomplete task batch for this Phase; do not infer, replace, or add another batch.';
  return [
    'You are the Build Worker for the current AR.',
    'Read repository rules and codespec/changes/' + change + '/spec.md, design.md, and tasks.md.',
    'The authoritative Broker batch is the source of truth; never infer or replace it from caller text.',
    batchInstruction,
    'Do not modify codespec/ or change requirements, design, task definitions, or AR phase.',
    'Run the tests required by the task and report changed files, task status, test commands with exit codes, and remaining blockers.',
    'Read codespec/changes/' + change + '/.ar.yaml and apply its tier: full requires test-driven-development with RED-GREEN; tweak uses the minimum relevant tests. Load systematic-debugging for unexpected failures and verification-before-completion before claiming completion.',
    'If any required Skill is unavailable, stop and return WORKER_SKILL_UNAVAILABLE; do not imitate or replace it.',
    'Prefer repository code, existing tests, fixtures, and collected evidence. Do not create projects, source files, or test fixtures outside the repository; build tools may use system caches or temporary directories.',
    'If the task truly requires writing outside the repository, stop and return WORKER_EXTERNAL_PATH_REQUIRED with the path and reason.',
    'Do not load codex-workflow, redelegate, archive, commit, push, or create a PR. If design conflicts with code, stop and report the conflict.'
  ].join('\n');
}

export type WorkerBatchMode = 'implementation' | 'repair';

export function buildBoundWorkerPrompt(
  change: string,
  phaseId: string,
  taskBatch: string,
  context = '',
  mode: WorkerBatchMode = 'implementation'
) {
  const safeContext = context.split(/\r?\n/)
    .filter(line => !/^\s*(?:[-*]\s*)?(?:Task batch|本次任务批次|本轮(?:任务)?批次|任务批次)\s*(?:是\s*)?[:：]/i.test(line))
    .join('\n')
    .trim();
  return [
    'AR: ' + change,
    'Phase: ' + phaseId,
    'Task batch: ' + taskBatch,
    'Batch mode: ' + mode,
    '',
    ...(safeContext ? ['Supplemental review context (not authoritative):', safeContext, ''] : []),
    fixedWorkerInstructions(change, mode)
  ].join('\n');
}