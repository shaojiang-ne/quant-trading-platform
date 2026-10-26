import { researchApi } from '@/api/research';

// ── 场景定义 ──────────────────────────────────────────────────────────────
export interface Scenario {
  label: string;
  prompt: string;
  bg: string;
  textColor: string;
  requiresCode?: boolean;
  multiCode?: boolean;
  fetchData: (code: string) => Promise<{ summary: string; detail?: any }>;
}

export const quickScenarios: Scenario[] = [
  {
    label: 'AI诊股', bg: 'bg-fuchsia-50', textColor: 'text-fuchsia-700',
    prompt: '帮我全面诊断一下 688017',
    fetchData: async (code) => {
      const [tech, info, quote, fundFlow, margin, holders, reports, news, anns, lockup, industry] =
        await Promise.all([
          researchApi.technicalAnalysis(code),
          researchApi.stockInfo(code),
          researchApi.quote(code),
          researchApi.fundFlow120d(code),
          researchApi.margin(code),
          researchApi.holders(code),
          researchApi.reports(code),
          researchApi.news(code),
          researchApi.announcements(code),
          researchApi.lockup(code),
          researchApi.industry(100),
        ]);

      const q = quote[code] || {};
      const industryName = info.industry || '';
      // 东财 stock-info 的行业名可能是长名（如"计算机、通信和其他电子设备制造业"),
      // 行业排名用的是板块短名（如"电子信息"），需要模糊匹配
      const industryRank = (industry.top || []).find((r: any) =>
        r.name === industryName || industryName.includes(r.name) || r.name.includes(industryName)
      );

      // 技术分析摘要可能过长，截取前 30 行关键信息避免撞讯飞长度限制
      const techAnalysis = (tech.analysis || '技术分析数据获取失败').split('\n').slice(0, 30).join('\n');

      const lines = [
        `## AI诊股数据汇总: ${q.name || info.name || code} (${code})`,
        `当前价: ${q.price}  涨跌: ${q.change_pct}%  行业: ${industryName}${industryRank ? ` (行业排名#${industryRank.rank}, 涨${industryRank.change_pct}%)` : ''}`,
        ``,
        `### 技术面`,
        techAnalysis,
        ``,
        `### 财务面`,
        `PE(TTM): ${q.pe_ttm}  PB: ${q.pb}  总市值: ${q.mcap_yi}亿  流通市值: ${q.float_mcap_yi}亿  换手率: ${q.turnover_pct}%`,
        `总股本: ${info.total_shares}  流通股: ${info.float_shares}  上市日期: ${info.list_date}`,
        ``,
        `### 资金面`,
        `近5日主力净流入(万): ${(fundFlow.data || []).slice(-5).map((r: any) => r.main_net).join(', ')}`,
        `融资余额(亿): ${(margin.data || []).slice(0, 3).map((r: any) => `${r.date}:${r.rzye}`).join(', ') || '无数据'}`,
        `股东户数: ${(holders.data || []).slice(0, 3).map((r: any) => `${r.date}:${r.holder_num}户 变化${r.change_ratio}%`).join(', ') || '无数据'}`,
        ``,
        `### 估值面`,
        `PE(TTM): ${q.pe_ttm}  PB: ${q.pb}  量比: ${q.vol_ratio}`,
        `研报: ${(reports.data || []).slice(0, 5).map((r: any) => `${r.date} ${r.org} 评级:${r.rating || '无'}`).join('; ') || '暂无研报'}`,
        ``,
        `### 消息面`,
        `新闻: ${(news.data || []).slice(0, 3).map((n: any) => n.title).join('; ') || '暂无'}`,
        `公告: ${(anns.data || []).slice(0, 3).map((a: any) => a.title).join('; ') || '暂无'}`,
        `解禁: ${(lockup.upcoming || []).length > 0 ? lockup.upcoming.map((u: any) => `${u.date} ${u.type} ${u.shares}股 占比${u.ratio}%`).join('; ') : '近90天无限售解禁'}`,
        ``,
        `### 行业排名`,
        `所属行业: ${industryName}${industryRank ? ` (排名#${industryRank.rank}/${industry.total}, 涨${industryRank.change_pct}%, 涨:${industryRank.up_count} 跌:${industryRank.down_count}, 领涨:${industryRank.leader})` : ''}`,
        `行业TOP3: ${(industry.top || []).slice(0, 3).map((r: any) => `#${r.rank} ${r.name} 涨${r.change_pct}%`).join(', ')}`,
        ``,
        `请基于以上数据，从技术面、财务面、资金面、估值面、消息面五个维度各打1-5分，给出综合评分和操作建议。并指出风险点（风险扫雷），包括但不限于：解禁压力、大宗折价交易、股东户数激增、融资余额异常变化、负面公告等。`,
      ];

      return {
        summary: lines.join('\n'),
        detail: { tech: tech.signals, quote: q, info, industryRank },
      };
    },
  },
  {
    label: '技术分析', bg: 'bg-pink-50', textColor: 'text-pink-700',
    prompt: '帮我分析一下 688017 的技术面',
    fetchData: async (code) => {
      const d = await researchApi.technicalAnalysis(code);
      return { summary: d.analysis || '技术分析数据获取失败', detail: d.signals };
    },
  },
  {
    label: '个股估值', bg: 'bg-blue-50', textColor: 'text-blue-700',
    prompt: '帮我估一下 688017，给我 PE / PEG / 消化时间',
    fetchData: async (code) => {
      const [info, quote] = await Promise.all([researchApi.stockInfo(code), researchApi.quote(code)]);
      const q = quote[code] || {};
      return {
        summary: `股票: ${q.name || code}, 价格: ${q.price}, PE(TTM): ${q.pe_ttm}, PB: ${q.pb}, 总市值: ${q.mcap_yi}亿, 流通市值: ${q.float_mcap_yi}亿, 换手率: ${q.turnover_pct}%, 行业: ${info.industry || '未知'}`,
      };
    },
  },
  {
    label: '新闻公告', bg: 'bg-slate-100', textColor: 'text-slate-700',
    prompt: '300476 最近的新闻和公告',
    fetchData: async (code) => {
      const [news, anns] = await Promise.all([researchApi.news(code), researchApi.announcements(code)]);
      const newsItems = (news.data || []).slice(0, 5).map((n: any) => `${n.time} ${n.title}`).join('\n');
      const annItems = (anns.data || []).slice(0, 5).map((a: any) => {
        const type = a.type ?? '';
        const head = type ? `${a.date} [${type}]` : `${a.date}`;
        return `${head} ${a.title ?? ''}`;
      }).join('\n');
      return { summary: `新闻:\n${newsItems}\n公告:\n${annItems}` };
    },
  },
  {
    label: '行业轮动', bg: 'bg-indigo-50', textColor: 'text-indigo-700',
    prompt: '今天哪些行业涨幅最大，资金在流入哪些板块',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.industry();
      const top = (d.top || []).slice(0, 10).map((r: any) => `#${r.rank} ${r.name} 涨${r.change_pct}% 涨:${r.up_count} 跌:${r.down_count} 领涨:${r.leader}`).join('\n');
      return { summary: `行业涨幅TOP10:\n${top}` };
    },
  },
  {
    label: '北向资金', bg: 'bg-cyan-50', textColor: 'text-cyan-700',
    prompt: '今天北向资金流入流出怎么样',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.northbound();
      const data = d.data || [];
      const latest = data.slice(-5).map((r: any) => `${r.time} 沪股通:${r.hgt_yi}亿 深股通:${r.sgt_yi}亿`).join('\n');
      return { summary: `北向资金分钟流(最近5个点):\n${latest}` };
    },
  },
  {
    label: '题材归因', bg: 'bg-purple-50', textColor: 'text-purple-700',
    prompt: '今天哪些股票走强，主要是什么题材',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.hotStocks();
      const data = d.data || [];
      const top5 = data.slice(0, 5).map((s: any) => `${s.name}(${s.code}) 涨幅${s.change_pct}% 题材:${s.reason || '未标注'}`).join('\n');
      return { summary: `今日热门股票(${data.length}只): ${top5}` };
    },
  },
  {
    label: '研报检索', bg: 'bg-emerald-50', textColor: 'text-emerald-700',
    prompt: '688017 最近的研报有哪些',
    fetchData: async (code) => {
      const d = await researchApi.reports(code);
      const data = d.data || [];
      const top5 = data.slice(0, 5).map((r: any) => `${r.date} ${r.org}: ${r.title} 评级:${r.rating || '无'}`).join('\n');
      return { summary: `研报列表(${data.length}篇):\n${top5}` };
    },
  },
  {
    label: '概念板块', bg: 'bg-orange-50', textColor: 'text-orange-700',
    prompt: '688017 属于哪些概念板块',
    fetchData: async (code) => {
      const d = await researchApi.concepts(code);
      const boards = d.boards || [];
      const tags = boards.slice(0, 10).map((b: any) => `${b.name}(涨${b.change_pct}%)`).join(', ');
      return { summary: `共${d.total}个板块: ${tags}` };
    },
  },
  {
    label: '资金流向', bg: 'bg-red-50', textColor: 'text-red-700',
    prompt: '000858 今天主力资金流入还是流出',
    fetchData: async (code) => {
      const d = await researchApi.fundFlow(code);
      const data = d.data || [];
      const latest = data.slice(-5).map((r: any) => `${r.time} 主力:${r.main_net}万 大户:${r.large_net}万`).join('\n');
      return { summary: `分钟资金流(最近5个点):\n${latest}` };
    },
  },
  {
    label: '龙虎榜', bg: 'bg-amber-50', textColor: 'text-amber-700',
    prompt: '002475 最近上过龙虎榜吗，哪些营业部在买',
    fetchData: async (code) => {
      const d = await researchApi.dragonTiger(code);
      const records = (d.records || []).slice(0, 5).map((r: any) => `${r.date} ${r.reason} 净买入${r.net_buy}万`).join('\n');
      const buySeats = (d.seats?.buy || []).map((s: any) => `${s.name} 买${s.buy_amt}万`).join(', ');
      return { summary: `龙虎榜记录:\n${records}\n买入席位: ${buySeats || '无'}` };
    },
  },
  {
    label: '全市场龙虎榜', bg: 'bg-yellow-50', textColor: 'text-yellow-700',
    prompt: '今天龙虎榜哪些票净买入最多',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.dailyDragonTiger();
      const stocks = (d.stocks || []).slice(0, 10).map((s: any) => `${s.name}(${s.code}) 净买入${s.net_buy_wan}万 ${s.reason}`).join('\n');
      return { summary: `全市场龙虎榜(${d.total_records}只):\n${stocks}` };
    },
  },
  {
    label: '解禁预警', bg: 'bg-rose-50', textColor: 'text-rose-700',
    prompt: '688017 未来3个月有没有限售解禁',
    fetchData: async (code) => {
      const d = await researchApi.lockup(code);
      const upcoming = (d.upcoming || []).map((u: any) => `${u.date} ${u.type} ${u.shares}股 占比${u.ratio}%`).join('\n');
      return { summary: `即将解禁(${(d.upcoming||[]).length}条):\n${upcoming || '未来90天无限售解禁'}` };
    },
  },
  {
    label: '融资融券', bg: 'bg-teal-50', textColor: 'text-teal-700',
    prompt: '600519 最近的融资余额变化趋势',
    fetchData: async (code) => {
      const d = await researchApi.margin(code);
      const data = d.data || [];
      const latest = data.slice(0, 5).map((r: any) => `${r.date} 融资余额${r.rzye}亿 融券余额${r.rqye}亿`).join('\n');
      return { summary: `融资融券(最近5日):\n${latest}` };
    },
  },
  {
    label: '大宗交易', bg: 'bg-lime-50', textColor: 'text-lime-700',
    prompt: '600519 最近有没有大宗交易，溢价还是折价',
    fetchData: async (code) => {
      const d = await researchApi.blockTrade(code);
      const data = d.data || [];
      const recent = data.slice(0, 5).map((r: any) => `${r.date} 成交价${r.price} 收盘价${r.close} 溢价${r.premium_pct}% 买方:${r.buyer}`).join('\n');
      return { summary: `大宗交易(最近5笔):\n${recent || '暂无大宗交易记录'}` };
    },
  },
  {
    label: '股东户数', bg: 'bg-sky-50', textColor: 'text-sky-700',
    prompt: '000858 股东户数在增加还是减少，筹码集中吗',
    fetchData: async (code) => {
      const d = await researchApi.holders(code);
      const data = d.data || [];
      const recent = data.slice(0, 5).map((r: any) => `${r.date} 户数${r.holder_num} 变化${r.change_ratio}% 人均${r.avg_shares}股`).join('\n');
      return { summary: `股东户数:\n${recent}` };
    },
  },
  {
    label: '分红送转', bg: 'bg-green-50', textColor: 'text-green-700',
    prompt: '600519 历年分红派息多少',
    fetchData: async (code) => {
      const d = await researchApi.dividend(code);
      const data = d.data || [];
      const recent = data.slice(0, 10).map((r: any) => {
        const parts = [`${r.date} 每10股派${r.bonus_rmb}元`];
        if (r.bonus_ratio) parts.push(`送${r.bonus_ratio}`);
        if (r.transfer_ratio) parts.push(`转${r.transfer_ratio}`);
        parts.push(r.plan);
        return parts.join(' ');
      }).join('\n');
      return { summary: `分红送转:\n${recent}` };
    },
  },
  {
    label: '批量对比', bg: 'bg-violet-50', textColor: 'text-violet-700',
    prompt: '帮我对比 688981,688396,300666 这几只半导体股的估值',
    multiCode: true,
    fetchData: async (code) => {
      const codes = code || '688981,688396,300666';
      const d = await researchApi.quote(codes);
      const rows = Object.entries(d).map(([c, q]: [string, any]) =>
        `${q.name || c}: PE=${q.pe_ttm}, PB=${q.pb}, 市值=${q.mcap_yi}亿, 涨${q.change_pct}%`
      ).join('\n');
      return { summary: `估值对比:\n${rows}` };
    },
  },
];

// ── 空态场景网格 ────────────────────────────────────────────────────────────
interface ScenarioGridProps {
  onSelect: (scenario: Scenario) => void;
}

export function ScenarioGrid({ onSelect }: ScenarioGridProps) {
  return (
    <div className="grid grid-cols-4 gap-2.5 px-4">
      {quickScenarios.map((s) => (
        <button
          key={s.label}
          onClick={() => onSelect(s)}
          className={`flex items-center justify-center p-3 rounded-2xl ${s.bg} active:scale-95 transition-transform`}
        >
          <span className={`text-xs font-semibold leading-tight ${s.textColor}`}>{s.label}</span>
        </button>
      ))}
    </div>
  );
}

// ── 聊天态场景 pill 栏 ─────────────────────────────────────────────────────
interface ScenarioPillsProps {
  scenarios: Scenario[];
  selectedLabel: string | null;
  onSelect: (scenario: Scenario) => void;
}

export function ScenarioPills({ scenarios, selectedLabel, onSelect }: ScenarioPillsProps) {
  return (
    <div className="flex gap-2 px-4 py-2 overflow-x-auto scrollbar-hide bg-white border-t border-gray-50">
      {scenarios.map((s) => (
        <button
          key={s.label}
          onClick={() => onSelect(s)}
          className={`px-3 py-1.5 text-[11px] font-medium rounded-full whitespace-nowrap active:scale-95 transition-transform ${
            selectedLabel === s.label
              ? 'bg-primary-600 text-white shadow-sm'
              : `${s.bg} ${s.textColor}`
          }`}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
