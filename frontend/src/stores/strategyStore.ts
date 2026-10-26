import { create } from 'zustand';
import { strategyApi, backtestApi } from '@/api';
import type { StrategyResponse, BacktestResultResponse, BacktestRunRequest } from '@/api/strategies';

interface ParamDict {
  value: unknown;
  type: string;
  label?: string;
  min?: number;
  max?: number;
  description?: string;
}

interface ParamArray {
  key: string;
  name: string;
  type: string;
  default: string | number | boolean;
  min?: number;
  max?: number;
  description: string;
}

/** Convert dict-format parameters from API to array format for UI */
function paramsDictToArray(params: Record<string, ParamDict> | ParamArray[] | undefined): ParamArray[] {
  if (Array.isArray(params)) return params;
  if (!params) return [];
  return Object.entries(params).map(([key, val]) => ({
    key,
    name: val.label || key,
    type: val.type || 'int',
    default: val.value as string | number | boolean,
    min: val.min,
    max: val.max,
    description: val.description || val.label || key,
  }));
}

/** Convert array-format parameters from UI to dict format for API */
function paramsArrayToDict(params: ParamArray[] | Record<string, ParamDict> | undefined): Record<string, ParamDict> {
  if (Array.isArray(params)) {
    return Object.fromEntries(
      params.map((p) => [p.key, { value: p.default, type: p.type, label: p.name, min: p.min, max: p.max }])
    );
  }
  return params || {};
}

interface StrategyState {
  strategies: StrategyResponse[];
  currentStrategy: StrategyResponse | null;
  backtestResults: BacktestResultResponse[];
  currentBacktest: BacktestResultResponse | null;
  loading: boolean;
  error: string | null;

  fetchStrategies: () => Promise<void>;
  fetchStrategy: (id: string) => Promise<void>;
  createStrategy: (data: Partial<StrategyResponse>) => Promise<StrategyResponse | null>;
  updateStrategy: (id: string, data: Partial<StrategyResponse>) => Promise<StrategyResponse | null>;
  deleteStrategy: (id: string) => Promise<void>;
  batchDeleteStrategies: (ids: string[]) => Promise<void>;
  runBacktest: (data: BacktestRunRequest) => Promise<BacktestResultResponse | null>;
  fetchBacktestResults: () => Promise<void>;
  fetchBacktestResult: (id: string) => Promise<void>;
  deleteBacktestResult: (id: string) => Promise<void>;
  batchDeleteBacktestResults: (ids: string[]) => Promise<void>;
}

function getErrorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export const useStrategyStore = create<StrategyState>()((set) => ({
  strategies: [],
  currentStrategy: null,
  backtestResults: [],
  currentBacktest: null,
  loading: false,
  error: null,

  fetchStrategies: async () => {
    set({ loading: true, error: null });
    try {
      const raw = await strategyApi.list();
      const strategies = raw.map((s) => ({
        ...s,
        parameters: paramsDictToArray(s.parameters as Record<string, ParamDict> | ParamArray[]),
      }));
      set({ strategies, loading: false });
    } catch (e: unknown) {
      set({ error: getErrorMessage(e), loading: false });
    }
  },

  fetchStrategy: async (id) => {
    set({ loading: true, error: null });
    try {
      const raw = await strategyApi.get(id);
      const strategy = {
        ...raw,
        parameters: paramsDictToArray(raw.parameters as Record<string, ParamDict> | ParamArray[]),
      };
      set({ currentStrategy: strategy, loading: false });
    } catch (e: unknown) {
      set({ error: getErrorMessage(e), loading: false });
    }
  },

  createStrategy: async (data) => {
    try {
      const params = paramsArrayToDict(data.parameters as any);
      const raw = await strategyApi.create({ ...data, parameters: params } as any);
      const strategy = {
        ...raw,
        parameters: paramsDictToArray(raw.parameters as any),
      } as StrategyResponse;
      set((state) => ({ strategies: [...state.strategies, strategy] }));
      return strategy;
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
      return null;
    }
  },

  deleteStrategy: async (id) => {
    try {
      await strategyApi.delete(id);
      set((state) => ({ strategies: state.strategies.filter((s) => s.id !== id) }));
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
    }
  },

  batchDeleteStrategies: async (ids) => {
    try {
      await strategyApi.batchDelete(ids);
      set((state) => ({ strategies: state.strategies.filter((s) => !ids.includes(s.id)) }));
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
    }
  },

  updateStrategy: async (id, data) => {
    try {
      const params = paramsArrayToDict(data.parameters as any);
      const raw = await strategyApi.update(id, { ...data, parameters: params } as any);
      const strategy = {
        ...raw,
        parameters: paramsDictToArray(raw.parameters as any),
      } as StrategyResponse;
      set((state) => ({
        strategies: state.strategies.map((s) => (s.id === id ? strategy : s)),
      }));
      return strategy;
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
      return null;
    }
  },

  runBacktest: async (data) => {
    set({ loading: true, error: null });
    try {
      const result = await backtestApi.run(data);
      set({ currentBacktest: result, loading: false });
      return result;
    } catch (e: unknown) {
      set({ error: getErrorMessage(e), loading: false });
      return null;
    }
  },

  fetchBacktestResults: async () => {
    set({ loading: true, error: null });
    try {
      const results = await backtestApi.list();
      set({ backtestResults: results, loading: false });
    } catch (e: unknown) {
      set({ error: getErrorMessage(e), loading: false });
    }
  },

  fetchBacktestResult: async (id) => {
    set({ loading: true, error: null });
    try {
      const result = await backtestApi.get(id);
      set({ currentBacktest: result, loading: false });
    } catch (e: unknown) {
      set({ error: getErrorMessage(e), loading: false });
    }
  },

  deleteBacktestResult: async (id) => {
    try {
      await backtestApi.delete(id);
      set((state) => ({
        backtestResults: state.backtestResults.filter((r) => r.id !== id),
        currentBacktest: state.currentBacktest?.id === id ? null : state.currentBacktest,
      }));
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
    }
  },

  batchDeleteBacktestResults: async (ids) => {
    try {
      await backtestApi.batchDelete(ids);
      set((state) => ({
        backtestResults: state.backtestResults.filter((r) => !ids.includes(r.id)),
        currentBacktest: state.currentBacktest && ids.includes(state.currentBacktest.id) ? null : state.currentBacktest,
      }));
    } catch (e: unknown) {
      set({ error: getErrorMessage(e) });
    }
  },
}));
