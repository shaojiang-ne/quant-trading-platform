import { useAuthStore } from '@/stores';

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

export async function* streamAIChat(
  req: AIChatRequest
): AsyncGenerator<StreamChunk> {
  const token = useAuthStore.getState().token;

  const response = await fetch(`${API_BASE}/ai/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(req),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `AI服务请求失败 (${response.status})`);
  }

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

export interface AnalyzeStockResult {
  success: boolean;
  error?: string;
  analysis?: string;
  strategy_id?: string;
  reason?: string;
  params?: Record<string, unknown>;
  risk_tip?: string;
}

export async function analyzeStock(symbol: string, stockName?: string): Promise<AnalyzeStockResult> {
  const token = useAuthStore.getState().token;
  const response = await fetch(`${API_BASE}/ai/analyze-stock`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ symbol, stock_name: stockName || '' }),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `AI分析请求失败 (${response.status})`);
  }

  return response.json();
}

// ── AI 研究助手（独立端点）─────────────────────────────────────────────────────

export async function* streamResearchChat(
  messages: AIChatMessage[]
): AsyncGenerator<StreamChunk> {
  const token = useAuthStore.getState().token;

  const response = await fetch(`${API_BASE}/ai/research-chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ messages }),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `AI助手请求失败 (${response.status})`);
  }

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

export interface GenerateStrategyResult {
  success: boolean;
  error?: string;
  name?: string;
  description?: string;
  code?: string;
  parameters?: Record<string, { value: unknown; type: string; label: string; min?: number; max?: number }>;
}

export async function generateStrategyFromIdea(idea: string): Promise<GenerateStrategyResult> {
  const token = useAuthStore.getState().token;
  const response = await fetch(`${API_BASE}/ai/generate-strategy`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ idea }),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `AI生成请求失败 (${response.status})`);
  }

  return response.json();
}

