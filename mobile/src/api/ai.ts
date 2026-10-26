import { useAuthStore } from '@/stores/authStore';

const API_BASE = '/api';

export interface AIChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface AIChatRequest {
  messages: AIChatMessage[];
  strategy_id?: string;
  context?: Record<string, unknown>;
}

export interface StreamChunk {
  type: 'text' | 'error' | 'done';
  content?: string;
  error?: string;
}

async function createAuthenticatedRequest(
  path: string,
  body: unknown
): Promise<Response> {
  const token = useAuthStore.getState().token;

  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `AI服务请求失败 (${response.status})`);
  }

  return response;
}

async function* parseSSEStream(response: Response): AsyncGenerator<StreamChunk> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          yield data as StreamChunk;
        } catch {
          // skip malformed JSON
        }
      }
    }
  }
}

export async function* streamResearchChat(
  messages: AIChatMessage[]
): AsyncGenerator<StreamChunk> {
  const response = await createAuthenticatedRequest('/ai/research-chat', { messages });
  yield* parseSSEStream(response);
}

export async function* streamAIChat(
  req: AIChatRequest
): AsyncGenerator<StreamChunk> {
  const response = await createAuthenticatedRequest('/ai/chat', req);
  yield* parseSSEStream(response);
}
