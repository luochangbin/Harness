import { BrokerError } from './errors.js';
import { RuntimeRecord } from './runtime-store.js';
import { ServerManager } from './server-manager.js';

export type OpenCodeStatus = 'pending' | 'running' | 'awaiting_permission' | 'completed' | 'failed' | 'interrupted' | 'unknown';
export type MessageBaseline = { messageCount?: number; assistantId?: string; userMessageId?: string };
export type SessionInfo = {
  id: string;
  status: OpenCodeStatus;
  progress?: string;
  interaction?: unknown;
  raw?: unknown;
};

function assistantMessages(messages: any[]): any[] {
  return messages.filter(item => item?.info?.role === 'assistant' || item?.role === 'assistant');
}

export function messageId(item: any): string | undefined {
  return item?.info?.id ?? item?.id;
}

function latestAssistant(messages: any[]): any | undefined {
  const list = assistantMessages(messages);
  return list[list.length - 1];
}

function errorText(item: any): string | null {
  const error = item?.info?.error ?? item?.error;
  if (!error) return null;
  if (typeof error === 'string') return error;
  return String(error.data?.message ?? error.message ?? error.name ?? error);
}

function parentId(item: any): string | undefined {
  return item?.info?.parentID ?? item?.info?.parentId ?? item?.parentID ?? item?.parentId;
}

function assistantCompleted(item: any): boolean {
  const info = item?.info ?? item;
  return (info?.time?.completed !== undefined && info?.time?.completed !== null) || info?.completed === true;
}

function completionEvidence(messages: any[], baseline?: MessageBaseline) {
  const assistants = assistantMessages(messages);
  if (!assistants.length) return { isNew: false, error: null as string | null, completed: false };
  let latest = assistants[assistants.length - 1];
  if (baseline?.userMessageId) {
    const linked = [...assistants].reverse().find(item => parentId(item) === baseline.userMessageId);
    if (linked) latest = linked;
    else if (assistants.some(item => parentId(item) !== undefined)) {
      return { isNew: false, error: null as string | null, completed: false };
    }
  }
  const isNew = !baseline || baseline.assistantId === undefined || messageId(latest) !== baseline.assistantId;
  if (!isNew) return { isNew: false, error: null as string | null, completed: false };
  return { isNew: true, error: errorText(latest), completed: assistantCompleted(latest) };
}

export class OpenCodeClient {
  constructor(private readonly server: ServerManager) {}

  async create(runtime: RuntimeRecord, options: { title: string; agent: string; access: string }) {
    const body = await this.server.requestJson<{ id?: string; sessionID?: string }>(runtime, '/session', {
      method: 'POST',
      body: JSON.stringify({ title: options.title }),
      headers: { 'content-type': 'application/json' }
    });
    const id = body?.id ?? body?.sessionID;
    if (!id) throw new BrokerError('PROTOCOL_ERROR', 'OpenCode did not return a Session ID');
    return id;
  }

  async listSessions(runtime: RuntimeRecord): Promise<Array<{ id: string; title?: string }>> {
    const body = await this.server.requestJson<any>(runtime, '/session');
    const sessions = Array.isArray(body) ? body :
      Array.isArray(body?.sessions) ? body.sessions : [];
    return sessions.flatMap((item: any) => {
      const id = item?.id ?? item?.sessionID;
      if (typeof id !== 'string') return [];
      return [{ id, ...(typeof item?.title === 'string' ? { title: item.title } : {}) }];
    });
  }
  async agentExists(runtime: RuntimeRecord, agent: string) {
    const agents = await this.server.requestJson<Array<{ name?: string; id?: string }>>(runtime, '/agent');
    return Array.isArray(agents) && agents.some(item => item.name === agent || item.id === agent);
  }

  async send(runtime: RuntimeRecord, sessionId: string, prompt: string, agent?: string, messageId?: string) {
    const body: Record<string, unknown> = { parts: [{ type: 'text', text: prompt }], ...(agent ? { agent } : {}) };
    if (messageId) body.messageID = messageId;
    await this.server.requestJson(runtime, '/session/' + encodeURIComponent(sessionId) + '/prompt_async', {
      method: 'POST',
      body: JSON.stringify(body),
      headers: { 'content-type': 'application/json' }
    });
    return { accepted: true };
  }

  async messages(runtime: RuntimeRecord, sessionId: string): Promise<any[]> {
    const body = await this.server.requestJson<any>(runtime, '/session/' + encodeURIComponent(sessionId) + '/message');
    return Array.isArray(body) ? body : Array.isArray(body?.messages) ? body.messages : [];
  }

  async status(runtime: RuntimeRecord, sessionId: string, baseline?: MessageBaseline): Promise<SessionInfo> {
    const all = await this.server.requestJson<Record<string, any>>(runtime, '/session/status');
    const raw = all?.[sessionId];
    if (!raw) {
      try {
        await this.server.requestJson(runtime, '/session/' + encodeURIComponent(sessionId));
      } catch (error) {
        if (error instanceof BrokerError && error.code === 'SERVER_HTTP_ERROR' && /HTTP 404\b/.test(error.message)) {
          throw new BrokerError('SESSION_NOT_FOUND', 'OpenCode Session not found');
        }
        throw error;
      }
      const evidence = completionEvidence(await this.messages(runtime, sessionId), baseline);
      if (evidence.error) return { id: sessionId, status: 'failed', progress: evidence.error, interaction: null, raw: { type: 'idle', confirmed: true } };
      if (evidence.isNew && evidence.completed) return { id: sessionId, status: 'completed', progress: undefined, interaction: null, raw: { type: 'idle', confirmed: true } };
      return { id: sessionId, status: 'running', progress: undefined, interaction: null, raw: { type: 'busy', confirmed: true } };
    }
    const value = raw.type ?? raw.status ?? raw.state;
    if (value === 'idle' || value === 'completed') {
      const evidence = completionEvidence(await this.messages(runtime, sessionId), baseline);
      if (evidence.error) return { id: sessionId, status: 'failed', progress: evidence.error, interaction: null, raw };
      if (evidence.isNew && evidence.completed) return { id: sessionId, status: 'completed', progress: undefined, interaction: null, raw };
      return { id: sessionId, status: 'running', progress: undefined, interaction: null, raw };
    }
    const status: OpenCodeStatus =
      value === 'busy' || value === 'retry' || value === 'running' ? 'running' :
      value === 'pending' ? 'pending' :
      value === 'awaiting_permission' ? 'awaiting_permission' :
      value === 'failed' ? 'failed' :
      value === 'interrupted' ? 'interrupted' : 'unknown';
    if (status === 'unknown') throw new BrokerError('PROTOCOL_ERROR', 'OpenCode returned an unknown Session status');
    return { id: sessionId, status, progress: raw.message ?? raw.progress ?? raw.summary ?? null, interaction: raw.interaction ?? null, raw };
  }

  async result(runtime: RuntimeRecord, sessionId: string) {
    const messages = await this.server.requestJson<unknown>(runtime, '/session/' + encodeURIComponent(sessionId) + '/message');
    const diff = await this.server.requestJson<unknown>(runtime, '/session/' + encodeURIComponent(sessionId) + '/diff');
    return { messages, diff };
  }

  async abort(runtime: RuntimeRecord, sessionId: string) {
    try {
      await this.server.requestJson(runtime, '/session/' + encodeURIComponent(sessionId) + '/abort', { method: 'POST' });
      return { status: 'interrupted' as const };
    } catch (error) {
      if (error instanceof BrokerError && error.code === 'SERVER_HTTP_ERROR') {
        throw new BrokerError('ABORT_FAILED', error.message);
      }
      throw error;
    }
  }

  async permissionList(runtime: RuntimeRecord): Promise<any[] | null> {
    try {
      const body = await this.server.requestJson<any>(runtime, '/permission');
      return Array.isArray(body) ? body : Array.isArray(body?.permissions) ? body.permissions : [];
    } catch (error) {
      if (error instanceof BrokerError && error.code === 'SERVER_HTTP_ERROR' && /HTTP 404\b/.test(error.message)) return null;
      throw error;
    }
  }

  async permission(runtime: RuntimeRecord, sessionId: string, permissionId: string, response: string) {
    try {
      await this.server.requestJson(runtime, '/session/' + encodeURIComponent(sessionId) + '/permissions/' + encodeURIComponent(permissionId), {
        method: 'POST',
        body: JSON.stringify({ response }),
        headers: { 'content-type': 'application/json' }
      });
    } catch (error) {
      const notFound = error instanceof BrokerError && error.code === 'SERVER_HTTP_ERROR' && /HTTP 404\b/.test(error.message);
      if (!notFound) throw error;
      // The newer endpoint uses a distinct `reply` field.
      await this.server.requestJson(runtime, '/permission/' + encodeURIComponent(permissionId) + '/reply', {
        method: 'POST',
        body: JSON.stringify({ reply: response }),
        headers: { 'content-type': 'application/json' }
      });
    }
    return { accepted: true };
  }

  async events(runtime: RuntimeRecord, signal: AbortSignal): Promise<Response> {
    return await this.server.request(runtime, '/event', { signal, headers: { accept: 'text/event-stream' } });
  }
}
