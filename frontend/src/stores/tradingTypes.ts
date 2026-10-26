export interface StrategyLogEntry {
  time: string;
  side: string;
  message: string;
  price: number;
  quantity: number;
  pnl: number;
}

export interface RealtimeTrade {
  instance_id: string;
  side: string;
  price: number;
  quantity: number;
  pnl: number;
  time: string;
}

export interface RealtimeTick {
  symbol: string;
  last_price: number;
  open_price: number;
  high_price: number;
  low_price: number;
  pre_close: number;
  volume: number;
  amount: number;
  bid_price_1: number;
  bid_volume_1: number;
  ask_price_1: number;
  ask_volume_1: number;
  datetime: string;
}

export interface AccountPosition {
  symbol: string;
  name: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  profit: number;
  profit_rate: number;
}

export interface AccountUpdate {
  balance: number;
  available: number;
  market_value: number;
  total_assets: number;
  profit: number;
  profit_rate: number;
  positions: AccountPosition[];
  current_price?: number;
  change_rate?: number;
}

/** Max log entries per instance to prevent memory overflow */
export const MAX_STRATEGY_LOGS = 500;
/** Max realtime trades per instance */
export const MAX_REALTIME_TRADES = 200;
