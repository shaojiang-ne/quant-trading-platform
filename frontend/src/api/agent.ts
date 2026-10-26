import { useAuthStore } from '@/stores';
import type { StreamChunk } from '@/api/ai';
import type {
  StockPickingStrategy,
  StockPickResult,
  WatchlistStock,
  MonitoringRule,
  MonitoringSignal,
} from '@/types/agent';

const API_BASE = '/api';

// ── Mock 兜底 ────────────────────────────────────────────────────────────
// 后端 /api/agent/* 接口已实现，USE_MOCK=false 走真实后端。
// mock 函数保留以便后续临时回退；正常使用无需开启。
const USE_MOCK = false;

function mockDelay<T>(value: T, ms = 200): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

// 简单伪随机：基于种子生成稳定数值，避免 Date.now/Math.random 在流式上下文波动
function seededRand(seedStr: string, max = 100): number {
  let h = 0;
  for (let i = 0; i < seedStr.length; i++) {
    h = (h * 31 + seedStr.charCodeAt(i)) >>> 0;
  }
  return h % max;
}

// mock 选股结果池
const MOCK_PICK_POOL: Array<{ code: string; name: string }> = [
  { code: '600519', name: '贵州茅台' },
  { code: '000858', name: '五粮液' },
  { code: '601318', name: '中国平安' },
  { code: '000333', name: '美的集团' },
  { code: '600036', name: '招商银行' },
  { code: '000651', name: '格力电器' },
  { code: '601166', name: '兴业银行' },
  { code: '600276', name: '恒瑞医药' },
];

const MATCH_REASONS = [
  '低估值高分红，符合策略条件',
  '近期放量突破前期高点',
  '北向资金持续净流入',
  '业绩超市场预期',
  '技术面多头排列，量价配合',
];

function buildMockPickResults(strategyId: string): StockPickResult[] {
  const count = 4 + (seededRand(strategyId, 3)); // 4-6 只
  const picks: StockPickResult[] = [];
  for (let i = 0; i < count; i++) {
    const stock = MOCK_PICK_POOL[i % MOCK_PICK_POOL.length];
    const seed = `${strategyId}-${stock.code}`;
    picks.push({
      id: `pick-${strategyId}-${i}`,
      strategyId,
      code: stock.code,
      name: stock.name,
      price: 20 + seededRand(seed, 1800) / 10,
      changePct: (seededRand(seed + 'c', 600) - 300) / 100, // -3.00 ~ +3.00
      matchScore: 70 + seededRand(seed + 's', 30),
      matchReason: MATCH_REASONS[i % MATCH_REASONS.length],
      addedToWatchlist: false,
      pickedAt: new Date().toISOString(),
    });
  }
  return picks;
}

function buildMockWatchlistStock(code: string, name: string, order: number): WatchlistStock {
  const seed = code;
  const price = 10 + seededRand(seed, 1900) / 10;
  return {
    id: `wl-${code}-${Date.now()}`,
    code,
    name: name || `股票${code}`,
    price,
    changePct: (seededRand(seed + 'c', 600) - 300) / 100,
    volume: (5 + seededRand(seed + 'v', 95)) * 10000,
    turnoverRate: seededRand(seed + 't', 800) / 100,
    floatMarketCap: 50 + seededRand(seed + 'm', 950),
    monitoringStatus: 'none',
    order,
    addedAt: new Date().toISOString(),
  };
}

async function agentFetch(path: string, options?: RequestInit) {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `请求失败 (${response.status})`);
  }

  return response.json();
}

// ── 选股策略 ──────────────────────────────────────────────────────────────
export async function createPickStrategy(
  description: string
): Promise<{ strategy: StockPickingStrategy; optimized: string }> {
  return agentFetch('/agent/pick/strategy', {
    method: 'POST',
    body: JSON.stringify({ description }),
  });
}

// ── 选股策略优化（SSE 流式）───────────────────────────────────────────────
// 流式输出策略优化描述供前端展示，不持久化。用户"采纳"后才走 createPickStrategy
// → confirmPickStrategy → executePickStrategy 三段式。
// history：自上次确认以来的未确认多轮对话，供 AI 在上一轮策略基础上继续优化；
// 为空（或不传）时单轮生成。后端默认 [] 兼容。
export async function* streamPickOptimize(
  description: string,
  history?: { role: string; content: string }[]
): AsyncGenerator<StreamChunk> {
  const token = useAuthStore.getState().token;

  const response = await fetch(`${API_BASE}/agent/pick/optimize-stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ description, history: history ?? [] }),
  });

  if (response.status === 401) {
    useAuthStore.getState().logout();
    window.location.hash = '#/login';
    throw new Error('登录已过期，请重新登录');
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `选股优化请求失败 (${response.status})`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          yield data as StreamChunk;
        } catch {
          // skip malformed JSON
        }
      }
    }
  }
}

export async function updatePickStrategy(
  strategyId: string,
  payload: { description?: string; optimizedDescription?: string }
): Promise<StockPickingStrategy> {
  return agentFetch(`/agent/pick/strategy/${strategyId}`, {
    method: 'PUT',
    body: JSON.stringify({
      description: payload.description,
      optimized_description: payload.optimizedDescription,
    }),
  });
}

export async function deletePickStrategy(strategyId: string): Promise<void> {
  await agentFetch(`/agent/pick/strategy/${strategyId}`, { method: 'DELETE' });
}

export async function batchDeleteStrategies(ids: string[]): Promise<{ deleted: number }> {
  return agentFetch('/agent/pick/strategies/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

export async function confirmPickStrategy(
  strategyId: string
): Promise<StockPickingStrategy> {
  const data = await agentFetch(`/agent/pick/strategy/${strategyId}/confirm`, {
    method: 'POST',
  });
  return data.strategy as StockPickingStrategy;
}

export async function fetchPickStrategies(): Promise<StockPickingStrategy[]> {
  if (USE_MOCK) return mockDelay([]);
  return agentFetch('/agent/pick/strategies');
}

export async function executePickStrategy(strategyId: string): Promise<StockPickResult[]> {
  if (USE_MOCK) return mockDelay(buildMockPickResults(strategyId));
  return agentFetch(`/agent/pick/execute/${strategyId}`, { method: 'POST' });
}

export async function schedulePickStrategy(
  strategyId: string,
  scheduleTime: string,
  enabled: boolean
): Promise<void> {
  if (USE_MOCK) return mockDelay(undefined);
  return agentFetch('/agent/pick/schedule', {
    method: 'POST',
    body: JSON.stringify({ strategy_id: strategyId, schedule_time: scheduleTime, enabled }),
  });
}

// ── 选股结果 ──────────────────────────────────────────────────────────────
export async function fetchPickResults(strategyId: string): Promise<StockPickResult[]> {
  if (USE_MOCK) return mockDelay(buildMockPickResults(strategyId));
  return agentFetch(`/agent/pick/results/${strategyId}`);
}

// ── 自选股 ────────────────────────────────────────────────────────────────
export async function fetchWatchlist(): Promise<WatchlistStock[]> {
  if (USE_MOCK) return mockDelay([]);
  return agentFetch('/agent/watchlist');
}

export async function addToWatchlist(code: string, name: string): Promise<WatchlistStock> {
  if (USE_MOCK) {
    const order = seededRand(code, 1000);
    return mockDelay(buildMockWatchlistStock(code, name, order));
  }
  return agentFetch('/agent/watchlist', {
    method: 'POST',
    body: JSON.stringify({ code, name }),
  });
}

export async function removeFromWatchlist(id: string): Promise<void> {
  if (USE_MOCK) return mockDelay(undefined);
  return agentFetch(`/agent/watchlist/${id}`, { method: 'DELETE' });
}

export async function batchRemoveFromWatchlist(ids: string[]): Promise<{ deleted: number }> {
  if (USE_MOCK) return mockDelay({ deleted: ids.length });
  return agentFetch('/agent/watchlist/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

export async function reorderWatchlist(ids: string[]): Promise<void> {
  if (USE_MOCK) return mockDelay(undefined);
  return agentFetch('/agent/watchlist/reorder', {
    method: 'PUT',
    body: JSON.stringify({ ids }),
  });
}

// ── 盯盘规则 ──────────────────────────────────────────────────────────────
export async function createMonitorRules(
  stockCode: string,
  description: string
): Promise<{ rules: MonitoringRule[]; suggestion: string }> {
  if (USE_MOCK) {
    const rules: MonitoringRule[] = [
      {
        id: `rule-${stockCode}-1`,
        stockCode,
        condition: '放量突破20日均线',
        action: 'buy',
        positionPct: 33,
        advanceMinutes: 5,
        trigger: { metric: 'vol_ratio', op: '>=', threshold: 2 },
        active: true,
        createdAt: new Date().toISOString(),
      },
    ];
    return mockDelay({ rules, suggestion: '建议增加最大回撤保护规则。' });
  }
  return agentFetch('/agent/monitor/rules', {
    method: 'POST',
    body: JSON.stringify({ stock_code: stockCode, description }),
  });
}

export async function fetchMonitorRules(stockCode: string): Promise<MonitoringRule[]> {
  if (USE_MOCK) return mockDelay([]);
  return agentFetch(`/agent/monitor/rules/${stockCode}`);
}

export async function updateMonitorRule(
  ruleId: string,
  updates: Partial<MonitoringRule>
): Promise<MonitoringRule> {
  if (USE_MOCK) {
    return mockDelay({ ...(updates as MonitoringRule), id: ruleId });
  }
  return agentFetch(`/agent/monitor/rules/${ruleId}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
}

export async function deleteMonitorRule(ruleId: string): Promise<void> {
  if (USE_MOCK) return mockDelay(undefined);
  return agentFetch(`/agent/monitor/rules/${ruleId}`, { method: 'DELETE' });
}

// 取消全部盯盘：删除当前用户所有盯盘规则并重置盯盘状态（股票保留）
export async function cancelAllMonitorRules(): Promise<void> {
  if (USE_MOCK) return mockDelay(undefined);
  return agentFetch('/agent/monitor/rules', { method: 'DELETE' });
}

export async function batchDeleteMonitorRules(ids: string[]): Promise<{ deleted: number }> {
  if (USE_MOCK) return mockDelay({ deleted: ids.length });
  return agentFetch('/agent/monitor/rules/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

// ── 盯盘信号 ──────────────────────────────────────────────────────────────
export async function fetchSignals(date?: string, status?: string): Promise<MonitoringSignal[]> {
  if (USE_MOCK) return mockDelay([]);
  const params: string[] = [];
  if (date) params.push(`date=${date}`);
  if (status) params.push(`status=${status}`);
  const qs = params.length ? `?${params.join('&')}` : '';
  return agentFetch(`/agent/monitor/signals${qs}`);
}

export async function updateSignalStatus(
  signalId: string,
  status: MonitoringSignal['status']
): Promise<MonitoringSignal> {
  if (USE_MOCK) {
    // 本地无原始 signal 副本，返回一个带新状态的占位对象；store 会用 id 合并
    return mockDelay({
      id: signalId,
      stockCode: '',
      stockName: '',
      type: 'alert' as const,
      ruleId: '',
      ruleDescription: '',
      triggerTime: new Date().toISOString(),
      targetPrice: 0,
      suggestedQuantity: 0,
      suggestedPositionPct: 0,
      advanceMinutes: 0,
      currentPrice: 0,
      status,
    });
  }
  return agentFetch(`/agent/monitor/signals/${signalId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
}

export async function batchDeleteSignals(ids: string[]): Promise<{ deleted: number }> {
  if (USE_MOCK) return mockDelay({ deleted: ids.length });
  return agentFetch('/agent/monitor/signals/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}
