import { create } from 'zustand';
import * as agentApi from '@/api/agent';
import type {
  StockPickingStrategy,
  StockPickResult,
  WatchlistStock,
  MonitoringRule,
  MonitoringSignal,
  AgentChatMessage,
  PanelKey,
  PanelLayout,
} from '@/types/agent';

const DEFAULT_WIDTHS: [number, number, number] = [30, 30, 40];

function generateId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
}

// 面板内上下分区顶部高度百分比默认值（与原 flex 比例一致：6:4 / 4.5:5.5）
const DEFAULT_PICK_SPLIT = 60;
const DEFAULT_MONITOR_SPLIT = 45;
const MIN_SPLIT = 10; // 顶部最小百分比
const MAX_SPLIT = 90; // 顶部最大百分比

function loadPanelLayout(): PanelLayout {
  const defaults: PanelLayout = {
    widths: [...DEFAULT_WIDTHS] as [number, number, number],
    collapsed: { pick: false, watch: false, monitor: false },
    pickSplit: DEFAULT_PICK_SPLIT,
    monitorSplit: DEFAULT_MONITOR_SPLIT,
  };
  try {
    const saved = localStorage.getItem('agent-panel-layout');
    if (!saved) return defaults;
    const parsed = JSON.parse(saved);
    // 向后兼容：旧持久化数据没有 pickSplit/monitorSplit，补上默认值
    return {
      ...defaults,
      ...parsed,
      pickSplit: typeof parsed.pickSplit === 'number' ? parsed.pickSplit : DEFAULT_PICK_SPLIT,
      monitorSplit: typeof parsed.monitorSplit === 'number' ? parsed.monitorSplit : DEFAULT_MONITOR_SPLIT,
    };
  } catch { /* ignore */ }
  return defaults;
}

function savePanelLayout(layout: PanelLayout) {
  try {
    localStorage.setItem('agent-panel-layout', JSON.stringify(layout));
  } catch { /* ignore */ }
}

// ── Quick templates ──────────────────────────────────────────────────────
export const PICK_TEMPLATES = [
  { label: '低估值高分红', prompt: '帮我筛选低估值高分红的股票，PE<15，股息率>3%', color: 'bg-blue-50 text-blue-600 border-blue-200' },
  { label: '放量突破', prompt: '找出近期放量突破前期高点的股票', color: 'bg-orange-50 text-orange-600 border-orange-200' },
  { label: '北向资金流入', prompt: '筛选北向资金近期持续净流入的股票', color: 'bg-cyan-50 text-cyan-600 border-cyan-200' },
  { label: '业绩超预期', prompt: '最近一期财报超市场预期的股票', color: 'bg-green-50 text-green-600 border-green-200' },
];

export const MONITOR_TEMPLATES = [
  { label: '均线突破', prompt: '突破20日均线买入1/3仓，跌破5日均线止损', color: 'bg-blue-50 text-blue-600 border-blue-200' },
  { label: '放量异动', prompt: '成交量放大2倍以上时预警，放量大涨买入半仓', color: 'bg-orange-50 text-orange-600 border-orange-200' },
  { label: '价格区间', prompt: '跌破支撑位预警，涨到压力位减仓1/2', color: 'bg-purple-50 text-purple-600 border-purple-200' },
];

// ── Store interface ───────────────────────────────────────────────────────
interface AgentStore {
  // Layout
  panelLayout: PanelLayout;
  setPanelWidths: (widths: [number, number, number]) => void;
  setPanelSplit: (panel: 'pick' | 'monitor', topPct: number) => void;
  togglePanelCollapse: (panel: PanelKey) => void;

  // Stock Picking
  strategies: StockPickingStrategy[];
  currentStrategyId: string | null;
  pickResults: StockPickResult[];
  pickMessages: AgentChatMessage[];
  // 未确认策略段的分割点：上次确认成功那一刻 pickMessages 的长度。
  // 未确认上下文 = pickMessages.slice(pickConfirmedSegmentEnd)。
  // 确认后推进到当前长度（封存该段）；clearPickChat 重置为 0。
  pickConfirmedSegmentEnd: number;
  pickLoading: boolean;
  pickError: string | null;
  sendPickMessage: (content: string) => Promise<void>;
  confirmStrategy: (id: string) => Promise<boolean>;
  clearPickChat: () => void;
  fetchStrategies: () => Promise<void>;
  createStrategy: (description: string) => Promise<StockPickingStrategy | null>;
  executeStrategy: (id: string) => Promise<void>;
  addPickResultToWatchlist: (resultId: string) => void;
  scheduleStrategy: (strategyId: string, scheduleTime: string, enabled: boolean) => Promise<boolean>;
  deleteStrategy: (id: string) => Promise<boolean>;
  batchDeleteStrategies: (ids: string[]) => Promise<boolean>;
  updateStrategy: (id: string, description: string, optimizedDescription?: string) => Promise<boolean>;

  // Watchlist
  watchlist: WatchlistStock[];
  watchlistLoading: boolean;
  fetchWatchlist: () => Promise<void>;
  addToWatchlist: (code: string, name: string) => Promise<void>;
  removeFromWatchlist: (id: string) => Promise<void>;
  batchRemoveFromWatchlist: (ids: string[]) => Promise<boolean>;
  reorderWatchlist: (ids: string[]) => Promise<void>;
  setWatchlistMonitoringStatus: (stockId: string, status: WatchlistStock['monitoringStatus']) => void;

  // Monitoring
  monitoringRules: MonitoringRule[];
  signals: MonitoringSignal[];
  /** WS 推送收到新 pending 信号时调用;重复 id 跳过 */
  addSignal: (signal: MonitoringSignal) => void;
  fetchMonitorRules: (stockCode: string) => Promise<void>;
  toggleMonitorRule: (id: string, active: boolean) => Promise<boolean>;
  deleteMonitorRule: (id: string) => Promise<boolean>;
  batchDeleteMonitorRules: (ids: string[]) => Promise<boolean>;
  cancelAllMonitorRules: () => Promise<void>;
  /** 取消单只自选股的盯盘:删该股所有规则 + 状态置 none + 刷新信号 */
  cancelStockMonitor: (stockCode: string, stockId: string) => Promise<boolean>;
  updateSignalStatus: (id: string, status: MonitoringSignal['status']) => Promise<void>;
  batchDeleteSignals: (ids: string[]) => Promise<boolean>;
  fetchSignals: (date?: string, status?: string) => Promise<void>;
}

export const useAgentStore = create<AgentStore>()((set, get) => ({
  // ── Layout ────────────────────────────────────────────────────────────
  panelLayout: loadPanelLayout(),

  setPanelWidths: (widths) => {
    const layout = { ...get().panelLayout, widths };
    savePanelLayout(layout);
    set({ panelLayout: layout });
  },

  setPanelSplit: (panel, topPct) => {
    const clamped = Math.max(MIN_SPLIT, Math.min(MAX_SPLIT, topPct));
    const layout = { ...get().panelLayout, [`${panel}Split`]: clamped };
    savePanelLayout(layout);
    set({ panelLayout: layout });
  },

  togglePanelCollapse: (panel) => {
    const collapsed = { ...get().panelLayout.collapsed, [panel]: !get().panelLayout.collapsed[panel] };
    const layout = { ...get().panelLayout, collapsed };
    savePanelLayout(layout);
    set({ panelLayout: layout });
  },

  // ── Stock Picking ─────────────────────────────────────────────────────
  strategies: [],
  currentStrategyId: null,
  pickResults: [],
  pickMessages: [],
  pickConfirmedSegmentEnd: 0,
  pickLoading: false,
  pickError: null,

  sendPickMessage: async (content) => {
    const userMsg: AgentChatMessage = {
      id: generateId('pu'),
      role: 'user',
      content,
      timestamp: Date.now(),
    };

    const assistantMsg: AgentChatMessage = {
      id: generateId('pa'),
      role: 'assistant',
      content: '',
      isStreaming: true,
      timestamp: Date.now(),
    };

    // 继续优化：在追加本轮消息之前，快照"自上次确认以来的未确认多轮对话"作为上下文，
    // 使 AI 基于上一轮未确认策略继续优化，而非当成新策略。后端再把本轮 description
    // 作为最后一条 user 拼上。确认成功后 pickConfirmedSegmentEnd 推进，已确认段不再带入。
    const pendingHistory = get()
      .pickMessages.slice(get().pickConfirmedSegmentEnd)
      .filter((m) => m.content && !m.isStreaming)
      .map((m) => ({ role: m.role, content: m.content }));

    set((state) => ({
      pickMessages: [...state.pickMessages, userMsg, assistantMsg],
      pickLoading: true,
      pickError: null,
      // 新一轮生成：清空上一轮的确认状态，以便再次弹出策略确认卡片
      currentStrategyId: null,
    }));

    try {
      // 继续优化：把"自上次确认以来的未确认多轮对话"作为上下文喂给 AI，
      // 使其基于上一轮未确认策略继续优化，而非当成新策略。快照在 set 之前取，
      // 故不含本轮 userMsg/assistantMsg；后端再把本轮 description 作为最后一条 user 拼上。
      // 确认成功后 pickConfirmedSegmentEnd 推进，已确认段不再带入下一段。
      const stream = agentApi.streamPickOptimize(content, pendingHistory);
      let fullContent = '';

      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          fullContent += chunk.content;
          set((state) => ({
            pickMessages: state.pickMessages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: fullContent } : m
            ),
          }));
        } else if (chunk.type === 'error') {
          set({ pickError: chunk.error || 'AI服务出错' });
        } else if (chunk.type === 'done') {
          set((state) => ({
            pickMessages: state.pickMessages.map((m) =>
              m.id === assistantMsg.id ? { ...m, isStreaming: false } : m
            ),
            pickLoading: false,
          }));
        }
      }
    } catch (e) {
      set((state) => ({
        pickLoading: false,
        pickError: e instanceof Error ? e.message : '发送失败',
        pickMessages: state.pickMessages.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, isStreaming: false, content: '抱歉，AI服务暂时不可用。' }
            : m
        ),
      }));
    }
  },

  confirmStrategy: async (id) => {
    try {
      const strategy = await agentApi.confirmPickStrategy(id);
      set((state) => ({
        strategies: state.strategies.map((s) =>
          s.id === id ? strategy : s
        ),
        currentStrategyId: id,
        // 封存当前未确认段：后续输入作为新策略段，不再带已确认上下文
        pickConfirmedSegmentEnd: state.pickMessages.length,
      }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '确认策略失败（规则生成失败）' });
      return false;
    }
  },

  clearPickChat: () => set({ pickMessages: [], pickConfirmedSegmentEnd: 0, pickError: null }),

  fetchStrategies: async () => {
    try {
      const strategies = await agentApi.fetchPickStrategies();
      set({ strategies });
    } catch (e) {
      console.error('Failed to fetch strategies:', e);
    }
  },

  createStrategy: async (description) => {
    try {
      const { strategy } = await agentApi.createPickStrategy(description);
      set((state) => ({ strategies: [strategy, ...state.strategies] }));
      return strategy;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '创建策略失败' });
      return null;
    }
  },

  executeStrategy: async (id) => {
    try {
      const results = await agentApi.executePickStrategy(id);
      set({ pickResults: results });
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '执行选股失败' });
    }
  },

  addPickResultToWatchlist: (resultId) => {
    set((state) => ({
      pickResults: state.pickResults.map((r) =>
        r.id === resultId ? { ...r, addedToWatchlist: true } : r
      ),
    }));
  },

  scheduleStrategy: async (strategyId, scheduleTime, enabled) => {
    try {
      await agentApi.schedulePickStrategy(strategyId, scheduleTime, enabled);
      set((state) => ({
        strategies: state.strategies.map((s) =>
          s.id === strategyId
            ? {
                ...s,
                scheduleTime,
                scheduleEnabled: enabled,
                // 关闭定时回退为已确认；启用则置定时
                status: (enabled ? 'scheduled' : 'confirmed') as StockPickingStrategy['status'],
              }
            : s
        ),
      }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '配置定时选股失败' });
      return false;
    }
  },

  deleteStrategy: async (id) => {
    try {
      await agentApi.deletePickStrategy(id);
      set((state) => ({ strategies: state.strategies.filter((s) => s.id !== id) }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '删除策略失败' });
      return false;
    }
  },

  batchDeleteStrategies: async (ids) => {
    if (!ids.length) return false;
    try {
      await agentApi.batchDeleteStrategies(ids);
      const idSet = new Set(ids);
      set((state) => ({ strategies: state.strategies.filter((s) => !idSet.has(s.id)) }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '批量删除策略失败' });
      return false;
    }
  },

  updateStrategy: async (id, description, optimizedDescription) => {
    try {
      const updated = await agentApi.updatePickStrategy(id, { description, optimizedDescription });
      set((state) => ({
        strategies: state.strategies.map((s) => (s.id === id ? updated : s)),
      }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '更新策略失败' });
      return false;
    }
  },

  // ── Watchlist ──────────────────────────────────────────────────────────
  watchlist: [],
  watchlistLoading: false,

  fetchWatchlist: async () => {
    set({ watchlistLoading: true });
    try {
      const watchlist = await agentApi.fetchWatchlist();
      set({ watchlist, watchlistLoading: false });
    } catch (e) {
      set({ watchlistLoading: false });
    }
  },

  addToWatchlist: async (code, name) => {
    try {
      const stock = await agentApi.addToWatchlist(code, name);
      set((state) => ({ watchlist: [...state.watchlist, stock] }));
    } catch (e) {
      console.error('Failed to add to watchlist:', e);
    }
  },

  removeFromWatchlist: async (id) => {
    try {
      await agentApi.removeFromWatchlist(id);
      set((state) => ({ watchlist: state.watchlist.filter((w) => w.id !== id) }));
    } catch (e) {
      console.error('Failed to remove from watchlist:', e);
    }
  },

  batchRemoveFromWatchlist: async (ids) => {
    if (!ids.length) return false;
    try {
      await agentApi.batchRemoveFromWatchlist(ids);
      const idSet = new Set(ids);
      set((state) => ({ watchlist: state.watchlist.filter((w) => !idSet.has(w.id)) }));
      return true;
    } catch (e) {
      set({ pickError: e instanceof Error ? e.message : '批量移除自选股失败' });
      return false;
    }
  },

  reorderWatchlist: async (ids) => {
    try {
      await agentApi.reorderWatchlist(ids);
      set((state) => {
        const orderMap = new Map(ids.map((id, idx) => [id, idx]));
        const sorted = [...state.watchlist].sort(
          (a, b) => (orderMap.get(a.id) ?? 999) - (orderMap.get(b.id) ?? 999)
        );
        return { watchlist: sorted };
      });
    } catch (e) {
      console.error('Failed to reorder watchlist:', e);
    }
  },

  setWatchlistMonitoringStatus: (stockId, status) => {
    set((state) => ({
      watchlist: state.watchlist.map((w) =>
        w.id === stockId ? { ...w, monitoringStatus: status } : w
      ),
    }));
  },

  // ── Monitoring ─────────────────────────────────────────────────────────
  monitoringRules: [],
  signals: [],

  addSignal: (signal) => {
    set((state) => {
      if (state.signals.some((s) => s.id === signal.id)) return state;  // 去重
      const next = [signal, ...state.signals];
      return { signals: next };
    });
  },

  fetchMonitorRules: async (stockCode) => {
    try {
      const rules = await agentApi.fetchMonitorRules(stockCode);
      set({ monitoringRules: rules });
    } catch (e) {
      console.error('Failed to fetch monitor rules:', e);
    }
  },

  toggleMonitorRule: async (id, active) => {
    try {
      const updated = await agentApi.updateMonitorRule(id, { active });
      set((state) => {
        const monitoringRules = state.monitoringRules.map((r) => (r.id === id ? updated : r));
        // 同步自选股盯盘状态:启用任一条 → active;停用时若该股已无 active 规则 → none
        const stockCode = updated.stockCode;
        const stillActive = monitoringRules.some((r) => r.stockCode === stockCode && r.active);
        const watchlist = state.watchlist.map((w) =>
          w.code === stockCode ? { ...w, monitoringStatus: (stillActive ? 'active' : 'none') as WatchlistStock['monitoringStatus'] } : w
        );
        return { monitoringRules, watchlist };
      });
      return true;
    } catch (e) {
      console.error('Failed to toggle monitor rule:', e);
      return false;
    }
  },

  deleteMonitorRule: async (id) => {
    try {
      await agentApi.deleteMonitorRule(id);
      set((state) => ({ monitoringRules: state.monitoringRules.filter((r) => r.id !== id) }));
      return true;
    } catch (e) {
      console.error('Failed to delete monitor rule:', e);
      return false;
    }
  },

  batchDeleteMonitorRules: async (ids) => {
    if (!ids.length) return false;
    try {
      await agentApi.batchDeleteMonitorRules(ids);
      const idSet = new Set(ids);
      set((state) => ({ monitoringRules: state.monitoringRules.filter((r) => !idSet.has(r.id)) }));
      return true;
    } catch (e) {
      console.error('Failed to batch delete monitor rules:', e);
      return false;
    }
  },

  cancelAllMonitorRules: async () => {
    try {
      await agentApi.cancelAllMonitorRules();
      set({ monitoringRules: [] });
      await get().fetchWatchlist();
      await get().fetchSignals(undefined, 'pending');
    } catch (e) {
      console.error('Failed to cancel all monitor rules:', e);
      throw e;
    }
  },

  cancelStockMonitor: async (stockCode, stockId) => {
    try {
      // 取消盯盘=停用该股所有规则(保留为历史策略),不删除;状态置 none
      const rules = await agentApi.fetchMonitorRules(stockCode);
      const activeIds = rules.filter((r) => r.active).map((r) => r.id);
      // 逐条停用(单股规则通常很少);toggleMonitorRule 会同步状态,但这里全停后强制置 none
      for (const id of activeIds) {
        await get().toggleMonitorRule(id, false);
      }
      set((state) => ({
        watchlist: state.watchlist.map((w) =>
          w.id === stockId ? { ...w, monitoringStatus: 'none' } : w
        ),
      }));
      await get().fetchSignals(undefined, 'pending');
      return true;
    } catch (e) {
      console.error('Failed to cancel stock monitor:', e);
      return false;
    }
  },

  updateSignalStatus: async (id, status) => {
    try {
      const updated = await agentApi.updateSignalStatus(id, status);
      set((state) => ({
        signals: state.signals.map((s) =>
          // 合并以防后端返回不完整字段，保留原对象其余属性
          s.id === id
            ? { ...s, ...updated, status: updated.status ?? status, resolvedAt: new Date().toISOString() }
            : s
        ),
      }));
    } catch (e) {
      console.error('Failed to update signal status:', e);
    }
  },

  batchDeleteSignals: async (ids) => {
    if (!ids.length) return false;
    try {
      await agentApi.batchDeleteSignals(ids);
      const idSet = new Set(ids);
      set((state) => ({ signals: state.signals.filter((s) => !idSet.has(s.id)) }));
      return true;
    } catch (e) {
      console.error('Failed to batch delete signals:', e);
      return false;
    }
  },

  fetchSignals: async (date, status) => {
    try {
      const signals = await agentApi.fetchSignals(date, status);
      set({ signals });
    } catch (e) {
      console.error('Failed to fetch signals:', e);
    }
  },
}));
