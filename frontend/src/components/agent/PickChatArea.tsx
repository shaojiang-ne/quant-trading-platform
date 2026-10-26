import { useEffect, useRef, useMemo } from 'react';
import { Bot } from 'lucide-react';
import { useAgentStore, PICK_TEMPLATES } from '@/stores/agentStore';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { StrategyCard } from './StrategyCard';
import type { QuickTemplate, PickRuleProgram } from '@/types/agent';

export function PickChatArea() {
  const { pickMessages, pickLoading, pickError, sendPickMessage, confirmStrategy, createStrategy, executeStrategy, currentStrategyId, strategies } = useAgentStore();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [pickMessages]);

  const handleTemplateClick = (template: QuickTemplate) => {
    sendPickMessage(template.prompt);
  };

  // Derive the last user/assistant message pair to feed the strategy card.
  // The AI streaming response IS the optimized strategy text; the user's
  // original prompt is the "before". Backend strategy parsing (createPickStrategy)
  // is wired in a later phase — for now the streamed content drives the card.
  const { lastUser, lastAssistant } = useMemo(() => {
    let lastUser = '';
    let lastAssistant = '';
    for (const msg of pickMessages) {
      if (msg.role === 'user' && msg.content) lastUser = msg.content;
      if (msg.role === 'assistant' && msg.content) lastAssistant = msg.content;
    }
    return { lastUser, lastAssistant };
  }, [pickMessages]);

  // 确认后从 store 取后端编译出的规则程序，传给卡片展示。
  // currentStrategyId 在确认成功后由 confirmStrategy 写入；新一轮发送时清空。
  const confirmedRules = useMemo(() => {
    if (!currentStrategyId) return null;
    const s = strategies.find((x) => x.id === currentStrategyId);
    const rules = s?.rules;
    // draft 时 rules 为空数组 []，视为未就绪
    return Array.isArray(rules) ? null : (rules as PickRuleProgram | null);
  }, [currentStrategyId, strategies]);

  // 流式回复完成后展示策略卡片；确认后卡片切换到"已确认+规则"态而非隐藏。
  // key 绑定 lastUser：新一轮输入时卡片重建，adopted 状态自然重置。
  const showStrategyCard =
    !pickLoading &&
    !!lastAssistant &&
    !!lastUser;

  // 采纳优化：以最新一轮 AI 优化描述持久化策略并执行选股
  // （继续优化的最终成果即最新 AI 优化描述）。兜底用用户原始描述，避免空描述。
  const handleAdopt = async () => {
    const strategy = await createStrategy(lastAssistant || lastUser);
    if (!strategy) return;
    const ok = await confirmStrategy(strategy.id);
    if (!ok) return;
    executeStrategy(strategy.id);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {pickMessages.length === 0 ? (
          <div className="text-center py-6">
            <Bot className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="text-gray-500 mb-1 text-sm font-medium">AI选股策略助手</p>
            <p className="text-gray-400 text-xs mb-4">输入你的选股策略，AI将深度分析并优化</p>
            <div className="flex flex-wrap gap-1.5 justify-center max-w-xs mx-auto">
              {PICK_TEMPLATES.map((t) => (
                <button
                  key={t.label}
                  onClick={() => handleTemplateClick(t)}
                  className={`flex items-center gap-1 px-2 py-1 text-xs border rounded-full transition hover:shadow-sm ${t.color}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {pickMessages.map((msg) => <ChatMessage key={msg.id} message={msg} />)}
            {showStrategyCard && (
              <StrategyCard
                key={lastUser}
                original={lastUser}
                optimized={lastAssistant}
                reason="AI 已根据你的策略深度分析并给出优化建议，确认后将用于选股。"
                onAdopt={handleAdopt}
                rules={confirmedRules}
              />
            )}
          </>
        )}
        {pickError && (
          <div className="px-3 py-1.5 bg-red-50 text-red-600 text-xs rounded-lg">{pickError}</div>
        )}
        <div ref={endRef} />
      </div>

      <ChatInput
        onSend={sendPickMessage}
        loading={pickLoading}
        placeholder="描述你的选股策略..."
        templates={PICK_TEMPLATES}
        onTemplateClick={handleTemplateClick}
      />
    </div>
  );
}
