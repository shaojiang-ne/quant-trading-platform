/**
 * 模拟交易 API
 */
import request from './request';
import type { TradingInstanceInfo, InstanceCreateRequest, AutoTradeConfig, AutoTradeConfigUpdate, SignalInfo } from './trading';

export const simulationApi = {
  list: () => request.get<TradingInstanceInfo[]>('/simulation/instances'),
  create: (data: InstanceCreateRequest) => request.post<TradingInstanceInfo>('/simulation/instances', data),
  start: (id: string) => request.post<TradingInstanceInfo>(`/simulation/instances/${id}/start`),
  stop: (id: string) => request.post<TradingInstanceInfo>(`/simulation/instances/${id}/stop`),
  delete: (id: string) => request.delete(`/simulation/instances/${id}`),
  placeOrder: (instanceId: string, params: { side: string; quantity: number; price?: number }) =>
    request.post(`/simulation/instances/${instanceId}/order`, params),

  // 自动交易配置
  getAutoTradeConfig: (instanceId: string) =>
    request.get<AutoTradeConfig>(`/simulation/instances/${instanceId}/auto-trade/config`),
  updateAutoTradeConfig: (instanceId: string, config: AutoTradeConfigUpdate) =>
    request.post<AutoTradeConfig>(`/simulation/instances/${instanceId}/auto-trade/config`, config),

  // 信号管理
  listSignals: (instanceId: string) =>
    request.get<SignalInfo[]>(`/simulation/instances/${instanceId}/signals`),
  listSignalHistory: (instanceId: string, limit?: number) =>
    request.get<SignalInfo[]>(`/simulation/instances/${instanceId}/signals/history`, limit ? { limit: String(limit) } : undefined),
  confirmSignal: (instanceId: string, signalId: string) =>
    request.post(`/simulation/instances/${instanceId}/signals/${signalId}/confirm`),
  rejectSignal: (instanceId: string, signalId: string) =>
    request.post(`/simulation/instances/${instanceId}/signals/${signalId}/reject`),
};
