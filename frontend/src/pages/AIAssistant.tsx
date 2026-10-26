import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Bot,
  Send,
  Trash2,
  User,
  TrendingUp,
  BarChart3,
  FileSearch,
  ArrowLeftRight,
  Layers,
  Wallet,
  ScrollText,
  ShieldAlert,
  RefreshCw,
  Landmark,
  Banknote,
  Users,
  Coins,
  Newspaper,
  Scale,
  Loader2,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Database,
  Activity,
  Stethoscope,
} from 'lucide-react';
import { useResearchChatStore, FREE_KEY } from '@/stores/researchChatStore';
import type { DataStep } from '@/stores/researchChatStore';
import { researchApi } from '@/api/research';
import { useStockCacheStore } from '@/stores';

// ── 快捷场景定义 ────────────────────────────────────────────────────────────
interface Scenario {
  icon: any;
  label: string;
  prompt: string;
  color: string;
  // 根据用户输入的实际内容获取数据，code 从 prompt 中提取
  fetchData: (code: string) => Promise<{ summary: string; detail?: any }>;
  // 是否需要股票代码：个股类场景为 true（默认），市场类场景（题材归因/北向资金/全市场龙虎榜/行业轮动）为 false
  requiresCode?: boolean;
  // 是否多代码场景：批量对比为 true，resolveCode 默认只取首个代码，多代码需走 resolveCodes 取全部
  multiCode?: boolean;
}

// 从文本解析股票代码：先提 6 位数字代码，提不到则用全量股票名做反向匹配（取最长命中）
async function resolveCode(text: string): Promise<string> {
  const m = text.match(/\d{6}/);
  if (m) return m[0];

  const store = useStockCacheStore.getState();
  if (!store.loaded) {
    await store.fetchAll(); // 幂等；失败则 stocks 为空，下方自然无命中
  }
  const lower = text.toLowerCase();
  let best: { code: string; name: string } | undefined;
  for (const s of useStockCacheStore.getState().stocks) {
    if (!s.name) continue;
    if (lower.includes(s.name.toLowerCase())) {
      if (!best || s.name.length > best.name.length) best = { code: s.code, name: s.name };
    }
  }
  return best?.code ?? '';
}

// 从文本解析全部 6 位代码（批量对比场景）：去重保序，逗号连接
function resolveCodes(text: string): string {
  const matches = text.match(/\d{6}/g) || [];
  const seen = new Set<string>();
  const uniq: string[] = [];
  for (const c of matches) {
    if (!seen.has(c)) { seen.add(c); uniq.push(c); }
  }
  return uniq.join(',');
}

const quickScenarios: Scenario[] = [
  {
    icon: Stethoscope, label: 'AI诊股', color: 'bg-fuchsia-50 text-fuchsia-600 border-fuchsia-200',
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
    icon: Activity, label: '技术分析', color: 'bg-pink-50 text-pink-600 border-pink-200',
    prompt: '帮我分析一下 688017 的技术面',
    fetchData: async (code) => {
      const d = await researchApi.technicalAnalysis(code);
      return { summary: d.analysis || '技术分析数据获取失败', detail: d.signals };
    },
  },
  {
    icon: TrendingUp, label: '个股估值', color: 'bg-blue-50 text-blue-600 border-blue-200',
    prompt: '帮我估一下 688017，给我 PE / PEG / 消化时间',
    fetchData: async (code) => {
      const [info, quote] = await Promise.all([
        researchApi.stockInfo(code),
        researchApi.quote(code),
      ]);
      const q = quote[code] || {};
      return {
        summary: `股票: ${q.name || code}, 价格: ${q.price}, PE(TTM): ${q.pe_ttm}, PB: ${q.pb}, 总市值: ${q.mcap_yi}亿, 流通市值: ${q.float_mcap_yi}亿, 换手率: ${q.turnover_pct}%, 行业: ${info.industry || '未知'}`,
      };
    },
  },
  {
    icon: Newspaper, label: '新闻公告', color: 'bg-slate-50 text-slate-600 border-slate-200',
    prompt: '300476 最近的新闻和公告',
    fetchData: async (code) => {
      const [news, anns] = await Promise.all([
        researchApi.news(code),
        researchApi.announcements(code),
      ]);
      const newsItems = (news.data || []).slice(0, 5).map((n: any) => `${n.time} ${n.title}`).join('\n');
      const annItems = (anns.data || []).slice(0, 5).map((a: any) => {
        const type = a.type ?? '';
        // type 为空（巨潮多数公告 announcementTypeName 为 null）时省略 [type]，避免 [null]/[]
        const head = type ? `${a.date} [${type}]` : `${a.date}`;
        return `${head} ${a.title ?? ''}`;
      }).join('\n');
      return { summary: `新闻:\n${newsItems}\n公告:\n${annItems}` };
    },
  },
  {
    icon: RefreshCw, label: '行业轮动', color: 'bg-indigo-50 text-indigo-600 border-indigo-200',
    prompt: '今天哪些行业涨幅最大，资金在流入哪些板块',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.industry();
      const top = (d.top || []).slice(0, 10).map((r: any) => `#${r.rank} ${r.name} 涨${r.change_pct}% 涨:${r.up_count} 跌:${r.down_count} 领涨:${r.leader}`).join('\n');
      return { summary: `行业涨幅TOP10:\n${top}` };
    },
  },
  {
    icon: ArrowLeftRight, label: '北向资金', color: 'bg-cyan-50 text-cyan-600 border-cyan-200',
    prompt: '今天北向资金流入流出怎么样',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.northbound();
      const data = d.data || [];
      // 深股通（sgt）接口只覆盖开盘前段约35个点（约09:10~09:45），其余位置接口补 null，
      // 后端已兜底成 0.0 并用 sgt_valid 标记；这里把无效点显成"—"避免 LLM 误读为"净流出0"
      // 也避免喂"接口未返回"这种内部标记让模型把它当分析对象来解释
      const validSgt = data.filter((r: any) => r.sgt_valid).length;
      const fmt = (r: any) => {
        const sgt = r.sgt_valid ? `${r.sgt_yi}` : '—';
        return `${r.time} 沪股通:${r.hgt_yi}亿 深股通:${sgt}`;
      };
      const latest = data.slice(-5).map(fmt).join('\n');
      const note = validSgt < data.length
        ? `\n（说明：深股通仅当日开盘前段 ${validSgt} 个点有效，— 表示该点接口未提供数据）`
        : '';
      return { summary: `北向资金分钟流(最近5个点):\n${latest}${note}` };
    },
  },
  {
    icon: Layers, label: '题材归因', color: 'bg-purple-50 text-purple-600 border-purple-200',
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
    icon: FileSearch, label: '研报检索', color: 'bg-emerald-50 text-emerald-600 border-emerald-200',
    prompt: '688017 最近的研报有哪些',
    fetchData: async (code) => {
      const d = await researchApi.reports(code);
      const data = d.data || [];
      const top5 = data.slice(0, 5).map((r: any) => `${r.date} ${r.org}: ${r.title} 评级:${r.rating || '无'}`).join('\n');
      return { summary: `研报列表(${data.length}篇):\n${top5}` };
    },
  },
  {
    icon: BarChart3, label: '概念板块', color: 'bg-orange-50 text-orange-600 border-orange-200',
    prompt: '688017 属于哪些概念板块',
    fetchData: async (code) => {
      const d = await researchApi.concepts(code);
      const boards = d.boards || [];
      const tags = boards.slice(0, 10).map((b: any) => `${b.name}(涨${b.change_pct}%)`).join(', ');
      return { summary: `共${d.total}个板块: ${tags}` };
    },
  },
  {
    icon: Wallet, label: '资金流向', color: 'bg-red-50 text-red-600 border-red-200',
    prompt: '000858 今天主力资金流入还是流出',
    fetchData: async (code) => {
      const d = await researchApi.fundFlow(code);
      const data = d.data || [];
      const latest = data.slice(-5).map((r: any) => `${r.time} 主力:${r.main_net}万 大户:${r.large_net}万`).join('\n');
      return { summary: `分钟资金流(最近5个点):\n${latest}` };
    },
  },
  {
    icon: ScrollText, label: '龙虎榜', color: 'bg-amber-50 text-amber-600 border-amber-200',
    prompt: '002475 最近上过龙虎榜吗，哪些营业部在买',
    fetchData: async (code) => {
      const d = await researchApi.dragonTiger(code);
      if (d.message) {
        return { summary: d.message };
      }
      const records = (d.records || []).slice(0, 5).map((r: any) => `${r.date} ${r.reason} 净买入${r.net_buy}万`).join('\n');
      const buySeats = (d.seats?.buy || []).map((s: any) => `${s.name} 买${s.buy_amt}万`).join(', ');
      return { summary: `龙虎榜记录:\n${records}\n买入席位: ${buySeats || '无'}` };
    },
  },
  {
    icon: ScrollText, label: '全市场龙虎榜', color: 'bg-yellow-50 text-yellow-700 border-yellow-200',
    prompt: '今天龙虎榜哪些票净买入最多',
    requiresCode: false,
    fetchData: async () => {
      const d = await researchApi.dailyDragonTiger();
      if (d.total_records === 0 && d.note) {
        return { summary: d.note };
      }
      const stocks = (d.stocks || []).slice(0, 10).map((s: any) => `${s.name}(${s.code}) 净买入${s.net_buy_wan}万 ${s.reason}`).join('\n');
      return { summary: `全市场龙虎榜(${d.total_records}只, ${d.date}):\n${stocks}` };
    },
  },
  {
    icon: ShieldAlert, label: '解禁预警', color: 'bg-rose-50 text-rose-600 border-rose-200',
    prompt: '688017 未来3个月有没有限售解禁',
    fetchData: async (code) => {
      const d = await researchApi.lockup(code);
      const upcoming = (d.upcoming || []).map((u: any) => `${u.date} ${u.type} ${u.shares}股 占比${u.ratio}%`).join('\n');
      return { summary: `即将解禁(${(d.upcoming||[]).length}条):\n${upcoming || '未来90天无限售解禁'}` };
    },
  },
  {
    icon: Landmark, label: '融资融券', color: 'bg-teal-50 text-teal-600 border-teal-200',
    prompt: '600519 最近的融资余额变化趋势',
    fetchData: async (code) => {
      const d = await researchApi.margin(code);
      const data = d.data || [];
      const latest = data.slice(0, 5).map((r: any) => `${r.date} 融资余额${r.rzye}亿 融券余额${r.rqye}亿`).join('\n');
      return { summary: `融资融券(最近5日):\n${latest}` };
    },
  },
  {
    icon: Banknote, label: '大宗交易', color: 'bg-lime-50 text-lime-600 border-lime-200',
    prompt: '600519 最近有没有大宗交易，溢价还是折价',
    fetchData: async (code) => {
      const d = await researchApi.blockTrade(code);
      const data = d.data || [];
      const recent = data.slice(0, 5).map((r: any) => `${r.date} 成交价${r.price} 收盘价${r.close} 溢价${r.premium_pct}% 买方:${r.buyer}`).join('\n');
      return { summary: `大宗交易(最近5笔):\n${recent || '暂无大宗交易记录'}` };
    },
  },
  {
    icon: Users, label: '股东户数', color: 'bg-sky-50 text-sky-600 border-sky-200',
    prompt: '000858 股东户数在增加还是减少，筹码集中吗',
    fetchData: async (code) => {
      const d = await researchApi.holders(code);
      const data = d.data || [];
      const recent = data.slice(0, 5).map((r: any) => `${r.date} 户数${r.holder_num} 变化${r.change_ratio}% 人均${r.avg_shares}股`).join('\n');
      return { summary: `股东户数:\n${recent}` };
    },
  },
  {
    icon: Coins, label: '分红送转', color: 'bg-green-50 text-green-600 border-green-200',
    prompt: '600519 历年分红派息多少',
    fetchData: async (code) => {
      const d = await researchApi.dividend(code);
      const data = d.data || [];
      const recent = data.slice(0, 10).map((r: any) => {
        // 纯现金分红时送/转为 0，省略对应片段，避免「送0转0」冗余
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
    icon: Scale, label: '批量对比', color: 'bg-violet-50 text-violet-600 border-violet-200',
    prompt: '帮我对比 688981,688396,300666 这几只半导体股的估值',
    multiCode: true,
    fetchData: async (code) => {
      // 批量对比：从输入提取多个代码，或用单个代码查同类
      const codes = code || '688981,688396,300666';
      const d = await researchApi.quote(codes);
      const rows = Object.entries(d).map(([c, q]: [string, any]) =>
        `${q.name || c}: PE=${q.pe_ttm}, PB=${q.pb}, 市值=${q.mcap_yi}亿, 涨${q.change_pct}%`
      ).join('\n');
      return { summary: `估值对比:\n${rows}` };
    },
  },
];

// ── 数据获取步骤卡片 ────────────────────────────────────────────────────────
function DataStepCard({ step }: { step: DataStep }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-lg border text-sm ${
      step.status === 'loading' ? 'bg-blue-50 border-blue-200' :
      step.status === 'done'    ? 'bg-green-50 border-green-200' :
                                   'bg-red-50 border-red-200'
    }`}>
      {/* 标题行 */}
      <button
        onClick={() => step.status !== 'loading' && setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {step.status === 'loading' && (
          <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
        )}
        {step.status === 'done' && (
          <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
        )}
        {step.status === 'error' && (
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
        )}
        <Database className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        <span className="font-medium text-gray-700">{step.label}</span>
        {step.status === 'loading' && (
          <span className="text-blue-500 text-xs">正在获取数据…</span>
        )}
        {step.status === 'done' && (
          <span className="text-green-600 text-xs">数据获取完成</span>
        )}
        {step.status === 'error' && (
          <span className="text-red-500 text-xs">获取失败</span>
        )}
        {step.status !== 'loading' && (
          expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-auto" />
            : <ChevronRight className="w-3.5 h-3.5 text-gray-400 ml-auto" />
        )}
      </button>

      {/* 展开内容 */}
      {expanded && step.status !== 'loading' && (
        <div className="px-3 pb-2 border-t border-inherit">
          {step.status === 'done' && step.summary && (
            <pre className="mt-2 text-xs text-gray-600 whitespace-pre-wrap break-words font-mono leading-relaxed max-h-48 overflow-y-auto">
              {step.summary}
            </pre>
          )}
          {step.status === 'error' && (
            <p className="mt-2 text-xs text-red-600">{step.error || '未知错误'}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Markdown 渲染 ──────────────────────────────────────────────────────────
function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-2 prose-table:text-xs">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 代码块样式
          code({ className, children, ...props }) {
            const isBlock = className?.startsWith('language-');
            if (isBlock) {
              return (
                <code className="text-gray-200" {...props}>
                  {children}
                </code>
              );
            }
            // 行内代码
            return (
              <code className="px-1 py-0.5 bg-gray-100 text-primary-700 rounded text-xs font-mono" {...props}>
                {children}
              </code>
            );
          },
          pre({ children }) {
            return (
              <pre className="p-3 bg-gray-900 rounded-lg overflow-x-auto max-h-96 leading-relaxed">
                {children}
              </pre>
            );
          },
          // 表格样式
          table({ children }) {
            return (
              <div className="overflow-x-auto my-2">
                <table className="min-w-full border border-gray-200 text-xs">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="px-2 py-1 bg-gray-50 border border-gray-200 text-left font-medium text-gray-700">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="px-2 py-1 border border-gray-200 text-gray-600">
                {children}
              </td>
            );
          },
          // 外部链接新标签页打开
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary-600 underline">
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ── 主页面 ──────────────────────────────────────────────────────────────────
export function AIAssistant() {
  const [input, setInput] = useState('');
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const {
    messagesByScenario, activeScenario,
    isLoading, error,
    sendMessage, sendMessageWithData,
    addMessage, updateMessage, clearMessages,
    setActiveScenario,
  } = useResearchChatStore();
  // 当前 active 桶的消息（按场景隔离）
  const messages = messagesByScenario[activeScenario ?? FREE_KEY] ?? [];

  // 只滚 AIAssistant 内部消息容器，避免 scrollIntoView 联动滚动外层 Layout/window
  useEffect(() => {
    const c = messagesContainerRef.current;
    if (c) c.scrollTop = c.scrollHeight;
  }, [messages]);

  // 预加载全量股票列表，供中文名→代码解析（resolveCode）使用
  useEffect(() => {
    useStockCacheStore.getState().fetchAll();
  }, []);

  // 点击场景按钮：切换到该场景的对话桶 + 填入 prompt 到输入框
  // 若该桶已有历史则一并显示，方便用户继续追问；无历史则空 + prompt 引导
  const handleSelectScenario = (scenario: Scenario) => {
    setSelectedScenario(scenario);
    setInput(scenario.prompt);
    setActiveScenario(scenario.label);
  };

  // 发送消息：判断是否追问（该桶已有 user 消息则视为追问，不取数不注入数据）
  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const content = input.trim();
    setInput('');

    // 确定目标桶 key 并切换
    const matchedScenario = selectedScenario;
    const targetLabel = matchedScenario?.label ?? FREE_KEY;
    if (activeScenario !== targetLabel) {
      setActiveScenario(targetLabel);
    }

    // 实时读 store 判断是否追问（已有 user 消息 → 追问，不再取数/注入）
    const targetMsgs =
      useResearchChatStore.getState().messagesByScenario[targetLabel] ?? [];
    const isFollowUp = targetMsgs.some(
      (m) => m.role === 'user' && !m.isStreaming && m.content,
    );

    setSelectedScenario(null);

    // 追问 或 无场景：直接 sendMessage（不带数据，纯历史 + 当前 user）
    if (isFollowUp || !matchedScenario?.fetchData) {
      addMessage({ role: 'user', content, type: 'text' });
      await sendMessage(content);
      return;
    }

    // 首次 + 有场景：取数 + 注入数据
    const needsCode = matchedScenario.requiresCode !== false;
    const code = needsCode
      ? (matchedScenario.multiCode ? resolveCodes(content) : await resolveCode(content))
      : '';

    // 1. 插入用户原始消息（不含数据拼接）
    addMessage({ role: 'user', content, type: 'text' });

    // 2. 插入数据获取步骤消息（loading 状态）
    const stepMsgId = addMessage({
      role: 'system',
      content: '',
      type: 'data-step',
      dataStep: { label: matchedScenario.label, status: 'loading' },
    });

    // 个股类场景未识别到代码/名称：标错并 fallback 让 LLM 回答
    if (needsCode && !code) {
      updateMessage(stepMsgId, {
        dataStep: {
          label: matchedScenario.label,
          status: 'error',
          error: '未识别到股票代码或名称，请输入 6 位代码（如 688017）或完整股票名称（如 盐湖股份）',
        },
      });
      await sendMessage(content);
      return;
    }

    try {
      // 3. 获取数据
      const { summary } = await matchedScenario.fetchData(code);

      // 4. 更新步骤消息为完成状态
      updateMessage(stepMsgId, {
        dataStep: { label: matchedScenario.label, status: 'done', summary },
      });

      // 5. 发给 LLM：用户原始问题 + system 注入数据（isFollowUp=false）
      await sendMessageWithData(content, summary, matchedScenario.label, false);
    } catch (e: any) {
      // 数据获取失败，更新步骤消息为错误状态
      updateMessage(stepMsgId, {
        dataStep: {
          label: matchedScenario.label,
          status: 'error',
          error: e.message || '未知错误' },
      });
      // fallback：不带数据发送原始消息
      await sendMessage(content);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 是否有任何数据步骤正在加载
  const dataLoading = messages.some(
    (m) => m.role === 'system' && m.type === 'data-step' && m.dataStep?.status === 'loading'
  );

  return (
    <div className="flex flex-col h-full">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-primary-600" />
          <h1 className="text-2xl font-bold text-gray-900">AI分析</h1>
        </div>
        <button onClick={() => { clearMessages(); setSelectedScenario(null); }}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
          <Trash2 className="w-4 h-4" />
          清空对话
        </button>
      </div>

      {/* 聊天区域 */}
      <div className="flex-1 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
        {/* 消息列表 */}
        <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center py-8">
              <Bot className="w-14 h-14 mx-auto text-gray-300 mb-4" />
              <p className="text-gray-500 mb-2 text-lg font-medium">你的 A 股研究助手</p>
              <p className="text-gray-400 text-sm mb-6">选择场景，输入股票代码或问题，发送后自动获取真实数据</p>
              <div className="grid grid-cols-4 gap-2.5 max-w-3xl mx-auto">
                {quickScenarios.map((s) => (
                  <button key={s.label}
                    onClick={() => handleSelectScenario(s)}
                    className={`flex items-center gap-2 p-2.5 text-sm border rounded-lg transition hover:shadow-sm text-left ${s.color}`}
                  >
                    <s.icon className="w-4 h-4 flex-shrink-0" />
                    <span className="font-medium">{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => {
              // 数据获取步骤卡片
              if (msg.role === 'system' && msg.type === 'data-step' && msg.dataStep) {
                return <DataStepCard key={msg.id} step={msg.dataStep} />;
              }

              // 普通消息
              return (
                <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                    msg.role === 'user' ? 'bg-primary-100 text-primary-600' : 'bg-gray-100 text-gray-600'
                  }`}>
                    {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                  </div>
                  <div className={`flex-1 min-w-0 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                    {msg.role === 'user' ? (
                      <div className="inline-block max-w-[80%] px-4 py-2.5 rounded-lg text-sm bg-primary-600 text-white">
                        <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                      </div>
                    ) : (
                      <div className="max-w-full text-sm text-gray-800 leading-relaxed">
                        {msg.content ? <MarkdownContent content={msg.content} /> : null}
                        {msg.isStreaming && (
                          <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse ml-1" />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="px-4 py-2 bg-red-50 text-red-600 text-sm border-t border-red-100">
            {error}
          </div>
        )}

        {/* 快捷场景（有消息时显示精简版） */}
        {messages.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-100 bg-gray-50">
            <div className="flex flex-wrap gap-1.5">
              {quickScenarios.map((s) => (
                <button key={s.label}
                  onClick={() => handleSelectScenario(s)}
                  className={`flex items-center gap-1 px-2.5 py-1 text-xs border rounded-full transition hover:shadow-sm ${s.color} ${
                    selectedScenario?.label === s.label ? 'ring-2 ring-primary-400' : ''
                  }`}
                >
                  <s.icon className="w-3 h-3" />
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 输入框 */}
        <div className="p-3 border-t border-gray-200">
          {/* 当前选中场景提示 */}
          {selectedScenario && (
            <div className="flex items-center gap-2 mb-2 px-1">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full border ${selectedScenario.color}`}>
                <selectedScenario.icon className="w-3 h-3" />
                {selectedScenario.label}
              </span>
              <span className="text-xs text-gray-400">— 发送时将自动获取相关数据</span>
            </div>
          )}
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={selectedScenario ? (
                selectedScenario.requiresCode === false
                  ? `已选择「${selectedScenario.label}」，可直接发送获取全市场数据`
                  : `已选择「${selectedScenario.label}」，可修改股票代码后发送`
              ) : "输入你的问题，如「帮我估一下 688017」..."}
              rows={2}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
              disabled={isLoading || dataLoading}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading || dataLoading}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition self-end flex items-center gap-1.5"
            >
              {isLoading || dataLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
