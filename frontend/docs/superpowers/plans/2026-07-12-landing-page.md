# 落地页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public landing page at `/` for the quant trading platform, moving all authenticated routes under `/app`.

**Architecture:** New `Landing.tsx` single-file page component with scroll-based sections (Navbar, Hero, Features, Demo, FAQ, CTA, Footer). Routes restructured so `/` is public and `/app/*` requires auth. Existing Layout nav links and Login redirect path updated to match new `/app` prefix.

**Tech Stack:** React 18, React Router 6 (HashRouter), Tailwind CSS 3, Lucide React icons, Recharts (for demo chart), Zustand (auth store read-only)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pages/Landing.tsx` | Create | Landing page with all sections |
| `src/pages/index.ts` | Modify | Export Landing component |
| `src/App.tsx` | Modify | Restructure routes: `/` → Landing, `/app/*` → ProtectedRoute |
| `src/components/Layout.tsx` | Modify | Update nav paths to `/app/...` prefix |
| `src/pages/Login.tsx` | Modify | Redirect to `/app` instead of `/` after login |

---

### Task 1: Create Landing page component

**Files:**
- Create: `src/pages/Landing.tsx`

- [ ] **Step 1: Create `src/pages/Landing.tsx` with the full landing page**

```tsx
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  TrendingUp,
  Sparkles,
  Activity,
  FlaskConical,
  BarChart3,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  CheckCircle2,
  Play,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from 'recharts';
import { useAuthStore } from '@/stores';

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

// ── AI选股示意数据 ────────────────────────────────────────────────────────
const pickResults = [
  { name: '贵州茅台', code: '600519', score: 92, reason: '基本面强劲，北向资金持续流入，技术面突破关键阻力位' },
  { name: '宁德时代', code: '300750', score: 87, reason: '新能源赛道龙头，量价齐升，MACD金叉确认' },
  { name: '比亚迪', code: '002594', score: 85, reason: '销量超预期，均线多头排列，资金面活跃' },
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

// ── 功能卡片数据 ──────────────────────────────────────────────────────────
const features = [
  {
    icon: Sparkles,
    title: 'AI选股',
    desc: '自然语言描述选股条件，AI自动筛选符合要求的标的',
    points: ['自然语言交互', '多因子综合评分', '实时市场扫描'],
    gradient: 'from-blue-500 to-cyan-400',
  },
  {
    icon: Activity,
    title: 'AI盯盘',
    desc: '24小时智能盯盘，实时监控异动、突破、量价异常',
    points: ['异动实时推送', '自定义监控规则', '多标的并行监控'],
    gradient: 'from-purple-500 to-pink-400',
  },
  {
    icon: FlaskConical,
    title: '策略生成',
    desc: '描述你的交易逻辑，AI自动生成可执行的量化策略',
    points: ['自然语言转策略代码', '多策略模板', '参数自动优化'],
    gradient: 'from-emerald-500 to-teal-400',
  },
  {
    icon: BarChart3,
    title: '策略回测',
    desc: '一键回测历史数据，可视化收益曲线和风险指标',
    points: ['历史数据回测', '收益曲线可视化', '风险指标分析'],
    gradient: 'from-amber-500 to-orange-400',
  },
];

// ── 导航栏 ────────────────────────────────────────────────────────────────
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
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-gray-900/90 backdrop-blur-md border-b border-gray-800'
          : 'bg-transparent'
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-primary-600 rounded-lg">
            <TrendingUp className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold text-white">量化交易平台</span>
        </div>
        <div className="hidden md:flex items-center gap-8">
          <a href="#features" className="text-sm text-gray-300 hover:text-white transition">
            功能
          </a>
          <a href="#demo" className="text-sm text-gray-300 hover:text-white transition">
            效果
          </a>
          <a href="#faq" className="text-sm text-gray-300 hover:text-white transition">
            FAQ
          </a>
          {isAuthenticated ? (
            <button
              onClick={() => navigate('/app')}
              className="px-4 py-2 text-sm font-medium text-primary-400 border border-primary-500/50 rounded-lg hover:bg-primary-500/10 transition"
            >
              进入工作台
            </button>
          ) : (
            <>
              <button
                onClick={() => navigate('/login')}
                className="text-sm text-gray-300 hover:text-white transition"
              >
                登录
              </button>
              <button
                onClick={() => navigate('/login')}
                className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition"
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

// ── Hero 区域 ─────────────────────────────────────────────────────────────
function HeroSection() {
  const navigate = useNavigate();

  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden bg-gradient-to-br from-gray-950 via-gray-900 to-blue-950">
      {/* 网格背景 */}
      <div className="absolute inset-0 opacity-10">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,130,246,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.3) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />
      </div>

      {/* 抽象K线装饰 */}
      <div className="absolute inset-0 overflow-hidden opacity-20">
        <svg className="absolute top-1/4 -left-20 w-96 h-48" viewBox="0 0 400 200">
          <path
            d="M0,150 L30,120 L30,80 L60,100 L60,60 L90,80 L90,40 L120,60 L120,90 L150,50 L150,80 L180,40 L180,70 L210,90 L210,30 L240,50 L240,80 L270,60 L270,100 L300,70 L300,40 L330,60 L330,90 L360,50 L360,80 L400,60"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="2"
          />
          {[30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360].map((x, i) => (
            <line
              key={i}
              x1={x}
              y1={60 + (i % 3) * 25}
              x2={x}
              y2={90 + (i % 4) * 20}
              stroke="#60a5fa"
              strokeWidth="3"
              strokeLinecap="round"
            />
          ))}
        </svg>
        <svg className="absolute bottom-1/4 -right-20 w-80 h-40" viewBox="0 0 400 200">
          <path
            d="M0,100 L40,80 L40,120 L80,90 L80,130 L120,70 L120,110 L160,60 L160,100 L200,80 L200,120 L240,50 L240,90 L280,70 L280,110 L320,40 L320,80 L360,60 L360,100 L400,70"
            fill="none"
            stroke="#8b5cf6"
            strokeWidth="2"
          />
        </svg>
      </div>

      {/* 发光球体 */}
      <div className="absolute top-1/3 left-1/4 w-96 h-96 bg-primary-600/20 rounded-full blur-3xl" />
      <div className="absolute bottom-1/3 right-1/4 w-80 h-80 bg-purple-600/15 rounded-full blur-3xl" />

      <div className="relative z-10 max-w-4xl mx-auto px-6 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary-500/10 border border-primary-500/20 mb-8">
          <Sparkles className="w-4 h-4 text-primary-400" />
          <span className="text-sm text-primary-300">AI驱动的量化交易新范式</span>
        </div>
        <h1 className="text-4xl md:text-6xl font-bold text-white leading-tight mb-6">
          让AI成为你的
          <br />
          <span className="bg-gradient-to-r from-primary-400 to-cyan-400 bg-clip-text text-transparent">
            量化交易引擎
          </span>
        </h1>
        <p className="text-lg md:text-xl text-gray-400 mb-10 max-w-2xl mx-auto">
          无需编程，用自然语言描述策略，AI帮你选股、盯盘、回测、执行
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <button
            onClick={() => navigate('/login')}
            className="px-8 py-3.5 bg-primary-600 text-white text-lg font-medium rounded-xl hover:bg-primary-700 transition flex items-center gap-2 shadow-lg shadow-primary-600/25"
          >
            立即体验
            <ArrowRight className="w-5 h-5" />
          </button>
          <a
            href="#features"
            className="px-8 py-3.5 border border-gray-600 text-gray-300 text-lg font-medium rounded-xl hover:bg-white/5 transition"
          >
            了解更多
          </a>
        </div>
      </div>

      {/* 底部渐变过渡 */}
      <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-gray-900 to-transparent" />
    </section>
  );
}

// ── 功能展示区域 ──────────────────────────────────────────────────────────
function FeaturesSection() {
  return (
    <section id="features" className="py-24 bg-gray-900">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">四大核心能力</h2>
          <p className="text-gray-400 text-lg">从选股到执行，AI覆盖量化交易全流程</p>
        </div>
        <div className="grid md:grid-cols-2 gap-6">
          {features.map((f) => (
            <div
              key={f.title}
              className="group p-8 rounded-2xl bg-gray-800/50 border border-gray-700/50 hover:border-gray-600/50 transition-all duration-300 hover:shadow-lg hover:shadow-primary-500/5"
            >
              <div
                className={`inline-flex p-3 rounded-xl bg-gradient-to-br ${f.gradient} mb-5 shadow-lg`}
              >
                <f.icon className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-xl font-bold text-white mb-2">{f.title}</h3>
              <p className="text-gray-400 mb-4">{f.desc}</p>
              <ul className="space-y-2">
                {f.points.map((p) => (
                  <li key={p} className="flex items-center gap-2 text-sm text-gray-300">
                    <CheckCircle2 className="w-4 h-4 text-primary-400 shrink-0" />
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── 效果展示区域 ──────────────────────────────────────────────────────────
function DemoSection() {
  return (
    <section id="demo" className="py-24 bg-gray-950">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">实战效果，数据说话</h2>
          <p className="text-gray-400 text-lg">AI策略回测 vs 基准收益对比</p>
        </div>

        {/* 回测曲线 + 指标 */}
        <div className="grid lg:grid-cols-3 gap-6 mb-12">
          <div className="lg:col-span-2 p-6 rounded-2xl bg-gray-800/50 border border-gray-700/50">
            <div className="flex items-center gap-4 mb-4">
              <span className="flex items-center gap-2 text-sm">
                <span className="w-3 h-0.5 bg-primary-400 rounded" />
                <span className="text-gray-400">AI策略</span>
              </span>
              <span className="flex items-center gap-2 text-sm">
                <span className="w-3 h-0.5 bg-gray-500 rounded" />
                <span className="text-gray-400">沪深300</span>
              </span>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={backtestData}>
                <defs>
                  <linearGradient id="strategyGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#6b7280" fontSize={12} tickLine={false} />
                <YAxis stroke="#6b7280" fontSize={12} tickLine={false} domain={[90, 140]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                    color: '#e5e7eb',
                    fontSize: '12px',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="strategy"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="url(#strategyGrad)"
                />
                <Line
                  type="monotone"
                  dataKey="benchmark"
                  stroke="#6b7280"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-1 gap-4">
            {[
              { label: '年化收益率', value: '+38.2%', color: 'text-emerald-400' },
              { label: '最大回撤', value: '-8.5%', color: 'text-red-400' },
              { label: '胜率', value: '67.3%', color: 'text-primary-400' },
              { label: '夏普比率', value: '2.15', color: 'text-amber-400' },
            ].map((m) => (
              <div
                key={m.label}
                className="p-5 rounded-xl bg-gray-800/50 border border-gray-700/50 flex flex-col justify-center"
              >
                <span className="text-sm text-gray-400 mb-1">{m.label}</span>
                <span className={`text-2xl font-bold ${m.color}`}>{m.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* AI选股结果示意 */}
        <div className="p-6 rounded-2xl bg-gray-800/50 border border-gray-700/50">
          <div className="flex items-center gap-2 mb-5">
            <Sparkles className="w-5 h-5 text-primary-400" />
            <h3 className="text-lg font-bold text-white">AI选股示例</h3>
          </div>
          <div className="grid md:grid-cols-3 gap-4">
            {pickResults.map((stock) => (
              <div
                key={stock.code}
                className="p-4 rounded-xl bg-gray-900/80 border border-gray-700/50"
              >
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <span className="font-bold text-white">{stock.name}</span>
                    <span className="ml-2 text-xs text-gray-500">{stock.code}</span>
                  </div>
                  <span className="px-2 py-0.5 rounded-md bg-primary-500/10 text-primary-400 text-sm font-bold">
                    {stock.score}分
                  </span>
                </div>
                <p className="text-sm text-gray-400 leading-relaxed">{stock.reason}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── FAQ 区域 ──────────────────────────────────────────────────────────────
function FAQSection() {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  return (
    <section id="faq" className="py-24 bg-gray-900">
      <div className="max-w-3xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">常见问题</h2>
          <p className="text-gray-400 text-lg">关于平台，你可能想知道的</p>
        </div>
        <div className="space-y-3">
          {faqs.map((faq, idx) => (
            <div
              key={idx}
              className="rounded-xl border border-gray-700/50 bg-gray-800/50 overflow-hidden"
            >
              <button
                onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
                className="w-full px-6 py-4 flex items-center justify-between text-left"
              >
                <span className="font-medium text-white">{faq.q}</span>
                {openIdx === idx ? (
                  <ChevronUp className="w-5 h-5 text-gray-400 shrink-0" />
                ) : (
                  <ChevronDown className="w-5 h-5 text-gray-400 shrink-0" />
                )}
              </button>
              {openIdx === idx && (
                <div className="px-6 pb-4 text-gray-400 leading-relaxed">{faq.a}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── 底部 CTA 区域 ─────────────────────────────────────────────────────────
function CTASection() {
  const navigate = useNavigate();

  return (
    <section className="py-24 bg-gradient-to-br from-primary-900 via-blue-900 to-gray-950">
      <div className="max-w-3xl mx-auto px-6 text-center">
        <h2 className="text-3xl md:text-4xl font-bold text-white mb-6">
          开始你的量化交易之旅
        </h2>
        <p className="text-gray-300 text-lg mb-10">
          无需编程，AI让量化交易触手可及
        </p>
        <button
          onClick={() => navigate('/login')}
          className="px-10 py-4 bg-white text-gray-900 text-lg font-bold rounded-xl hover:bg-gray-100 transition shadow-lg shadow-primary-600/25"
        >
          免费注册
        </button>
      </div>
    </section>
  );
}

// ── 页脚 ──────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="py-8 bg-gray-950 border-t border-gray-800">
      <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <div className="p-1 bg-primary-600 rounded">
            <TrendingUp className="w-4 h-4 text-white" />
          </div>
          <span className="text-sm font-bold text-gray-400">量化交易平台</span>
        </div>
        <div className="flex items-center gap-6 text-sm text-gray-500">
          <span>关于我们</span>
          <span>使用条款</span>
          <span>隐私政策</span>
        </div>
        <span className="text-sm text-gray-600">&copy; 2026 量化交易平台. All rights reserved.</span>
      </div>
    </footer>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────────
export function Landing() {
  return (
    <div className="bg-gray-900">
      <Navbar />
      <HeroSection />
      <FeaturesSection />
      <DemoSection />
      <FAQSection />
      <CTASection />
      <Footer />
    </div>
  );
}
```

- [ ] **Step 2: Verify the file compiles**

Run: `cd D:/MyProj/stock/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors related to Landing.tsx (other pre-existing errors may exist)

- [ ] **Step 3: Commit**

```bash
git add src/pages/Landing.tsx
git commit -m "feat: add landing page component"
```

---

### Task 2: Export Landing from pages index

**Files:**
- Modify: `src/pages/index.ts`

- [ ] **Step 1: Add Landing export**

The current `src/pages/index.ts` content is:

```ts
export { SimulationTrading } from './SimulationTrading';
export { Trading } from './Trading';
export { FactorBoard } from './FactorBoard';
export { TradingData } from './TradingData';
export { AIAssistant } from './AIAssistant';
export { Settings } from './Settings';
export { Login } from './Login';
export { StrategyWorkspace } from './StrategyWorkspace';
export { AIAgent } from './AIAgent';
```

Add this line at the end:

```ts
export { Landing } from './Landing';
```

- [ ] **Step 2: Commit**

```bash
git add src/pages/index.ts
git commit -m "feat: export Landing from pages index"
```

---

### Task 3: Restructure routes in App.tsx

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: Update App.tsx route structure**

The current `src/App.tsx` is:

```tsx
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { Layout } from '@/components';
import { WebSocketProvider } from '@/components/WebSocketProvider';
import {
  SimulationTrading,
  Trading,
  FactorBoard,
  TradingData,
  AIAssistant,
  Settings,
  Login,
  StrategyWorkspace,
  AIAgent,
} from '@/pages';
import { useAuthStore } from '@/stores';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadUser = useAuthStore((s) => s.loadUser);

  // 恢复登录状态
  useEffect(() => {
    loadUser();
  }, [loadUser]);

  return (
    <HashRouter>
      <Routes>
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/" element={<ProtectedRoute><WebSocketProvider><Layout /></WebSocketProvider></ProtectedRoute>}>
          <Route index element={<Navigate to="/ai-assistant" replace />} />
          <Route path="strategy-workspace" element={<StrategyWorkspace />} />
          <Route path="simulation" element={<SimulationTrading />} />
          <Route path="trading" element={<Trading />} />
          <Route path="factor-board" element={<FactorBoard />} />
          <Route path="trading-data" element={<TradingData />} />
          <Route path="ai-assistant" element={<AIAssistant />} />
          <Route path="ai-agent" element={<AIAgent />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/trading-data" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
```

Replace with:

```tsx
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { Layout } from '@/components';
import { WebSocketProvider } from '@/components/WebSocketProvider';
import {
  SimulationTrading,
  Trading,
  FactorBoard,
  TradingData,
  AIAssistant,
  Settings,
  Login,
  StrategyWorkspace,
  AIAgent,
  Landing,
} from '@/pages';
import { useAuthStore } from '@/stores';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadUser = useAuthStore((s) => s.loadUser);

  // 恢复登录状态
  useEffect(() => {
    loadUser();
  }, [loadUser]);

  return (
    <HashRouter>
      <Routes>
        {/* 公开页面 */}
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={isAuthenticated ? <Navigate to="/app" replace /> : <Login />} />

        {/* 需认证的应用页面 */}
        <Route path="/app" element={<ProtectedRoute><WebSocketProvider><Layout /></WebSocketProvider></ProtectedRoute>}>
          <Route index element={<Navigate to="/app/ai-assistant" replace />} />
          <Route path="ai-assistant" element={<AIAssistant />} />
          <Route path="ai-agent" element={<AIAgent />} />
          <Route path="strategy-workspace" element={<StrategyWorkspace />} />
          <Route path="simulation" element={<SimulationTrading />} />
          <Route path="trading" element={<Trading />} />
          <Route path="factor-board" element={<FactorBoard />} />
          <Route path="trading-data" element={<TradingData />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/app/ai-assistant" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
```

Key changes:
- `/` now renders `<Landing />` (public, no auth)
- `/login` redirects to `/app` instead of `/` when authenticated
- All app routes moved under `/app` prefix
- Import `Landing` from `@/pages`
- Catch-all `*` redirects to `/app/ai-assistant`

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd D:/MyProj/stock/frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No new errors

- [ ] **Step 3: Commit**

```bash
git add src/App.tsx
git commit -m "refactor: restructure routes - / for landing, /app for authenticated pages"
```

---

### Task 4: Update Layout navigation paths

**Files:**
- Modify: `src/components/Layout.tsx`

- [ ] **Step 1: Update nav paths to include `/app` prefix**

In `src/components/Layout.tsx`, find the `navItems` array (lines 33-42):

```tsx
const navItems = [
  { path: '/ai-assistant', icon: Sparkles, label: 'AI分析' },
  { path: '/ai-agent', icon: Brain, label: 'AI智能体' },
  { path: '/factor-board', icon: BarChart3, label: '因子看板' },
  { path: '/strategy-workspace', icon: FlaskConical, label: '策略与回测' },
  { path: '/simulation', icon: Cpu, label: '模拟交易' },
  { path: '/trading', icon: TrendingUp, label: '实盘交易' },
  { path: '/trading-data', icon: Database, label: '数据源' },
  { path: '/settings', icon: Settings, label: '系统设置' },
];
```

Replace with:

```tsx
const navItems = [
  { path: '/app/ai-assistant', icon: Sparkles, label: 'AI分析' },
  { path: '/app/ai-agent', icon: Brain, label: 'AI智能体' },
  { path: '/app/factor-board', icon: BarChart3, label: '因子看板' },
  { path: '/app/strategy-workspace', icon: FlaskConical, label: '策略与回测' },
  { path: '/app/simulation', icon: Cpu, label: '模拟交易' },
  { path: '/app/trading', icon: TrendingUp, label: '实盘交易' },
  { path: '/app/trading-data', icon: Database, label: '数据源' },
  { path: '/app/settings', icon: Settings, label: '系统设置' },
];
```

Also update the logout redirect. Find the `handleLogout` function (line 30):

```tsx
const handleLogout = () => {
  logout();
  navigate('/login');
};
```

This stays the same — `/login` is still the correct path after logout.

- [ ] **Step 2: Commit**

```bash
git add src/components/Layout.tsx
git commit -m "refactor: update Layout nav paths to /app prefix"
```

---

### Task 5: Update Login redirect path

**Files:**
- Modify: `src/pages/Login.tsx`

- [ ] **Step 1: Update login success redirect from `/` to `/app`**

In `src/pages/Login.tsx`, find `handleLogin` function (around line 42):

```tsx
const err = await login(loginForm.username, loginForm.password);
setLoginLoading(false);
if (err) {
  setLoginError(err);
} else {
  navigate('/');
}
```

Change `navigate('/')` to `navigate('/app')`:

```tsx
const err = await login(loginForm.username, loginForm.password);
setLoginLoading(false);
if (err) {
  setLoginError(err);
} else {
  navigate('/app');
}
```

Also find `handleRegister` function (around line 67):

```tsx
const err = await register(username, email, password);
setRegisterLoading(false);
if (err) {
  setRegisterError(err);
} else {
  navigate('/');
}
```

Change `navigate('/')` to `navigate('/app')`:

```tsx
const err = await register(username, email, password);
setRegisterLoading(false);
if (err) {
  setRegisterError(err);
} else {
  navigate('/app');
}
```

- [ ] **Step 2: Commit**

```bash
git add src/pages/Login.tsx
git commit -m "fix: update login/register redirect to /app"
```

---

### Task 6: Verify end-to-end

- [ ] **Step 1: Run dev server**

Run: `cd D:/MyProj/stock/frontend && npm run dev`

- [ ] **Step 2: Verify landing page loads at root**

Open the app root URL. Expected: Landing page with dark theme, hero section, feature cards, demo chart, FAQ, CTA, footer.

- [ ] **Step 3: Verify CTA buttons navigate to login**

Click "立即体验" button. Expected: Navigates to login page.

- [ ] **Step 4: Verify login redirects to /app**

Log in. Expected: Redirects to `/app/ai-assistant` (the main app with sidebar).

- [ ] **Step 5: Verify sidebar navigation works**

Click each nav item in sidebar. Expected: All routes work correctly under `/app/` prefix.

- [ ] **Step 6: Verify unauthenticated access to /app redirects to login**

Log out, then try to access `/app/ai-assistant` directly. Expected: Redirected to `/login`.

- [ ] **Step 7: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: landing page integration adjustments"
```
