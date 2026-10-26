import { api } from './client';

// ── 数据源信息 ──────────────────────────────────────────────────────────────

export interface DataSourceInfo {
  name: string;
  available: boolean;
  description: string;
  priority_min: number | null;
  priority_daily: number | null;
}

// ── K线数据 ────────────────────────────────────────────────────────────────

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  source: string;
  klines: KlineBar[];
  count: number;
}

// ── 基本面数据 ──────────────────────────────────────────────────────────────

export interface FinancialAbstractItem {
  date?: string;
  net_profit?: string;
  net_profit_yoy?: string;
  deducted_net_profit?: string;
  deducted_net_profit_yoy?: string;
  total_revenue?: string;
  total_revenue_yoy?: string;
  basic_eps?: string;
  bps?: string;
  capital_reserve_per_share?: string;
  undistributed_profit_per_share?: string;
  ocf_per_share?: string;
  net_margin?: string;
  gross_margin?: string;
  roe?: string;
  roe_diluted?: string;
  operating_cycle?: string;
  inventory_turnover?: string;
  inventory_days?: string;
  ar_days?: string;
  current_ratio?: string;
  quick_ratio?: string;
  conservative_quick_ratio?: string;
  equity_ratio?: string;
  debt_ratio?: string;
  [key: string]: string | undefined;
}

export interface FinancialIndicatorResponse {
  symbol: string;
  data: Record<string, string | number>[];
  columns: string[];
}

export interface FinancialReportResponse {
  symbol: string;
  data: Record<string, string | number>[];
  columns: string[];
}

export interface DividendItem {
  announce_date?: string;
  dividend_type?: string;
  bonus_share_ratio?: string | number;
  conversion_ratio?: string | number;
  cash_dividend_ratio?: string | number;
  record_date?: string;
  ex_dividend_date?: string;
  payment_date?: string;
  share_arrival_date?: string;
  description?: string;
  report_period?: string;
  [key: string]: string | number | undefined;
}

// ── API ────────────────────────────────────────────────────────────────────

export const marketApi = {
  getDataSources: () => api.get<DataSourceInfo[]>('/market/data-sources'),

  getKlines: (params: {
    symbol: string;
    period: string;
    start_time: string;
    end_time: string;
    source?: string;
    dividend_type?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set('symbol', params.symbol);
    qs.set('period', params.period);
    if (params.start_time) qs.set('start_time', params.start_time);
    if (params.end_time) qs.set('end_time', params.end_time);
    if (params.source) qs.set('source', params.source);
    if (params.dividend_type) qs.set('dividend_type', params.dividend_type);
    return api.get<KlineResponse>(`/market/data-sources/klines?${qs.toString()}`);
  },

  // 基本面数据
  getFinancialAbstract: (symbol: string) =>
    api.get<{ symbol: string; data: FinancialAbstractItem[] }>(`/market/financial/abstract?symbol=${symbol}`),

  getFinancialIndicators: (symbol: string, startYear: string = '2023') =>
    api.get<FinancialIndicatorResponse>(`/market/financial/indicators?symbol=${symbol}&start_year=${startYear}`),

  getIncomeStatement: (symbol: string) =>
    api.get<FinancialReportResponse>(`/market/financial/income?symbol=${symbol}`),

  getBalanceSheet: (symbol: string) =>
    api.get<FinancialReportResponse>(`/market/financial/balance?symbol=${symbol}`),

  getCashflowStatement: (symbol: string) =>
    api.get<FinancialReportResponse>(`/market/financial/cashflow?symbol=${symbol}`),

  getDividendHistory: (symbol: string) =>
    api.get<{ symbol: string; data: DividendItem[] }>(`/market/financial/dividend?symbol=${symbol}`),
};
