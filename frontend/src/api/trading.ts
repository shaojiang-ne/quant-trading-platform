/**
 * 交易相关 API
 */
import request from './request';

// ─── 实盘交易类型（对齐 stock-trade-api.md） ───

/** 账户资金 — GET /api/v1/asset */
export interface LiveAccount {
  account_id: string;
  total_assets: number;
  cash: number;
  available: number;
  market_value: number;
  frozen: number;
}

/** 持仓 — GET /api/v1/positions */
export interface LivePosition {
  symbol: string;
  name: string;
  quantity: number;
  available: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  profit: number;
  profit_rate: number;
  daily_profit?: number;
}

/** 委托 — GET /api/v1/orders */
export interface LiveOrder {
  order_id: string;
  symbol: string;
  name: string;
  side: string;
  quantity: number;
  price: number;
  filled_quantity: number;
  filled_price: number;
  status: string;
  order_type: string;
  create_time: string;
  update_time: string;
}

/** 成交 — GET /api/v1/trades */
export interface LiveTrade {
  trade_id: string;
  order_id: string;
  symbol: string;
  name?: string;
  side: string;
  price: number;
  quantity: number;
  time: string;
}

/** 下单参数 — POST /api/v1/orders */
export interface PlaceOrderParams {
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price?: number;
  order_type?: 'limit' | 'market';
}

/** 网关状态 */
export interface GatewayStatus {
  connected: boolean;
  broker: string;
  display_name: string;
  account_id: string;
}

/** 连接结果 */
export interface ConnectResult {
  success: boolean;
  message: string;
  account_id?: string;
  broker?: string;
  display_name?: string;
}

/** 券商信息 */
export interface BrokerInfo {
  name: string;
  display_name: string;
  available: boolean;
  category?: string;
}

// ─── 模拟交易类型 ───

export interface SimulationOrder {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  filled_quantity: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TradeOrderResponse {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  filled_quantity: number;
  status: string;
  created_at: string;
  updated_at: string;
  strategy_id?: string;
  strategy_name?: string;
}

// ─── 自动交易（对齐后端 AutoTradeConfig DB 模型） ───

export interface AutoTradeConfig {
  id: string;
  user_id: string;
  account_id: string;
  auto_trade_enabled: boolean;
  confirm_required: boolean;
  max_order_amount: number;
  max_position_ratio: number;
  daily_loss_limit: number;
  created_at: string;
  updated_at: string;
}

export interface AutoTradeConfigUpdate {
  auto_trade_enabled?: boolean;
  confirm_required?: boolean;
  max_order_amount?: number;
  max_position_ratio?: number;
  daily_loss_limit?: number;
}

// ─── 信号 ───

export interface SignalInfo {
  id: string;
  user_id: string;
  instance_id: string;
  account_id: string;
  symbol: string;
  name: string;
  side: string;
  price: number;
  quantity: number;
  status: string;
  strategy_id: string;
  reason?: string;
  created_at: string;
  updated_at: string;
}

// ─── 策略实例管理 ───

export interface TradingInstanceInfo {
  id: string;
  name: string;
  symbol: string;
  strategy_id: string;
  strategy_name?: string;
  account_id: string;
  params: Record<string, unknown>;
  mode: string;
  status: string;
  total_trades: number;
  win_trades: number;
  loss_trades: number;
  total_profit: number;
  current_equity: number;
  max_drawdown: number;
  position: unknown;
  trades: unknown[];
  current_price: number;
  change_rate: number;
  auto_trade_enabled: boolean;
  confirm_required: boolean;
  created_at: string;
  updated_at: string;
}

export type TradingInstanceResponse = TradingInstanceInfo;
export type InstanceCreateRequest = Partial<TradingInstanceInfo> & {
  initial_equity?: number;
  auto_trade_enabled?: boolean | null;
  confirm_required?: boolean | null;
};

// ─── 实盘交易 API ───

/** 连接交易网关 */
export async function connectGateway(broker: string = 'qmt', xtpParams?: Record<string, string>): Promise<ConnectResult> {
  const body: Record<string, string> = { broker };
  if (xtpParams) {
    Object.assign(body, xtpParams);
  }
  return request.post<ConnectResult>('/trading/gateway/connect', body);
}

/** 断开交易网关 */
export async function disconnectGateway(): Promise<void> {
  return request.post('/trading/gateway/disconnect');
}

/** 获取网关状态 */
export async function getGatewayStatus(): Promise<GatewayStatus> {
  return request.get<GatewayStatus>('/trading/gateway/status');
}

/** 获取可用券商列表 */
export async function fetchBrokers(): Promise<BrokerInfo[]> {
  return request.get<BrokerInfo[]>('/trading/brokers');
}

/** 获取账户资金 */
export async function getAccount(): Promise<LiveAccount> {
  return request.get<LiveAccount>('/trading/account');
}

/** 获取持仓 */
export async function getPositions(): Promise<LivePosition[]> {
  return request.get<LivePosition[]>('/trading/positions');
}

/** 获取委托 */
export async function getOrders(): Promise<LiveOrder[]> {
  return request.get<LiveOrder[]>('/trading/orders');
}

/** 获取成交 */
export async function getTrades(): Promise<LiveTrade[]> {
  return request.get<LiveTrade[]>('/trading/trades');
}

/** 下单 */
export async function placeOrder(params: PlaceOrderParams): Promise<LiveOrder> {
  return request.post<LiveOrder>('/trading/order', params);
}

/** 撤单 */
export async function cancelOrder(orderId: string): Promise<void> {
  return request.delete(`/trading/order/${orderId}`);
}

/** 获取实时行情 */
export async function getQuote(symbol: string): Promise<Record<string, unknown>> {
  return request.get('/trading/quote', { symbol });
}

/** 获取自动交易配置 */
export async function getAutoTradeConfig(): Promise<AutoTradeConfig> {
  return request.get<AutoTradeConfig>('/trading/auto-trade/config');
}

/** 更新自动交易配置 */
export async function updateAutoTradeConfig(config: Partial<AutoTradeConfig>): Promise<AutoTradeConfig> {
  return request.post<AutoTradeConfig>('/trading/auto-trade/config', config);
}

/** 获取待确认信号 */
export async function listSignals(): Promise<SignalInfo[]> {
  return request.get<SignalInfo[]>('/trading/signals');
}

/** 获取信号历史（所有状态） */
export async function listSignalHistory(instanceId?: string, limit?: number): Promise<SignalInfo[]> {
  const params: Record<string, string> = {};
  if (instanceId) params.instance_id = instanceId;
  if (limit) params.limit = String(limit);
  return request.get<SignalInfo[]>('/trading/signals/history', params);
}

/** 获取实盘实例日志 */
export async function getInstanceLogs(instanceId: string): Promise<{ instance_id: string; logs: any[] }> {
  return request.get(`/trading/instances/${instanceId}/logs`);
}

/** 确认信号（下单） */
export async function confirmSignal(id: string): Promise<SignalInfo> {
  return request.post<SignalInfo>(`/trading/signals/${id}/confirm`);
}

/** 拒绝信号 */
export async function rejectSignal(id: string): Promise<SignalInfo> {
  return request.post<SignalInfo>(`/trading/signals/${id}/reject`);
}

/** 手动同步 */
export async function syncTradingData(): Promise<void> {
  return request.post('/trading/sync');
}

// ─── 模拟交易 API ───

/** 获取模拟交易历史 */
export async function getOrderHistory(params: {
  strategy_id?: string;
  start_date?: string;
  end_date?: string;
}): Promise<TradeOrderResponse[]> {
  const p: Record<string, string> = {};
  if (params.strategy_id) p.strategy_id = params.strategy_id;
  if (params.start_date) p.start_date = params.start_date;
  if (params.end_date) p.end_date = params.end_date;
  return request.get<TradeOrderResponse[]>('/trading/order-history', p);
}

// ─── 策略实例 API ───

export async function listInstances(): Promise<TradingInstanceInfo[]> {
  return request.get<TradingInstanceInfo[]>('/trading/instances');
}

export async function createInstance(data: InstanceCreateRequest): Promise<TradingInstanceResponse> {
  return request.post<TradingInstanceResponse>('/trading/instances', data);
}

export async function startInstance(id: string): Promise<TradingInstanceInfo> {
  return request.post<TradingInstanceInfo>(`/trading/instances/${id}/start`);
}

export async function stopInstance(id: string): Promise<TradingInstanceInfo> {
  return request.post<TradingInstanceInfo>(`/trading/instances/${id}/stop`);
}

export async function deleteInstance(id: string): Promise<void> {
  return request.delete(`/trading/instances/${id}`);
}

export async function updateInstance(id: string, data: { name?: string; params?: Record<string, any> }): Promise<TradingInstanceResponse> {
  return request.put<TradingInstanceResponse>(`/trading/instances/${id}`, data);
}
