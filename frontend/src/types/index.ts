// 用户相关类型
export interface User {
  id: string;
  username: string;
  email: string;
  password?: string;
  avatar?: string;
  createdAt: string;
}

// 账户相关类型
export interface Account {
  id: string;
  name: string;
  type: 'real' | 'virtual';
  broker?: string;
  balance: number;
  available: number;
  frozen: number;
  marketValue: number;
  profit: number;
  profitRate: number;
  commissionRate: number; // 交易佣金比例 (如 0.0003 = 万3)
  stampTaxRate: number;   // 印花税比例 (如 0.001 = 千1)
  createdAt: string;
  status: 'active' | 'inactive' | 'suspended';
}

export interface Position {
  id: string;
  accountId: string;
  symbol: string;
  name: string;
  quantity: number;
  avgCost: number;
  currentPrice: number;
  marketValue: number;
  profit: number;
  profitRate: number;
  updateTime: string;
}

export interface Order {
  id: string;
  accountId: string;
  symbol: string;
  name: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit' | 'stop';
  quantity: number;
  price?: number;
  status: 'pending' | 'filled' | 'partial' | 'cancelled' | 'rejected';
  filledQuantity: number;
  filledPrice?: number;
  createdAt: string;
  updatedAt: string;
}

// 策略相关类型
export interface Strategy {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  code: string;
  algorithm: string;
  advantages: string[];
  disadvantages: string[];
  params: StrategyParam[];
  backtestCount: number;
  avgReturn: number;
  createdAt: string;
  author: string;
}

export interface StrategyParam {
  name: string;
  key: string;
  type: 'number' | 'string' | 'boolean' | 'select';
  default: any;
  min?: number;
  max?: number;
  options?: { label: string; value: any }[];
  description: string;
}

export interface StrategyTemplate {
  id: string;
  name: string;
  description: string;
  template: string;
  explanation: string[];
}

// 回测相关类型
export interface BacktestConfig {
  strategyId: string;
  accountId: string;
  symbol: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  params: Record<string, any>;
}

export interface BacktestResult {
  id: string;
  config: BacktestConfig;
  status: 'running' | 'completed' | 'failed';
  progress: number;
  metrics: BacktestMetrics;
  trades: TradeRecord[];
  equityCurve: EquityPoint[];
  createdAt: string;
  completedAt?: string;
}

export interface BacktestMetrics {
  totalReturn: number;
  annualizedReturn: number;
  maxDrawdown: number;
  sharpeRatio: number;
  sortinoRatio: number;
  winRate: number;
  profitFactor: number;
  totalTrades: number;
  avgTradeReturn: number;
  volatility: number;
  beta: number;
  alpha: number;
}

export interface TradeRecord {
  id: string;
  timestamp: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  commission: number;
  pnl?: number;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
}

// 市场数据类型
export interface StockQuote {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  turnover: number;
  high: number;
  low: number;
  open: number;
  preClose: number;
  timestamp: string;
}

export interface KlineData {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// 用户设置
export interface UserSettings {
  theme: 'light' | 'dark';
  language: 'zh' | 'en';
  defaultAccountId?: string;
  notifications: boolean;
  riskWarning: boolean;
}

// 模拟交易实例
export interface SimulationInstance {
  id: string;
  name: string;
  symbol: string;           // 交易标的
  strategyId: string;       // 策略ID
  accountId: string;        // 账户ID
  params: Record<string, any>;  // 策略参数
  status: 'running' | 'stopped' | 'paused';
  createdAt: string;
  updatedAt: string;
  // 运行统计
  totalTrades: number;
  winTrades: number;
  lossTrades: number;
  totalProfit: number;
  currentEquity: number;
  maxDrawdown: number;
  // 持仓
  position: {
    quantity: number;
    avgCost: number;
    marketValue: number;
  };
  // 交易记录
  trades: SimulationTrade[];
}

export interface SimulationTrade {
  id: string;
  instanceId: string;
  timestamp: string;
  side: 'buy' | 'sell';
  symbol: string;
  quantity: number;
  price: number;
  commission: number;
  stampTax: number;
  pnl?: number;
  signal: string;  // 交易信号说明
}
