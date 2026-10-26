import { useEffect, useRef } from 'react';
import { useAuthStore, useStockCacheStore } from '@/stores';
import { useSimulationStore } from '@/stores/simulationStore';
import { useLiveTradingStore } from '@/stores/liveTradingStore';
import { useAgentStore } from '@/stores/agentStore';

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
const RECONNECT_DELAY = 3000;

// 暴露订阅/取消订阅方法，供其他组件调用
let _wsRef: WebSocket | null = null;
let _subsRef: Map<string, Set<string>> = new Map();

// 回测日志实时回调（StrategyWorkspace 注册/注销）
let _backtestLogCallback: ((msg: string) => void) | null = null;

export function onBacktestLog(cb: (msg: string) => void) {
  _backtestLogCallback = cb;
  return () => { _backtestLogCallback = null; };
}

export function wsSubscribe(channel: string, symbols: string[]) {
  if (!_subsRef.has(channel)) _subsRef.set(channel, new Set());
  for (const s of symbols) _subsRef.get(channel)!.add(s);
  if (_wsRef && _wsRef.readyState === WebSocket.OPEN) {
    _wsRef.send(JSON.stringify({ type: 'subscribe', channel, symbols }));
  }
}

export function wsUnsubscribe(channel: string, symbols: string[]) {
  const set = _subsRef.get(channel);
  if (set) for (const s of symbols) set.delete(s);
  if (_wsRef && _wsRef.readyState === WebSocket.OPEN) {
    _wsRef.send(JSON.stringify({ type: 'unsubscribe', channel, symbols }));
  }
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (!isAuthenticated || !token) return;

    const connect = () => {
      const currentToken = useAuthStore.getState().token;
      if (!currentToken) return;

      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(`${WS_BASE}?token=${currentToken}`);
      wsRef.current = ws;
      _wsRef = ws;

      ws.onopen = () => {
        console.log('[WS] connected');
        // Re-send subscriptions after reconnect
        _subsRef.forEach((symbols, channel) => {
          ws.send(JSON.stringify({ type: 'subscribe', channel, symbols: Array.from(symbols) }));
        });
        // 重连后全量对齐 pending 信号,补掉线期间漏的
        useAgentStore.getState().fetchSignals(undefined, 'pending');
      };

      ws.onclose = () => {
        console.log('[WS] closed');
      };

      ws.onerror = (e) => {
        console.error('[WS] error', e);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'tick') {
            const data = msg.data;
            const tickData = {
              symbol: data.symbol,
              name: data.name || useStockCacheStore.getState().lookup(data.symbol)?.name || '',
              last_price: data.last_price || 0,
              open_price: data.open_price || 0,
              high_price: data.high_price || 0,
              low_price: data.low_price || 0,
              pre_close: data.pre_close || 0,
              volume: data.volume || 0,
              amount: data.amount || 0,
              bid_price_1: data.bid_price_1 || 0,
              bid_volume_1: data.bid_volume_1 || 0,
              ask_price_1: data.ask_price_1 || 0,
              ask_volume_1: data.ask_volume_1 || 0,
              change: data.change || ((data.last_price || 0) - (data.pre_close || 0)),
              datetime: data.datetime || '',
            };
            useSimulationStore.getState().updateRealtimePrice(data.symbol, tickData);
          }

          if (msg.type === 'strategy_log') {
            const data = msg.data;
            const logEntry = {
              time: data.time,
              side: data.side || '',
              message: data.message,
              price: data.price || 0,
              quantity: data.quantity || 0,
              pnl: data.pnl || 0,
            };
            useSimulationStore.getState().addStrategyLog(data.instance_id, logEntry);
            // 实盘实例也推送日志
            const liveInstIds = useLiveTradingStore.getState().liveInstances.map((i) => i.id);
            if (liveInstIds.includes(data.instance_id)) {
              useLiveTradingStore.getState().addStrategyLog(data.instance_id, logEntry);
            }
          }

          if (msg.type === 'backtest_log') {
            console.log('[WS backtest_log]', msg.data);
            _backtestLogCallback?.(msg.data?.message || '');
          }

          if (msg.type === 'strategy_trade') {
            useSimulationStore.getState().addRealtimeTrade(msg.data);
            // 实盘实例也推送交易
            const liveInstIds = useLiveTradingStore.getState().liveInstances.map((i) => i.id);
            if (liveInstIds.includes(msg.data.instance_id)) {
              useLiveTradingStore.getState().addRealtimeTrade(msg.data);
            }
          }

          if (msg.type === 'strategy_signal') {
            // 策略信号推送（信号确认模式）
            useSimulationStore.getState().addPendingSignal(msg.data.instance_id, msg.data);
          }

          if (msg.type === 'strategy_account') {
            const data = msg.data;
            useSimulationStore.getState().updateAccount(data.instance_id, data);
          }

          if (msg.type === 'live_order_update') {
            // 实盘委托状态更新 — 刷新所有数据
            useLiveTradingStore.getState().fetchAll();
          }

          if (msg.type === 'live_trade') {
            // 实盘成交推送 — 刷新成交和委托
            useLiveTradingStore.getState().fetchAll();
          }

          if (msg.type === 'live_gateway_status') {
            const data = msg.data;
            if (data?.connected !== undefined) {
              useLiveTradingStore.getState().fetchStatus();
            }
          }

          if (msg.type === 'live_account_sync') {
            useLiveTradingStore.getState().fetchAccount();
          }

          if (msg.type === 'live_positions_sync') {
            useLiveTradingStore.getState().fetchPositions();
            useLiveTradingStore.getState().fetchOrders();
          }

          if (msg.type === 'trade_sync') {
            // 交易数据同步 — 刷新委托和成交
            useLiveTradingStore.getState().fetchOrders();
            useLiveTradingStore.getState().fetchTrades();
          }

          if (msg.type === 'agent_signal') {
            const data = msg.data;
            if (data) {
              useAgentStore.getState().addSignal(data);
            }
          }
        } catch {
          // ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        reconnectTimerRef.current = setTimeout(() => {
          if (useAuthStore.getState().isAuthenticated) {
            connect();
          }
        }, RECONNECT_DELAY);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
        _wsRef = null;
      }
    };
  }, [isAuthenticated, token]);

  return <>{children}</>;
}
