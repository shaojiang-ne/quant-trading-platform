import { memo, useCallback, useEffect, useState, useRef } from 'react';
import { useSimulationStore } from '@/stores/simulationStore';
import { simulationApi } from '@/api';
import { useStrategyStore } from '@/stores/strategyStore';
import { useStockCacheStore } from '@/stores/stockCacheStore';
import type { StrategyParamResponse } from '@/api/strategies';
import type { SignalInfo } from '@/api/trading';
import { api } from '@/api/client';
import { wsSubscribe, wsUnsubscribe } from '@/components/WebSocketProvider';
import { analyzeStock } from '@/api';
import { Sparkles, Check, X, Bell } from 'lucide-react';

export function SimulationTrading() {
  const instances = useSimulationStore((s) => s.instances);
  const loading = useSimulationStore((s) => s.loading);
  const error = useSimulationStore((s) => s.error);
  const realtimePrices = useSimulationStore((s) => s.realtimePrices);
  const strategyLogs = useSimulationStore((s) => s.strategyLogs);
  const realtimeTrades = useSimulationStore((s) => s.realtimeTrades);
  const accountUpdates = useSimulationStore((s) => s.accountUpdates);
  const pendingSignals = useSimulationStore((s) => s.pendingSignals);
  const fetchInstances = useSimulationStore((s) => s.fetchInstances);
  const createInstance = useSimulationStore((s) => s.createInstance);
  const startInstance = useSimulationStore((s) => s.startInstance);
  const stopInstance = useSimulationStore((s) => s.stopInstance);
  const deleteInstance = useSimulationStore((s) => s.deleteInstance);
  const fetchPendingSignals = useSimulationStore((s) => s.fetchPendingSignals);

  const { strategies, fetchStrategies } = useStrategyStore();
  const { stocks, fetchAll } = useStockCacheStore();

  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [newName, setNewName] = useState('');
  const [newSymbol, setNewSymbol] = useState('');
  const [newStrategy, setNewStrategy] = useState('');
  const [newInitialEquity, setNewInitialEquity] = useState(1000000);
  const [newAutoTradeMode, setNewAutoTradeMode] = useState<'auto' | 'confirm'>('auto');
  const [paramValues, setParamValues] = useState<Record<string, any>>({});
  const [symbolSearch, setSymbolSearch] = useState('');
  const [symbolResults, setSymbolResults] = useState<any[]>([]);
  const [selectedStockName, setSelectedStockName] = useState('');
  const [aiAnalyzing, setAiAnalyzing] = useState(false);
  const [aiResult, setAiResult] = useState<{ analysis: string; reason: string; risk_tip: string } | null>(null);
  const [aiError, setAiError] = useState('');

  useEffect(() => {
    fetchStrategies();
    fetchAll();
    fetchInstances();
  }, []);

  // 订阅运行中实例的 tick 行情 + 加载待确认信号
  useEffect(() => {
    const runningInstances = instances.filter((inst) => inst.status === 'running');
    const runningSymbols = runningInstances.map((inst) => inst.symbol);
    const uniqueSymbols = [...new Set(runningSymbols)];

    if (uniqueSymbols.length > 0) {
      wsSubscribe('tick', uniqueSymbols);
    }

    // 加载信号确认模式实例的待确认信号
    for (const inst of runningInstances) {
      if (inst.confirm_required) {
        fetchPendingSignals(inst.id);
      }
    }

    return () => {
      if (uniqueSymbols.length > 0) {
        wsUnsubscribe('tick', uniqueSymbols);
      }
    };
  }, [instances]);

  useEffect(() => {
    if (symbolSearch.length >= 1) {
      const q = symbolSearch.toLowerCase();
      setSymbolResults(stocks.filter((s) =>
        s.code.includes(q) || s.name.toLowerCase().includes(q) ||
        (s.pinyin && s.pinyin.includes(q)) || (s.full_pinyin && s.full_pinyin.includes(q))
      ).slice(0, 10));
    } else {
      setSymbolResults([]);
    }
  }, [symbolSearch, stocks]);

  const currentStrategy = strategies.find((s) => s.id === newStrategy);

  const handleStrategyChange = (id: string) => {
    setNewStrategy(id);
    const s = strategies.find((st) => st.id === id);
    if (s) {
      const defaults: Record<string, any> = {};
      s.parameters.forEach((p: StrategyParamResponse) => { defaults[p.key] = p.default; });
      setParamValues(defaults);
    } else {
      setParamValues({});
    }
  };

  const handleAIAnalyze = async () => {
    if (!newSymbol || aiAnalyzing) return;
    setAiAnalyzing(true);
    setAiError('');
    setAiResult(null);
    try {
      const res = await analyzeStock(newSymbol, selectedStockName);
      if (res.success && res.strategy_id) {
        setAiResult({
          analysis: res.analysis || '',
          reason: res.reason || '',
          risk_tip: res.risk_tip || '',
        });
        setNewStrategy(res.strategy_id);
        const s = strategies.find((st) => st.id === res.strategy_id);
        if (s) {
          const defaults: Record<string, any> = {};
          s.parameters.forEach((p: StrategyParamResponse) => { defaults[p.key] = p.default; });
          if (res.params) {
            Object.assign(defaults, res.params);
          }
          setParamValues(defaults);
        }
      } else {
        setAiError(res.error || 'AI分析失败，请稍后重试');
      }
    } catch (e: any) {
      setAiError(e?.message || 'AI分析请求失败');
    } finally {
      setAiAnalyzing(false);
    }
  };

  const handleCreate = async () => {
    if (!newSymbol || !newStrategy) return;
    const inst = await createInstance({
      name: newName || `${newSymbol}-${currentStrategy?.name || newStrategy}`,
      symbol: newSymbol,
      strategy_id: newStrategy,
      account_id: `sim-${Date.now()}`,
      params: paramValues,
      initial_equity: newInitialEquity,
      auto_trade_enabled: newAutoTradeMode === 'auto',
      confirm_required: newAutoTradeMode === 'confirm',
    });
    if (inst) {
      setShowCreate(false);
      setNewSymbol(''); setNewStrategy(''); setNewName('');
      setNewInitialEquity(1000000); setNewAutoTradeMode('auto');
      setParamValues({}); setSymbolSearch(''); setSymbolResults([]);
      setSelectedStockName(''); setAiResult(null); setAiError('');
    }
  };

  const formatPercent = (v: number) => {
    const sign = v >= 0 ? '+' : '';
    return `${sign}${(v * 100).toFixed(2)}%`;
  };
  const formatMoney = (v: number) => v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const inputCls = 'w-full px-3 py-2 bg-white border border-gray-300 rounded-lg text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500';

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">模拟交易</h1>
        <button
          onClick={() => {
            setNewName(''); setNewSymbol(''); setNewStrategy('');
            setNewInitialEquity(1000000); setNewAutoTradeMode('auto');
            setParamValues({}); setSymbolSearch(''); setSymbolResults([]);
            setSelectedStockName(''); setAiResult(null); setAiError('');
            setShowCreate(true);
          }}
          className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          + 新建实例
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-center text-gray-500 py-12">加载中...</div>
      ) : instances.length === 0 ? (
        <div className="text-center text-gray-400 py-12">暂无模拟交易实例，点击上方按钮创建</div>
      ) : (
        <div className="space-y-4">
          {instances.map((inst) => {
            const isRunning = inst.status === 'running';
            const isExpanded = expandedId === inst.id;
            const tick = realtimePrices[inst.symbol];
            const logs = strategyLogs[inst.id] || [];
            const trades = realtimeTrades[inst.id] || [];
            const acct = accountUpdates[inst.id];
            const signals = pendingSignals[inst.id] || [];
            const currentPrice = Number(acct?.current_price || inst.current_price || tick?.last_price || 0) || 0;
            const changeRate = Number(acct?.change_rate || inst.change_rate || 0) || 0;

            return (
              <div key={inst.id} className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
                <div
                  className="flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-gray-50 transition-colors"
                  onClick={() => {
                    setExpandedId(isExpanded ? null : inst.id);
                    // 展开时加载待确认信号
                    if (!isExpanded && inst.confirm_required) {
                      fetchPendingSignals(inst.id);
                    }
                  }}
                >
                  <div className="flex items-center gap-4">
                    <div className={`w-2.5 h-2.5 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-300'}`} />
                    <div>
                      <div className="text-gray-900 font-medium flex items-center gap-2">
                        {inst.name}
                        {inst.confirm_required && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-amber-50 text-amber-600 text-[10px] font-medium rounded">
                            <Bell className="w-3 h-3" />需确认
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {inst.symbol} · {strategies.find((s) => s.id === inst.strategy_id)?.name || inst.strategy_id}
                        <span className="ml-2 text-gray-400">
                          {inst.auto_trade_enabled
                            ? (inst.confirm_required ? '信号确认' : '自动成交')
                            : '仅信号'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-6">
                    {isRunning && signals.length > 0 && (
                      <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-medium rounded-full animate-pulse">
                        {signals.length} 条待确认
                      </span>
                    )}

                    {isRunning && (
                      <div className="text-right">
                        {currentPrice > 0 ? (
                          <>
                            <div className={`text-lg font-mono font-bold ${changeRate >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                              {currentPrice.toFixed(2)}
                            </div>
                            <div className={`text-xs font-mono ${changeRate >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                              {formatPercent(changeRate)}
                            </div>
                          </>
                        ) : (
                          <div className="text-lg font-mono font-bold text-gray-300">--</div>
                        )}
                      </div>
                    )}

                    <div className="text-right min-w-[120px] space-y-0.5">
                      <div className="text-sm text-gray-500">
                        权益 <span className="text-gray-900 font-mono">{formatMoney(acct?.total_assets || inst.current_equity)}</span>
                      </div>
                      <div className="text-sm text-gray-500">
                        市值 <span className="text-gray-900 font-mono">{formatMoney(acct?.market_value || 0)}</span>
                      </div>
                      <div className={`text-xs font-mono ${(acct?.profit || inst.total_profit) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                        盈亏 {formatMoney(acct?.profit ?? inst.total_profit)}
                      </div>
                    </div>

                    <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                      {isRunning ? (
                        <button onClick={() => stopInstance(inst.id)} className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white rounded text-xs font-medium transition-colors">停止</button>
                      ) : (
                        <button onClick={() => startInstance(inst.id)} className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-medium transition-colors">启动</button>
                      )}
                      <button onClick={() => { deleteInstance(inst.id); if (expandedId === inst.id) setExpandedId(null); }} className="px-3 py-1.5 bg-gray-100 hover:bg-red-50 text-gray-600 hover:text-red-600 rounded text-xs font-medium transition-colors">删除</button>
                    </div>

                    <svg className={`w-5 h-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-gray-200 px-5 py-4 space-y-4 bg-gray-50/50">
                    <div className="grid grid-cols-5 gap-3">
                      <StatCard label="总资产" value={formatMoney(acct?.total_assets || inst.current_equity)} />
                      <StatCard label="可用资金" value={formatMoney(acct?.available || 0)} />
                      <StatCard label="持仓市值" value={formatMoney(acct?.market_value || 0)} />
                      <StatCard label="总交易次数" value={String(inst.total_trades + trades.length)} />
                      <StatCard label="收益率" value={formatPercent(acct?.profit_rate || (inst.total_profit / (inst.current_equity - inst.total_profit || 1)))} highlight={(acct?.profit_rate || inst.total_profit) >= 0 ? 'up' : 'down'} />
                    </div>

                    {/* 实时行情 */}
                    {isRunning && (
                      <div className="flex items-baseline gap-4 px-1">
                        {currentPrice > 0 ? (
                          <>
                            <span className="text-2xl font-mono font-bold text-gray-900">{currentPrice.toFixed(2)}</span>
                            <span className={`text-sm font-mono font-medium ${changeRate >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                              {changeRate >= 0 ? '+' : ''}{(changeRate * 100).toFixed(2)}%
                            </span>
                          </>
                        ) : (
                          <span className="text-2xl font-mono font-bold text-gray-300">--</span>
                        )}
                        <span className="text-xs text-gray-400">{inst.symbol}</span>
                      </div>
                    )}

                    {/* 自动交易配置 */}
                    <AutoTradeConfig instanceId={inst.id}
                      autoTradeEnabled={inst.auto_trade_enabled}
                      confirmRequired={inst.confirm_required} />

                    {/* 待确认信号 */}
                    {inst.confirm_required && signals.length > 0 && (
                      <SignalConfirmPanel instanceId={inst.id} signals={signals} />
                    )}

                    {/* 手动下单 */}
                    <SimOrderForm instanceId={inst.id} currentPrice={currentPrice} />

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <h3 className="text-sm font-medium text-gray-700 mb-2">策略日志</h3>
                        <div className="bg-white rounded-lg border border-gray-200 h-64 overflow-y-auto">
                          {logs.length === 0 ? (
                            <div className="text-gray-400 text-xs text-center py-8">{isRunning ? '等待策略信号...' : '实例未运行'}</div>
                          ) : (
                            <div className="divide-y divide-gray-100">
                              {logs.slice(-50).reverse().map((log, i) => (
                                <div key={i} className="px-3 py-2 flex items-start gap-2 text-xs">
                                  <span className="text-gray-400 font-mono shrink-0">{log.time}</span>
                                  <span className={`shrink-0 font-medium ${log.side === 'buy' ? 'text-red-500' : log.side === 'sell' ? 'text-green-500' : 'text-gray-500'}`}>
                                    {log.side === 'buy' ? '买入' : log.side === 'sell' ? '卖出' : '信号'}
                                  </span>
                                  <span className="text-gray-700">{log.message}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      <div>
                        <h3 className="text-sm font-medium text-gray-700 mb-2">持仓 & 交易</h3>
                        <div className="bg-white rounded-lg border border-gray-200 h-64 overflow-y-auto">
                          {acct?.positions?.length > 0 && (
                            <div className="px-3 py-2 border-b border-gray-100">
                              <div className="text-xs text-gray-500 mb-1">当前持仓</div>
                              {acct.positions.map((p: any, i: number) => (
                                <div key={i} className="flex justify-between text-xs">
                                  <span className="text-gray-900">{p.symbol || inst.symbol}</span>
                                  <span className="text-gray-500">{p.quantity}股 @ {p.avg_cost?.toFixed(2)}</span>
                                  <span className={p.profit >= 0 ? 'text-red-500' : 'text-green-500'}>
                                    {p.profit?.toFixed(2)} ({(p.profit_rate * 100)?.toFixed(2)}%)
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                          {trades.length > 0 ? (
                            <div className="divide-y divide-gray-100">
                              {trades.slice(-20).reverse().map((t, i) => (
                                <div key={i} className="px-3 py-2 flex items-center gap-3 text-xs">
                                  <span className="text-gray-400 font-mono">{t.time}</span>
                                  <span className={`font-medium ${t.side === 'buy' ? 'text-red-500' : 'text-green-500'}`}>
                                    {t.side === 'buy' ? '买入' : '卖出'}
                                  </span>
                                  <span className="text-gray-900">{t.quantity}股 @ {t.price?.toFixed(2)}</span>
                                  {t.pnl !== 0 && (
                                    <span className={t.pnl >= 0 ? 'text-red-500' : 'text-green-500'}>
                                      {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="text-gray-400 text-xs text-center py-8">{isRunning ? '等待交易执行...' : '暂无交易'}</div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 创建实例弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-xl p-6 w-[600px] max-h-[85vh] overflow-y-auto space-y-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-gray-900">新建模拟交易实例</h2>

            <div>
              <label className="block text-sm text-gray-700 mb-1">实例名称</label>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="如：茅台双均线"
                className={inputCls} />
            </div>

            <div className="relative">
              <label className="block text-sm text-gray-700 mb-1">股票代码</label>
              <input value={symbolSearch} onChange={(e) => { setSymbolSearch(e.target.value); setNewSymbol(e.target.value.slice(0, 6)); }}
                placeholder="输入代码/名称/拼音搜索"
                className={inputCls} />
              {symbolResults.length > 0 && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {symbolResults.map((s) => (
                    <button key={s.code} className="w-full text-left px-3 py-2 hover:bg-primary-50 text-sm text-gray-900 flex justify-between"
                      onClick={() => { setNewSymbol(s.code); setSymbolSearch(`${s.code} ${s.name}`); setSelectedStockName(s.name); setSymbolResults([]); }}>
                      <span>{s.code}</span><span className="text-gray-500">{s.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm text-gray-700">策略</label>
                <button
                  type="button"
                  onClick={handleAIAnalyze}
                  disabled={!newSymbol || aiAnalyzing}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-purple-600 bg-purple-50 hover:bg-purple-100 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  {aiAnalyzing ? 'AI分析中...' : 'AI智能选策略'}
                </button>
              </div>
              <select value={newStrategy} onChange={(e) => handleStrategyChange(e.target.value)}
                className={inputCls}>
                <option value="">选择策略</option>
                {strategies.filter((s) => !s.is_system).map((s) => (<option key={s.id} value={s.id}>{s.name}</option>))}
              </select>
            </div>

            {aiError && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{aiError}</div>
            )}

            {aiResult && (
              <div className="p-3 bg-purple-50 border border-purple-200 rounded-lg space-y-2 text-sm">
                <div className="flex items-center gap-1.5 text-purple-700 font-medium">
                  <Sparkles className="w-4 h-4" />
                  AI分析结果
                </div>
                <p className="text-gray-700">{aiResult.analysis}</p>
                <p className="text-gray-600"><span className="font-medium text-gray-700">推荐理由：</span>{aiResult.reason}</p>
                {aiResult.risk_tip && (
                  <p className="text-amber-600 text-xs">⚠ {aiResult.risk_tip}</p>
                )}
              </div>
            )}

            <div>
              <label className="block text-sm text-gray-700 mb-1">初始资金</label>
              <input type="number" value={newInitialEquity} onChange={(e) => setNewInitialEquity(Number(e.target.value))}
                step="100000" min="10000"
                className={inputCls} />
              <p className="text-xs text-gray-400 mt-1">模拟账户的初始资金，默认 1,000,000</p>
            </div>

            <div>
              <label className="block text-sm text-gray-700 mb-2">自动交易模式</label>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setNewAutoTradeMode('auto')}
                  className={`flex-1 p-3 rounded-lg border-2 text-left transition-colors ${
                    newAutoTradeMode === 'auto'
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 bg-white hover:border-gray-300'
                  }`}
                >
                  <div className="text-sm font-medium text-gray-900">自动成交</div>
                  <div className="text-xs text-gray-500 mt-1">策略产生信号后自动成交，无需手动操作</div>
                </button>
                <button
                  type="button"
                  onClick={() => setNewAutoTradeMode('confirm')}
                  className={`flex-1 p-3 rounded-lg border-2 text-left transition-colors ${
                    newAutoTradeMode === 'confirm'
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 bg-white hover:border-gray-300'
                  }`}
                >
                  <div className="text-sm font-medium text-gray-900">信号确认</div>
                  <div className="text-xs text-gray-500 mt-1">策略产生信号后需手动确认才成交</div>
                </button>
              </div>
            </div>

            {currentStrategy && currentStrategy.parameters.length > 0 && (
              <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-4">
                <h4 className="text-sm font-medium text-gray-700">策略参数</h4>
                {currentStrategy.parameters.map((param: StrategyParamResponse) => (
                  <div key={param.key}>
                    <label className="block text-sm text-gray-700 mb-1">
                      {param.name}
                      {param.min !== undefined && param.max !== undefined && (
                        <span className="text-gray-400 ml-1">({param.min}~{param.max})</span>
                      )}
                    </label>
                    {param.description && (
                      <p className="text-xs text-gray-400 mb-1.5 leading-relaxed">{param.description}</p>
                    )}
                    {param.key === 'grid_size' && newSymbol && (
                      <GridSizeHint symbol={newSymbol} gridSize={paramValues[param.key] ?? param.default} />
                    )}
                    {param.key === 'grid_range' && newSymbol && (
                      <GridRangeHint symbol={newSymbol} gridRange={paramValues[param.key] ?? param.default} />
                    )}
                    {param.key === 'grid_quantity' && newSymbol && (
                      <GridQuantityHint symbol={newSymbol} quantity={paramValues[param.key] ?? param.default} />
                    )}
                    {param.type === 'boolean' ? (
                      <button type="button" onClick={() => setParamValues((prev) => ({ ...prev, [param.key]: !prev[param.key] }))}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${paramValues[param.key] ? 'bg-primary-600' : 'bg-gray-300'}`}>
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${paramValues[param.key] ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    ) : param.type === 'string' ? (
                      <input type="text" value={paramValues[param.key] ?? param.default} onChange={(e) => setParamValues((prev) => ({ ...prev, [param.key]: e.target.value }))}
                        className="w-full px-3 py-1.5 bg-white border border-gray-300 rounded text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                    ) : (
                      <input type="number" value={paramValues[param.key] ?? param.default} min={param.min} max={param.max} step="any"
                        onChange={(e) => setParamValues((prev) => ({ ...prev, [param.key]: Number(e.target.value) }))}
                        className="w-full px-3 py-1.5 bg-white border border-gray-300 rounded text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <button onClick={handleCreate} disabled={!newSymbol || !newStrategy}
                className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors">创建</button>
              <button onClick={() => setShowCreate(false)}
                className="flex-1 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-sm font-medium transition-colors">取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, highlight }: { label: string; value: string; highlight?: 'up' | 'down' }) {
  const colorClass = highlight === 'up' ? 'text-red-500' : highlight === 'down' ? 'text-green-500' : 'text-gray-900';
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-sm font-mono font-medium ${colorClass}`}>{value}</div>
    </div>
  );
}

/** 自动交易配置面板 */
function AutoTradeConfig({ instanceId, autoTradeEnabled, confirmRequired }: {
  instanceId: string;
  autoTradeEnabled: boolean;
  confirmRequired: boolean;
}) {
  const updateAutoTradeConfig = useSimulationStore((s) => s.updateAutoTradeConfig);
  const [enabled, setEnabled] = useState(autoTradeEnabled);
  const [confirm, setConfirm] = useState(confirmRequired);

  const handleToggleEnabled = async () => {
    const newVal = !enabled;
    setEnabled(newVal);
    try {
      await updateAutoTradeConfig(instanceId, {
        auto_trade_enabled: newVal,
        // 关闭自动交易时，默认开启需确认
        confirm_required: newVal ? confirm : true,
      });
      if (!newVal) setConfirm(true);
    } catch {
      setEnabled(!newVal);
    }
  };

  const handleToggleConfirm = async () => {
    const newVal = !confirm;
    setConfirm(newVal);
    try {
      await updateAutoTradeConfig(instanceId, { confirm_required: newVal });
    } catch {
      setConfirm(!newVal);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">自动交易</h3>
        <button
          type="button"
          onClick={handleToggleEnabled}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${enabled ? 'bg-primary-600' : 'bg-gray-300'}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>
      {enabled && (
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={handleToggleConfirm}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              confirm
                ? 'bg-amber-100 text-amber-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {confirm ? <Bell className="w-3.5 h-3.5" /> : <Check className="w-3.5 h-3.5" />}
            {confirm ? '需确认' : '自动成交'}
          </button>
          <span className="text-xs text-gray-400">
            {confirm ? '策略信号需手动确认后才成交' : '策略信号直接自动成交'}
          </span>
        </div>
      )}
      {!enabled && (
        <p className="mt-2 text-xs text-gray-400">仅记录信号，不自动执行交易</p>
      )}
    </div>
  );
}

/** 信号确认面板 */
const SignalConfirmPanel = memo(function SignalConfirmPanel({ instanceId, signals }: {
  instanceId: string;
  signals: SignalInfo[];
}) {
  const confirmSignal = useSimulationStore((s) => s.confirmSignal);
  const rejectSignal = useSimulationStore((s) => s.rejectSignal);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const handleConfirm = async (signalId: string) => {
    setLoadingId(signalId);
    try {
      await confirmSignal(instanceId, signalId);
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || '确认失败');
    } finally {
      setLoadingId(null);
    }
  };

  const handleReject = async (signalId: string) => {
    setLoadingId(signalId);
    try {
      await rejectSignal(instanceId, signalId);
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || '拒绝失败');
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <div className="bg-amber-50 rounded-lg border border-amber-200 p-3">
      <h3 className="text-sm font-medium text-amber-800 mb-2 flex items-center gap-1.5">
        <Bell className="w-4 h-4" />
        待确认信号 ({signals.length})
      </h3>
      <div className="space-y-2">
        {signals.map((sig) => (
          <div key={sig.id} className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-amber-100">
            <div className="flex items-center gap-3">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                sig.side === 'buy' ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
              }`}>
                {sig.side === 'buy' ? '买入' : '卖出'}
              </span>
              <span className="text-sm text-gray-900">{sig.symbol}</span>
              <span className="text-sm text-gray-600">{sig.quantity}股 @ {Number(sig.price).toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleConfirm(sig.id)}
                disabled={loadingId === sig.id}
                className="inline-flex items-center gap-1 px-3 py-1 bg-primary-600 hover:bg-primary-700 text-white rounded text-xs font-medium transition-colors disabled:opacity-50"
              >
                <Check className="w-3.5 h-3.5" />
                {loadingId === sig.id ? '...' : '确认'}
              </button>
              <button
                onClick={() => handleReject(sig.id)}
                disabled={loadingId === sig.id}
                className="inline-flex items-center gap-1 px-3 py-1 bg-gray-100 hover:bg-red-50 text-gray-600 hover:text-red-600 rounded text-xs font-medium transition-colors disabled:opacity-50"
              >
                <X className="w-3.5 h-3.5" />
                拒绝
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

/** 网格间距提示：根据当前股价计算实际间距金额 */
function GridSizeHint({ symbol, gridSize }: { symbol: string; gridSize: number }) {
  const [price, setPrice] = useState(0);
  const fetchedRef = useRef('');

  useEffect(() => {
    if (!symbol || fetchedRef.current === symbol) return;
    fetchedRef.current = symbol;
    api.get<any>(`/market/tick/${symbol}`).then((res) => {
      const p = res?.last_price || res?.close || res?.price || 0;
      if (p > 0) setPrice(p);
    }).catch(() => {});
  }, [symbol]);

  if (!price || !gridSize) return null;
  const priceStep = price * gridSize;
  const gridCount = Math.round(1 / gridSize);
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 mb-1.5 text-xs text-blue-700 leading-relaxed">
      <span className="font-medium">当前股价 {price.toFixed(2)} 元</span>，网格间距 {gridSize * 100}% = <span className="font-medium">{priceStep.toFixed(2)} 元/格</span>，
      涨跌 {gridCount} 格 = {(gridSize * gridCount * 100).toFixed(0)}% = <span className="font-medium">{(priceStep * gridCount).toFixed(2)} 元</span>
    </div>
  );
}

/** 网格范围提示：根据当前股价计算实际覆盖范围 */
function GridRangeHint({ symbol, gridRange }: { symbol: string; gridRange: number }) {
  const [price, setPrice] = useState(0);
  const fetchedRef = useRef('');

  useEffect(() => {
    if (!symbol || fetchedRef.current === symbol) return;
    fetchedRef.current = symbol;
    api.get<any>(`/market/tick/${symbol}`).then((res) => {
      const p = res?.last_price || res?.close || res?.price || 0;
      if (p > 0) setPrice(p);
    }).catch(() => {});
  }, [symbol]);

  if (!price || !gridRange) return null;
  const rangeAmount = price * gridRange;
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 mb-1.5 text-xs text-blue-700 leading-relaxed">
      <span className="font-medium">当前股价 {price.toFixed(2)} 元</span>，网格范围 ±{gridRange * 100}% = 上下各 <span className="font-medium">{rangeAmount.toFixed(2)} 元</span>，
      覆盖区间 {(price - rangeAmount).toFixed(2)} ~ {(price + rangeAmount).toFixed(2)} 元
    </div>
  );
}

/** 每格交易数量提示：根据当前股价计算每格投入金额 */
function GridQuantityHint({ symbol, quantity }: { symbol: string; quantity: number }) {
  const [price, setPrice] = useState(0);
  const fetchedRef = useRef('');

  useEffect(() => {
    if (!symbol || fetchedRef.current === symbol) return;
    fetchedRef.current = symbol;
    api.get<any>(`/market/tick/${symbol}`).then((res) => {
      const p = res?.last_price || res?.close || res?.price || 0;
      if (p > 0) setPrice(p);
    }).catch(() => {});
  }, [symbol]);

  if (!price || !quantity) return null;
  const amount = price * quantity;
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 mb-1.5 text-xs text-blue-700 leading-relaxed">
      <span className="font-medium">当前股价 {price.toFixed(2)} 元</span>，每格 {quantity} 股 = 每格投入 <span className="font-medium">{amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元</span>
    </div>
  );
}

/** 手动下单表单 — 独立组件，避免 WebSocket 推送导致频繁重渲染丢失交互状态 */
const SimOrderForm = memo(function SimOrderForm({ instanceId, currentPrice }: { instanceId: string; currentPrice: number }) {
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [quantity, setQuantity] = useState(100);
  const [price, setPrice] = useState(0);
  const [loading, setLoading] = useState(false);
  const fetchInstances = useSimulationStore((s) => s.fetchInstances);

  const handleSubmit = useCallback(async () => {
    if (quantity <= 0 || loading) return;
    setLoading(true);
    try {
      await simulationApi.placeOrder(instanceId, {
        side,
        quantity,
        price,
      });
      setSide('buy');
      setQuantity(100);
      setPrice(0);
      fetchInstances();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '下单失败';
      alert(msg);
    } finally {
      setLoading(false);
    }
  }, [instanceId, side, quantity, price, loading, fetchInstances]);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3">
      <h3 className="text-sm font-medium text-gray-700 mb-2">手动下单</h3>
      <div className="flex items-center gap-3">
        <div className="flex gap-1">
          <button onClick={() => setSide('buy')}
            className={`px-3 py-1.5 rounded-lg font-medium text-sm ${side === 'buy' ? 'bg-red-500 text-white' : 'bg-gray-100 text-gray-700'}`}>买入</button>
          <button onClick={() => setSide('sell')}
            className={`px-3 py-1.5 rounded-lg font-medium text-sm ${side === 'sell' ? 'bg-green-500 text-white' : 'bg-gray-100 text-gray-700'}`}>卖出</button>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-gray-500 text-sm">数量</span>
          <input type="number" value={quantity} min="1" step="100"
            onChange={(e) => setQuantity(Number(e.target.value))}
            className="w-24 px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-sm" />
        </div>
        <div className="flex items-center gap-1">
          <span className="text-gray-500 text-sm">价格</span>
          <input type="number" value={price} min="0" step="0.01"
            onChange={(e) => setPrice(Number(e.target.value))}
            className="w-28 px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-sm" />
          <span className="text-gray-400 text-xs">0=市价({currentPrice > 0 ? currentPrice.toFixed(2) : '--'})</span>
        </div>
        <button onClick={handleSubmit}
          disabled={loading}
          className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors min-w-[80px] ${loading ? 'bg-gray-400 text-gray-200 cursor-not-allowed' : 'bg-primary-600 hover:bg-primary-700 text-white cursor-pointer'}`}>
          {loading ? '下单中...' : '下单'}
        </button>
      </div>
    </div>
  );
});
