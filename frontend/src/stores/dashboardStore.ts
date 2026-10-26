import { create } from 'zustand';
import { dashboardApi } from '@/api/dashboard';
import type { DashboardSummary, ServicesStatus } from '@/api/dashboard';

interface DashboardState {
  summary: DashboardSummary | null;
  services: ServicesStatus | null;
  loading: boolean;
  lastFetchedAt: number;
  _reconnectAttempted: boolean;

  getCachedSummary: () => DashboardSummary | null;
  fetchSummary: () => Promise<DashboardSummary | null>;
  refreshSummary: () => Promise<DashboardSummary | null>;
  fetchServices: () => Promise<void>;
}

const CACHE_STALE_MS = 30_000;

export const useDashboardStore = create<DashboardState>()((set, get) => ({
  summary: null,
  services: null,
  loading: false,
  lastFetchedAt: 0,
  _reconnectAttempted: false,

  getCachedSummary: () => get().summary,

  fetchSummary: async () => {
    const state = get();
    if (state.summary && Date.now() - state.lastFetchedAt < CACHE_STALE_MS) {
      return state.summary;
    }
    if (state.loading) return state.summary;

    set({ loading: true });
    try {
      const data = await dashboardApi.summary();
      set({ summary: data, loading: false, lastFetchedAt: Date.now() });
      return data;
    } catch {
      set({ loading: false });
      return state.summary;
    }
  },

  refreshSummary: async () => {
    const state = get();
    if (state.loading) return state.summary;
    set({ loading: true });
    try {
      const data = await dashboardApi.summary();
      set({ summary: data, loading: false, lastFetchedAt: Date.now() });
      return data;
    } catch {
      set({ loading: false });
      return state.summary;
    }
  },

  fetchServices: async () => {
    try {
      const data = await dashboardApi.health();
      set({ services: data });

      // 交易服务不可用时，尝试一次重连
      const tradingOffline = data.trading?.status === 'offline' || !data.trading?.xtquant?.connected;
      if (tradingOffline && !get()._reconnectAttempted) {
        set({ _reconnectAttempted: true });
        try {
          const { connectGateway } = await import('@/api/trading');
          const res = await connectGateway();
          if (res.success) {
            // 重连成功，刷新服务状态
            const updated = await dashboardApi.health();
            set({ services: updated, _reconnectAttempted: false });
          }
        } catch {
          // 重连失败，静默处理
        }
      } else if (!tradingOffline) {
        // 交易服务已在线，重置重连标记
        set({ _reconnectAttempted: false });
      }
    } catch {
      // 静默失败
    }
  },
}));