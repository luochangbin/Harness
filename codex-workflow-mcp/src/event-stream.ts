export type ServerEvent = { event: string; data: unknown };

const READ_TIMEOUT = Symbol('read-timeout');

function parseFrame(frame: string): ServerEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  const text = data.join('\n');
  try { return { event, data: JSON.parse(text) }; }
  catch { return { event, data: text }; }
}

export async function waitForEvent(
  response: Response,
  timeoutMs: number,
  signal?: AbortSignal,
  onEvent?: (event: ServerEvent) => void | Promise<void>,
  shouldReturn?: (event: ServerEvent) => boolean,
  onEnd?: (reason: 'eof' | 'timeout') => void
): Promise<ServerEvent | null> {
  if (!response.body) return null;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      const remaining = Math.max(1, deadline - Date.now());
      let timer: ReturnType<typeof setTimeout> | undefined;
      const pending = reader.read();
      pending.catch(() => undefined);
      const result = await Promise.race([
        pending,
        new Promise<typeof READ_TIMEOUT>(resolve => {
          timer = setTimeout(() => resolve(READ_TIMEOUT), remaining);
        })
      ]);
      if (timer) clearTimeout(timer);
      if (result === READ_TIMEOUT) { onEnd?.('timeout'); return null; }
      if (result.done) { onEnd?.('eof'); return null; }
      buffer += decoder.decode(result.value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (!event) continue;
        await onEvent?.(event);
        if (!shouldReturn || shouldReturn(event)) return event;
      }
    }
    onEnd?.('timeout');
    return null;
  } finally {
    signal?.throwIfAborted();
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
