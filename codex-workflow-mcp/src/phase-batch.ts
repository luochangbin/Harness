import fs from 'node:fs/promises';
import path from 'node:path';
import { BrokerError } from './errors.js';

const changePattern = /^[A-Za-z0-9_-]{1,256}$/;
const designPhasePattern = /^###\s+Phase\s+([A-Za-z0-9_.-]+)(?:\s*[：:].*)?$/gm;

export function normalizePhaseId(value: string) {
  const trimmed = value.trim();
  const display = trimmed.match(/^Phase\s+([A-Za-z0-9_.-]+)$/i);
  return display ? display[1] : trimmed;
}

function changeDir(root: string, change: string) {
  if (!changePattern.test(change)) throw new BrokerError('INVALID_CHANGE', 'Invalid AR change name');
  return path.join(root, 'codespec', 'changes', change);
}

function declaredPhases(design: string) {
  return [...design.matchAll(designPhasePattern)].map(match => match[1]);
}

function phaseTasks(tasks: string, allowImplicit: boolean, includeCompleted = false) {
  const result = new Map<string, string[]>();
  const seenPhases = new Set<string>();
  const seenTasks = new Set<string>();
  let current: string | undefined;
  for (const line of tasks.split(/\r?\n/)) {
    const phase = line.match(/^##\s+Phase\s+([A-Za-z0-9_.-]+)(?:\s*[：:].*)?$/);
    if (phase) {
      current = phase[1];
      if (seenPhases.has(current)) throw new BrokerError('INVALID_PHASE_MAPPING', 'Tasks contain a duplicate Phase heading');
      seenPhases.add(current);
      if (!result.has(current)) result.set(current, []);
      continue;
    }
    const task = line.match(/^-\s+\[([ xX])\]\s+([0-9]+\.[0-9]+)\b/);
    if (task) {
      if (seenTasks.has(task[2])) throw new BrokerError('INVALID_PHASE_MAPPING', 'Task is assigned more than once: ' + task[2]);
      seenTasks.add(task[2]);
      if (!current) {
        if (!allowImplicit) throw new BrokerError('INVALID_PHASE_MAPPING', 'Task is not under a Phase heading');
        current = 'implicit';
        if (!result.has(current)) result.set(current, []);
      }
      if (task[1] === ' ' || includeCompleted) result.get(current)!.push(task[2]);
    }
  }
  return result;
}

export type PhaseBatchMode = 'implementation' | 'repair';

export async function resolvePhaseBatch(root: string, change: string, phaseId: string, mode: PhaseBatchMode = 'implementation') {
  const canonicalPhaseId = normalizePhaseId(phaseId);
  const dir = changeDir(root, change);
  let design: string;
  let tasks: string;
  try {
    [design, tasks] = await Promise.all([
      fs.readFile(path.join(dir, 'design.md'), 'utf8'),
      fs.readFile(path.join(dir, 'tasks.md'), 'utf8')
    ]);
  } catch (error: any) {
    throw new BrokerError('PHASE_DOCUMENT_MISSING', 'Cannot read AR design/tasks documents', error?.code);
  }

  const phases = declaredPhases(design);
  const taskMap = phaseTasks(tasks, phases.length === 0);
  const selectedTasks = mode === 'repair' ? phaseTasks(tasks, phases.length === 0, true) : taskMap;
  let taskIds: string[];
  if (phases.length === 0) {
    if (canonicalPhaseId !== 'implicit') throw new BrokerError('PHASE_NOT_DECLARED', 'AR has only one implicit Phase');
    taskIds = [...selectedTasks.values()].flat();
  } else {
    if (new Set(phases).size !== phases.length || phases.length !== taskMap.size ||
        phases.some((id, index) => [...taskMap.keys()][index] !== id)) {
      throw new BrokerError('INVALID_PHASE_MAPPING', 'Design and tasks Phase declarations do not match');
    }
    if (!phases.includes(canonicalPhaseId)) throw new BrokerError('PHASE_NOT_DECLARED', 'Phase is not declared by design.md');
    taskIds = selectedTasks.get(canonicalPhaseId) ?? [];
  }
  if (taskIds.length === 0) throw new BrokerError('PHASE_COMPLETE', 'The selected Phase has no incomplete tasks');
  return { phaseId: canonicalPhaseId, taskIds, taskBatch: taskIds.join(',') };
}
