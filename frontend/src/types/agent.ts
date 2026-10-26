// ── 选股策略 ──────────────────────────────────────────────────────────────
export interface StrategyRule {
  id: string;
  condition: string;
  action: string;
  params: Record<string, unknown>;
  active: boolean;
}

// 选股规则程序（用户确认后由 AI 编译的结构化规则）
export interface PickFilter {
  field: string;
  op: string;
  value: number;
}
export interface PickScoring {
  field: string;
  weight: number;
  direction: 'high' | 'low';
}
export interface PickRuleProgram {
  pool: string;
  filters?: PickFilter[];
  scoring?: PickScoring[];
  top_n?: number;
}

export type StrategyStatus = 'draft' | 'confirmed' | 'scheduled';

export interface StockPickingStrategy {
  id: string;
  name: string;
  description: string;
  optimizedDescription: string;
  rules: PickRuleProgram | unknown[];  // 规则程序 dict；draft 时为空 []
  status: StrategyStatus;
  scheduleTime?: string;
  scheduleEnabled: boolean;
  createdAt: string;
  updatedAt: string;
}

// ── 选股结果 ──────────────────────────────────────────────────────────────
export interface StockPickResult {
  id: string;
  strategyId: string;
  code: string;
  name: string;
  price: number;
  changePct: number;
  matchScore: number;
  matchReason: string;
  addedToWatchlist: boolean;
  pickedAt: string;
}

// ── 自选股 ────────────────────────────────────────────────────────────────
export type MonitoringStatus = 'active' | 'pending' | 'none';

export interface WatchlistStock {
  id: string;
  code: string;
  name: string;
  price: number;
  changePct: number;
  volume: number;
  turnoverRate: number;
  floatMarketCap: number;
  monitoringStatus: MonitoringStatus;
  order: number;
  addedAt: string;
}

// ── 盯盘规则 ──────────────────────────────────────────────────────────────
export type MonitoringAction = 'buy' | 'sell' | 'alert';

/** 盯盘引擎可评估的触发规范：metric op threshold */
export type RuleTriggerMetric = 'price' | 'change_pct' | 'vol_ratio' | 'turnover_pct';
export type RuleTriggerOp = '>=' | '<=';

export interface RuleTrigger {
  metric: RuleTriggerMetric;
  op: RuleTriggerOp;
  threshold: number;
}

export interface MonitoringRule {
  id: string;
  stockCode: string;
  condition: string;
  action: MonitoringAction;
  targetPrice?: number;
  quantity?: number;
  positionPct?: number;
  advanceMinutes: number;
  trigger?: RuleTrigger | null;
  active: boolean;
  createdAt: string;
}

// ── 盯盘信号 ──────────────────────────────────────────────────────────────
export type SignalType = 'buy' | 'sell' | 'alert';
export type SignalStatus = 'pending' | 'confirmed' | 'ignored' | 'expired';

export interface MonitoringSignal {
  id: string;
  stockCode: string;
  stockName: string;
  type: SignalType;
  ruleId: string;
  ruleDescription: string;
  triggerTime: string;
  targetPrice: number;
  suggestedQuantity: number;
  suggestedPositionPct: number;
  advanceMinutes: number;
  currentPrice: number;
  status: SignalStatus;
  resolvedAt?: string;
}

// ── 聊天消息 ──────────────────────────────────────────────────────────────
export type ChatMessageRole = 'user' | 'assistant' | 'system';

export interface AgentChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  isStreaming?: boolean;
  timestamp: number;
}

// ── 面板布局 ──────────────────────────────────────────────────────────────
export type PanelKey = 'pick' | 'watch' | 'monitor';

export interface PanelLayout {
  widths: [number, number, number];
  collapsed: Record<PanelKey, boolean>;
  /** 面板内上下分区的顶部高度百分比（0-100）。pick=AI选股，monitor=智能盯盘 */
  pickSplit: number;
  monitorSplit: number;
}

// ── 快捷模板 ──────────────────────────────────────────────────────────────
export interface QuickTemplate {
  label: string;
  prompt: string;
  color: string;
}
