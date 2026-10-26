import { api } from './client';

// ── 研究数据 API ────────────────────────────────────────────────────────────

export const researchApi = {
  // 腾讯实时行情
  quote: (codes: string) => api.get<Record<string, any>>(`/research/quote?codes=${codes}`),

  // 概念板块归属
  concepts: (code: string) => api.get<Record<string, any>>(`/research/concepts?code=${code}`),

  // 分钟资金流
  fundFlow: (code: string) => api.get<Record<string, any>>(`/research/fund-flow?code=${code}`),

  // 120日资金流
  fundFlow120d: (code: string) => api.get<Record<string, any>>(`/research/fund-flow-120d?code=${code}`),

  // 个股龙虎榜
  dragonTiger: (code: string, date?: string) => {
    const d = date || new Date().toISOString().slice(0, 10);
    return api.get<Record<string, any>>(`/research/dragon-tiger?code=${code}&date=${d}`);
  },

  // 全市场龙虎榜
  dailyDragonTiger: (date?: string) => {
    const d = date || new Date().toISOString().slice(0, 10);
    return api.get<Record<string, any>>(`/research/daily-dragon-tiger?date=${d}`);
  },

  // 限售解禁
  lockup: (code: string, date?: string) => {
    const d = date || new Date().toISOString().slice(0, 10);
    return api.get<Record<string, any>>(`/research/lockup?code=${code}&date=${d}`);
  },

  // 行业排名
  industry: (topN: number = 20) => api.get<Record<string, any>>(`/research/industry?top_n=${topN}`),

  // 融资融券
  margin: (code: string) => api.get<Record<string, any>>(`/research/margin?code=${code}`),

  // 大宗交易
  blockTrade: (code: string) => api.get<Record<string, any>>(`/research/block-trade?code=${code}`),

  // 股东户数
  holders: (code: string) => api.get<Record<string, any>>(`/research/holders?code=${code}`),

  // 分红送转
  dividend: (code: string) => api.get<Record<string, any>>(`/research/dividend?code=${code}`),

  // 个股新闻
  news: (code: string) => api.get<Record<string, any>>(`/research/news?code=${code}`),

  // 基本信息
  stockInfo: (code: string) => api.get<Record<string, any>>(`/research/stock-info?code=${code}`),

  // 研报
  reports: (code: string) => api.get<Record<string, any>>(`/research/reports?code=${code}`),

  // 公告
  announcements: (code: string) => api.get<Record<string, any>>(`/research/announcements?code=${code}`),

  // 热门题材归因
  hotStocks: (date?: string) => {
    const d = date || new Date().toISOString().slice(0, 10);
    return api.get<Record<string, any>>(`/research/hot-stocks?date=${d}`);
  },

  // 北向资金
  northbound: () => api.get<Record<string, any>>('/research/northbound'),

  // 技术分析
  technicalAnalysis: (code: string) => api.get<Record<string, any>>(`/research/technical-analysis?code=${code}`),
};
