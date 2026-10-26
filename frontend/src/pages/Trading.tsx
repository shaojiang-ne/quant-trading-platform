import { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLiveTradingStore } from '@/stores/liveTradingStore';
import { useStrategyStore } from '@/stores/strategyStore';
import { TradeHistoryPanel } from '@/components/trading/TradeHistoryPanel';
import { AutoTradePanel } from '@/components/trading/AutoTradePanel';
import { SignalPanel } from '@/components/trading/SignalPanel';
import { GatewayPanel } from '@/components/trading/GatewayPanel';
import { OrderPanel } from '@/components/trading/OrderPanel';
import type { SignalInfo } from '@/api/trading';

export function Trading() {
  const {
    connected, connectError, actionError, accountId,
    account, positions, autoTradeConfig,
  } = useLiveTradingStore();

  const [showOrderPanel, setShowOrderPanel] = useState(false);
  const [prefillSymbol, setPrefillSymbol] = useState('');

  // 从 URL query 读取预填股票代码（智能体信号「确认操作」跳转而来）
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const sym = searchParams.get('symbol') || '';
    if (sym) {
      setPrefillSymbol(sym);
      setShowOrderPanel(true);
    }
  }, [searchParams]);

  useEffect(() => {
    useLiveTradingStore.getState().fetchStatus();
  }, []);

  useEffect(() => {
    const fetch = () => {
      const store = useLiveTradingStore.getState();
      store.fetchAccount();
      store.fetchPositions();
      store.fetchOrders();
      store.fetchTrades();
    };
    if (connected) {
      fetch();
      const timer = setInterval(fetch, 2000);
      return () => clearInterval(timer);
    }
  }, [connected]);

  const formatMoney = (v: number) => v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pnlColor = (val: number | undefined) => {
    if (val == null) return 'text-gray-500';
    return val > 0 ? 'text-red-500' : val < 0 ? 'text-green-500' : 'text-gray-500';
  };

  const handlePlaceOrder = async (symbol: string, side: string, quantity: number, price: number, orderType: string) => {
    if (!symbol) return;
    await useLiveTradingStore.getState().placeOrder({
      symbol,
      side: side as 'buy' | 'sell',
      quantity,
      price: orderType === 'market' ? undefined : price,
      order_type: orderType as 'limit' | 'market',
    });
    await useLiveTradingStore.getState().fetchAll();
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">实盘交易</h1>
          <p className="text-gray-500 mt-1">通过 stock_trade 服务进行实盘交易</p>
        </div>
        <button
          onClick={() => setShowOrderPanel(true)}
          disabled={!connected}
          className="px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
        >
          手动下单
        </button>
      </div>

      {connectError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{connectError}</div>
      )}
      {actionError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{actionError}</div>
      )}

      <GatewayPanel />

      {connected && (
        <>
          {/* 账户概览 */}
          {account && (
            <div className="grid grid-cols-5 gap-3">
              <AcctCard label="总资产" value={formatMoney(account.total_assets)} />
              <AcctCard label="可用资金" value={formatMoney(account.available)} />
              <AcctCard label="持仓市值" value={formatMoney(account.market_value)} />
              <AcctCard label="冻结资金" value={formatMoney(account.frozen)} />
              <AcctCard label="今日盈亏" value={formatMoney(positions.reduce((s, p) => s + (p.daily_profit ?? 0), 0))} highlight={positions.reduce((s, p) => s + (p.daily_profit ?? 0), 0) >= 0 ? 'up' : 'down'} />
            </div>
          )}

          {/* 实盘持仓 */}
          {positions.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
              <h3 className="text-sm font-medium text-gray-700 mb-3">实盘持仓</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-200">
                      <th className="text-left py-2 px-2">标的</th>
                      <th className="text-right py-2 px-2">持仓/可用</th>
                      <th className="text-right py-2 px-2">成本</th>
                      <th className="text-right py-2 px-2">现价</th>
                      <th className="text-right py-2 px-2">市值</th>
                      <th className="text-right py-2 px-2">盈亏</th>
                      <th className="text-right py-2 px-2">今日盈亏</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {positions.map((pos, i) => (
                      <tr key={i}>
                        <td className="py-2 px-2 text-gray-900">{pos.symbol} <span className="text-gray-500">{pos.name}</span></td>
                        <td className="py-2 px-2 text-right text-gray-700">{pos.available}/{pos.quantity}</td>
                        <td className="py-2 px-2 text-right text-gray-500">{pos.avg_cost.toFixed(2)}</td>
                        <td className="py-2 px-2 text-right text-gray-900">{pos.current_price.toFixed(2)}</td>
                        <td className="py-2 px-2 text-right text-gray-900">{formatMoney(pos.market_value)}</td>
                        <td className={`py-2 px-2 text-right font-mono ${pnlColor(pos.profit)}`}>
                          {pos.profit >= 0 ? '+' : ''}{formatMoney(pos.profit)} ({(pos.profit_rate * 100).toFixed(2)}%)
                        </td>
                        <td className={`py-2 px-2 text-right font-mono ${pnlColor(pos.daily_profit)}`}>
                          {pos.daily_profit != null ? `${pos.daily_profit >= 0 ? '+' : ''}${formatMoney(pos.daily_profit)}` : '--'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 信号确认 */}
          {accountId && autoTradeConfig?.confirm_required && <SignalPanel />}

          {/* 交易历史 */}
          <TradeHistoryPanel />

          {/* 自动交易 */}
          {accountId && <AutoTradePanel />}

          {/* 策略日志 & 信号历史 */}
          <StrategyLogAndSignals />
        </>
      )}

      {/* 手动下单弹窗 */}
      {showOrderPanel && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowOrderPanel(false)}>
          <div className="bg-white rounded-xl p-6 w-[420px] shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">手动下单</h2>
              <button onClick={() => setShowOrderPanel(false)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
            </div>
            <OrderPanel
              symbol={prefillSymbol}
              onPlaceOrder={async (sym, side, quantity, price, orderType) => {
                await handlePlaceOrder(sym, side, quantity, price, orderType);
                setShowOrderPanel(false);
              }}
            />
          </div>
     </div>
      )}
    </div>
  );
}

function AcctCard({ label, value, highlight }: { label: string; value: string; highlight?: 'up' | 'down' }) {
  const cls = highlight === 'up' ? 'text-red-500' : highlight === 'down' ? 'text-green-500' : 'text-gray-900';
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 shadow-sm">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-sm font-mono font-medium ${cls}`}>{value}</div>
    </div>
  );
}

function StrategyLogAndSignals() {
  const liveInstances = useLiveTradingStore((s) => s.liveInstances);
  const strategyLogs = useLiveTradingStore((s) => s.strategyLogs);
  const signalHistory = useLiveTradingStore((s) => s.signalHistory);
  const fetchSignalHistory = useLiveTradingStore((s) => s.fetchSignalHistory);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'logs' | 'signals'>('logs');
  const { strategies } = useStrategyStore();
  const logsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchSignalHistory();
    const timer = setInterval(() => fetchSignalHistory(), 10000);
    return () => clearInterval(timer);
  }, [fetchSignalHistory]);

  if (liveInstances.length === 0) return null;

  const getStrategyName = (id: string) => strategies.find((s) => s.id === id)?.name || id.slice(0, 8);

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center gap-4 mb-4">
        <button onClick={() => setActiveTab('logs')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium ${activeTab === 'logs' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
          策略日志
        </button>
        <button onClick={() => setActiveTab('signals')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium ${activeTab === 'signals' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
          信号历史
        </button>
      </div>

      {activeTab === 'logs' && (
        <div className="space-y-2">
          {liveInstances.map((inst) => {
            const logs = strategyLogs[inst.id] || [];
            const isExpanded = expandedId === inst.id;
            return (
              <div key={inst.id} className="border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedId(isExpanded ? null : inst.id)}>
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${inst.status === 'running' ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <span className="text-sm font-medium text-gray-900">{inst.name}</span>
                    <span className="text-xs text-gray-500">{inst.symbol} · {getStrategyName(inst.strategy_id)}</span>
                  </div>
                  <span className="text-xs text-gray-400">{logs.length} 条日志</span>
                </div>
                {isExpanded && (
                  <div ref={logsRef} className="border-t border-gray-100 h-48 overflow-y-auto px-3 py-2">
                    {logs.length === 0 ? (
                      <div className="text-xs text-gray-400 text-center py-6">{inst.status === 'running' ? '等待策略信号...' : '暂无日志'}</div>
                    ) : (
                      <div className="divide-y divide-gray-50">
                        {logs.slice(-50).reverse().map((log, i) => (
                          <div key={i} className="py-1.5 flex items-start gap-2 text-xs">
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
                )}
              </div>
            );
          })}
        </div>
      )}

      {activeTab === 'signals' && (
        <div>
          {signalHistory.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-6">暂无信号记录</div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-200">
                  <th className="text-left py-2 px-2">时间</th>
                  <th className="text-left py-2 px-2">实例</th>
                  <th className="text-left py-2 px-2">标的</th>
                  <th className="text-left py-2 px-2">方向</th>
                  <th className="text-right py-2 px-2">价格</th>
                  <th className="text-right py-2 px-2">数量</th>
                  <th className="text-left py-2 px-2">状态</th>
                  <th className="text-left py-2 px-2">信号路径</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {signalHistory.map((sig) => (
                  <SignalRow key={sig.id} sig={sig} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function SignalRow({ sig }: { sig: SignalInfo }) {
  return (
    <tr className="text-sm text-gray-700 border-b border-gray-100">
      <td className="py-2 px-2">{new Date(sig.created_at).toLocaleString()}</td>
      <td className="py-2 px-2">{sig.instance_id.slice(0, 8)}</td>
      <td className="py-2 px-2">{sig.name || sig.symbol}</td>
      <td className="py-2 px-2">{sig.side}</td>
      <td className="text-right py-2 px-2">{sig.price}</td>
      <td className="text-right py-2 px-2">{sig.quantity}</td>
      <td className="py-2 px-2"><SignalStatusBadge status={sig.status} /></td>
      <td className="py-2 px-2">{sig.reason || '-'}</td>
    </tr>
  );
}

function SignalStatusBadge({ status }: { status: string }) {
  const cls = status === 'pending' ? 'bg-yellow-50 text-yellow-700'
    : status === 'executed' ? 'bg-green-50 text-green-700'
    : status === 'rejected' ? 'bg-red-50 text-red-600'
    : status === 'expired' ? 'bg-gray-50 text-gray-500'
    : 'bg-gray-50 text-gray-500';
  const label = status === 'pending' ? '待确认'
    : status === 'executed' ? '已执行'
    : status === 'rejected' ? '已拒绝'
    : status === 'expired' ? '已过期'
    : status;
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>{label}</span>;
}