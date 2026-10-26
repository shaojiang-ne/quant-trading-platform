import { create } from 'zustand';
import { streamResearchChat } from '@/api/ai';
import type { AIChatMessage } from '@/api/ai';

// ── 数据获取步骤 ──────────────────────────────────────────────────────────────
export interface DataStep {
  label: string;
  status: 'loading' | 'done' | 'error';
  summary?: string;
  detail?: any;
  error?: string;
}

// ── 消息类型 ────────────────────────────────────────────────────────────────
export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageType = 'text' | 'data-step';

export interface ResearchChatMessage extends AIChatMessage {
  id: string;
  role: MessageRole;
  isStreaming?: boolean;
  type?: MessageType;
  dataStep?: DataStep;
}

interface ResearchChatState {
  messages: ResearchChatMessage[];
  isLoading: boolean;
  error: string | null;

  sendMessage: (content: string) => Promise<void>;
  sendMessageWithData: (userContent: string, dataSummary: string, stepLabel: string) => Promise<void>;
  addMessage: (msg: Partial<ResearchChatMessage> & { role: MessageRole; content: string }) => string;
  updateMessage: (id: string, updates: Partial<ResearchChatMessage>) => void;
  clearMessages: () => void;
}

let msgCounter = 0;
function nextId(prefix: string) {
  return `${prefix}-${Date.now()}-${++msgCounter}`;
}

export const useResearchChatStore = create<ResearchChatState>()((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,

  addMessage: (msg) => {
    const id = nextId('m');
    const fullMsg: ResearchChatMessage = {
      id,
      role: msg.role,
      content: msg.content || '',
      type: msg.type || 'text',
      isStreaming: msg.isStreaming,
      dataStep: msg.dataStep,
    };
    set((state) => ({ messages: [...state.messages, fullMsg] }));
    return id;
  },

  updateMessage: (id, updates) => {
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, ...updates } : m
      ),
    }));
  },

  sendMessage: async (content) => {
    const assistantId = nextId('a');
    const assistantMessage: ResearchChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      type: 'text',
      isStreaming: true,
    };

    set((state) => ({
      messages: [...state.messages,
        { id: nextId('u'), role: 'user', content, type: 'text' },
        assistantMessage,
      ],
      isLoading: true,
      error: null,
    }));

    try {
      const chatMessages = buildLLMMessages(get().messages, content);
      const stream = streamResearchChat(chatMessages);

      let fullContent = '';
      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          fullContent += chunk.content;
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, content: fullContent } : m
            ),
          }));
        } else if (chunk.type === 'error') {
          set({ error: chunk.error || 'AI服务出错' });
        } else if (chunk.type === 'done') {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, isStreaming: false } : m
            ),
            isLoading: false,
          }));
        }
      }
    } catch (e) {
      set((state) => ({
        isLoading: false,
        error: e instanceof Error ? e.message : '发送失败',
        messages: state.messages.map((m) =>
          m.id === assistantId
            ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
            : m
        ),
      }));
    }
  },

  sendMessageWithData: async (userContent, dataSummary, stepLabel) => {
    const assistantId = nextId('a');
    const assistantMessage: ResearchChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      type: 'text',
      isStreaming: true,
    };

    set((state) => ({
      messages: [...state.messages, assistantMessage],
      isLoading: true,
      error: null,
    }));

    try {
      const chatMessages = buildLLMMessagesWithData(get().messages, userContent, dataSummary, stepLabel);
      const stream = streamResearchChat(chatMessages);

      let fullContent = '';
      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          fullContent += chunk.content;
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, content: fullContent } : m
            ),
          }));
        } else if (chunk.type === 'error') {
          set({ error: chunk.error || 'AI服务出错' });
        } else if (chunk.type === 'done') {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, isStreaming: false } : m
            ),
            isLoading: false,
          }));
        }
      }
    } catch (e) {
      set((state) => ({
        isLoading: false,
        error: e instanceof Error ? e.message : '发送失败',
        messages: state.messages.map((m) =>
          m.id === assistantId
            ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
            : m
        ),
      }));
    }
  },

  clearMessages: () => set({ messages: [], error: null }),
}));

// ── 构造发给 LLM 的消息 ──────────────────────────────────────────────────────
function buildLLMMessages(messages: ResearchChatMessage[], userContent: string): AIChatMessage[] {
  const filtered = messages.filter(
    (m) => !(m.role === 'system' && m.type === 'data-step')
  );

  const chatMessages: AIChatMessage[] = filtered
    .filter((m) => !m.isStreaming && m.content)
    .map((m) => ({ role: m.role as 'user' | 'assistant' | 'system', content: m.content }));

  if (!chatMessages.find((m) => m.role === 'user' && m.content === userContent)) {
    chatMessages.push({ role: 'user', content: userContent });
  }

  return chatMessages;
}

function buildLLMMessagesWithData(
  messages: ResearchChatMessage[],
  userContent: string,
  dataSummary: string,
  stepLabel: string,
): AIChatMessage[] {
  const filtered = messages.filter(
    (m) => !(m.role === 'system' && m.type === 'data-step')
  );

  const historyMessages: AIChatMessage[] = filtered
    .filter((m) => !m.isStreaming && m.content)
    .map((m) => ({ role: m.role as 'user' | 'assistant' | 'system', content: m.content }));

  const systemDataMessage: AIChatMessage = {
    role: 'system',
    content: `【系统已自动获取「${stepLabel}」相关数据，请基于这些数据进行分析】\n${dataSummary}`,
  };

  return [
    ...historyMessages,
    systemDataMessage,
    { role: 'user', content: userContent },
  ];
}
