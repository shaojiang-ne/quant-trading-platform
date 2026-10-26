import { create } from 'zustand';
import { api } from '@/api/client';

export interface StockInfo {
  code: string;
  name: string;
  exchange: string;
  pinyin: string;
  full_pinyin: string;
}

interface StockCacheState {
  stocks: StockInfo[];
  _index: Record<string, StockInfo>;
  loaded: boolean;
  loading: boolean;

  fetchAll: () => Promise<void>;
  search: (q: string, limit?: number) => StockInfo[];
  lookup: (code: string) => StockInfo | undefined;
}

export const useStockCacheStore = create<StockCacheState>()((set, get) => ({
  stocks: [],
  _index: {},
  loaded: false,
  loading: false,

  fetchAll: async () => {
    const state = get();
    if (state.loaded || state.loading) return;
    set({ loading: true });
    try {
      const data = await api.get<StockInfo[]>('/stocks/all');
      const index: Record<string, StockInfo> = {};
      for (const s of data) index[s.code] = s;
      set({ stocks: data, _index: index, loaded: true, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  search: (q, limit = 20) => {
    const { stocks } = get();
    if (!q.trim()) return [];
    const query = q.trim().toLowerCase();
    const results: StockInfo[] = [];
    for (const s of stocks) {
      if (
        s.code.startsWith(query)
        || s.name.toLowerCase().includes(query)
        || s.pinyin.startsWith(query)
        || s.full_pinyin.includes(query)
      ) {
        results.push(s);
        if (results.length >= limit) break;
      }
    }
    return results;
  },

  lookup: (code) => get()._index[code],
}));
