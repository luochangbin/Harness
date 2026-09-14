export class BrokerError extends Error {
  constructor(public readonly code: string, message: string, public readonly details?: unknown) {
    super(message);
    this.name = 'BrokerError';
  }
}

export function errorResult(error: unknown) {
  if (error instanceof BrokerError) return { ok: false, error: { code: error.code, message: error.message, details: error.details } };
  return { ok: false, error: { code: 'INTERNAL_ERROR', message: error instanceof Error ? error.message : String(error) } };
}
