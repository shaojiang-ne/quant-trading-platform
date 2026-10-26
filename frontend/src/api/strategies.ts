import { api } from './client';

export interface DailyResult {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  equity: number;
}

export interface IntradayResult {
  date: string;
  bars: IntradayBar[];
  trades: BacktestTrade[];
}

export interface IntradayBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BacktestTrade {
  date: string;
  time?: string;
  side: string;
  symbol: string;
  price: number;
  quantity: number;
  commission?: number;
  pnl?: number;
}

export interface StrategyParamResponse {
  name: string;
  key: string;
  type: string;
  default: string | number | boolean;
  min?: number;
  max?: number;
  description: string;
}

export interface StrategyResponse {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  code: string;
  class_name: string;
  algorithm: string;
  advantages: string[];
  disadvantages: string[];
  parameters: StrategyParamResponse[];
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface BacktestRunRequest {
  strategy_id: string;
  symbol: string;
  interval: string;
  period: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  initial_position: number;
  params: Record<string, unknown>;
  commission_rate: number;
  stamp_tax_rate: number;
  data_source?: string;
  incremental_mode?: boolean;
}

export interface DataSourceInfo {
  name: string;
  available: boolean;
}

export interface DataSourcesResponse {
  default: string;
  sources: DataSourceInfo[];
}

export interface BacktestResultResponse {
  id: string;
  strategy_id: string;
  symbol: string;
  interval: string;
  period: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  initial_position: number;
  commission_rate: number;
  stamp_tax_rate: number;
  params: Record<string, unknown>;
  status: string;
  progress: number;
  total_return: number;
  annualized_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  avg_trade_return: number;
  volatility: number;
  beta: number;
  alpha: number;
  benchmark_return?: number;
  daily_results: DailyResult[];
  intraday_results: IntradayResult[];
  trades: BacktestTrade[];
  initial_cash: number;
  initial_position_value: number;
  initial_position_quantity: number;
  final_cash: number;
  final_position_value: number;
  final_position_quantity: number;
  total_profit: number;
  strategy_logs: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export const strategyApi = {
  list: () => api.get<StrategyResponse[]>('/strategies'),
  get: (id: string) => api.get<StrategyResponse>(`/strategies/${id}`),
  create: (data: Partial<StrategyResponse>) => api.post<StrategyResponse>('/strategies', data),
  update: (id: string, data: Partial<StrategyResponse>) => api.put<StrategyResponse>(`/strategies/${id}`, data),
  delete: (id: string) => api.delete(`/strategies/${id}`),
  batchDelete: (ids: string[]) => api.post<{ message: string; deleted_count: number }>('/strategies/batch-delete', { ids }),
};

export const backtestApi = {
  run: (data: BacktestRunRequest) => api.post<BacktestResultResponse>('/backtest/run', data),
  list: () => api.get<BacktestResultResponse[]>('/backtest/results'),
  get: (id: string) => api.get<BacktestResultResponse>(`/backtest/results/${id}`),
  delete: (id: string) => api.delete(`/backtest/results/${id}`),
  batchDelete: (ids: string[]) => api.post<{ message: string; deleted_count: number }>('/backtest/results/batch-delete', { ids }),
  dataSources: () => api.get<DataSourcesResponse>('/backtest/data-sources'),
};

import { type StockInfo } from '@/stores/stockCacheStore';

export const stockApi = {
  fetchAll: () => api.get<StockInfo[]>('/stocks/all'),
  search: (q: string) => api.get<StockInfo[]>(`/stocks/search?q=${encodeURIComponent(q)}`),
  lookup: (code: string) => api.get<StockInfo | null>(`/stocks/lookup/${code}`),
};
