import { useState, useRef, useEffect } from 'react';
import { Header } from '@/components/Header';
import { ChatBubble } from '@/components/ChatBubble';
import { DataStepCard } from '@/components/DataStepCard';
import { ScenarioGrid, ScenarioPills, quickScenarios } from '@/components/ScenarioGrid';
import { ChatInput } from '@/components/ChatInput';
import { useResearchChatStore } from '@/stores/researchChatStore';
import { useStockCacheStore, resolveCode, resolveCodes } from '@/stores/stockCacheStore';
import { useAuthStore } from '@/stores/authStore';
import type { Scenario } from '@/components/ScenarioGrid';

export function AIAssistant() {
  const [input, setInput] = useState('');
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, isLoading, error, sendMessage, sendMessageWithData, addMessage, updateMessage, clearMessages } = useResearchChatStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    useStockCacheStore.getState().fetchAll();
  }, []);

  const handleSelectScenario = (scenario: Scenario) => {
    setSelectedScenario(scenario);
    setInput(scenario.prompt);
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const content = input.trim();
    setInput('');
    const matchedScenario = selectedScenario;
    setSelectedScenario(null);

    if (matchedScenario?.fetchData) {
      const needsCode = matchedScenario.requiresCode !== false;
      const code = needsCode
        ? (matchedScenario.multiCode ? resolveCodes(content) : await resolveCode(content))
        : '';

      addMessage({ role: 'user', content, type: 'text' });

      const stepMsgId = addMessage({
        role: 'system',
        content: '',
        type: 'data-step',
        dataStep: { label: matchedScenario.label, status: 'loading' },
      });

      if (needsCode && !code) {
        updateMessage(stepMsgId, {
          dataStep: {
            label: matchedScenario.label,
            status: 'error',
            error: '未识别到股票代码或名称，请输入 6 位代码或完整股票名称',
          },
        });
        await sendMessage(content);
        return;
      }

      try {
        const { summary } = await matchedScenario.fetchData(code);
        updateMessage(stepMsgId, {
          dataStep: { label: matchedScenario.label, status: 'done', summary },
        });
        await sendMessageWithData(content, summary, matchedScenario.label);
      } catch (e: any) {
        updateMessage(stepMsgId, {
          dataStep: { label: matchedScenario.label, status: 'error', error: e.message || '未知错误' },
        });
        await sendMessage(content);
      }
    } else {
      await sendMessage(content);
    }
  };

  const dataLoading = messages.some(
    (m) => m.role === 'system' && m.type === 'data-step' && m.dataStep?.status === 'loading'
  );

  return (
    <div className="flex flex-col h-screen h-[100dvh] bg-gray-50">
      <Header onClear={() => { clearMessages(); setSelectedScenario(null); }} onLogout={() => useAuthStore.getState().logout()} hasMessages={messages.length > 0} />

      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full px-4 pb-20">
            <div className="w-14 h-14 rounded-2xl bg-primary-600 flex items-center justify-center mb-3 shadow-lg shadow-primary-600/20">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <h2 className="text-lg font-bold text-gray-900 mb-0.5">AI股票研究助手</h2>
            <p className="text-xs text-gray-400 mb-6 text-center">选择场景，输入股票代码或问题，自动获取真实数据</p>
            <ScenarioGrid onSelect={handleSelectScenario} />
          </div>
        ) : (
          <div className="py-3 space-y-1">
            {messages.map((msg) => {
              if (msg.role === 'system' && msg.type === 'data-step' && msg.dataStep) {
                return <DataStepCard key={msg.id} step={msg.dataStep} />;
              }
              return <ChatBubble key={msg.id} message={msg} />;
            })}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 场景快捷栏：始终固定在底部 */}
      {messages.length > 0 && (
        <ScenarioPills
          scenarios={quickScenarios}
          selectedLabel={selectedScenario?.label ?? null}
          onSelect={handleSelectScenario}
        />
      )}

      {error && (
        <div className="px-4 py-1.5 bg-red-50 text-red-600 text-xs border-t border-red-100">
          {error}
        </div>
      )}

      <ChatInput
        value={input}
        onChange={setInput}
        onSend={handleSend}
        disabled={isLoading || dataLoading}
        placeholder={
          selectedScenario
            ? selectedScenario.requiresCode === false
              ? `已选择「${selectedScenario.label}」，可直接发送`
              : `已选择「${selectedScenario.label}」，可修改代码后发送`
            : '输入问题，如「帮我估一下 688017」…'
        }
        scenarioLabel={selectedScenario?.label}
      />
    </div>
  );
}
