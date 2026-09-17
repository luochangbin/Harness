import { BrokerError } from './errors.js';

export type PermissionResponse = 'once' | 'always' | 'reject';
export type AllowedPermissionResponses = PermissionResponse[];
export type PermissionRequest = {
  id: string;
  projectKey: string;
  sessionId: string;
  permission: string;
  type?: string;
  target?: string;
  operation?: string;
  outside?: boolean;
  unknownScope?: boolean;
  alwaysOutside?: boolean;
  alwaysUnknown?: boolean;
  alwaysTargets?: string[];
  status: 'pending' | PermissionResponse;
};

const SAFE_ALWAYS = new Set(['read', 'file.read']);
const HIGH_RISK = /api[_ -]?key|password|secret|token|credential|external|outside|system|network|install|exec|shell|bash|sudo|root|(?:^|[\/\\])(?:\.env(?:\..*)?|\.npmrc|\.pypirc|id_(?:rsa|ed25519)|[^\/\\]*\.(?:pem|key|p12|pfx))$/i;
const SAFE_READ_TYPES = new Set(['read', 'file.read']);
const DEPENDENCY_INSTALL = /^(npm|pnpm|yarn|bun)\s+(?:i|install|add)(?:\s|$)/i;
const SHELL_META = /[;&|<>`$()]/;

export function automaticPermissionResponse(item: Pick<PermissionRequest, 'permission' | 'type' | 'target' | 'operation' | 'outside' | 'unknownScope' | 'alwaysOutside' | 'alwaysUnknown'>): PermissionResponse | null {
  const permission = item.permission.toLowerCase();
  const type = (item.type ?? item.permission).toLowerCase();
  const operation = item.operation?.toLowerCase();
  const target = item.target?.trim() ?? '';
  const scopeSafe = !item.unknownScope && !HIGH_RISK.test(target);

  if (scopeSafe && item.outside && (SAFE_READ_TYPES.has(permission) || SAFE_READ_TYPES.has(type) ||
      (permission === 'external_directory' && operation === 'read'))) return target ? 'once' : null;

  if (!item.outside && permission === 'bash' && target && !SHELL_META.test(target) &&
      !/(^|\s)(?:-g|--global|--prefix|\.\.[\\/]|[A-Za-z]:[\\/]|~[\\/])(?:\s|$)/i.test(target) &&
      DEPENDENCY_INSTALL.test(target)) return 'once';

  if ((permission === 'webfetch' || type === 'webfetch') && /^https?:\/\//i.test(target)) return 'once';
  return null;
}

function canAlways(item: Pick<PermissionRequest, 'permission' | 'type' | 'target' | 'outside' | 'unknownScope' | 'alwaysOutside' | 'alwaysUnknown' | 'alwaysTargets'>) {
  const type = (item.type ?? item.permission).toLowerCase();
  const riskyAlwaysTarget = (item.alwaysTargets ?? []).some(target => HIGH_RISK.test(target));
  const hasTarget = typeof item.target === 'string' && item.target.trim() !== '';
  return !(!hasTarget || item.outside || item.unknownScope || item.alwaysOutside || item.alwaysUnknown ||
    riskyAlwaysTarget || !SAFE_ALWAYS.has(type) || HIGH_RISK.test(item.permission) || HIGH_RISK.test(item.target ?? ''));
}

function allowedResponses(item: Pick<PermissionRequest, 'permission' | 'type' | 'target' | 'outside' | 'unknownScope' | 'alwaysOutside' | 'alwaysUnknown' | 'alwaysTargets'>): AllowedPermissionResponses {
  return canAlways(item) ? ['once', 'always', 'reject'] : ['once', 'reject'];
}

export class PermissionBridge {
  private requests = new Map<string, PermissionRequest>();

  private present(item: PermissionRequest) {
    return {
      id: item.id, projectKey: item.projectKey, sessionId: item.sessionId, permission: item.permission,
      type: item.type ?? null, target: item.target ?? null, operation: item.operation ?? null, outside: item.outside ?? false,
      unknownScope: item.unknownScope ?? false, alwaysOutside: item.alwaysOutside ?? false,
      alwaysUnknown: item.alwaysUnknown ?? false, alwaysTargets: item.alwaysTargets ?? null,
      allowedResponses: allowedResponses(item), status: item.status
    };
  }

  add(request: Omit<PermissionRequest, 'status'>) {
    const item = { ...request, status: 'pending' as const };
    this.requests.set(item.id, item);
    return this.present(item);
  }

  restore(request: unknown) {
    const item = request as Partial<PermissionRequest> | null;
    if (!item || typeof item.id !== 'string' || typeof item.projectKey !== 'string' ||
        typeof item.sessionId !== 'string' || typeof item.permission !== 'string' || item.status !== 'pending') return false;
    const restored = item as PermissionRequest;
    this.requests.set(restored.id, restored);
    return this.present(restored);
  }

  validate(projectKey: string, sessionId: string, id: string, response: PermissionResponse) {
    const item = this.requests.get(id);
    if (!item || item.status !== 'pending') throw new BrokerError('PERMISSION_NOT_FOUND', 'Permission request not found');
    if (item.projectKey !== projectKey || item.sessionId !== sessionId) {
      throw new BrokerError('PROJECT_PERMISSION_MISMATCH', 'Permission belongs to another project or Session');
    }
    if (response === 'always') {
      if (!canAlways(item)) {
        throw new BrokerError('PERMISSION_REQUIRED', 'High-risk, out-of-workspace or unverifiable permissions cannot use always');
      }
    }
    return item;
  }

  respond(projectKey: string, sessionId: string, id: string, response: PermissionResponse) {
    this.validate(projectKey, sessionId, id, response);
    const item = this.requests.get(id);
    item!.status = response;
    this.requests.delete(id);
    return { id, status: response, type: item!.type ?? null, target: item!.target ?? null };
  }

  pending(projectKey: string, sessionId: string) {
    return [...this.requests.values()].find(item => item.projectKey === projectKey && item.sessionId === sessionId && item.status === 'pending');
  }

  discard(id: string) {
    this.requests.delete(id);
  }
}

type Writer = { sessionId: string; status: string; access: 'read-only' | 'workspace-write' };

export class ProjectWriteLock {
  private owners = new Map<string, Writer>();

  acquire(projectKey: string, sessionId: string, access: 'read-only' | 'workspace-write', status = 'ready') {
    const owner = this.owners.get(projectKey);
    if (owner && owner.sessionId !== sessionId && ['sending', 'ready', 'running', 'awaiting_permission'].includes(owner.status)) {
      throw new BrokerError('PROJECT_WRITER_BUSY', 'Another active Session is operating this project');
    }
    this.owners.set(projectKey, { sessionId, status, access });
    return { acquired: true };
  }

  assertReplaceAllowed(projectKey: string, previousSessionId: string) {
    const owner = this.owners.get(projectKey);
    if (owner && owner.sessionId !== previousSessionId && ['sending', 'ready', 'running', 'awaiting_permission'].includes(owner.status)) {
      throw new BrokerError('PROJECT_WRITER_BUSY', 'Another active Session is operating this project');
    }
  }

  restore(projectKey: string, sessionId: string, access: 'read-only' | 'workspace-write', status: string) {
    this.owners.set(projectKey, { sessionId, status, access });
    return { acquired: true };
  }

  update(projectKey: string, sessionId: string, status: string) {
    const owner = this.owners.get(projectKey);
    if (owner?.sessionId === sessionId) owner.status = status;
  }

  owner(projectKey: string) {
    return this.owners.get(projectKey) ?? null;
  }

  isBusy(projectKey: string) {
    const owner = this.owners.get(projectKey);
    return Boolean(owner && ['sending', 'ready', 'running', 'awaiting_permission'].includes(owner.status));
  }

  clear(projectKey: string) {
    this.owners.delete(projectKey);
  }

  release(projectKey: string, sessionId: string) {
    if (this.owners.get(projectKey)?.sessionId === sessionId) this.owners.delete(projectKey);
  }
}
