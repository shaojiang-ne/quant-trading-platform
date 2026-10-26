import { create } from 'zustand';
import { simulationApi } from '@/api';
import type { TradingInstanceResponse, InstanceCreateRequest, AutoTradeConfig, AutoTradeConfigUpdate, SignalInfo } from '@/api/trading';
import type { StrategyLogEntry, RealtimeTrade, RealtimeTick, AccountUpdate } from './tradingTypes';
import { MAX_STRATEGY_LOGS, MAX_REALTIME_TRADES } from './tradingTypes';

export type { StrategyLogEntry, RealtimeTrade, RealtimeTick, AccountUpdate };

interface SimulationState {
  instances: TradingInstanceResponse[];
  loading: boolean;
  error: string | null;

  // 实时数据
  realtimePrices: Record<string, RealtimeTick>;
  strategyLogs: Record<string, StrategyLogEntry[]>;
  realtimeTrades: Record<string, RealtimeTrade[]>;
  accountUpdates: Record<string, AccountUpdate>;

  // 自动交易配置
  autoTradeConfigs: Record<string, AutoTradeConfig>;

  // 待确认信号
  pendingSignals: Record<string, SignalInfo[]>;

  fetchInstances: () => Promise<void>;
  createInstance: (data: InstanceCreateRequest) => Promise<TradingInstanceResponse | null>;
  startInstance: (id: string) => Promise<void>;
  stopInstance: (id: string) => Promise<void>;
  deleteInstance: (id: string) => Promise<void>;
  placeSimOrder: (instanceId: string, params: { side: string; quantity: number; price?: number }) => Promise<void>;

  // 自动交易配置
  fetchAutoTradeConfig: (instanceId: string) => Promise<void>;
  updateAutoTradeConfig: (instanceId: string, config: AutoTradeConfigUpdate) => Promise<void>;

  // 信号管理
  fetchPendingSignals: (instanceId: string) => Promise<void>;
  confirmSignal: (instanceId: string, signalId: string) => Promise<void>;
  rejectSignal: (instanceId: string, signalId: string) => Promise<void>;
  addPendingSignal: (instanceId: string, signal: SignalInfo) => void;
  removePendingSignal: (instanceId: string, signalId: string) => void;

  // 实时数据更新
  updateRealtimePrice: (symbol: string, tick: RealtimeTick) => void;
  addStrategyLog: (instanceId: string, log: StrategyLogEntry) => void;
  addRealtimeTrade: (trade: RealtimeTrade) => void;
  updateAccount: (instanceId: string, data: AccountUpdate) => void;
  clearInstanceRealtime: (instanceId: string) => void;
}

export const useSimulationStore = create<SimulationState>()((set, get) => ({
  instances: [],
  loading: false,
  error: null,
  realtimePrices: {},
  strategyLogs: {},
  realtimeTrades: {},
  accountUpdates: {},
  autoTradeConfigs: {},
  pendingSignals: {},

  fetchInstances: async () => {
    set({ loading: true, error: null });
    try {
      const instances = await simulationApi.list();
      set({ instances, loading: false });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message, loading: false });
    }
  },

  createInstance: async (data) => {
    try {
      const instance = await simulationApi.create(data);
      set((state) => ({ instances: [instance, ...state.instances] }));
      return instance;
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
      return null;
    }
  },

  startInstance: async (id) => {
    try {
      const updated = await simulationApi.start(id);
      set((state) => ({
        instances: state.instances.map((i) => (i.id === id ? updated : i)),
      }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  stopInstance: async (id) => {
    try {
      const updated = await simulationApi.stop(id);
      set((state) => ({
        instances: state.instances.map((i) => (i.id === id ? updated : i)),
      }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  deleteInstance: async (id) => {
    try {
      await simulationApi.delete(id);
      set((state) => ({
        instances: state.instances.filter((i) => i.id !== id),
        strategyLogs: Object.fromEntries(Object.entries(state.strategyLogs).filter(([k]) => k !== id)),
        realtimeTrades: Object.fromEntries(Object.entries(state.realtimeTrades).filter(([k]) => k !== id)),
        accountUpdates: Object.fromEntries(Object.entries(state.accountUpdates).filter(([k]) => k !== id)),
        autoTradeConfigs: Object.fromEntries(Object.entries(state.autoTradeConfigs).filter(([k]) => k !== id)),
        pendingSignals: Object.fromEntries(Object.entries(state.pendingSignals).filter(([k]) => k !== id)),
      }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  placeSimOrder: async (instanceId, params) => {
    try {
      await simulationApi.placeOrder(instanceId, params);
      // 刷新实例数据以反映账户变化
      const instances = await simulationApi.list();
      set({ instances });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  // 自动交易配置
  fetchAutoTradeConfig: async (instanceId) => {
    try {
      const config = await simulationApi.getAutoTradeConfig(instanceId);
      set((state) => ({
        autoTradeConfigs: { ...state.autoTradeConfigs, [instanceId]: config },
      }));
    } catch (e: unknown) {
      // 静默失败，不影响主流程
    }
  },

  updateAutoTradeConfig: async (instanceId, config) => {
    try {
      const updated = await simulationApi.updateAutoTradeConfig(instanceId, config);
      set((state) => ({
        autoTradeConfigs: { ...state.autoTradeConfigs, [instanceId]: updated },
        // 同步更新 instances 中的 auto_trade 字段
        instances: state.instances.map((i) =>
          i.id === instanceId
            ? { ...i, auto_trade_enabled: updated.auto_trade_enabled, confirm_required: updated.confirm_required }
            : i
        ),
      }));
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  // 信号管理
  fetchPendingSignals: async (instanceId) => {
    try {
      const signals = await simulationApi.listSignals(instanceId);
      set((state) => ({
        pendingSignals: { ...state.pendingSignals, [instanceId]: signals },
      }));
    } catch (e: unknown) {
      // 静默失败
    }
  },

  confirmSignal: async (instanceId, signalId) => {
    try {
      await simulationApi.confirmSignal(instanceId, signalId);
      // 移除已确认的信号
      get().removePendingSignal(instanceId, signalId);
      // 刷新实例数据
      const instances = await simulationApi.list();
      set({ instances });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  rejectSignal: async (instanceId, signalId) => {
    try {
      await simulationApi.rejectSignal(instanceId, signalId);
      get().removePendingSignal(instanceId, signalId);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      set({ error: message });
    }
  },

  addPendingSignal: (instanceId, signal) => {
    set((state) => {
      const signals = state.pendingSignals[instanceId] || [];
      return {
        pendingSignals: {
          ...state.pendingSignals,
          [instanceId]: [signal, ...signals],
        },
      };
    });
  },

  removePendingSignal: (instanceId, signalId) => {
    set((state) => {
      const signals = (state.pendingSignals[instanceId] || []).filter((s) => s.id !== signalId);
      return {
        pendingSignals: {
          ...state.pendingSignals,
          [instanceId]: signals,
        },
      };
    });
  },

  updateRealtimePrice: (symbol, tick) => {
    set((state) => ({
      realtimePrices: { ...state.realtimePrices, [symbol]: tick },
    }));
  },

  addStrategyLog: (instanceId, log) => {
    set((state) => {
      const logs = state.strategyLogs[instanceId] || [];
      const updated = [...logs, log];
      return {
        strategyLogs: {
          ...state.strategyLogs,
          [instanceId]: updated.length > MAX_STRATEGY_LOGS
            ? updated.slice(-MAX_STRATEGY_LOGS)
            : updated,
        },
      };
    });
  },

  addRealtimeTrade: (trade) => {
    set((state) => {
      const trades = state.realtimeTrades[trade.instance_id] || [];
      const updated = [...trades, trade];
      return {
        realtimeTrades: {
          ...state.realtimeTrades,
          [trade.instance_id]: updated.length > MAX_REALTIME_TRADES
            ? updated.slice(-MAX_REALTIME_TRADES)
            : updated,
        },
      };
    });
  },

  updateAccount: (instanceId, data) => {
    set((state) => ({
      accountUpdates: { ...state.accountUpdates, [instanceId]: data },
    }));
  },

  clearInstanceRealtime: (instanceId) => {
    set((state) => ({
      strategyLogs: Object.fromEntries(Object.entries(state.strategyLogs).filter(([k]) => k !== instanceId)),
      realtimeTrades: Object.fromEntries(Object.entries(state.realtimeTrades).filter(([k]) => k !== instanceId)),
      accountUpdates: Object.fromEntries(Object.entries(state.accountUpdates).filter(([k]) => k !== instanceId)),
    }));
  },
}));
