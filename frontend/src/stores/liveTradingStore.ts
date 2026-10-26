/**
 * 实盘交易 Store
 */
import { create } from 'zustand';
import * as tradingApi from '../api/trading';
import type {
  LiveAccount, LivePosition, LiveOrder, LiveTrade,
  PlaceOrderParams, AutoTradeConfig, SignalInfo, TradingInstanceInfo,
} from '../api/trading';
import type { StrategyLogEntry, RealtimeTrade } from './tradingTypes';
import { MAX_STRATEGY_LOGS, MAX_REALTIME_TRADES } from './tradingTypes';

interface LiveTradingState {
  connected: boolean;
  accountId: string;
  connecting: boolean;
  connectError: string | null;
  actionError: string | null;
  brokerName: string;
  brokerDisplayName: string;
  brokers: tradingApi.BrokerInfo[];

  account: LiveAccount | null;
  positions: LivePosition[];
  orders: LiveOrder[];
  trades: LiveTrade[];

  autoTradeConfig: AutoTradeConfig | null;
  liveInstances: TradingInstanceInfo[];
  signals: SignalInfo[];
  signalHistory: SignalInfo[];
  strategyLogs: Record<string, StrategyLogEntry[]>;
  realtimeTrades: Record<string, RealtimeTrade[]>;

  connect: (broker?: string, xtpParams?: Record<string, string>) => Promise<void>;
  disconnect: () => Promise<void>;
  fetchStatus: () => Promise<void>;
  loadBrokers: () => Promise<void>;
  fetchAccount: () => Promise<void>;
  fetchPositions: () => Promise<void>;
  fetchOrders: () => Promise<void>;
  fetchTrades: () => Promise<void>;
  fetchAll: () => Promise<void>;
  placeOrder: (params: PlaceOrderParams) => Promise<LiveOrder | null>;
  cancelOrder: (orderId: string) => Promise<boolean>;
  fetchAutoTradeConfig: () => Promise<void>;
  updateAutoTradeConfig: (config: Partial<AutoTradeConfig>) => Promise<void>;
  fetchLiveInstances: () => Promise<void>;
  createLiveInstance: (data: tradingApi.InstanceCreateRequest) => Promise<void>;
  startLiveInstance: (id: string) => Promise<void>;
  stopLiveInstance: (id: string) => Promise<void>;
  deleteLiveInstance: (id: string) => Promise<void>;
  updateLiveInstance: (id: string, data: { name?: string; params?: Record<string, any> }) => Promise<void>;
  fetchSignals: () => Promise<void>;
  confirmSignal: (id: string) => Promise<void>;
  rejectSignal: (id: string) => Promise<void>;
  fetchSignalHistory: (instanceId?: string) => Promise<void>;
  addStrategyLog: (instanceId: string, log: StrategyLogEntry) => void;
  addRealtimeTrade: (trade: RealtimeTrade) => void;
}

const extractError = (err: any, fallback: string) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // Pydantic 验证错误: [{type, loc, msg, input}]
    return detail.map((e: any) => e.msg || String(e)).join('; ');
  }
  return err?.message || fallback;
};

export const useLiveTradingStore = create<LiveTradingState>((set, get) => ({
  connected: false,
  accountId: '',
  connecting: false,
  connectError: null,
  actionError: null,
  brokerName: 'qmt',
  brokerDisplayName: '',
  brokers: [],
  account: null,
  positions: [],
  orders: [],
  trades: [],
  autoTradeConfig: null,
  liveInstances: [],
  signals: [],
  signalHistory: [],
  strategyLogs: {},
  realtimeTrades: {},

  // 连接网关
  connect: async () => {
    set({ connecting: true, connectError: null });
    try {
      const res = await tradingApi.connectGateway();
      set({
        connected: res.success,
        accountId: res.account_id ?? '',
        connecting: false,
      });
      if (res.success) {
        await get().fetchAll();
      }
    } catch (err: any) {
      const msg = extractError(err, '连接失败');
      set({ connected: false, connecting: false, connectError: msg });
    }
  },

  // 断开连接
  disconnect: async () => {
    try {
      await tradingApi.disconnectGateway();
    } catch {}
    set({
      connected: false, accountId: '', account: null,
      positions: [], orders: [], trades: [], connectError: null, actionError: null,
      brokerDisplayName: '',
    });
  },

  // 获取连接状态
  fetchStatus: async () => {
    try {
      const res = await tradingApi.getGatewayStatus();
      set({
        connected: res.connected ?? false,
        accountId: res.account_id ?? '',
        brokerName: res.broker ?? get().brokerName,
        brokerDisplayName: res.display_name ?? '',
      });
    } catch {}
  },

  loadBrokers: async () => {
    try {
      const brokers = await tradingApi.fetchBrokers();
      set({ brokers });
    } catch {}
  },

  // 获取账户信息
  fetchAccount: async () => {
    try {
      const res = await tradingApi.getAccount();
      set({ account: res });
    } catch {}
  },

  // 获取持仓
  fetchPositions: async () => {
    try {
      const res = await tradingApi.getPositions();
      set({ positions: Array.isArray(res) ? res : (res as any).positions ?? [] });
    } catch {}
  },

  // 获取委托
  fetchOrders: async () => {
    try {
      const res = await tradingApi.getOrders();
      set({ orders: Array.isArray(res) ? res : (res as any).orders ?? [] });
    } catch {}
  },

  // 获取成交
  fetchTrades: async () => {
    try {
      const res = await tradingApi.getTrades();
      set({ trades: Array.isArray(res) ? res : (res as any).trades ?? [] });
    } catch {}
  },

  // 拉取所有数据
  fetchAll: async () => {
    await Promise.allSettled([
      get().fetchAccount(),
      get().fetchPositions(),
      get().fetchOrders(),
      get().fetchTrades(),
    ]);
  },

  // 下单
  placeOrder: async (params: PlaceOrderParams) => {
    set({ actionError: null });
    try {
      const res = await tradingApi.placeOrder(params);
      await get().fetchOrders();
      return res;
    } catch (err: any) {
      const msg = extractError(err, '下单失败');
      set({ actionError: msg });
      return null;
    }
  },

  // 撤单
  cancelOrder: async (orderId: string) => {
    try {
      await tradingApi.cancelOrder(orderId);
      await get().fetchOrders();
      return true;
    } catch (err: any) {
      set({ actionError: extractError(err, '撤单失败') });
      return false;
    }
  },

  // 自动交易配置
  fetchAutoTradeConfig: async () => {
    try {
      const res = await tradingApi.getAutoTradeConfig();
      set({ autoTradeConfig: res });
    } catch {}
  },

  updateAutoTradeConfig: async (config: Partial<AutoTradeConfig>) => {
    set({ actionError: null });
    try {
      const res = await tradingApi.updateAutoTradeConfig(config);
      set({ autoTradeConfig: res });
    } catch (err: any) {
      set({ actionError: extractError(err, '更新配置失败') });
    }
  },

  // 实盘策略实例
  fetchLiveInstances: async () => {
    try {
      const res = await tradingApi.listInstances();
      set({ liveInstances: res });
    } catch {}
  },

  createLiveInstance: async (data) => {
    set({ actionError: null });
    try {
      await tradingApi.createInstance(data);
      await get().fetchLiveInstances();
    } catch (err: any) {
      set({ actionError: extractError(err, '创建实例失败') });
    }
  },

  startLiveInstance: async (id) => {
    set({ actionError: null });
    try {
      await tradingApi.startInstance(id);
      await get().fetchLiveInstances();
    } catch (err: any) {
      set({ actionError: extractError(err, '启动实例失败') });
    }
  },

  stopLiveInstance: async (id) => {
    set({ actionError: null });
    try {
      await tradingApi.stopInstance(id);
      await get().fetchLiveInstances();
    } catch (err: any) {
      set({ actionError: extractError(err, '停止实例失败') });
    }
  },

  deleteLiveInstance: async (id) => {
    set({ actionError: null });
    try {
      await tradingApi.deleteInstance(id);
      await get().fetchLiveInstances();
    } catch (err: any) {
      set({ actionError: extractError(err, '删除实例失败') });
    }
  },

  updateLiveInstance: async (id, data) => {
    set({ actionError: null });
    try {
      await tradingApi.updateInstance(id, data);
      await get().fetchLiveInstances();
    } catch (err: any) {
      set({ actionError: extractError(err, '更新实例失败') });
    }
  },

  // 信号管理
  fetchSignals: async () => {
    try {
      const res = await tradingApi.listSignals();
      set({ signals: res });
    } catch {}
  },

  confirmSignal: async (id) => {
    set({ actionError: null });
    try {
      await tradingApi.confirmSignal(id);
      await get().fetchSignals();
    } catch (err: any) {
      set({ actionError: extractError(err, '确认信号失败') });
    }
  },

  rejectSignal: async (id) => {
    set({ actionError: null });
    try {
      await tradingApi.rejectSignal(id);
      await get().fetchSignals();
    } catch (err: any) {
      set({ actionError: extractError(err, '拒绝信号失败') });
    }
  },

  // 信号历史
  fetchSignalHistory: async (instanceId?: string) => {
    try {
      const res = await tradingApi.listSignalHistory(instanceId, 100);
      set({ signalHistory: res });
    } catch {}
  },

  // 策略日志
  addStrategyLog: (instanceId, log) => {
    const logs = { ...get().strategyLogs };
    const list = [...(logs[instanceId] || []), log].slice(-MAX_STRATEGY_LOGS);
    logs[instanceId] = list;
    set({ strategyLogs: logs });
  },

  // 实时成交
  addRealtimeTrade: (trade) => {
    const trades = { ...get().realtimeTrades };
    const iid = trade.instance_id;
    const list = [...(trades[iid] || []), trade].slice(-MAX_REALTIME_TRADES);
    trades[iid] = list;
    set({ realtimeTrades: trades });
  },
}));