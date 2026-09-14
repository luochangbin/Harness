export const toolDefinitions = [
  { name: 'opencode_project_probe' }, { name: 'opencode_project_start' },
  { name: 'opencode_session_create' }, { name: 'opencode_session_send' },
  { name: 'opencode_session_send_bound' },
  { name: 'opencode_session_binding' },
  { name: 'opencode_session_replace' },
  { name: 'opencode_session_wait' }, { name: 'opencode_permission_respond' },
  { name: 'opencode_session_abort' }, { name: 'opencode_session_result' },
  { name: 'opencode_project_stop' }
] as const;

const secretKeys = new Set(['password', 'token', 'apiKey', 'api_key', 'authorization', 'pid', 'port', 'baseUrl']);

export function redactSecrets(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !secretKeys.has(key))
    .map(([key, item]) => [key, redactSecrets(item)]));
}
