import { api } from './client';

export interface SimInstanceSummary {
  id: string;
  name: string;
  symbol: string;
  status: string;
  total_assets: number;
  profit: number;
  profit_rate: number;
  current_price: number;
  change_rate: number;
  position: {
    symbol: string;
    name: string;
    quantity: number;
    avg_cost: number;
    current_price: number;
    market_value: number;
    profit: number;
    profit_rate: number;
  } | null;
  total_trades: number;
  win_trades: number;
  loss_trades: number;
}

export interface SimulationSummary {
  total_assets: number;
  total_profit: number;
  profit_rate: number;
  running_count: number;
  total_count: number;
  instances: SimInstanceSummary[];
}

export interface BacktestRecentItem {
  id: string;
  strategy_name: string;
  symbol: string;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  created_at: string;
}

export interface BacktestSummary {
  total_count: number;
  avg_return: number;
  best_return: number;
  recent: BacktestRecentItem[];
}

export interface AccountCard {
  type: 'real' | 'virtual';
  name: string;
  account_id: string;
  total_assets: number;
  market_value: number;
  total_profit: number;
  total_profit_rate: number;
  daily_profit: number;
  daily_profit_rate: number;
  total_trades: number;
  daily_trades: number;
}

export interface XtquantStatus {
  available: boolean;
  connected: boolean;
  error: string;
}

export interface ServiceHealth {
  service: string;
  status: string;  // "online" | "offline" | "unknown"
  xtquant: XtquantStatus;
}

export interface ServicesStatus {
  market: ServiceHealth;
  trading: ServiceHealth;
}

export interface DashboardSummary {
  services: ServicesStatus;
  simulation: SimulationSummary;
  backtest: BacktestSummary;
  accounts: AccountCard[];
}

export const dashboardApi = {
  summary: () => api.get<DashboardSummary>('/dashboard/summary'),
  health: () => api.get<ServicesStatus>('/health'),
};
