import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, Trash2, Bot, User, Sparkles, Code, Settings, FileText, X, Play, Check, Copy, Maximize2, Minimize2, Zap, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { useAIChatStore, type GenerationPhase } from '@/stores';

interface AIChatPanelProps {
  strategyId?: string;
  strategyContext?: Record<string, unknown>;
  onApplyCode?: (code: string) => void;
  onApplyDescription?: (desc: string) => void;
  onApplyParameters?: (params: Record<string, unknown>) => void;
  onCodeGenerated?: (result: { code: string; desc?: string; params?: Record<string, unknown> }) => void;
  mode?: 'chat' | 'generate';
  onClose?: () => void;
}

// ── Markdown segment parser ──────────────────────────────────────────────
interface TextSegment {
  type: 'text';
  content: string;
}
interface CodeSegment {
  type: 'code';
  lang: string;
  code: string;
}
type Segment = TextSegment | CodeSegment;

function parseSegments(raw: string): Segment[] {
  const segments: Segment[] = [];
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    if (m.index > last) {
      segments.push({ type: 'text', content: raw.slice(last, m.index) });
    }
    segments.push({ type: 'code', lang: m[1] || 'python', code: m[2] });
    last = re.lastIndex;
  }
  if (last < raw.length) {
    segments.push({ type: 'text', content: raw.slice(last) });
  }
  return segments;
}

// ── Code block component ──────────────────────────────────────────────────
function CodeBlock({
  lang,
  code,
  onApply,
  onTest,
  isTesting,
}: {
  lang: string;
  code: string;
  onApply?: () => void;
  onTest?: () => void;
  isTesting?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="my-2 rounded-lg overflow-hidden border border-gray-700">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 text-gray-400 text-xs">
        <span className="font-mono">{lang}</span>
        <div className="flex items-center gap-1.5">
          {onApply && (
            <button
              onClick={onApply}
              className="flex items-center gap-1 px-2 py-0.5 bg-primary-600 text-white rounded text-xs hover:bg-primary-700 transition"
            >
              <Check className="w-3 h-3" />
              应用
            </button>
          )}
          {onTest && (
            <button
              onClick={onTest}
              disabled={isTesting}
              className="flex items-center gap-1 px-2 py-0.5 bg-green-600 text-white rounded text-xs hover:bg-green-700 disabled:opacity-50 transition"
            >
              <Play className="w-3 h-3" />
              {isTesting ? '测试中...' : '测试'}
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-1.5 py-0.5 hover:bg-gray-700 rounded text-xs transition"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      </div>
      <pre className="bg-gray-900 p-3 text-sm text-gray-200 overflow-x-auto max-h-[32rem] leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ── Test result display ────────────────────────────────────────────────────
function TestResult({ result }: { result: Record<string, unknown> }) {
  if (result.success) {
    const s = result.summary as Record<string, number>;
    return (
      <div className="my-2 p-3 bg-green-50 border border-green-200 rounded-lg text-sm">
        <div className="flex items-center gap-1.5 text-green-700 font-medium mb-2">
          <CheckCircle className="w-3.5 h-3.5" />
          测试通过
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-gray-700">
          <span>数据条数: {s.total_bars}</span>
          <span>买入信号: {s.buy_signals}</span>
          <span>卖出信号: {s.sell_signals}</span>
          <span>模拟收益: <span className={Number(result.simulated_return_pct) >= 0 ? 'text-green-600' : 'text-red-600'}>{String(result.simulated_return_pct)}%</span></span>
        </div>
        {(result.signals as unknown[])?.length > 0 && (
          <details className="mt-2">
            <summary className="text-xs text-gray-500 cursor-pointer">查看信号明细</summary>
            <div className="mt-1 max-h-24 overflow-y-auto text-xs font-mono text-gray-600">
              {(result.signals as { date: string; signal: number; close: number }[]).map((sig, i) => (
                <div key={i}>{sig.date} {sig.signal === 1 ? '买入' : '卖出'} @ {sig.close}</div>
              ))}
            </div>
          </details>
        )}
      </div>
    );
  }
  return (
    <div className="my-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm">
      <div className="flex items-center gap-1.5 text-red-700 font-medium mb-1">
        <X className="w-3.5 h-3.5" />
        测试失败
      </div>
      <p className="text-red-600 text-xs">{String(result.error)}</p>
      {Boolean(result.traceback) && (
        <pre className="mt-1 text-xs text-gray-600 bg-red-50 p-2 rounded overflow-x-auto max-h-32">{String(result.traceback)}</pre>
      )}
    </div>
  );
}

// ── Phase indicator ──────────────────────────────────────────────────────
function PhaseIndicator({ phase }: { phase: GenerationPhase }) {
  const phases: { key: GenerationPhase; label: string }[] = [
    { key: 'understanding', label: '理解需求' },
    { key: 'generating', label: '生成代码' },
    { key: 'testing', label: '自动测试' },
    { key: 'done', label: '完成' },
  ];

  const currentIndex = phases.findIndex((p) => p.key === phase);
  // fixing is same as generating for the indicator
  const activeIndex = phase === 'fixing' ? 1 : currentIndex;
  // awaiting_confirmation highlights the current active step (same as the completed one)
  const isAwaitingConfirmation = phase === 'awaiting_confirmation';

  if (phase === 'idle') return null;

  return (
    <div className="flex items-center gap-1 px-4 py-2 bg-gray-50 border-b border-gray-200 text-xs">
      {phases.map((p, i) => (
        <div key={p.key} className="flex items-center gap-1">
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
            i < activeIndex || (isAwaitingConfirmation && i === activeIndex) ? 'bg-green-500 text-white'
            : i === activeIndex ? 'bg-primary-600 text-white animate-pulse'
            : 'bg-gray-200 text-gray-400'
          }`}>
            {i < activeIndex || (isAwaitingConfirmation && i === activeIndex) ? '✓' : i + 1}
          </div>
          <span className={i <= activeIndex || (isAwaitingConfirmation && i === activeIndex) ? 'text-gray-700 font-medium' : 'text-gray-400'}>{p.label}</span>
          {i < phases.length - 1 && <Chevron className="w-3 h-3 text-gray-300 mx-0.5" />}
        </div>
      ))}
      {phase === 'fixing' && (
        <span className="ml-2 text-yellow-600 font-medium">（修复中...）</span>
      )}
      {isAwaitingConfirmation && (
        <span className="ml-2 text-amber-600 font-medium animate-pulse">⏸ 等待确认</span>
      )}
    </div>
  );
}

function Chevron({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────
export function AIChatPanel({
  strategyId,
  strategyContext,
  onApplyCode,
  onApplyDescription,
  onApplyParameters,
  onCodeGenerated,
  mode = 'chat',
  onClose,
}: AIChatPanelProps) {
  const [input, setInput] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, Record<string, unknown>>>({});
  const [testingKeys, setTestingKeys] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    isLoading,
    error,
    generationPhase,
    lastCompletedPhase,
    testResult,
    retryCount,
    sendMessage,
    sendMessageForGeneration,
    advanceToNextPhase,
    clearMessages,
  } = useAIChatStore();

  // 只滚动 AIChatPanel 内部消息容器，避免 scrollIntoView 联动滚动外层 Layout/window
  useEffect(() => {
    const c = messagesContainerRef.current;
    if (c) c.scrollTop = c.scrollHeight;
  }, [messages]);

  // 自动测试已移除：改为用户点击确认按钮后才触发测试
  // 测试通过/失败后的阶段转换由 autoTestCode 内部处理

  // ESC 关闭全屏
  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [expanded]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const content = input.trim();
    setInput('');

    if (mode === 'generate') {
      if (generationPhase === 'idle') {
        // 首次输入：启动理解阶段
        sendMessageForGeneration(content, 'understand');
      } else if (generationPhase === 'awaiting_confirmation') {
        // 等待确认阶段：用户输入修改意见 → 重新运行对应阶段
        if (lastCompletedPhase === 'understanding') {
          sendMessageForGeneration(`请根据以下意见调整理解：${content}\n\n请重新输出你对策略的完整理解。`, 'understand');
        } else if (lastCompletedPhase === 'generating' || lastCompletedPhase === 'fixing') {
          // 用户主动调整代码 → 走 generate 而非 fix，避免显示"自动修复"
          sendMessageForGeneration(`请根据以下意见调整代码：${content}\n\n请输出完整的调整后代码。`, 'generate');
        }
      } else if (generationPhase === 'done') {
        // 已完成：用户追加修改 → 走 generate 避免"自动修复"提示
        sendMessageForGeneration(`请根据以下需求调整策略：${content}\n\n请输出完整的调整后代码。`, 'generate');
      }
      // 其他阶段（understanding/generating/testing/fixing 进行中）忽略输入，避免打断
    } else {
      sendMessage(content, strategyId, strategyContext);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleConfirmAndAdvance = () => {
    if (isLoading) return;
    advanceToNextPhase();
  };

  const extractDesc = (_content: string): string => {
    const m = _content.match(/```desc\n([\s\S]*?)```/);
    return m ? m[1].trim() : '';
  };

  const extractParams = (_content: string): Record<string, unknown> | null => {
    const m = _content.match(/```json\n([\s\S]*?)```/);
    if (!m) return null;
    try { return JSON.parse(m[1].trim()); } catch { return null; }
  };

  const extractPythonCode = (_content: string): string => {
    const m = _content.match(/```python\n([\s\S]*?)```/);
    return m ? m[1].trim() : '';
  };

  const handleApplyGenerated = (msgContent: string) => {
    const code = extractPythonCode(msgContent);
    const desc = extractDesc(msgContent);
    const params = extractParams(msgContent);

    if (onCodeGenerated) {
      onCodeGenerated({ code, desc: desc || undefined, params: params || undefined });
    } else {
      if (code && onApplyCode) onApplyCode(code);
      if (desc && onApplyDescription) onApplyDescription(desc);
      if (params && onApplyParameters) onApplyParameters(params);
    }
  };

  const handleTest = useCallback(async (msgId: string, code: string) => {
    setTestingKeys((prev) => new Set(prev).add(msgId));
    try {
      const { useAuthStore } = await import('@/stores');
      const token = useAuthStore.getState().token;

      // 提取参数值（前端参数格式为 {key: {value, type, label}}，需要提取为 {key: value}）
      const paramValues: Record<string, unknown> = {};
      if (strategyContext?.parameters) {
        Object.entries(strategyContext.parameters as Record<string, any>).forEach(([k, v]) => {
          if (v && typeof v === 'object' && 'value' in v) {
            paramValues[k] = v.value;
          } else {
            paramValues[k] = v;
          }
        });
      }

      const res = await fetch('/api/ai/test-code', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ code, parameters: paramValues }),
      });
      const data = await res.json();
      setTestResults((prev) => ({ ...prev, [msgId]: data }));
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [msgId]: { success: false, error: String(e) } }));
    } finally {
      setTestingKeys((prev) => {
        const next = new Set(prev);
        next.delete(msgId);
        return next;
      });
    }
  }, [strategyContext]);

  const quickPrompts = mode === 'generate'
    ? [
        { icon: Sparkles, text: '趋势跟踪', prompt: '我想做一个趋势跟踪策略，当均线金叉时买入，死叉时卖出' },
        { icon: Code, text: '超买超卖', prompt: '我想做一个RSI超买超卖策略，RSI低于30买入，高于70卖出' },
        { icon: Settings, text: '布林带突破', prompt: '我想做布林带策略，价格触及下轨买入，触及上轨卖出' },
      ]
    : [
        { icon: Sparkles, text: '分析策略', prompt: '请分析当前策略的优缺点，并给出改进建议。' },
        { icon: Code, text: '优化代码', prompt: '请帮我优化策略代码，提高可读性和性能。' },
        { icon: Settings, text: '推荐参数', prompt: '根据策略逻辑，推荐最优的参数设置。' },
        { icon: FileText, text: '生成描述', prompt: '请根据策略代码生成一段清晰的策略描述。' },
      ];

  // 判断是否显示阶段确认按钮（awaiting_confirmation 阶段）
  const showConfirmButton = mode === 'generate' && generationPhase === 'awaiting_confirmation' && !isLoading && (() => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && !m.isStreaming);
    if (!lastAssistant) return false;
    return lastAssistant.content.length > 20;
  })();

  // 根据上一阶段确定确认按钮文案
  const confirmButtonLabel = (() => {
    if (lastCompletedPhase === 'understanding') return '理解正确，生成代码';
    if (lastCompletedPhase === 'generating') return '确认代码，开始测试';
    if (lastCompletedPhase === 'fixing') return '确认修复，重新测试';
    return '确认并继续';
  })();

  // 判断是否显示"应用代码"按钮（测试通过时）
  const showApplyButton = mode === 'generate' && generationPhase === 'done' && !isLoading && (() => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && !m.isStreaming);
    if (!lastAssistant) return false;
    return /```python/.test(lastAssistant.content);
  })();

  const panel = (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center gap-2">
          <Bot className="w-5 h-5 text-primary-600" />
          <h3 className="font-semibold text-gray-900">
            {mode === 'generate' ? 'AI 策略生成' : 'AI 策略助手'}
          </h3>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
            title={expanded ? '缩小' : '全屏'}
          >
            {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          <button
            onClick={() => { clearMessages(); }}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
            title="清空对话"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Phase indicator (generate mode only) */}
      {mode === 'generate' && <PhaseIndicator phase={generationPhase} />}

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-5 space-y-5">
        {messages.length === 0 ? (
          <div className="text-center py-12">
            <Bot className="w-14 h-14 mx-auto text-gray-300 mb-4" />
            <p className="text-gray-500 mb-5">
              {mode === 'generate'
                ? '描述您的策略想法，AI 会先理解确认再生成代码'
                : '我是你的策略助手，可以帮你：'}
            </p>
            <div className={`grid gap-3 max-w-sm mx-auto ${quickPrompts.length <= 3 ? 'grid-cols-1' : 'grid-cols-2'}`}>
              {quickPrompts.map((qp) => (
                <button
                  key={qp.text}
                  onClick={() => {
                    if (mode === 'generate') {
                      sendMessageForGeneration(qp.prompt, 'understand');
                    } else {
                      sendMessage(qp.prompt, strategyId, strategyContext);
                    }
                  }}
                  className="flex items-center gap-2 p-3 text-sm text-gray-600 bg-gray-50 hover:bg-gray-100 rounded-lg transition text-left"
                >
                  <qp.icon className="w-4 h-4 text-primary-500 flex-shrink-0" />
                  <span>{qp.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const segments = msg.role === 'assistant' && msg.content ? parseSegments(msg.content) : [];
            return (
              <div
                key={msg.id}
                className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                    msg.role === 'user'
                      ? 'bg-primary-100 text-primary-600'
                      : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {msg.role === 'user' ? (
                    <User className="w-4 h-4" />
                  ) : (
                    <Bot className="w-4 h-4" />
                  )}
                </div>
                <div className={`flex-1 min-w-0 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                  {msg.role === 'user' ? (
                    <div className="inline-block max-w-[85%] px-3 py-2 rounded-lg text-sm bg-primary-600 text-white">
                      <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                    </div>
                  ) : (
                    <div className="max-w-full">
                      {segments.length > 0 ? (
                        segments.map((seg, i) =>
                          seg.type === 'code' ? (
                            <CodeBlock
                              key={i}
                              lang={seg.lang}
                              code={seg.code}
                              onApply={
                                seg.lang === 'python' && onApplyCode
                                  ? () => onApplyCode(seg.code)
                                  : undefined
                              }
                              onTest={
                                seg.lang === 'python'
                                  ? () => handleTest(msg.id, seg.code)
                                  : undefined
                              }
                              isTesting={testingKeys.has(msg.id)}
                            />
                          ) : (
                            <div key={i} className="text-sm text-gray-800 leading-relaxed">
                              <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-2 prose-table:text-xs">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.content}</ReactMarkdown>
                              </div>
                            </div>
                          ),
                        )
                      ) : (
                        <div className="max-w-full text-sm text-gray-800 leading-relaxed">
                          <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-2 prose-table:text-xs">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>
                          </div>
                        </div>
                      )}
                      {msg.isStreaming && (
                        <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse ml-1" />
                      )}

                      {/* 阶段确认按钮（awaiting_confirmation 阶段） */}
                      {showConfirmButton && msg === [...messages].reverse().find((m) => m.role === 'assistant') && (
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <button
                            onClick={handleConfirmAndAdvance}
                            className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition text-sm font-medium shadow-sm"
                          >
                            <CheckCircle className="w-4 h-4" />
                            {confirmButtonLabel}
                          </button>
                          <span className="text-xs text-gray-400">或输入修改意见后发送</span>
                        </div>
                      )}

                      {/* 自动测试结果（generate 模式） */}
                      {mode === 'generate' && testResult && msg === [...messages].reverse().find((m) => m.role === 'assistant' && /```python/.test(m.content)) && !msg.isStreaming && (
                        <TestResult result={testResult as unknown as Record<string, unknown>} />
                      )}

                      {/* 应用代码按钮（测试通过后） */}
                      {showApplyButton && msg === [...messages].reverse().find((m) => m.role === 'assistant') && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            onClick={() => handleApplyGenerated(msg.content)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition shadow-sm"
                          >
                            <Zap className="w-3.5 h-3.5" />
                            应用代码到编辑器
                          </button>
                          {testResult && !testResult.success && (
                            <button
                              onClick={() => {
                                useAIChatStore.setState({ retryCount: retryCount + 1 });
                                const fixMsg = `代码测试失败，错误如下：\n${testResult.error}\n\n${testResult.traceback || ''}\n\n请修复以上错误，输出完整的修复后代码。`;
                                sendMessageForGeneration(fixMsg, 'fix');
                              }}
                              disabled={isLoading}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-yellow-500 text-white rounded-lg hover:bg-yellow-600 transition disabled:opacity-50"
                            >
                              <AlertTriangle className="w-3.5 h-3.5" />
                              手动修复
                            </button>
                          )}
                        </div>
                      )}

                      {/* Chat 模式的应用按钮 */}
                      {mode === 'chat' && msg.role === 'assistant' && !msg.isStreaming && msg.content && (() => {
                        const _code = extractPythonCode(msg.content);
                        const _desc = extractDesc(msg.content);
                        const _params = extractParams(msg.content);
                        const hasAny = (_code && onApplyCode) || (_desc && onApplyDescription) || (_params && onApplyParameters);
                        if (!hasAny) return null;
                        return (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {(_code && onApplyCode) || (_desc && onApplyDescription) || (_params && onApplyParameters) ? (
                              <button
                                onClick={() => {
                                  if (_code && onApplyCode) onApplyCode(_code);
                                  if (_desc && onApplyDescription) onApplyDescription(_desc);
                                  if (_params && onApplyParameters) onApplyParameters(_params!);
                                }}
                                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-primary-600 text-white rounded hover:bg-primary-700 transition"
                              >
                                <Zap className="w-3 h-3" />
                                一键应用全部
                              </button>
                            ) : null}
                            {_code && onApplyCode && (
                              <button
                                onClick={() => onApplyCode(_code)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-blue-50 text-blue-600 rounded hover:bg-blue-100 transition"
                              >
                                <Code className="w-3 h-3" />
                                仅应用代码
                              </button>
                            )}
                            {_desc && onApplyDescription && (
                              <button
                                onClick={() => onApplyDescription(_desc)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-purple-50 text-purple-600 rounded hover:bg-purple-100 transition"
                              >
                                <FileText className="w-3 h-3" />
                                仅应用描述
                              </button>
                            )}
                            {_params && onApplyParameters && (
                              <button
                                onClick={() => onApplyParameters(_params!)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-green-50 text-green-600 rounded hover:bg-green-100 transition"
                              >
                                <Settings className="w-3 h-3" />
                                仅应用参数
                              </button>
                            )}
                          </div>
                        );
                      })()}

                      {/* Chat 模式的测试按钮结果 */}
                      {mode === 'chat' && testResults[msg.id] && <TestResult result={testResults[msg.id]} />}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* 自动测试/修复中的状态提示 */}
        {mode === 'generate' && generationPhase === 'testing' && (
          <div className="flex items-center gap-2 px-4 py-2 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700">
            <Loader2 className="w-4 h-4 animate-spin" />
            正在自动测试代码...
          </div>
        )}
        {mode === 'generate' && generationPhase === 'fixing' && (
          <div className="flex items-center gap-2 px-4 py-2 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-700">
            <Loader2 className="w-4 h-4 animate-spin" />
            测试未通过，正在自动修复（第 {retryCount} 次尝试）...
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-red-50 text-red-600 text-sm">{error}</div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-gray-200">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === 'generate'
                ? (generationPhase === 'idle' ? '描述您的策略想法...' : generationPhase === 'awaiting_confirmation' ? '输入修改意见，或点击确认按钮继续...' : '输入确认或修改意见...')
                : '输入问题或需求...'
            }
            rows={2}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="px-3 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition self-end"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );

  // 全屏模式：覆盖整个页面
  if (expanded) {
    return (
      <div className="fixed inset-0 z-50 bg-white flex flex-col">
        {panel}
      </div>
    );
  }

  // 嵌入模式
  return panel;
}
