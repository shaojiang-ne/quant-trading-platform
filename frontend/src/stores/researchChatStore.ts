import { create } from 'zustand';
import { streamResearchChat } from '@/api/ai';
import type { AIChatMessage } from '@/api/ai';

// ── 数据获取步骤 ──────────────────────────────────────────────────────────────
export interface DataStep {
  label: string;              // 步骤名称，如"个股估值"
  status: 'loading' | 'done' | 'error';
  summary?: string;           // 获取到的数据摘要（可折叠）
  detail?: any;               // 原始数据（折叠详情）
  error?: string;             // 错误信息
}

// ── 消息类型 ────────────────────────────────────────────────────────────────
export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageType = 'text' | 'data-step';

export interface ResearchChatMessage extends AIChatMessage {
  id: string;
  role: MessageRole;
  isStreaming?: boolean;
  type?: MessageType;         // 默认 'text'，data-step 表示数据获取步骤
  dataStep?: DataStep;        // 数据步骤详情（仅 type=data-step 时有值）
}

// 无场景时的自由对话桶 key（与所有场景隔离）
export const FREE_KEY = '__free__';

interface ResearchChatState {
  // 每个场景（label）独立一份对话历史；无场景时用 FREE_KEY
  messagesByScenario: Record<string, ResearchChatMessage[]>;
  activeScenario: string | null;     // 当前正在编辑/查看的桶 key
  isLoading: boolean;
  error: string | null;

  // 切到指定场景（label 或 null=自由）
  setActiveScenario: (label: string | null) => void;
  // 清空当前 active 桶
  clearMessages: () => void;
  // 清空全部桶（备用）
  clearAll: () => void;

  addMessage: (msg: Partial<ResearchChatMessage> & { role: MessageRole; content: string }) => string;
  updateMessage: (id: string, updates: Partial<ResearchChatMessage>) => void;

  // 普通发送（仅带历史 + 当前 user，无 system 数据注入）— 用于追问或无场景提问
  sendMessage: (content: string) => Promise<void>;
  // 带数据注入的发送：isFollowUp=false 时注入 system 数据；true 时忽略 dataSummary，按追问处理
  sendMessageWithData: (
    userContent: string,
    dataSummary: string,
    stepLabel: string,
    isFollowUp: boolean,
  ) => Promise<void>;
}

export const useResearchChatStore = create<ResearchChatState>()((set, get) => {
  // 内部：对当前 active 桶做不可变更新
  const updateActive = (
    updater: (msgs: ResearchChatMessage[]) => ResearchChatMessage[],
  ): void => {
    set((state) => {
      const key = state.activeScenario ?? FREE_KEY;
      const current = state.messagesByScenario[key] ?? [];
      return {
        messagesByScenario: {
          ...state.messagesByScenario,
          [key]: updater(current),
        },
      };
    });
  };

  // 读取当前 active 桶
  const readActive = (): ResearchChatMessage[] => {
    const state = get();
    const key = state.activeScenario ?? FREE_KEY;
    return state.messagesByScenario[key] ?? [];
  };

  return {
    messagesByScenario: {},
    activeScenario: null,
    isLoading: false,
    error: null,

    setActiveScenario: (label) => set({ activeScenario: label }),

    clearMessages: () => {
      set((state) => {
        const key = state.activeScenario ?? FREE_KEY;
        const next = { ...state.messagesByScenario };
        delete next[key];
        return { messagesByScenario: next, error: null };
      });
    },

    clearAll: () => set({ messagesByScenario: {}, error: null }),

    // ── 直接添加一条消息到当前 active 桶，返回消息 ID ─────────────────
    addMessage: (msg) => {
      const id = `m-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const fullMsg: ResearchChatMessage = {
        id,
        role: msg.role,
        content: msg.content || '',
        type: msg.type || 'text',
        isStreaming: msg.isStreaming,
        dataStep: msg.dataStep,
      };
      updateActive((msgs) => [...msgs, fullMsg]);
      return id;
    },

    // ── 更新指定消息的部分字段 ─────────────────────────────────────
    updateMessage: (id, updates) => {
      updateActive((msgs) => msgs.map((m) => (m.id === id ? { ...m, ...updates } : m)));
    },

    // ── 普通发送（追问或无场景提问）：仅历史 + 当前 user ─────────────
    // 注意：user 消息由调用方在外部 addMessage；本方法只 addMessage assistant 占位 + 流式
    sendMessage: async (content) => {
      const assistantMessage: ResearchChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        type: 'text',
        isStreaming: true,
      };

      updateActive((msgs) => [...msgs, assistantMessage]);
      set({ isLoading: true, error: null });

      try {
        const chatMessages = buildLLMMessages(readActive(), content);
        const stream = streamResearchChat(chatMessages);

        let fullContent = '';
        for await (const chunk of stream) {
          if (chunk.type === 'text' && chunk.content) {
            fullContent += chunk.content;
            updateActive((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessage.id ? { ...m, content: fullContent } : m,
              ),
            );
          } else if (chunk.type === 'error') {
            set({ error: chunk.error || 'AI服务出错' });
          } else if (chunk.type === 'done') {
            updateActive((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessage.id ? { ...m, isStreaming: false } : m,
              ),
            );
            set({ isLoading: false });
          }
        }
      } catch (e) {
        updateActive((msgs) =>
          msgs.map((m) =>
            m.id === assistantMessage.id
              ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
              : m,
          ),
        );
        set({
          isLoading: false,
          error: e instanceof Error ? e.message : '发送失败',
        });
      }
    },

    // ── 带数据注入的发送 ──────────────────────────────────────
    // isFollowUp=false → 首次：注入 system data message
    // isFollowUp=true  → 追问：忽略 dataSummary，仅历史 + 当前 user
    // 注意：user 消息由调用方在外部 addMessage；本方法只 addMessage assistant 占位 + 流式
    sendMessageWithData: async (userContent, dataSummary, stepLabel, isFollowUp) => {
      const assistantMessage: ResearchChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        type: 'text',
        isStreaming: true,
      };

      updateActive((msgs) => [...msgs, assistantMessage]);
      set({ isLoading: true, error: null });

      try {
        const chatMessages = buildLLMMessagesWithData(
          readActive(),
          userContent,
          dataSummary,
          stepLabel,
          isFollowUp,
        );
        const stream = streamResearchChat(chatMessages);

        let fullContent = '';
        for await (const chunk of stream) {
          if (chunk.type === 'text' && chunk.content) {
            fullContent += chunk.content;
            updateActive((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessage.id ? { ...m, content: fullContent } : m,
              ),
            );
          } else if (chunk.type === 'error') {
            set({ error: chunk.error || 'AI服务出错' });
          } else if (chunk.type === 'done') {
            updateActive((msgs) =>
              msgs.map((m) =>
                m.id === assistantMessage.id ? { ...m, isStreaming: false } : m,
              ),
            );
            set({ isLoading: false });
          }
        }
      } catch (e) {
        updateActive((msgs) =>
          msgs.map((m) =>
            m.id === assistantMessage.id
              ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
              : m,
          ),
        );
        set({
          isLoading: false,
          error: e instanceof Error ? e.message : '发送失败',
        });
      }
    },
  };
});

// ── 构造发给 LLM 的消息（追问/无数据，纯历史 + 当前 user）───────────────
function buildLLMMessages(
  messages: ResearchChatMessage[],
  userContent: string,
): AIChatMessage[] {
  // 过滤掉 type=data-step 的系统消息（这些是 UI 展示用的）
  const filtered = messages.filter(
    (m) => !(m.role === 'system' && m.type === 'data-step'),
  );

  const chatMessages: AIChatMessage[] = filtered
    .filter((m) => !m.isStreaming && m.content)
    .map((m) => ({ role: m.role as 'user' | 'assistant' | 'system', content: m.content }));

  // 确保最新的用户消息在内
  if (!chatMessages.find((m) => m.role === 'user' && m.content === userContent)) {
    chatMessages.push({ role: 'user', content: userContent });
  }

  return chatMessages;
}

// ── 构造发给 LLM 的消息（带数据注入，按 isFollowUp 决定是否注入）─────────
function buildLLMMessagesWithData(
  messages: ResearchChatMessage[],
  userContent: string,
  dataSummary: string,
  stepLabel: string,
  isFollowUp: boolean,
): AIChatMessage[] {
  // 过滤掉 UI-only 的 data-step 系统消息
  const filtered = messages.filter(
    (m) => !(m.role === 'system' && m.type === 'data-step'),
  );

  // 取已完成的历史消息
  const historyMessages: AIChatMessage[] = filtered
    .filter((m) => !m.isStreaming && m.content)
    .map((m) => ({ role: m.role as 'user' | 'assistant' | 'system', content: m.content }));

  // 首次：注入 system 数据；追问：直接带历史，LLM 自行参考上下文
  if (!isFollowUp) {
    historyMessages.push({
      role: 'system',
      content: `【系统已自动获取「${stepLabel}」相关数据，请基于这些数据进行分析】\n${dataSummary}`,
    });
  }

  if (!historyMessages.find((m) => m.role === 'user' && m.content === userContent)) {
    historyMessages.push({ role: 'user', content: userContent });
  }

  return historyMessages;
}