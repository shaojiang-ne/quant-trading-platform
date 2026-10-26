import { create } from 'zustand';
import { streamAIChat } from '@/api/ai';
import type { AIChatMessage } from '@/api/ai';

export interface ChatMessage extends AIChatMessage {
  id: string;
  isStreaming?: boolean;
}

export type GenerationPhase = 'idle' | 'understanding' | 'awaiting_confirmation' | 'generating' | 'testing' | 'done' | 'fixing';

/** 记录最近完成的阶段，用于 awaiting_confirmation 时判断下一步 */
export type CompletedPhase = 'understanding' | 'generating' | 'fixing';

interface TestSummary {
  total_bars: number;
  buy_signals: number;
  sell_signals: number;
}

interface TestResult {
  success: boolean;
  error?: string;
  traceback?: string;
  summary?: TestSummary;
  simulated_return_pct?: number;
  signals?: { date: string; signal: number; close: number }[];
}

interface AIChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  generationPhase: GenerationPhase;
  /** 最近完成的阶段，用于 awaiting_confirmation 时判断下一步操作 */
  lastCompletedPhase: CompletedPhase | null;
  testResult: TestResult | null;
  retryCount: number;

  sendMessage: (
    content: string,
    strategyId?: string,
    context?: Record<string, unknown>
  ) => Promise<void>;
  sendMessageForGeneration: (
    content: string,
    phase: 'understand' | 'generate' | 'fix'
  ) => Promise<void>;
  autoTestCode: (code: string, parameters?: Record<string, unknown>) => Promise<TestResult>;
  /** 用户确认后推进到下一阶段 */
  advanceToNextPhase: () => void;
  clearMessages: () => void;
  setGenerationPhase: (phase: GenerationPhase) => void;
  resetGeneration: () => void;
}

const API_BASE = '/api';

function getErrorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

async function* streamGenerate(
  messages: { role: string; content: string }[],
  phase: string
): AsyncGenerator<{ type: string; content?: string; error?: string }> {
  const { useAuthStore } = await import('@/stores');
  const token = useAuthStore.getState().token;

  const response = await fetch(`${API_BASE}/ai/generate-stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ messages, phase }),
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
          yield data;
        } catch {
          // skip malformed JSON
        }
      }
    }
  }
}

export const useAIChatStore = create<AIChatState>()((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,
  generationPhase: 'idle',
  lastCompletedPhase: null,
  testResult: null,
  retryCount: 0,

  sendMessage: async (content, strategyId, context) => {
    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content,
    };

    const assistantMessage: ChatMessage = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };

    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
    }));

    try {
      const chatMessages: AIChatMessage[] = [
        ...get().messages
          .filter((m) => !m.isStreaming && m.content)
          .map((m) => ({ role: m.role, content: m.content })),
      ];
      if (!chatMessages.find((m) => m.role === 'user' && m.content === content)) {
        chatMessages.push({ role: 'user', content });
      }

      const stream = streamAIChat({
        messages: chatMessages,
        strategy_id: strategyId,
        context,
      });

      let fullContent = '';

      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          fullContent += chunk.content;
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id
                ? { ...m, content: fullContent }
                : m
            ),
          }));
        } else if (chunk.type === 'error') {
          set({ error: chunk.error || 'AI服务出错' });
        } else if (chunk.type === 'done') {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id
                ? { ...m, isStreaming: false }
                : m
            ),
            isLoading: false,
          }));
        }
      }
    } catch (e) {
      set((state) => ({
        isLoading: false,
        error: getErrorMessage(e),
        messages: state.messages.map((m) =>
          m.id === assistantMessage.id
            ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
            : m
        ),
      }));
    }
  },

  sendMessageForGeneration: async (content, phase) => {
    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content,
    };

    const assistantMessage: ChatMessage = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };

    const phaseMap: Record<string, GenerationPhase> = {
      understand: 'understanding',
      generate: 'generating',
      fix: 'fixing',
    };

    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
      generationPhase: phaseMap[phase] || 'idle',
      testResult: null,
    }));

    try {
      // 构建消息历史（不含正在流式输出的消息）
      const historyMessages = get().messages
        .filter((m) => !m.isStreaming && m.content && m.id !== assistantMessage.id && m.id !== userMessage.id)
        .map((m) => ({ role: m.role, content: m.content }));
      historyMessages.push({ role: 'user', content });

      const stream = streamGenerate(historyMessages, phase);

      let fullContent = '';

      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          fullContent += chunk.content;
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id
                ? { ...m, content: fullContent }
                : m
            ),
          }));
        } else if (chunk.type === 'error') {
          set({ error: chunk.error || 'AI服务出错' });
        } else if (chunk.type === 'done') {
          // 流式输出完成 → 暂停等待用户确认，而非自动推进
          const completedPhaseMap: Record<string, CompletedPhase> = {
            understand: 'understanding',
            generate: 'generating',
            fix: 'fixing',
          };
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id
                ? { ...m, isStreaming: false }
                : m
            ),
            isLoading: false,
            generationPhase: 'awaiting_confirmation',
            lastCompletedPhase: completedPhaseMap[phase] || state.lastCompletedPhase,
          }));
        }
      }
    } catch (e) {
      set((state) => ({
        isLoading: false,
        error: getErrorMessage(e),
        generationPhase: 'idle',
        messages: state.messages.map((m) =>
          m.id === assistantMessage.id
            ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
            : m
        ),
      }));
    }
  },

  autoTestCode: async (code, parameters) => {
    set({ generationPhase: 'testing' });

    try {
      const { useAuthStore } = await import('@/stores');
      const token = useAuthStore.getState().token;

      const res = await fetch(`${API_BASE}/ai/test-code`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ code, parameters: parameters || {} }),
      });
      const data = await res.json();
      set({ testResult: data, generationPhase: 'done' });
      return data as TestResult;
    } catch (e) {
      const result: TestResult = { success: false, error: getErrorMessage(e) };
      set({ testResult: result });
      return result;
    }
  },

  clearMessages: () => set({ messages: [], error: null, generationPhase: 'idle', lastCompletedPhase: null, testResult: null, retryCount: 0 }),
  setGenerationPhase: (phase) => set({ generationPhase: phase }),
  resetGeneration: () => set({ generationPhase: 'idle', lastCompletedPhase: null, testResult: null, retryCount: 0 }),

  advanceToNextPhase: () => {
    const state = get();

    if (state.lastCompletedPhase === 'understanding') {
      // 理解确认 → 生成代码
      state.sendMessageForGeneration('确认，请根据以上理解生成策略代码。', 'generate');
    } else if (state.lastCompletedPhase === 'generating' || state.lastCompletedPhase === 'fixing') {
      // 代码确认 → 自动测试
      const lastAssistant = [...state.messages].reverse().find((m) => m.role === 'assistant' && !m.isStreaming);
      if (!lastAssistant || !lastAssistant.content) return;
      const codeMatch = lastAssistant.content.match(/```python\n([\s\S]*?)```/);
      if (!codeMatch) return;
      const code = codeMatch[1].trim();
      state.autoTestCode(code);
    }
  },
}));
