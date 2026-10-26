export { api } from './client';
export { authApi } from './auth';
export { strategyApi, backtestApi } from './strategies';
export { dashboardApi } from './dashboard';
export { simulationApi } from './simulation';
export { marketApi } from './market';
export type { DataSourceInfo, KlineBar, KlineResponse, FinancialAbstractItem, FinancialIndicatorResponse, FinancialReportResponse, DividendItem } from './market';
export { researchApi } from './research';
export { streamAIChat } from './ai';
export type { AIChatMessage, AIChatRequest, StreamChunk } from './ai';
export { analyzeStock, generateStrategyFromIdea } from './ai';
export type { AnalyzeStockResult, GenerateStrategyResult } from './ai';

