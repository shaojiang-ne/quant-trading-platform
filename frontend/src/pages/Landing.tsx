import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  TrendingUp,
  Activity,
  FlaskConical,
  BarChart3,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  CheckCircle2,
  Bot,
  User,
  Send,
  Loader2,
  Play,
  Zap,
  Search,
  BrainCircuit,
  Database,
  FileCode2,
  LineChart,
  Bell,
  AlertTriangle,
  Radio,
  Clock,
  Cpu,
  Terminal,
  ShieldCheck,
  Crosshair,
} from 'lucide-react';
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  ComposedChart,
} from 'recharts';
import { useAuthStore } from '@/stores';

// ── 终端色板（与 index.css 变量一致） ──────────────────────────────────────
// amber #ffab2e = 品牌/数据主色；红 #f04e45 涨 / 绿 #10b981 跌，仅用于行情语义
const AMBER = '#ffab2e';
const UP = '#f04e45';
const DOWN = '#10b981';

// ── 示意回测数据 ──────────────────────────────────────────────────────────
const backtestData = [
  { date: '01', strategy: 100, benchmark: 100 },
  { date: '02', strategy: 103, benchmark: 101 },
  { date: '03', strategy: 101, benchmark: 99 },
  { date: '04', strategy: 107, benchmark: 102 },
  { date: '05', strategy: 112, benchmark: 103 },
  { date: '06', strategy: 109, benchmark: 101 },
  { date: '07', strategy: 115, benchmark: 104 },
  { date: '08', strategy: 121, benchmark: 106 },
  { date: '09', strategy: 118, benchmark: 105 },
  { date: '10', strategy: 126, benchmark: 108 },
  { date: '11', strategy: 132, benchmark: 110 },
  { date: '12', strategy: 138, benchmark: 112 },
];

const heroMockChartData = [
  { date: '09:30', val: 100 },
  { date: '10:00', val: 102 },
  { date: '10:30', val: 101 },
  { date: '11:00', val: 106 },
  { date: '11:30', val: 105 },
  { date: '13:00', val: 110 },
  { date: '13:30', val: 109 },
  { date: '14:00', val: 115 },
  { date: '14:30', val: 113 },
  { date: '15:00', val: 121 },
];

// ── 行情跑马灯数据（演示） ─────────────────────────────────────────────────
const tickerItems = [
  { name: '上证指数', code: 'SH000001', price: '3,247.85', chg: 0.72 },
  { name: '深证成指', code: 'SZ399001', price: '10,584.32', chg: 1.15 },
  { name: '创业板指', code: 'SZ399006', price: '2,168.40', chg: -0.38 },
  { name: '沪深300', code: 'SH000300', price: '3,912.56', chg: 0.54 },
  { name: '科创50', code: 'SH000688', price: '986.12', chg: 1.87 },
  { name: '贵州茅台', code: '600519', price: '1,688.00', chg: 1.24 },
  { name: '宁德时代', code: '300750', price: '187.45', chg: -0.86 },
  { name: '比亚迪', code: '002594', price: '245.30', chg: 2.03 },
  { name: '中芯国际', code: '688981', price: '48.72', chg: 3.15 },
  { name: '东方财富', code: '300059', price: '13.58', chg: -0.22 },
  { name: '招商银行', code: '600036', price: '34.21', chg: 0.61 },
  { name: '隆基绿能', code: '601012', price: '18.92', chg: -1.05 },
];

// ── FAQ 数据 ──────────────────────────────────────────────────────────────
const faqs = [
  {
    q: '是否需要编程基础？',
    a: '不需要，全程自然语言交互。你只需用日常语言描述你的交易想法，AI会帮你完成从策略编写到回测执行的全过程。',
  },
  {
    q: '支持哪些市场？',
    a: '目前支持A股全市场覆盖，包括主板、创业板、科创板和北交所。',
  },
  {
    q: 'AI选股的准确率如何？',
    a: 'AI选股是辅助决策工具，结合多种因子模型和技术指标进行综合评分。建议结合自身判断使用，不构成投资建议。',
  },
  {
    q: '策略回测的数据来源？',
    a: '基于历史真实行情数据，包含日K、分钟K等多周期数据，确保回测结果的可靠性。',
  },
  {
    q: '是否支持实盘交易？',
    a: '支持模拟交易和实盘对接。建议先在模拟环境验证策略，再进行实盘操作。',
  },
];

// ── 选股演示数据 ──────────────────────────────────────────────────────────
const pickDemoSteps = [
  { role: 'user' as const, text: '帮我找一下最近北向资金持续流入、技术面突破、基本面稳健的消费股' },
  { role: 'ai' as const, text: '收到！正在分析北向资金流向、技术形态和基本面数据...' },
  { role: 'ai' as const, text: '已扫描全市场5000+标的，筛选出符合条件的3只优质股票' },
];

const pickDemoStocks = [
  { name: '贵州茅台', code: '600519', score: 92, tags: ['北向流入', '突破新高', 'ROE>25%'], trend: 'up' as const },
  { name: '五粮液', code: '000858', score: 88, tags: ['外资增持', '均线多头排列', '现金流充裕'], trend: 'up' as const },
  { name: '海天味业', code: '603288', score: 85, tags: ['机构调研', '量价齐升', '护城河深'], trend: 'up' as const },
];

// 确定性的模拟K线高度，避免每次渲染抖动
const pickBarHeights = [35, 48, 42, 60, 52, 68, 58, 74, 66, 82, 78, 92];

// ── 回测演示策略代码 ──────────────────────────────────────────────────────
const demoStrategyCode = [
  '# 双均线策略',
  'def strategy(context):',
  '    # 获取历史数据',
  '    prices = get_history(20)',
  '    ',
  '    # 计算均线',
  '    ma5 = prices.rolling(5).mean()',
  '    ma20 = prices.rolling(20).mean()',
  '    ',
  '    # 交易信号',
  '    if ma5[-1] > ma20[-1] and ma5[-2] <= ma20[-2]:',
  '        buy(context.symbol, 100)',
  '    elif ma5[-1] < ma20[-1] and ma5[-2] >= ma20[-2]:',
  '        sell(context.symbol, 100)',
];

// ── 锚点滚动辅助 ──────────────────────────────────────────────────────────
function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
}

// ── 滚动显现 ──────────────────────────────────────────────────────────────
function useReveal() {
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            (e.target as HTMLElement).classList.add('ql-visible');
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.1 }
    );
    document.querySelectorAll('.ql-reveal').forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

// ── 进入视口自动播放演示 ──────────────────────────────────────────────────
function useAutoPlay(ref: React.RefObject<HTMLElement | null>, play: () => void) {
  const playRef = useRef(play);
  playRef.current = play;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) playRef.current();
      },
      { threshold: 0.35 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
}

// ── 图表 Tooltip 通用样式 ─────────────────────────────────────────────────
const darkTooltipStyle = {
  backgroundColor: '#12151b',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '2px',
  color: '#e9e7e2',
  fontSize: '12px',
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
};

// ── 代码行着色（终端语法高亮：关键字琥珀 / 买红 / 卖绿） ────────────────────
function codeLineClass(line: string): string {
  if (!line.trim()) return 'h-4';
  if (line.trimStart().startsWith('#')) return 'text-[#4a4f58] italic';
  if (line.includes('buy')) return 'text-[#f04e45] font-medium';
  if (line.includes('sell')) return 'text-[#10b981] font-medium';
  if (line.includes('def ') || line.includes('if ') || line.includes('elif ')) return 'text-[#ffab2e]';
  if (line.includes('=')) return 'text-[#e9e7e2]';
  return 'text-[#b9bec6]';
}

// ═══════════════════════════════════════════════════════════════════════════
//  行情跑马灯
// ═══════════════════════════════════════════════════════════════════════════
function TickerTape() {
  const row = (key: string) => (
    <div key={key} className="flex shrink-0 items-center">
      {tickerItems.map((t) => (
        <div
          key={`${key}-${t.code}`}
          className="ql-mono flex items-center gap-2.5 px-6 py-2.5 text-[11px] border-r border-white/[0.07]"
        >
          <span className="text-[#8f959e] font-medium">{t.name}</span>
          <span className="text-[#555c66] text-[10px]">{t.code}</span>
          <span className="text-[#e9e7e2] font-semibold">{t.price}</span>
          <span
            className={`flex items-center gap-0.5 font-bold ${
              t.chg >= 0 ? 'text-[#f04e45]' : 'text-[#10b981]'
            }`}
          >
            {t.chg >= 0 ? (
              <ArrowUpRight className="w-3 h-3" />
            ) : (
              <ArrowDownRight className="w-3 h-3" />
            )}
            {t.chg >= 0 ? '+' : ''}
            {t.chg.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );

  return (
    <div className="relative w-full overflow-hidden border-y border-white/[0.08] bg-[#050608]">
      <div className="ql-marquee-track">
        {row('a')}
        {row('b')}
      </div>
      {/* 两侧渐隐 */}
      <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-[#050608] to-transparent pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-[#050608] to-transparent pointer-events-none" />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  分区标题
// ═══════════════════════════════════════════════════════════════════════════
function SectionHeading({
  index,
  kicker,
  title,
  desc,
}: {
  index: string;
  kicker: string;
  title: React.ReactNode;
  desc?: string;
}) {
  return (
    <div className="text-center mb-16 ql-reveal">
      <div className="ql-mono inline-flex items-center gap-3 text-[11px] tracking-[0.3em] text-[#ffab2e] mb-5">
        <span className="h-px w-8 bg-[#ffab2e]/40" />
        {index} / {kicker}
        <span className="h-px w-8 bg-[#ffab2e]/40" />
      </div>
      <h2 className="text-3xl md:text-5xl font-black text-[#e9e7e2] mb-5 tracking-tight leading-tight">
        {title}
      </h2>
      {desc && <p className="text-[#8f959e] text-base md:text-lg max-w-2xl mx-auto">{desc}</p>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  导航栏
// ═══════════════════════════════════════════════════════════════════════════
function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 border-b ${
        scrolled
          ? 'bg-[#07080a]/85 border-white/[0.08] backdrop-blur-xl shadow-[0_4px_24px_rgba(0,0,0,0.5)]'
          : 'bg-transparent border-transparent'
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div
          className="flex items-center gap-3 cursor-pointer group"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        >
          <div className="w-8 h-8 flex items-center justify-center bg-[#ffab2e]">
            <TrendingUp className="w-4 h-4 text-black" strokeWidth={2.5} />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-[15px] font-bold text-[#e9e7e2] tracking-tight">量化交易平台</span>
            <span className="ql-mono text-[9px] tracking-[0.25em] text-[#555c66] mt-0.5 group-hover:text-[#ffab2e] transition-colors">
              QUANT TERMINAL
            </span>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-7">
          {[
            { label: '功能', id: 'features' },
            { label: 'AI选股', id: 'demo-pick' },
            { label: 'AI盯盘', id: 'demo-monitor' },
            { label: '策略回测', id: 'demo-backtest' },
            { label: 'FAQ', id: 'faq' },
          ].map((l) => (
            <button
              key={l.id}
              onClick={() => scrollTo(l.id)}
              className="ql-mono text-xs tracking-wider text-[#8f959e] hover:text-[#ffab2e] transition-colors"
            >
              {l.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <button
              onClick={() => navigate('/app')}
              className="ql-btn-glow ql-mono px-5 py-2 text-xs font-bold tracking-wider text-black bg-[#ffab2e] hover:bg-[#ffbb4d]"
            >
              进入工作台 →
            </button>
          ) : (
            <>
              <button
                onClick={() => navigate('/login')}
                className="ql-mono text-xs tracking-wider text-[#8f959e] hover:text-[#e9e7e2] transition-colors px-2"
              >
                登录
              </button>
              <button
                onClick={() => navigate('/login')}
                className="ql-btn-glow ql-mono px-5 py-2 text-xs font-bold tracking-wider text-black bg-[#ffab2e] hover:bg-[#ffbb4d]"
              >
                免费注册
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  Hero 区域 — 黑底 + 琥珀终端看板
// ═══════════════════════════════════════════════════════════════════════════
function HeroSection() {
  const navigate = useNavigate();

  return (
    <section className="relative min-h-screen pt-16 flex flex-col overflow-hidden">
      {/* 背景层 */}
      <div className="absolute inset-0 ql-grid-bg" />
      <div className="absolute -top-32 left-1/4 w-[560px] h-[560px] bg-[#ffab2e]/[0.05] rounded-full blur-[160px]" />

      {/* 背景发光走势线 */}
      <svg
        className="absolute bottom-0 left-0 w-full h-[46%] pointer-events-none"
        viewBox="0 0 1440 420"
        preserveAspectRatio="none"
        fill="none"
      >
        <defs>
          <linearGradient id="heroArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffab2e" stopOpacity="0.1" />
            <stop offset="100%" stopColor="#ffab2e" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d="M0,360 L80,345 L160,352 L240,318 L320,328 L400,290 L480,300 L560,262 L640,275 L720,228 L800,240 L880,196 L960,210 L1040,168 L1120,180 L1200,138 L1280,150 L1360,108 L1440,92 L1440,420 L0,420 Z"
          fill="url(#heroArea)"
        />
        <path
          className="ql-draw-line"
          d="M0,360 L80,345 L160,352 L240,318 L320,328 L400,290 L480,300 L560,262 L640,275 L720,228 L800,240 L880,196 L960,210 L1040,168 L1120,180 L1200,138 L1280,150 L1360,108 L1440,92"
          stroke="#ffab2e"
          strokeWidth="1.5"
          style={{ filter: 'drop-shadow(0 0 6px rgba(255,171,46,0.4))' }}
        />
        <circle cx="1440" cy="92" r="4" fill="#ffab2e" style={{ filter: 'drop-shadow(0 0 8px rgba(255,171,46,0.6))' }} />
      </svg>

      {/* 终端状态条 */}
      <div className="relative z-10 hidden md:block border-b border-white/[0.06]">
        <div className="max-w-7xl mx-auto px-6 py-2 flex items-center justify-between ql-mono text-[10px] tracking-[0.2em] text-[#555c66]">
          <span className="flex items-center gap-2">
            <span className="ql-amber-dot w-1.5 h-1.5 rounded-full bg-[#ffab2e]" />
            TERMINAL v2.4.1 · SESSION 2026-07-20
          </span>
          <span className="hidden lg:inline">SSE/SZSE CONNECTED · FEED 12ms · ALL SYSTEMS NOMINAL</span>
        </div>
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 w-full flex-1 flex flex-col justify-center py-16">
        <div className="grid lg:grid-cols-12 gap-14 items-center">
          {/* 左侧文字 */}
          <div className="lg:col-span-5 text-left">
            <div className="ql-mono inline-flex items-center gap-2.5 px-3.5 py-1.5 border border-[#ffab2e]/30 bg-[#ffab2e]/[0.06] text-[11px] tracking-[0.2em] text-[#ffab2e] mb-8 ql-reveal">
              <span className="ql-live-dot w-1.5 h-1.5 rounded-full bg-emerald-500" />
              AI-DRIVEN QUANT TERMINAL
            </div>

            <h1 className="text-4xl md:text-5xl lg:text-[3.6rem] font-black text-[#e9e7e2] leading-[1.15] tracking-tight ql-reveal" style={{ transitionDelay: '80ms' }}>
              让 AI 成为你的
              <br />
              <span className="text-[#ffab2e]">量化交易引擎</span>
            </h1>

            <p className="mt-7 text-[#8f959e] text-base md:text-lg leading-relaxed ql-reveal" style={{ transitionDelay: '160ms' }}>
              无需编写复杂代码。使用最直观的自然语言，即可完成策略构建、因子扫描、智能盯盘与历史回测。
            </p>

            <div className="ql-mono mt-6 flex items-center gap-2 text-xs text-[#8f959e] ql-reveal" style={{ transitionDelay: '220ms' }}>
              <span className="text-[#ffab2e]">$</span>
              <span>init --strategy "自然语言" --market A股 --mode auto</span>
              <span className="ql-caret inline-block w-2 h-3.5 bg-[#ffab2e]" />
            </div>

            <div className="mt-9 flex flex-col sm:flex-row items-stretch sm:items-center gap-4 ql-reveal" style={{ transitionDelay: '280ms' }}>
              <button
                onClick={() => navigate('/login')}
                className="ql-btn-glow group ql-mono px-8 py-4 bg-[#ffab2e] text-black text-sm font-bold tracking-wider hover:bg-[#ffbb4d] flex items-center justify-center gap-2"
              >
                立即体验
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </button>
              <button
                onClick={() => scrollTo('demo-pick')}
                className="ql-mono px-8 py-4 border border-white/15 bg-white/[0.02] text-[#c8cdd4] text-sm font-bold tracking-wider hover:border-[#ffab2e]/60 hover:text-[#ffab2e] transition-colors flex items-center justify-center gap-2"
              >
                <Play className="w-4 h-4" />
                观看演示
              </button>
            </div>

            {/* 数据指标条 */}
            <div className="mt-12 grid grid-cols-2 sm:grid-cols-4 gap-px bg-white/[0.08] border border-white/[0.08] ql-reveal" style={{ transitionDelay: '360ms' }}>
              {[
                { v: '5000+', k: '覆盖标的' },
                { v: '12ms', k: '信号延迟' },
                { v: '20年', k: '历史数据' },
                { v: '99.95%', k: '系统可用性' },
              ].map((s) => (
                <div key={s.k} className="bg-[#0a0c10] px-4 py-4">
                  <div className="ql-mono text-xl font-bold text-[#e9e7e2]">{s.v}</div>
                  <div className="text-[11px] text-[#8f959e] mt-1">{s.k}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 右侧：终端看板 */}
          <div className="lg:col-span-7 relative ql-reveal" style={{ transitionDelay: '200ms' }}>
            <div className="ql-terminal relative max-w-2xl mx-auto shadow-[0_24px_70px_rgba(0,0,0,0.6)]">
              {/* 终端头部 */}
              <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.08] bg-white/[0.02]">
                <div className="flex items-center gap-3">
                  <div className="flex gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#f04e45]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ffab2e]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#10b981]/80" />
                  </div>
                  <span className="ql-mono text-[11px] text-[#555c66]">quant@terminal: ~/dashboard</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="ql-mono flex items-center gap-1.5 text-[10px] text-emerald-400">
                    <span className="ql-live-dot w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    LIVE
                  </span>
                  <span className="ql-mono text-[10px] text-[#555c66]">2026-07-20 11:00</span>
                </div>
              </div>

              <div className="p-5">
                {/* 指标卡 */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="p-3.5 border border-white/[0.08] bg-white/[0.02]">
                    <div className="text-[10px] text-[#8f959e] mb-1.5">总资产估值</div>
                    <div className="ql-mono text-sm font-bold text-[#e9e7e2]">¥1,238,590.20</div>
                    <div className="ql-mono text-[10px] font-bold text-[#f04e45] mt-1">+¥42,190 今日</div>
                  </div>
                  <div className="p-3.5 border border-white/[0.08] bg-white/[0.02]">
                    <div className="text-[10px] text-[#8f959e] mb-1.5">持仓盈亏比</div>
                    <div className="ql-mono text-sm font-bold text-[#f04e45]">+18.42%</div>
                    <div className="text-[10px] text-[#8f959e] mt-1">跑赢沪深300</div>
                  </div>
                  <div className="p-3.5 border border-white/[0.08] bg-white/[0.02]">
                    <div className="text-[10px] text-[#8f959e] mb-1.5">运行中策略</div>
                    <div className="ql-mono text-sm font-bold text-[#e9e7e2]">4 <span className="text-[#555c66] font-normal">active</span></div>
                    <div className="ql-mono text-[10px] text-[#ffab2e] mt-1 flex items-center gap-1">
                      <Cpu className="w-3 h-3" /> AI 盯盘中
                    </div>
                  </div>
                </div>

                {/* 走势图 */}
                <div className="border border-white/[0.08] bg-white/[0.02] p-4 mb-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="ql-mono text-[11px] tracking-wider text-[#8f959e]">EQUITY CURVE · 近30交易日</span>
                    <span className="ql-mono text-[11px] font-bold text-[#f04e45] flex items-center gap-0.5">
                      <ArrowUpRight className="w-3.5 h-3.5" /> +21.4%
                    </span>
                  </div>
                  <div className="h-32">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={heroMockChartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                        <defs>
                          <linearGradient id="heroGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ffab2e" stopOpacity={0.28} />
                            <stop offset="95%" stopColor="#ffab2e" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <Area
                          type="monotone"
                          dataKey="val"
                          stroke="#ffab2e"
                          strokeWidth={2}
                          fill="url(#heroGrad)"
                          isAnimationActive={false}
                          style={{ filter: 'drop-shadow(0 0 6px rgba(255,171,46,0.4))' }}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* 实时日志流 */}
                <div className="border border-white/[0.08] bg-[#050608] p-4">
                  <div className="ql-mono text-[10px] tracking-wider text-[#555c66] mb-2.5 flex items-center gap-2">
                    <Terminal className="w-3 h-3" /> LIVE SELECTION STREAM
                  </div>
                  <div className="ql-mono text-[11px] leading-relaxed space-y-1.5">
                    <div className="flex items-center justify-between text-[#8f959e]">
                      <span>[09:30:01] model init · factor engine v2.4</span>
                      <span className="text-emerald-400">READY</span>
                    </div>
                    <div className="text-[#c8cdd4]">&gt; 帮我找一下最近北向资金持续流入的消费股</div>
                    <div className="text-[#8f959e]">&gt; 扫描沪深主板 · ROE &gt; 15% · 外资净流入 &gt; 5000万</div>
                    <div className="text-[#ffab2e]">&gt; 命中：贵州茅台 (score 92) · 五粮液 (score 88)</div>
                  </div>
                </div>
              </div>
            </div>

            {/* 浮动徽章（上方留空区 + 右下骑角，不遮挡看板内容） */}
            <div className="ql-float hidden lg:flex absolute -top-12 left-4 z-10 ql-terminal px-4 py-3 items-center gap-3 shadow-[0_12px_40px_rgba(0,0,0,0.6)]">
              <Crosshair className="w-4 h-4 text-[#ffab2e]" />
              <div>
                <div className="ql-mono text-xs font-bold text-[#e9e7e2]">信号触发</div>
                <div className="ql-mono text-[10px] text-[#f04e45]">BUY · 600519 @ 1688.00</div>
              </div>
            </div>
            <div className="ql-float hidden lg:flex absolute -bottom-6 right-4 z-10 ql-terminal px-4 py-3 items-center gap-3 shadow-[0_12px_40px_rgba(0,0,0,0.6)]" style={{ animationDelay: '2s' }}>
              <ShieldCheck className="w-4 h-4 text-[#ffab2e]" />
              <div>
                <div className="ql-mono text-xs font-bold text-[#e9e7e2]">风控通过</div>
                <div className="ql-mono text-[10px] text-[#8f959e]">回撤阈值 8.5%</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Hero 底部跑马灯 */}
      <div className="relative z-10">
        <TickerTape />
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  核心功能展示 — 终端面板 Grid
// ═══════════════════════════════════════════════════════════════════════════
function FeaturesSection() {
  return (
    <section id="features" className="py-28 relative border-t border-white/[0.07]">
      <div className="relative max-w-7xl mx-auto px-6">
        <SectionHeading
          index="01"
          kicker="CORE FEATURES"
          title={
            <>
              量化交易，<span className="text-[#ffab2e]">从未如此简单</span>
            </>
          }
          desc="智能引擎覆盖数据筛选、动态监控、策略生成及历史验证"
        />

        <div className="grid grid-cols-1 md:grid-cols-6 gap-5">
          {/* Card 1: AI选股 */}
          <div className="ql-reveal md:col-span-3 ql-panel p-8 group hover:border-[#ffab2e]/40 hover:shadow-[0_16px_48px_rgba(0,0,0,0.5)] transition-all duration-300 flex flex-col justify-between min-h-[340px]">
            <div>
              <div className="flex items-start justify-between mb-7">
                <div className="w-11 h-11 flex items-center justify-center border border-[#ffab2e]/25 bg-[#ffab2e]/[0.06]">
                  <Search className="w-5 h-5 text-[#ffab2e]" />
                </div>
                <span className="ql-mono text-[10px] tracking-[0.3em] text-[#3a3f47] group-hover:text-[#ffab2e]/50 transition-colors">F.01</span>
              </div>
              <h3 className="text-xl font-bold text-[#e9e7e2] mb-3">AI 自然语言选股</h3>
              <p className="text-[#8f959e] text-sm leading-relaxed">
                无需编写复杂的数据库查询指令。直接用口语表达选股想法，AI 实时转换并获取最新的财务、资金及技术形态因子。
              </p>
            </div>
            <div className="mt-7 pt-5 border-t border-white/[0.07]">
              <div className="ql-mono text-[10px] tracking-[0.25em] text-[#555c66] mb-2">PROMPT 范例</div>
              <div className="ql-mono p-3 bg-[#050608] border border-white/[0.08] text-xs text-[#ffab2e]/90 leading-relaxed">
                "连续5日主力净流入 · 换手率3%~5% · 突破半年线的成长股"
              </div>
            </div>
          </div>

          {/* Card 2: AI盯盘 */}
          <div className="ql-reveal md:col-span-3 ql-panel p-8 group hover:border-[#ffab2e]/40 hover:shadow-[0_16px_48px_rgba(0,0,0,0.5)] transition-all duration-300 flex flex-col justify-between min-h-[340px]" style={{ transitionDelay: '100ms' }}>
            <div>
              <div className="flex items-start justify-between mb-7">
                <div className="w-11 h-11 flex items-center justify-center border border-[#ffab2e]/25 bg-[#ffab2e]/[0.06]">
                  <Activity className="w-5 h-5 text-[#ffab2e]" />
                </div>
                <span className="ql-mono text-[10px] tracking-[0.3em] text-[#3a3f47] group-hover:text-[#ffab2e]/50 transition-colors">F.02</span>
              </div>
              <h3 className="text-xl font-bold text-[#e9e7e2] mb-3">24 小时实时智能盯盘</h3>
              <p className="text-[#8f959e] text-sm leading-relaxed">
                盯盘策略解析、实时量价异常检测、自定义异动监控推送。多标的实时并行监控，帮您捕捉日内的最佳买卖窗口。
              </p>
            </div>
            <div className="mt-7 flex flex-wrap items-center gap-2.5">
              {['金叉突破', '成交量翻倍', '异动实时推送'].map((t) => (
                <span key={t} className="ql-mono text-[10px] tracking-wider px-2.5 py-1 border border-[#ffab2e]/25 text-[#ffab2e] bg-[#ffab2e]/[0.05]">
                  {t}
                </span>
              ))}
              <span className="ql-mono text-[10px] tracking-wider px-2.5 py-1 border border-emerald-500/30 text-emerald-400 bg-emerald-500/[0.06] flex items-center gap-1.5">
                <span className="ql-live-dot w-1.5 h-1.5 rounded-full bg-emerald-500" />
                MONITORING
              </span>
            </div>
          </div>

          {/* Card 3: 策略生成 */}
          <div className="ql-reveal md:col-span-2 ql-panel p-8 group hover:border-[#ffab2e]/40 hover:shadow-[0_16px_48px_rgba(0,0,0,0.5)] transition-all duration-300 flex flex-col justify-between min-h-[340px]" style={{ transitionDelay: '160ms' }}>
            <div>
              <div className="flex items-start justify-between mb-7">
                <div className="w-11 h-11 flex items-center justify-center border border-[#ffab2e]/25 bg-[#ffab2e]/[0.06]">
                  <FlaskConical className="w-5 h-5 text-[#ffab2e]" />
                </div>
                <span className="ql-mono text-[10px] tracking-[0.3em] text-[#3a3f47] group-hover:text-[#ffab2e]/50 transition-colors">F.03</span>
              </div>
              <h3 className="text-lg font-bold text-[#e9e7e2] mb-3">自然语言编写量化策略</h3>
              <p className="text-[#8f959e] text-sm leading-relaxed">
                描述你的交易逻辑，AI 自动理解并转成专业的 Python 策略脚本，省去繁琐的数据清洗与条件配置。
              </p>
            </div>
            <div className="mt-7 ql-mono text-[10px] p-3.5 bg-[#050608] border border-white/[0.08] leading-relaxed">
              <span className="text-[#ffab2e]">def</span> <span className="text-[#e9e7e2]">strategy</span><span className="text-[#8f959e]">(context):</span>
              <br />
              <span className="text-[#8f959e]">&nbsp;&nbsp;prices = get_history(20)</span>
              <br />
              <span className="text-[#4a4f58]">&nbsp;&nbsp;# 均线信号判定...</span>
            </div>
          </div>

          {/* Card 4: 策略回测 */}
          <div className="ql-reveal md:col-span-4 ql-panel p-8 group hover:border-[#ffab2e]/40 hover:shadow-[0_16px_48px_rgba(0,0,0,0.5)] transition-all duration-300 flex flex-col justify-between min-h-[340px]" style={{ transitionDelay: '220ms' }}>
            <div>
              <div className="flex items-start justify-between mb-7">
                <div className="w-11 h-11 flex items-center justify-center border border-[#ffab2e]/25 bg-[#ffab2e]/[0.06]">
                  <BarChart3 className="w-5 h-5 text-[#ffab2e]" />
                </div>
                <span className="ql-mono text-[10px] tracking-[0.3em] text-[#3a3f47] group-hover:text-[#ffab2e]/50 transition-colors">F.04</span>
              </div>
              <h3 className="text-xl font-bold text-[#e9e7e2] mb-3">一键策略历史回测</h3>
              <p className="text-[#8f959e] text-sm leading-relaxed max-w-xl">
                基于高频历史真实 K 线行情数据，一键回测策略并输出精准的年化收益率、最大回撤、夏普比率、胜率等可视化科学量化报表。
              </p>
            </div>
            <div className="mt-7 grid grid-cols-2 gap-4 pt-5 border-t border-white/[0.07]">
              <div>
                <div className="ql-mono text-[11px] tracking-wider text-[#8f959e]">策略期望收益</div>
                <div className="ql-mono text-xl font-bold text-[#f04e45] mt-1.5">+38.2%</div>
              </div>
              <div>
                <div className="ql-mono text-[11px] tracking-wider text-[#8f959e]">沪深300同期</div>
                <div className="ql-mono text-xl font-bold text-[#555c66] mt-1.5">+12.0%</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  AI选股交互演示（进入视口自动播放）
// ═══════════════════════════════════════════════════════════════════════════
function StockPickingDemo() {
  const [step, setStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [chatMessages, setChatMessages] = useState<{role: 'user' | 'ai'; text: string}[]>([]);
  const [showStocks, setShowStocks] = useState(false);
  const [stocks, setStocks] = useState<{name: string; code: string; score: number; tags: string[]; trend: 'up' | 'down'}[]>([]);
  const sectionRef = useRef<HTMLElement>(null);

  const barHeights = pickBarHeights;

  const play = useCallback(() => {
    if (isPlaying) return;
    setIsPlaying(true);
    setStep(0);
    setChatMessages([]);
    setShowStocks(false);
    setStocks([]);

    let currentStep = 0;
    const runStep = () => {
      if (currentStep >= pickDemoSteps.length) {
        setTimeout(() => {
          setStep(4);
          setShowStocks(true);
          setStocks(pickDemoStocks);
          setIsPlaying(false);
        }, 800);
        return;
      }
      const msg = pickDemoSteps[currentStep];
      setChatMessages(prev => [...prev, msg]);
      setStep(currentStep + 1);
      currentStep++;
      setTimeout(runStep, 1800);
    };
    setTimeout(runStep, 500);
  }, [isPlaying]);

  useAutoPlay(sectionRef, play);

  return (
    <section ref={sectionRef} id="demo-pick" className="py-28 relative overflow-hidden border-t border-white/[0.07]">
      <div className="absolute top-0 right-0 w-[560px] h-[560px] bg-[#ffab2e]/[0.04] rounded-full blur-[140px]" />

      <div className="relative max-w-7xl mx-auto px-6">
        <div className="ql-reveal">
          <SectionHeading
            index="02"
            kicker="AUTO DEMO · PICK"
            title={
              <>
                AI 选股<span className="text-[#ffab2e]">全流程</span>
              </>
            }
            desc="输入自然语言，AI 自动完成语义解析、数据获取与多因子筛选"
          />
        </div>

        <div className="grid lg:grid-cols-2 gap-6 items-start">
          {/* 左侧：对话窗口 */}
          <div className="ql-reveal ql-panel overflow-hidden shadow-[0_16px_48px_rgba(0,0,0,0.45)]">
            <div className="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 flex items-center justify-center border border-[#ffab2e]/40 bg-[#ffab2e]/10">
                  <Bot className="w-4 h-4 text-[#ffab2e]" />
                </div>
                <div>
                  <div className="text-sm font-bold text-[#e9e7e2]">AI 选股助手</div>
                  <div className="ql-mono flex items-center gap-1.5 text-[10px] text-emerald-400">
                    <span className="ql-live-dot w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    ONLINE
                  </div>
                </div>
              </div>
              <span className="ql-mono text-[10px] tracking-[0.2em] text-[#3a3f47]">SESSION #4281</span>
            </div>

            <div className="px-5 py-6 space-y-4 min-h-[280px]">
              {chatMessages.length === 0 && !isPlaying && (
                <div className="flex flex-col items-center justify-center h-[220px] text-[#555c66] gap-3">
                  <Bot className="w-9 h-9 text-[#3a3f47]" />
                  <p className="ql-mono text-xs tracking-wider">进入视口后自动演示 AI 选股过程</p>
                </div>
              )}
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} animate-fade-in`}>
                  <div className={`w-8 h-8 flex items-center justify-center shrink-0 border ${
                    msg.role === 'user'
                      ? 'border-white/10 bg-white/[0.04] text-[#8f959e]'
                      : 'border-[#ffab2e]/40 bg-[#ffab2e]/10 text-[#ffab2e]'
                  }`}>
                    {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                  </div>
                  <div className={`max-w-[80%] px-4 py-3 text-sm leading-relaxed border ${
                    msg.role === 'user'
                      ? 'bg-[#ffab2e]/[0.07] border-[#ffab2e]/25 text-[#f0e6d2]'
                      : 'bg-white/[0.03] border-white/[0.08] text-[#b9bec6]'
                  }`}>
                    {msg.text}
                    {msg.role === 'ai' && i === chatMessages.length - 1 && isPlaying && (
                      <span className="ql-caret inline-block w-1.5 h-3.5 bg-[#ffab2e] ml-1 align-middle" />
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-5 py-4 border-t border-white/[0.08] bg-white/[0.02]">
              <div className="flex items-center gap-3 px-4 py-3 bg-white/[0.03] border border-white/10">
                <span className="ql-mono text-[#ffab2e] text-sm">›</span>
                <input
                  type="text"
                  readOnly
                  value={isPlaying ? '' : '帮我找一下最近北向资金持续流入的消费股...'}
                  className="flex-1 bg-transparent text-sm text-[#8f959e] outline-none ql-mono"
                />
                <button className="p-2 bg-[#ffab2e]/10 border border-[#ffab2e]/40 text-[#ffab2e]">
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* 右侧：处理流程 */}
          <div className="space-y-3">
            {[
              { icon: Search, label: '语义解析', desc: '理解用户选股意图', code: 'PARSE' },
              { icon: Database, label: '数据获取', desc: '实时获取市场数据', code: 'FETCH' },
              { icon: BrainCircuit, label: '策略生成', desc: '构建多因子选股模型', code: 'MODEL' },
              { icon: Zap, label: '智能筛选', desc: '综合评分排序输出', code: 'RANK' },
            ].map((s, i) => (
              <div
                key={s.label}
                className={`flex items-center gap-4 p-5 border transition-all duration-500 ${
                  step > i
                    ? 'bg-[#0d1015] border-[#ffab2e]/40 shadow-[0_8px_32px_rgba(255,171,46,0.07)]'
                    : 'bg-white/[0.02] border-white/[0.07]'
                }`}
                style={{ transitionDelay: `${i * 60}ms` }}
              >
                <div className={`w-11 h-11 flex items-center justify-center shrink-0 border transition-all duration-500 ${
                  step > i ? 'border-[#ffab2e]/50 bg-[#ffab2e]/10' : 'border-white/[0.08] bg-white/[0.02]'
                }`}>
                  <s.icon className={`w-5 h-5 transition-colors ${step > i ? 'text-[#ffab2e]' : 'text-[#555c66]'}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`font-bold text-sm transition-colors ${step > i ? 'text-[#e9e7e2]' : 'text-[#555c66]'}`}>
                      {s.label}
                    </span>
                    {step > i && <CheckCircle2 className="w-4 h-4 text-emerald-500" />}
                  </div>
                  <span className={`text-xs transition-colors ${step > i ? 'text-[#8f959e]' : 'text-[#4a4f58]'}`}>
                    {s.desc}
                  </span>
                </div>
                <span className={`ql-mono text-[10px] tracking-[0.2em] ${step > i ? 'text-[#ffab2e]' : 'text-[#3a3f47]'}`}>
                  {s.code}
                </span>
                {step === i + 1 && isPlaying && (
                  <Loader2 className="w-4 h-4 text-[#ffab2e] animate-spin shrink-0" />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* 选股结果 */}
        {showStocks && (
          <div className="mt-10 animate-fade-in">
            <div className="ql-mono flex items-center gap-3 mb-6 text-[11px] tracking-[0.25em] text-[#ffab2e]">
              <span className="h-px w-10 bg-[#ffab2e]/40" />
              RESULT SET · 命中 3 只标的
            </div>
            <div className="grid md:grid-cols-3 gap-5">
              {stocks.map((stock, i) => (
                <div
                  key={stock.code}
                  className="ql-panel p-6 hover:border-[#ffab2e]/40 hover:shadow-[0_16px_48px_rgba(0,0,0,0.5)] transition-all duration-300 group"
                  style={{ animationDelay: `${i * 150}ms` }}
                >
                  <div className="flex items-center justify-between mb-5">
                    <div>
                      <div className="font-bold text-[#e9e7e2] text-lg">{stock.name}</div>
                      <div className="ql-mono text-[11px] text-[#555c66] mt-0.5">{stock.code}.SH</div>
                    </div>
                    <div className="text-right">
                      <div className="ql-mono text-2xl font-bold text-[#ffab2e]">{stock.score}</div>
                      <div className="ql-mono text-[9px] tracking-[0.2em] text-[#555c66]">SCORE</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {stock.tags.map(tag => (
                      <span key={tag} className="ql-mono px-2 py-0.5 text-[10px] border border-[#ffab2e]/25 text-[#ffab2e] bg-[#ffab2e]/[0.05]">
                        {tag}
                      </span>
                    ))}
                  </div>
                  {/* 模拟K线 */}
                  <div className="mt-6 flex items-end gap-1 h-10">
                    {barHeights.map((h, j) => (
                      <div
                        key={j}
                        className="flex-1 bg-[#f04e45]/25 group-hover:bg-[#f04e45]/40 transition-colors"
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  AI盯盘交互演示（进入视口自动播放）
// ═══════════════════════════════════════════════════════════════════════════
function MonitoringDemo() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [step, setStep] = useState(0);
  const [showSignals, setShowSignals] = useState(false);
  const [monitoringActive, setMonitoringActive] = useState(false);
  const [priceData, setPriceData] = useState<{time: string; price: number; signal?: 'buy' | 'sell' | null}[]>([]);
  const [logs, setLogs] = useState<{time: string; type: 'info' | 'signal' | 'alert'; message: string}[]>([]);
  const timersRef = useRef<number[]>([]);
  const intervalRef = useRef<number | null>(null);
  const sectionRef = useRef<HTMLElement>(null);

  const renderDot = useCallback((props: { cx: number; cy: number; index: number; payload: { signal?: 'buy' | 'sell' | null } }) => {
    const { cx, cy, index, payload } = props;
    if (payload.signal === 'buy') {
      return (
        <g key={`dot-buy-${index}`}>
          <circle cx={cx} cy={cy} r="10" fill="#f04e45" fillOpacity="0.25" className="animate-pulse" />
          <circle cx={cx} cy={cy} r="5" fill="#f04e45" stroke="#050608" strokeWidth="1.5" />
          <text x={cx} y={cy - 12} textAnchor="middle" fill="#f04e45" fontSize="11" fontWeight="bold">B</text>
        </g>
      );
    }
    if (payload.signal === 'sell') {
      return (
        <g key={`dot-sell-${index}`}>
          <circle cx={cx} cy={cy} r="10" fill="#10b981" fillOpacity="0.25" className="animate-pulse" />
          <circle cx={cx} cy={cy} r="5" fill="#10b981" stroke="#050608" strokeWidth="1.5" />
          <text x={cx} y={cy - 12} textAnchor="middle" fill="#10b981" fontSize="11" fontWeight="bold">S</text>
        </g>
      );
    }
    if (index === priceData.length - 1 && monitoringActive) {
      return (
        <g key={`dot-active-${index}`}>
          <circle cx={cx} cy={cy} r="9" fill="#ffab2e" fillOpacity="0.25" className="animate-pulse" />
          <circle cx={cx} cy={cy} r="4.5" fill="#ffab2e" stroke="#050608" strokeWidth="1.5" />
        </g>
      );
    }
    return <g />;
  }, [priceData.length, monitoringActive]);

  const clearAllTimers = useCallback(() => {
    timersRef.current.forEach(id => clearTimeout(id));
    timersRef.current = [];
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const addTimer = useCallback((fn: () => void, delay: number) => {
    const id = window.setTimeout(fn, delay);
    timersRef.current.push(id);
    return id;
  }, []);

  // 生成模拟价格数据
  const generatePriceData = useCallback(() => {
    const data: typeof priceData = [];
    let price = 100;
    for (let i = 0; i < 30; i++) {
      const change = (Math.random() - 0.45) * 2;
      price = Math.max(85, Math.min(115, price + change));
      // 映射到 A 股交易时段：09:30 起每点 +8 分钟，跳过 11:30–13:00 午休
      const mins = 570 + i * 8;
      const t = mins >= 690 ? mins + 90 : mins;
      const hour = Math.floor(t / 60);
      const min = t % 60;
      const time = `${hour.toString().padStart(2, '0')}:${min.toString().padStart(2, '0')}`;
      data.push({ time, price: Math.round(price * 100) / 100 });
    }
    data[15] = { ...data[15], signal: 'buy' as const };
    data[25] = { ...data[25], signal: 'sell' as const };
    return data;
  }, []);

  const play = useCallback(() => {
    if (isPlaying) return;
    clearAllTimers();
    setIsPlaying(true);
    setStep(0);
    setShowSignals(false);
    setMonitoringActive(false);
    setPriceData([]);
    setLogs([]);

    const data = generatePriceData();

    addTimer(() => {
      setStep(1);
      setLogs([{ time: '09:30', type: 'info' as const, message: '用户设置盯盘策略：MACD金叉买入，死叉卖出' }]);

      addTimer(() => {
        setStep(2);
        setLogs(prev => [...prev, { time: '09:30', type: 'info' as const, message: 'AI解析完成：MACD指标监控，参数(12,26,9)' }]);

        addTimer(() => {
          setStep(3);
          setMonitoringActive(true);
          setLogs(prev => [...prev, { time: '09:31', type: 'info' as const, message: '开始实时监控：贵州茅台(600519)' }]);

          let idx = 0;
          intervalRef.current = window.setInterval(() => {
            if (idx >= data.length) {
              if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
              }
              addTimer(() => {
                setStep(4);
                setMonitoringActive(false);
                setShowSignals(true);
                setLogs(prev => [...prev, { time: '15:00', type: 'info' as const, message: '监控结束，共产生 2 个交易信号' }]);
                setIsPlaying(false);
              }, 800);
              return;
            }

            const point = data[idx];
            setPriceData(prev => [...prev, point]);

            if (point.signal === 'buy') {
              setLogs(prev => [...prev, { time: point.time, type: 'signal' as const, message: `买入信号触发 @ ¥${point.price.toFixed(2)}` }]);
            } else if (point.signal === 'sell') {
              setLogs(prev => [...prev, { time: point.time, type: 'signal' as const, message: `卖出信号触发 @ ¥${point.price.toFixed(2)}` }]);
            }

            idx++;
          }, 120);
        }, 1500);
      }, 1500);
    }, 600);
  }, [isPlaying, clearAllTimers, addTimer, generatePriceData]);

  useAutoPlay(sectionRef, play);

  return (
    <section ref={sectionRef} id="demo-monitor" className="py-28 relative overflow-hidden border-t border-white/[0.07]">
      <div className="absolute top-0 left-0 w-[560px] h-[560px] bg-[#ffab2e]/[0.04] rounded-full blur-[140px]" />

      <div className="relative max-w-7xl mx-auto px-6">
        <div className="ql-reveal">
          <SectionHeading
            index="03"
            kicker="AUTO DEMO · MONITOR"
            title={
              <>
                AI 智能<span className="text-[#ffab2e]">盯盘</span>
              </>
            }
            desc="输入自然语言，AI 自动生成盯盘策略并实时监控"
          />
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* Left: Settings and Flow */}
          <div className="space-y-5">
            <div className="ql-reveal ql-panel p-6 shadow-[0_16px_48px_rgba(0,0,0,0.45)]">
              <div className="flex items-center gap-2 mb-4">
                <Bot className="w-4 h-4 text-[#ffab2e]" />
                <h3 className="font-bold text-[#e9e7e2] text-sm">策略设置</h3>
                <span className="ql-mono ml-auto text-[10px] tracking-[0.2em] text-[#3a3f47]">CONFIG</span>
              </div>
              <div className="p-4 bg-white/[0.03] border border-white/[0.08]">
                <p className="ql-mono text-xs text-[#b9bec6] leading-relaxed">
                  <span className="text-[#ffab2e]">› </span>
                  “帮我监控贵州茅台，当 MACD 出现金叉时买入信号，死叉时卖出信号”
                </p>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${monitoringActive ? 'bg-emerald-500 ql-live-dot' : 'bg-[#3a3f47]'}`} />
                <span className={`ql-mono text-[11px] tracking-wider ${monitoringActive ? 'text-emerald-400' : 'text-[#555c66]'}`}>
                  {monitoringActive ? '实时监控中...' : step > 0 ? '监控完成' : '进入视口自动开始'}
                </span>
              </div>
            </div>

            <div className="space-y-3">
              {[
                { icon: BrainCircuit, label: '策略解析', desc: 'AI 理解用户盯盘意图', code: 'PARSE' },
                { icon: Database, label: '数据接入', desc: '实时连接行情数据源', code: 'FEED' },
                { icon: Radio, label: '实时监控', desc: '持续扫描市场信号', code: 'SCAN' },
                { icon: Bell, label: '信号推送', desc: '触发条件时即时通知', code: 'PUSH' },
              ].map((s, i) => (
                <div
                  key={s.label}
                  className={`flex items-center gap-4 p-4 border transition-all duration-500 ${
                    step > i
                      ? 'bg-[#0d1015] border-[#ffab2e]/40 shadow-[0_8px_32px_rgba(255,171,46,0.07)]'
                      : 'bg-white/[0.02] border-white/[0.07]'
                  }`}
                  style={{ transitionDelay: `${i * 60}ms` }}
                >
                  <div className={`w-10 h-10 flex items-center justify-center shrink-0 border transition-all duration-300 ${
                    step >= i + 1 ? 'border-[#ffab2e]/50 bg-[#ffab2e]/10' : 'border-white/[0.08] bg-white/[0.02]'
                  }`}>
                    <s.icon className={`w-5 h-5 transition-colors ${step >= i + 1 ? 'text-[#ffab2e]' : 'text-[#555c66]'}`} />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className={`font-bold text-sm ${step >= i + 1 ? 'text-[#e9e7e2]' : 'text-[#555c66]'}`}>
                        {s.label}
                      </span>
                      {step > i && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />}
                    </div>
                    <span className={`text-xs ${step >= i + 1 ? 'text-[#8f959e]' : 'text-[#4a4f58]'}`}>
                      {s.desc}
                    </span>
                  </div>
                  <span className={`ql-mono text-[10px] tracking-[0.2em] ${step >= i + 1 ? 'text-[#ffab2e]' : 'text-[#3a3f47]'}`}>
                    {s.code}
                  </span>
                  {step === i + 1 && isPlaying && (
                    <Loader2 className="w-4 h-4 text-[#ffab2e] animate-spin shrink-0" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Right: Charts and logs */}
          <div className="space-y-5">
            <div className="ql-reveal ql-panel p-6 shadow-[0_16px_48px_rgba(0,0,0,0.45)]">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-[#ffab2e]" />
                  <h3 className="font-bold text-[#e9e7e2] text-sm">实时行情</h3>
                </div>
                <div className="ql-mono flex items-center gap-2.5 text-[11px]">
                  <span className="text-[#c8cdd4]">贵州茅台</span>
                  <span className="text-[#555c66]">600519</span>
                  {monitoringActive && (
                    <span className="flex items-center gap-1.5 px-2 py-0.5 border border-emerald-500/30 text-emerald-400 bg-emerald-500/[0.06]">
                      <span className="ql-live-dot w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      LIVE
                    </span>
                  )}
                </div>
              </div>

              {/* 行情图 */}
              <div className="h-48 relative mb-4 bg-[#050608] border border-white/[0.08] overflow-hidden p-2">
                {priceData.length === 0 ? (
                  <div className="w-full h-full flex items-center justify-center text-[#555c66] ql-mono text-xs tracking-wider">
                    等待行情数据接入...
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={priceData} margin={{ top: 15, right: 10, left: 10, bottom: 5 }}>
                      <defs>
                        <linearGradient id="monitorGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#ffab2e" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#ffab2e" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
                      <XAxis dataKey="time" hide />
                      <YAxis domain={['auto', 'auto']} hide />
                      <Area
                        type="monotone"
                        dataKey="price"
                        stroke="#ffab2e"
                        strokeWidth={2}
                        fill="url(#monitorGrad)"
                        dot={renderDot}
                        isAnimationActive={false}
                        style={{ filter: 'drop-shadow(0 0 5px rgba(255,171,46,0.35))' }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>

              {priceData.length > 0 && (
                <div className="flex items-center justify-between pt-4 border-t border-white/[0.07]">
                  <div>
                    <div className="ql-mono text-2xl font-bold text-[#e9e7e2]">
                      ¥{priceData[priceData.length - 1]?.price.toFixed(2)}
                    </div>
                    <div className="ql-mono text-[10px] tracking-wider text-[#555c66] mt-0.5">最新价</div>
                  </div>
                  <div className="text-right">
                    <div className={`ql-mono text-lg font-bold ${
                      (priceData[priceData.length - 1]?.price ?? 100) >= 100 ? 'text-[#f04e45]' : 'text-[#10b981]'
                    }`}>
                      {(priceData[priceData.length - 1]?.price ?? 100) >= 100 ? '+' : ''}
                      {((priceData[priceData.length - 1]?.price ?? 100) - 100).toFixed(2)}%
                    </div>
                    <div className="ql-mono text-[10px] tracking-wider text-[#555c66] mt-0.5">今日涨跌</div>
                  </div>
                </div>
              )}
            </div>

            <div className="ql-reveal ql-panel p-6 shadow-[0_16px_48px_rgba(0,0,0,0.45)]">
              <div className="flex items-center gap-2 mb-4">
                <Terminal className="w-4 h-4 text-[#ffab2e]" />
                <h3 className="font-bold text-[#e9e7e2] text-sm">信号日志</h3>
                <span className="ql-mono ml-auto text-[10px] tracking-[0.2em] text-[#3a3f47]">STDOUT</span>
              </div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1 ql-mono">
                {logs.length === 0 ? (
                  <div className="text-center py-8 text-[#555c66] text-xs tracking-wider">
                    // 暂无信号记录
                  </div>
                ) : (
                  logs.map((log, i) => (
                    <div
                      key={i}
                      className={`flex items-start gap-3 px-3 py-2 text-[11px] animate-fade-in border-l-2 ${
                        log.type === 'signal'
                          ? log.message.includes('买入')
                            ? 'border-[#f04e45] bg-[#f04e45]/[0.06] text-[#f2a9a4]'
                            : 'border-[#10b981] bg-[#10b981]/[0.06] text-[#8fd8bd]'
                          : 'border-white/15 bg-white/[0.03] text-[#8f959e]'
                      }`}
                    >
                      <span className="text-[#555c66] shrink-0">[{log.time}]</span>
                      <span className="leading-relaxed">{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Signal Stats */}
        {showSignals && (
          <div className="mt-10 animate-fade-in">
            <div className="ql-mono flex items-center gap-3 mb-6 text-[11px] tracking-[0.25em] text-[#ffab2e]">
              <span className="h-px w-10 bg-[#ffab2e]/40" />
              SESSION SUMMARY · 今日盯盘总结
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
              {[
                { label: '监控时长', value: '6.5h', icon: Clock, color: AMBER },
                { label: '买入信号', value: '1', icon: ArrowUpRight, color: UP },
                { label: '卖出信号', value: '1', icon: AlertTriangle, color: DOWN },
                { label: '累计收益', value: '+12.5%', icon: TrendingUp, color: UP },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="ql-panel p-5 flex items-center gap-4"
                >
                  <div
                    className="w-10 h-10 border flex items-center justify-center shrink-0"
                    style={{ borderColor: `${stat.color}40`, backgroundColor: `${stat.color}0f` }}
                  >
                    <stat.icon className="w-5 h-5" style={{ color: stat.color }} />
                  </div>
                  <div>
                    <div className="ql-mono text-xl font-bold" style={{ color: stat.color }}>{stat.value}</div>
                    <div className="text-[11px] text-[#8f959e] mt-0.5">{stat.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  策略回测交互演示（进入视口自动播放）
// ═══════════════════════════════════════════════════════════════════════════
function BacktestDemo() {
  const [step, setStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const [showChart, setShowChart] = useState(false);
  const [codeLines, setCodeLines] = useState<string[]>([]);
  const [typingLine, setTypingLine] = useState(0);
  const timersRef = useRef<number[]>([]);
  const sectionRef = useRef<HTMLElement>(null);

  const clearAllTimers = useCallback(() => {
    timersRef.current.forEach(id => {
      clearTimeout(id);
      clearInterval(id);
    });
    timersRef.current = [];
  }, []);

  const addTimer = useCallback((fn: () => void, delay: number) => {
    const id = window.setTimeout(fn, delay);
    timersRef.current.push(id);
    return id;
  }, []);

  const play = useCallback(() => {
    if (isPlaying) return;
    clearAllTimers();
    setIsPlaying(true);
    setStep(0);
    setShowCode(false);
    setShowChart(false);
    setCodeLines([]);
    setTypingLine(0);

    addTimer(() => {
      setStep(1);
      addTimer(() => {
        setStep(2);
        addTimer(() => {
          setStep(3);
          setShowCode(true);
          let lineIdx = 0;
          const typeInterval = window.setInterval(() => {
            if (lineIdx < demoStrategyCode.length) {
              const line = demoStrategyCode[lineIdx];
              setCodeLines(prev => [...prev, line]);
              setTypingLine(lineIdx + 1);
              lineIdx++;
            } else {
              clearInterval(typeInterval);
              addTimer(() => {
                setStep(4);
                addTimer(() => {
                  setStep(5);
                  setShowChart(true);
                  setIsPlaying(false);
                }, 1200);
              }, 800);
            }
          }, 200);
          timersRef.current.push(typeInterval);
        }, 1500);
      }, 1200);
    }, 600);
  }, [isPlaying, clearAllTimers, addTimer]);

  useAutoPlay(sectionRef, play);

  useEffect(() => {
    return () => clearAllTimers();
  }, [clearAllTimers]);

  return (
    <section ref={sectionRef} id="demo-backtest" className="py-28 relative overflow-hidden border-t border-white/[0.07]">
      <div className="absolute bottom-0 right-0 w-[560px] h-[560px] bg-[#ffab2e]/[0.04] rounded-full blur-[140px]" />

      <div className="relative max-w-7xl mx-auto px-6">
        <div className="ql-reveal">
          <SectionHeading
            index="04"
            kicker="AUTO DEMO · BACKTEST"
            title={
              <>
                策略生成与<span className="text-[#ffab2e]">回测</span>
              </>
            }
            desc="描述策略逻辑，AI 生成代码并自动回测"
          />
        </div>

        <div className="grid lg:grid-cols-5 gap-6">
          {/* 左侧：流程步骤 */}
          <div className="lg:col-span-2 space-y-3">
            {[
              { icon: User, label: '策略描述', desc: '用户用自然语言描述交易逻辑', code: 'INPUT' },
              { icon: BrainCircuit, label: 'AI 理解', desc: '解析策略意图，识别关键参数', code: 'PARSE' },
              { icon: FileCode2, label: '代码生成', desc: '自动生成可执行的 Python 策略代码', code: 'GEN' },
              { icon: Play, label: '自动回测', desc: '在历史数据上运行策略验证', code: 'RUN' },
              { icon: LineChart, label: '结果展示', desc: '可视化收益曲线和风险指标', code: 'REPORT' },
            ].map((s, i) => (
              <div
                key={s.label}
                className={`flex items-center gap-4 p-4 border transition-all duration-500 ${
                  step > i
                    ? 'bg-[#0d1015] border-[#ffab2e]/40 shadow-[0_8px_32px_rgba(255,171,46,0.07)]'
                    : step === i + 1
                    ? 'bg-[#ffab2e]/[0.04] border-[#ffab2e]/25'
                    : 'bg-white/[0.02] border-white/[0.07]'
                }`}
                style={{ transitionDelay: `${i * 60}ms` }}
              >
                <div className={`w-10 h-10 flex items-center justify-center shrink-0 border transition-all duration-300 ${
                  step >= i + 1 ? 'border-[#ffab2e]/50 bg-[#ffab2e]/10' : 'border-white/[0.08] bg-white/[0.02]'
                }`}>
                  <s.icon className={`w-5 h-5 transition-colors ${step >= i + 1 ? 'text-[#ffab2e]' : 'text-[#555c66]'}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`font-bold text-sm ${step >= i + 1 ? 'text-[#e9e7e2]' : 'text-[#555c66]'}`}>
                      {s.label}
                    </span>
                    {step > i && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />}
                  </div>
                  <span className={`text-xs ${step >= i + 1 ? 'text-[#8f959e]' : 'text-[#4a4f58]'}`}>
                    {s.desc}
                  </span>
                </div>
                <span className={`ql-mono text-[10px] tracking-[0.2em] ${step >= i + 1 ? 'text-[#ffab2e]' : 'text-[#3a3f47]'}`}>
                  {s.code}
                </span>
                {step === i + 1 && isPlaying && (
                  <Loader2 className="w-4 h-4 text-[#ffab2e] animate-spin shrink-0" />
                )}
              </div>
            ))}
          </div>

          {/* 右侧：代码 + 图表 */}
          <div className="lg:col-span-3 space-y-5">
            {/* 用户输入 */}
            <div className={`ql-panel p-5 transition-all duration-500 shadow-[0_8px_32px_rgba(0,0,0,0.4)] ${step >= 1 ? 'opacity-100' : 'opacity-50'}`}>
              <div className="ql-mono flex items-center gap-2 mb-2 text-[10px] tracking-[0.25em] text-[#555c66]">
                <User className="w-3.5 h-3.5" />
                INPUT · 策略描述
              </div>
              <p className="ql-mono text-sm text-[#b9bec6]">
                <span className="text-[#ffab2e]">› </span>
                “写一个双均线策略，5日均线上穿20日均线时买入，下穿时卖出”
              </p>
            </div>

            {/* 代码编辑器 */}
            {showCode && (
              <div className="ql-terminal overflow-hidden shadow-[0_16px_60px_rgba(0,0,0,0.6)] animate-fade-in">
                <div className="px-4 py-3 border-b border-white/[0.08] flex items-center gap-3 bg-white/[0.02]">
                  <div className="flex gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#f04e45]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ffab2e]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#10b981]/80" />
                  </div>
                  <span className="ql-mono text-[11px] text-[#555c66]">strategy.py</span>
                  <div className="ml-auto ql-mono flex items-center gap-1.5 text-[10px] tracking-wider text-[#555c66]">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    Python 3.11
                  </div>
                </div>
                <div className="px-5 py-5 ql-mono text-[13px] leading-relaxed overflow-x-auto">
                  {codeLines.map((line, i) => {
                    if (typeof line !== 'string') return null;
                    return (
                      <div key={i} className="flex">
                        <span className="w-8 text-right text-[#3a3f47] text-xs select-none mr-4">{i + 1}</span>
                        <span className={codeLineClass(line)}>
                          {line || ' '}
                        </span>
                      </div>
                    );
                  })}
                  {isPlaying && typingLine < demoStrategyCode.length && (
                    <div className="flex">
                      <span className="w-8 text-right text-[#3a3f47] text-xs select-none mr-4">{typingLine + 1}</span>
                      <span className="ql-caret w-2 h-4 bg-[#ffab2e]" />
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 回测结果图表 */}
            {showChart && (
              <div className="ql-panel p-6 animate-fade-in shadow-[0_16px_48px_rgba(0,0,0,0.5)]">
                <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
                  <div className="ql-mono flex items-center gap-2 text-[11px] tracking-[0.25em] text-[#8f959e]">
                    <LineChart className="w-4 h-4 text-[#ffab2e]" />
                    BACKTEST REPORT
                  </div>
                  <div className="ql-mono flex items-center gap-4 text-[11px]">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 bg-[#ffab2e]" />
                      <span className="text-[#ffab2e]">策略 +38.2%</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 bg-[#555c66]" />
                      <span className="text-[#8f959e]">沪深300 +12.0%</span>
                    </span>
                  </div>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={backtestData}>
                    <defs>
                      <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ffab2e" stopOpacity={0.18} />
                        <stop offset="95%" stopColor="#ffab2e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" stroke="#555c66" fontSize={11} tickLine={false} />
                    <YAxis stroke="#555c66" fontSize={11} tickLine={false} domain={[90, 145]} />
                    <Tooltip contentStyle={darkTooltipStyle} />
                    <Area
                      type="monotone"
                      dataKey="strategy"
                      stroke="#ffab2e"
                      strokeWidth={2}
                      fill="url(#btGrad)"
                      style={{ filter: 'drop-shadow(0 0 5px rgba(255,171,46,0.3))' }}
                    />
                    <Line
                      type="monotone"
                      dataKey="benchmark"
                      stroke="#6b7280"
                      strokeWidth={1.5}
                      strokeDasharray="5 5"
                      dot={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
                {/* 关键指标 */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-white/[0.07]">
                  {[
                    { label: '年化收益', value: '+38.2%', color: 'text-[#f04e45]' },
                    { label: '最大回撤', value: '-8.5%', color: 'text-[#10b981]' },
                    { label: '胜率', value: '67.3%', color: 'text-[#e9e7e2]' },
                    { label: '夏普比率', value: '2.15', color: 'text-[#ffab2e]' },
                  ].map(m => (
                    <div key={m.label} className="text-center">
                      <div className={`ql-mono text-xl font-bold ${m.color}`}>{m.value}</div>
                      <div className="text-[11px] text-[#8f959e] mt-1">{m.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  FAQ 区域
// ═══════════════════════════════════════════════════════════════════════════
function FAQSection() {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  return (
    <section id="faq" className="py-28 relative border-t border-white/[0.07]">
      <div className="relative max-w-3xl mx-auto px-6">
        <SectionHeading
          index="05"
          kicker="FAQ"
          title="常见问题"
          desc="关于平台，你可能想知道的"
        />
        <div className="space-y-3">
          {faqs.map((faq, idx) => (
            <div
              key={idx}
              className={`border transition-all duration-300 ${
                openIdx === idx ? 'bg-white/[0.03] border-[#ffab2e]/30' : 'bg-white/[0.01] border-white/[0.08] hover:border-white/[0.16]'
              }`}
              style={{ transitionDelay: `${idx * 60}ms` }}
            >
              <button
                onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
                className="w-full px-6 py-5 flex items-center justify-between text-left gap-4"
              >
                <div className="flex items-center gap-4">
                  <span className={`ql-mono text-[11px] tracking-wider ${openIdx === idx ? 'text-[#ffab2e]' : 'text-[#555c66]'}`}>
                    Q{String(idx + 1).padStart(2, '0')}
                  </span>
                  <span className={`font-bold ${openIdx === idx ? 'text-[#e9e7e2]' : 'text-[#c8cdd4]'}`}>{faq.q}</span>
                </div>
                {openIdx === idx ? (
                  <ChevronUp className="w-4 h-4 text-[#ffab2e] shrink-0" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-[#555c66] shrink-0" />
                )}
              </button>
              {openIdx === idx && (
                <div className="px-6 pb-5 pl-[4.25rem] text-[#8f959e] text-sm leading-relaxed border-t border-white/[0.06] pt-4 animate-fade-in">
                  {faq.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  底部 CTA
// ═══════════════════════════════════════════════════════════════════════════
function CTASection() {
  const navigate = useNavigate();

  return (
    <section className="py-32 relative overflow-hidden border-t border-white/[0.07]">
      <div className="absolute inset-0 ql-grid-bg" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[720px] h-[720px] bg-[#ffab2e]/[0.06] rounded-full blur-[160px]" />

      <div className="relative z-10 max-w-3xl mx-auto px-6 text-center ql-reveal">
        <div className="ql-mono inline-flex items-center gap-3 text-[11px] tracking-[0.3em] text-[#ffab2e] mb-8">
          <span className="h-px w-8 bg-[#ffab2e]/40" />
          06 / GET STARTED
          <span className="h-px w-8 bg-[#ffab2e]/40" />
        </div>
        <h2 className="text-4xl md:text-6xl font-black text-[#e9e7e2] mb-6 tracking-tight leading-tight">
          开始你的
          <span className="text-[#ffab2e]">量化交易</span>
          之旅
        </h2>
        <p className="text-[#8f959e] text-lg mb-12">
          无需编程，AI 让量化交易触手可及
        </p>
        <button
          onClick={() => navigate('/login')}
          className="ql-btn-glow group ql-mono px-12 py-5 bg-[#ffab2e] text-black text-sm font-bold tracking-[0.2em] hover:bg-[#ffbb4d] inline-flex items-center gap-3"
        >
          免费注册
          <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
        </button>
        <div className="ql-mono mt-8 text-[11px] tracking-wider text-[#555c66]">
          NO CREDIT CARD REQUIRED · 3 分钟创建你的第一个策略
        </div>
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  页脚
// ═══════════════════════════════════════════════════════════════════════════
function Footer() {
  return (
    <footer className="border-t border-white/[0.08] bg-[#050608]">
      <div className="max-w-7xl mx-auto px-6 py-10 flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 flex items-center justify-center bg-[#ffab2e]">
            <TrendingUp className="w-3.5 h-3.5 text-black" strokeWidth={2.5} />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-bold text-[#e9e7e2]">量化交易平台</span>
            <span className="ql-mono text-[9px] tracking-[0.25em] text-[#555c66] mt-0.5">QUANT TERMINAL</span>
          </div>
        </div>
        <div className="ql-mono flex items-center gap-8 text-[11px] tracking-wider text-[#8f959e]">
          <span className="hover:text-[#ffab2e] cursor-pointer transition-colors">关于我们</span>
          <span className="hover:text-[#ffab2e] cursor-pointer transition-colors">使用条款</span>
          <span className="hover:text-[#ffab2e] cursor-pointer transition-colors">隐私政策</span>
        </div>
        <span className="ql-mono text-[11px] text-[#555c66]">&copy; 2026 QUANT TERMINAL</span>
      </div>
      <div className="border-t border-white/[0.06]">
        <div className="max-w-7xl mx-auto px-6 py-4 text-center ql-mono text-[10px] tracking-wider text-[#4a4f58]">
          市场有风险，投资需谨慎。本页面所展示数据均为演示用途，不构成任何投资建议。
        </div>
      </div>
    </footer>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  主组件
// ═══════════════════════════════════════════════════════════════════════════
export function Landing() {
  useReveal();

  return (
    <div className="quant-landing relative min-h-screen selection:bg-[#ffab2e]/30 selection:text-black">
      <Navbar />
      <HeroSection />
      <FeaturesSection />
      <StockPickingDemo />
      <MonitoringDemo />
      <BacktestDemo />
      <FAQSection />
      <CTASection />
      <Footer />
    </div>
  );
}
