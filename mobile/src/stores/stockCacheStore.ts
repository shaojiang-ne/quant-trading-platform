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

  lookup: (code) => get()._index[code],
}));

// ── 股票代码解析 ──────────────────────────────────────────────────────────────
export async function resolveCode(text: string): Promise<string> {
  const m = text.match(/\d{6}/);
  if (m) return m[0];

  const store = useStockCacheStore.getState();
  if (!store.loaded) {
    await store.fetchAll();
  }
  const lower = text.toLowerCase();
  let best: { code: string; name: string } | undefined;
  for (const s of useStockCacheStore.getState().stocks) {
    if (!s.name) continue;
    if (lower.includes(s.name.toLowerCase())) {
      if (!best || s.name.length > best.name.length) best = { code: s.code, name: s.name };
    }
  }
  return best?.code ?? '';
}

export function resolveCodes(text: string): string {
  const matches = text.match(/\d{6}/g) || [];
  const seen = new Set<string>();
  const uniq: string[] = [];
  for (const c of matches) {
    if (!seen.has(c)) { seen.add(c); uniq.push(c); }
  }
  return uniq.join(',');
}
