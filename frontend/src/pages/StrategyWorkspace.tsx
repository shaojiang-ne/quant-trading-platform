import { useState, useEffect, useRef, useMemo } from 'react';
import { useStrategyStore } from '@/stores';
import { StockSearchInput, AIChatPanel } from '@/components';
import { onBacktestLog } from '@/components/WebSocketProvider';
import {
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  AreaChart,
  Area,
} from 'recharts';
import {
  Play,
  Save,
  Plus,
  Settings,
  TrendingUp,
  AlertTriangle,
  Clock,
  Terminal,
  FileCode2,
  ChevronRight,
  FolderOpen,
  Eye,
  X,
  Trash2,
  CheckSquare,
  Square,
} from 'lucide-react';
import type { StrategyResponse, BacktestResultResponse } from '@/api/strategies';


const DEFAULT_CODE = `# 在此编写策略代码，或使用左侧 AI 生成
#
# 函数签名：generate_signals(df, setting) -> pd.Series
#   df: DataFrame，包含列 date, open, high, low, close, volume, turnover
#   setting: dict，策略参数，通过 setting.get("key", default) 读取
#   返回值: pandas Series，1=买入, -1=卖出, 0=持有
#
# 可用的技术指标函数（已内置，无需 import）：
#   sma(series, window)         简单移动平均
#   ema(series, window)         指数移动平均
#   rsi(series, window=14)      相对强弱指标
#   macd(series, fast, slow, signal)  MACD 指标，返回 (dif, dea, hist)
#   bollinger(series, window, num_std) 布林带，返回 (mid, upper, lower)
#   atr(high, low, close, window)     平均真实波幅
#   donchian(high, low, window)       唐奇安通道，返回 (upper, lower)
#   kdj(high, low, close, n, m1, m2)  KDJ 指标，返回 (k, d, j)
#   cci(high, low, close, window)     CCI 指标
#
# 信号值必须为整数：1=买入, -1=卖出, 0=持有（不要使用 True/False）
`;

function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return '-';
  // 后端无偏移量时视为 UTC
  const normalized = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  return new Date(normalized).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
}

export function StrategyWorkspace() {
  const {
    strategies,
    fetchStrategies,
    createStrategy,
    updateStrategy,
    runBacktest,
    deleteStrategy,
    batchDeleteStrategies,
    backtestResults,
    fetchBacktestResults,
    deleteBacktestResult,
    batchDeleteBacktestResults,
  } = useStrategyStore();

  // 策略基本状态
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('new');
  const [strategyName, setStrategyName] = useState('未命名策略');
  const [strategyDesc, setStrategyDesc] = useState('这是基于 AI 生成的量化交易策略');
  const [code, setCode] = useState(DEFAULT_CODE);
  const [parameters, setParameters] = useState<Record<string, any>>({});

  // 回测配置状态
  const [symbol, setSymbol] = useState('600519');
  const [period, setPeriod] = useState('daily');
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [initialCapital, setInitialCapital] = useState(100000);

  // 页面交互状态
  const [logs, setLogs] = useState<string[]>([]);
  const [errorLog, setErrorLog] = useState<string>('');
  const [consoleTab, setConsoleTab] = useState<'log' | 'error'>('log');
  const [backtestResult, setBacktestResult] = useState<BacktestResultResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [viewMode, setViewMode] = useState<'editor' | 'results'>('editor');
  const [resultTab, setResultTab] = useState<'overview' | 'trades' | 'logs' | 'code'>('overview');
  const [backtestElapsed, setBacktestElapsed] = useState<string>('');
  const [isMyStrategiesOpen, setIsMyStrategiesOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [filterCurrentOnly, setFilterCurrentOnly] = useState(false);
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set());
  const [selectedResultIds, setSelectedResultIds] = useState<Set<string>>(new Set());
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState<{ type: 'strategy' | 'backtest'; count: number } | null>(null);


  // 滚动行号同步
  const lineRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const customStrategies = useMemo(() => strategies.filter((s) => !s.is_system), [strategies]);

  const filteredBacktestResults = useMemo(() => {
    if (filterCurrentOnly && selectedStrategyId !== 'new') {
      return backtestResults.filter((r) => r.strategy_id === selectedStrategyId);
    }
    return backtestResults;
  }, [backtestResults, filterCurrentOnly, selectedStrategyId]);

  // 加载策略
  useEffect(() => {
    fetchStrategies();
    fetchBacktestResults();
  }, [fetchStrategies, fetchBacktestResults]);

  // 切换选中策略时重置编辑器
  useEffect(() => {
    if (selectedStrategyId === 'new') {
      setStrategyName(`AI智能策略_${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }).replace(/:/g, '')}`);
      setStrategyDesc('我的自定义 AI 量化策略。');
      setCode(DEFAULT_CODE);
      setParameters({});
      setBacktestResult(null);
    } else {
      const s = strategies.find((st) => st.id === selectedStrategyId);
      if (s) {
        setStrategyName(s.name);
        setStrategyDesc(s.description || '');
        setCode(s.code || '');

        const paramsDict: Record<string, any> = {};
        if (Array.isArray(s.parameters)) {
          s.parameters.forEach((p: any) => {
            paramsDict[p.key] = { value: p.default, type: p.type || 'int', label: p.name || p.key };
          });
          setParameters(paramsDict);
        } else if (s.parameters && typeof s.parameters === 'object') {
          setParameters(s.parameters);
        } else {
          setParameters({});
        }
        setBacktestResult(null);
      }
    }
  }, [selectedStrategyId, strategies]);

  // 同步滚动
  const handleScroll = () => {
    if (textareaRef.current && lineRef.current) {
      lineRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  const lineNumbers = useMemo(() => {
    const lines = code.split('\n').length;
    return Array.from({ length: lines }, (_, i) => i + 1);
  }, [code]);

  const addLog = (msg: string) => {
    setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  // 一键保存策略
  const handleSaveStrategy = async (): Promise<StrategyResponse | null> => {
    setSaving(true);
    try {
      if (selectedStrategyId === 'new') {
        const customClassName = `CustomStrategy_${Date.now()}`;
        const newStrategy = await createStrategy({
          name: strategyName,
          description: strategyDesc,
          difficulty: 'intermediate',
          tags: ['AI生成', '自定义'],
          code,
          class_name: customClassName,
          parameters: parameters as any,
          advantages: [],
          disadvantages: [],
          algorithm: '',
        });
        if (newStrategy) {
          addLog(`【系统】成功创建自定义策略「${strategyName}」`);
          setSelectedStrategyId(newStrategy.id);
          return newStrategy;
        }
      } else {
        const current = strategies.find((s) => s.id === selectedStrategyId);
        if (current) {
          const updated = await updateStrategy(selectedStrategyId, {
            name: strategyName,
            description: strategyDesc,
            code,
            class_name: current.class_name || `CustomStrategy_${Date.now()}`,
            parameters: parameters as any,
          });
          if (updated) {
            addLog(`【系统】策略「${strategyName}」保存成功`);
            return updated;
          }
        }
      }
    } catch (e: any) {
      addLog(`【错误】策略保存失败: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
    return null;
  };

  // AI 生成代码回调
  const handleCodeGenerated = ({ code, desc, params }: { code: string; desc?: string; params?: Record<string, unknown> }) => {
    setCode(code);
    addLog('✨ AI 策略代码已应用到编辑器');
    if (desc) {
      setStrategyDesc(desc);
      addLog('【系统】策略描述已更新');
    }
    if (params) {
      const formattedParams: Record<string, any> = {};
      Object.entries(params).forEach(([k, v]) => {
        const val = v as { value: unknown; type: string; label: string; min?: number; max?: number };
        formattedParams[k] = {
          value: val.value,
          type: val.type || 'int',
          label: val.label || k,
          ...(val.min !== undefined ? { min: val.min } : {}),
          ...(val.max !== undefined ? { max: val.max } : {}),
        };
      });
      setParameters(formattedParams);
      addLog('【系统】AI 推荐参数已自动填充');
    }
  };


  // 运行回测流程
  const handleRunBacktest = async () => {
    if (running) return;
    setRunning(true);
    setConsoleTab('log');
    setLogs([]);
    setErrorLog('');

    // 注册回测日志实时监听（WebSocket 推送的日志实时追加到面板）
    const unsubscribeBacktestLog = onBacktestLog((logMsg) => {
      addLog(logMsg);
    });

    const t0 = Date.now();

    addLog('🚀 开启编译与回测流程...');

    addLog('步骤 1: 正在自动保存策略代码与配置...');
    const savedStrategy = await handleSaveStrategy();
    if (!savedStrategy) {
      addLog('❌ 策略保存失败，回测中止');
      setRunning(false);
      unsubscribeBacktestLog();
      return;
    }

    addLog(`步骤 2: 策略持久化成功。class_name 为 ${savedStrategy.class_name}`);
    addLog(`步骤 3: 准备启动 vnpy CTA 回测引擎...`);
    addLog(`步骤 4: 正在获取行情历史数据 (标的代码: ${symbol}, 周期: ${period === 'daily' ? '日K' : period}, 时间范围: ${startDate} 至 ${endDate})...`);

    const paramValues: Record<string, any> = {};
    Object.entries(parameters).forEach(([k, v]) => {
      paramValues[k] = v.value;
    });

    try {
      const result = await runBacktest({
        strategy_id: savedStrategy.id,
        symbol,
        interval: 'd',
        period,
        start_date: startDate,
        end_date: endDate,
        initial_capital: initialCapital,
        initial_position: 0,
        params: paramValues,
        commission_rate: 0.0003,
        stamp_tax_rate: 0.001,
        incremental_mode: true,
      });

      if (result) {
        const elapsed = ((Date.now() - t0) / 1000).toFixed(0);
        setBacktestElapsed(`${Math.floor(Number(elapsed) / 60)}分${Number(elapsed) % 60}秒`);
        addLog('步骤 5: vnpy CTA 回测引擎计算完成。读取表现指标...');
        addLog(`【回测结果】策略收益: ${(result.total_return * 100).toFixed(2)}%, 基准收益: ${result.benchmark_return ? (result.benchmark_return * 100).toFixed(2) : '0.00'}%, 夏普比率: ${result.sharpe_ratio.toFixed(2)}, 最大回撤: ${(result.max_drawdown * 100).toFixed(2)}%`);
        // 输出策略代码中的日志
        if (result.strategy_logs && result.strategy_logs.length > 0) {
          addLog('── 策略运行日志 ──');
          result.strategy_logs.forEach((log: string) => addLog(log));
          addLog(`── 共 ${result.strategy_logs.length} 条策略日志 ──`);
        }
        addLog('✨ 编译与回测成功！');
        setBacktestResult(result);
        setViewMode('results');
        setResultTab('overview');
      } else {
        const storeErr = useStrategyStore.getState().error;
        throw new Error(storeErr || '未获得有效回测结果');
      }
    } catch (e: any) {
      const errMsg = e.message || String(e);
      addLog(`❌ 回测运行过程中发生错误！`);
      setErrorLog(errMsg);
      setConsoleTab('error');
    } finally {
      setRunning(false);
      unsubscribeBacktestLog();  // 注销回测日志监听
    }
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // 回测结果视图 (JoinQuant 风格)
  // ═══════════════════════════════════════════════════════════════════════════
  if (viewMode === 'results' && backtestResult) {
    const r = backtestResult;
    const trades = [...(r.trades || [])].sort((a: any, b: any) => (b.date || '').localeCompare(a.date || ''));
    const buyTrades = trades.filter((t: any) => t.side === 'buy');
    const sellTrades = trades.filter((t: any) => t.side === 'sell');

    const RESULT_TABS = [
      { key: 'overview' as const, icon: TrendingUp, label: '收益概述' },
      { key: 'trades' as const, icon: ChevronRight, label: '交易详情' },
      { key: 'logs' as const, icon: Terminal, label: '日志输出' },
      { key: 'code' as const, icon: FileCode2, label: '策略代码' },
    ];

    const sidebarMetrics = [
      { label: '策略收益', value: `${(r.total_return * 100).toFixed(2)}%`, positive: r.total_return >= 0 },
      { label: '基准收益', value: r.benchmark_return != null ? `${(r.benchmark_return * 100).toFixed(2)}%` : '--', positive: (r.benchmark_return ?? 0) >= 0 },
      { label: '阿尔法', value: r.alpha?.toFixed(3) ?? '--', positive: (r.alpha ?? 0) >= 0 },
      { label: '贝塔', value: r.beta?.toFixed(3) ?? '--', positive: true },
      { label: '夏普比率', value: r.sharpe_ratio.toFixed(3), positive: r.sharpe_ratio >= 0 },
      { label: '索提诺比率', value: r.sortino_ratio?.toFixed(3) ?? '--', positive: (r.sortino_ratio ?? 0) >= 0 },
      { label: '波动率', value: r.volatility?.toFixed(3) ?? '--', positive: true },
      { label: '最大回撤', value: `${(r.max_drawdown * 100).toFixed(2)}%`, positive: false },
    ];

    return (
      <div className="flex flex-col h-full">
        {/* 顶部状态栏 */}
        <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setViewMode('editor')}
              className="text-primary-600 hover:text-primary-700 text-sm font-medium flex items-center gap-1"
            >
              ← 返回编辑
            </button>
            <span className="text-gray-300">|</span>
            <span className="font-semibold text-gray-800">{strategyName}</span>
            <span className="text-xs text-gray-400">
              {startDate} ~ {endDate}，¥{initialCapital.toLocaleString()}，{period === 'daily' ? '每天' : period}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5 text-xs">
              <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
              <span className="text-gray-500">回测完成</span>
              {backtestElapsed && <span className="text-gray-400">耗时 {backtestElapsed}</span>}
            </span>
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded font-mono">Python3</span>
          </div>
        </div>

        {/* 主体：左侧栏 + 右侧内容 */}
        <div className="flex flex-1 overflow-hidden">
          {/* 左侧侧边栏 */}
          <div className="w-48 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0 overflow-y-auto">
            <div className="border-b border-gray-200">
              {RESULT_TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setResultTab(tab.key)}
                  className={`w-full flex items-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
                    resultTab === tab.key
                      ? 'bg-primary-600 text-white'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <tab.icon className="w-3.5 h-3.5" />
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="py-2 text-xs">
              {sidebarMetrics.map((m) => (
                <div key={m.label} className="flex items-center justify-between px-4 py-1.5 hover:bg-gray-100 cursor-default">
                  <span className="text-gray-500 flex items-center gap-1">
                    <ChevronRight className="w-3 h-3 text-gray-400" />
                    {m.label}
                  </span>
                  <span className={`font-mono font-semibold ${m.positive ? 'text-red-500' : 'text-green-500'}`}>
                    {m.value}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* 右侧主内容区 */}
          <div className="flex-1 overflow-y-auto bg-white p-6">
            {/* ═══ 收益概述 ═══ */}
            {resultTab === 'overview' && (
              <div className="space-y-6">
                <h3 className="text-sm font-bold text-gray-800 border-b border-gray-100 pb-2">收益概述</h3>
                {/* 两行指标网格 */}
                <div className="space-y-px bg-gray-100 rounded-lg overflow-hidden border border-gray-200">
                  <div className="grid grid-cols-6 bg-white">
                    {[
                      { label: '策略收益', value: `${(r.total_return * 100).toFixed(2)}%`, color: r.total_return >= 0 ? 'text-red-500' : 'text-green-500' },
                      { label: '策略年化收益', value: `${(r.annualized_return * 100).toFixed(2)}%`, color: r.annualized_return >= 0 ? 'text-red-500' : 'text-green-500' },
                      { label: '基准收益', value: r.benchmark_return != null ? `${(r.benchmark_return * 100).toFixed(2)}%` : '--', color: (r.benchmark_return ?? 0) >= 0 ? 'text-red-500' : 'text-green-500' },
                      { label: '阿尔法', value: r.alpha?.toFixed(3) ?? '--', color: 'text-gray-800' },
                      { label: '贝塔', value: r.beta?.toFixed(3) ?? '--', color: 'text-gray-800' },
                      { label: '夏普比率', value: r.sharpe_ratio.toFixed(3), color: 'text-gray-800' },
                    ].map((m) => (
                      <div key={m.label} className="p-3 text-center border-r border-gray-100 last:border-r-0">
                        <p className="text-[10px] text-gray-400 mb-1">{m.label}</p>
                        <p className={`text-sm font-bold font-mono ${m.color}`}>{m.value}</p>
                      </div>
                    ))}
                  </div>
                  <div className="grid grid-cols-6 bg-white">
                    {[
                      { label: '胜率', value: `${(r.win_rate * 100).toFixed(1)}%`, color: 'text-gray-800' },
                      { label: '盈亏比', value: r.profit_factor.toFixed(3), color: 'text-gray-800' },
                      { label: '最大回撤', value: `${(r.max_drawdown * 100).toFixed(2)}%`, color: 'text-green-500' },
                      { label: '总交易次数', value: String(r.total_trades), color: 'text-gray-800' },
                      { label: '波动率', value: r.volatility?.toFixed(3) ?? '--', color: 'text-gray-800' },
                      { label: '索提诺比率', value: r.sortino_ratio?.toFixed(3) ?? '--', color: 'text-gray-800' },
                    ].map((m) => (
                      <div key={m.label} className="p-3 text-center border-r border-gray-100 last:border-r-0">
                        <p className="text-[10px] text-gray-400 mb-1">{m.label}</p>
                        <p className={`text-sm font-bold font-mono ${m.color}`}>{m.value}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 收益曲线图 */}
                {r.daily_results && r.daily_results.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-4 text-xs text-gray-500">
                      <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500 inline-block" /> 策略收益</span>
                      <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-orange-400 inline-block" /> 沪深300</span>
                      <span className="ml-auto text-gray-400 font-mono">{r.start_date} ~ {r.end_date}</span>
                    </div>
                    <div className="h-64 text-xs">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={r.daily_results}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="date" tickFormatter={(v) => String(v).slice(5)} stroke="#bbb" tick={{ fontSize: 10 }} />
                          <YAxis tickFormatter={(v) => `${v}%`} stroke="#bbb" tick={{ fontSize: 10 }} />
                          <Tooltip formatter={(value: number, name: string) => [`${value.toFixed(2)}%`, name]} />
                          <Legend />
                          <Area type="monotone" dataKey="return" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.06} strokeWidth={1.5} name="策略收益" />
                          {r.daily_results.some((d: any) => d.benchmark_return != null) && (
                            <Area type="monotone" dataKey="benchmark_return" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.03} strokeWidth={1.5} name="沪深300" />
                          )}
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ═══ 交易详情 ═══ */}
            {resultTab === 'trades' && (
              <div className="space-y-4">
                <h3 className="text-sm font-bold text-gray-800 border-b border-gray-100 pb-2">交易详情</h3>
                <div className="grid grid-cols-4 gap-3 text-xs">
                  <div className="bg-red-50 rounded-lg p-3 border border-red-100">
                    <p className="text-gray-500">买入</p>
                    <p className="text-base font-bold text-red-600 mt-0.5">{buyTrades.length} 次</p>
                  </div>
                  <div className="bg-green-50 rounded-lg p-3 border border-green-100">
                    <p className="text-gray-500">卖出</p>
                    <p className="text-base font-bold text-green-600 mt-0.5">{sellTrades.length} 次</p>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                    <p className="text-gray-500">买入总额</p>
                    <p className="text-sm font-semibold mt-0.5">¥{buyTrades.reduce((s: number, t: any) => s + t.price * t.quantity, 0).toLocaleString()}</p>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                    <p className="text-gray-500">手续费合计</p>
                    <p className="text-sm font-semibold mt-0.5">¥{trades.reduce((s: number, t: any) => s + (t.commission || 0), 0).toFixed(2)}</p>
                  </div>
                </div>
                {trades.length > 0 ? (
                  <div className="border border-gray-200 rounded-lg overflow-hidden">
                    <div className="max-h-[55vh] overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50 sticky top-0 border-b border-gray-200 text-left">
                          <tr>
                            <th className="px-3 py-2 text-gray-500">序号</th>
                            <th className="px-3 py-2 text-gray-500">日期</th>
                            <th className="px-3 py-2 text-center text-gray-500">方向</th>
                            <th className="px-3 py-2 text-right text-gray-500">价格</th>
                            <th className="px-3 py-2 text-right text-gray-500">数量</th>
                            <th className="px-3 py-2 text-right text-gray-500">金额</th>
                            <th className="px-3 py-2 text-right text-gray-500">手续费</th>
                            <th className="px-3 py-2 text-right text-gray-500">盈亏</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {trades.map((t: any, i: number) => (
                            <tr key={i} className="hover:bg-gray-50">
                              <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                              <td className="px-3 py-2 text-gray-600">{t.date}</td>
                              <td className="px-3 py-2 text-center">
                                <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold ${t.side === 'buy' ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>
                                  {t.side === 'buy' ? '买入' : '卖出'}
                                </span>
                              </td>
                              <td className="px-3 py-2 text-right font-mono">¥{t.price?.toFixed(2)}</td>
                              <td className="px-3 py-2 text-right">{t.quantity}</td>
                              <td className="px-3 py-2 text-right font-mono">¥{((t.price || 0) * (t.quantity || 0)).toLocaleString()}</td>
                              <td className="px-3 py-2 text-right text-gray-400">¥{(t.commission || 0).toFixed(2)}</td>
                              <td className={`px-3 py-2 text-right font-mono font-medium ${t.side === 'sell' && t.pnl > 0 ? 'text-red-500' : t.side === 'sell' && t.pnl < 0 ? 'text-green-500' : 'text-gray-400'}`}>
                                {t.side === 'sell' && t.pnl != null ? `${t.pnl > 0 ? '+' : ''}¥${t.pnl.toFixed(2)}` : '--'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <p className="text-center py-8 text-gray-400 text-sm">暂无交易记录</p>
                )}
              </div>
            )}

            {/* ═══ 日志输出 ═══ */}
            {resultTab === 'logs' && (
              <div className="space-y-3">
                <h3 className="text-sm font-bold text-gray-800 border-b border-gray-100 pb-2">日志输出</h3>
                <div className="bg-[#1a1a1a] rounded-lg p-4 font-mono text-xs leading-relaxed text-green-400/90 max-h-[70vh] overflow-y-auto">
                  {logs.length === 0 ? (
                    <span className="text-gray-600">暂无日志</span>
                  ) : (
                    logs.map((log, i) => (
                      <div key={i} className="whitespace-pre-wrap break-all">{log}</div>
                    ))
                  )}
                  {errorLog && (
                    <pre className="text-red-400 mt-4 whitespace-pre-wrap break-all border-t border-gray-800 pt-3">{errorLog}</pre>
                  )}
                </div>
              </div>
            )}

            {/* ═══ 策略代码 ═══ */}
            {resultTab === 'code' && (
              <div className="space-y-3">
                <h3 className="text-sm font-bold text-gray-800 border-b border-gray-100 pb-2">策略代码（只读）</h3>
                <pre className="bg-[#1e1e1e] text-gray-200 rounded-lg p-4 font-mono text-xs leading-relaxed max-h-[70vh] overflow-y-auto whitespace-pre-wrap">{code}</pre>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 默认编辑器视图
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <div className="space-y-5 flex flex-col">
      {/* 头部控制栏 */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary-50 text-primary-600 rounded-lg">
            <FolderOpen className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <select
                value={selectedStrategyId}
                onChange={(e) => setSelectedStrategyId(e.target.value)}
                className="font-semibold text-gray-800 bg-transparent outline-none focus:ring-1 focus:ring-primary-500 rounded px-1.5 py-0.5 border border-transparent hover:border-gray-200 cursor-pointer"
              >
                <option value="new">+ 新建自定义策略</option>
                {customStrategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <p className="text-xs text-gray-400 mt-0.5">选择现有策略或创建新策略</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsMyStrategiesOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition"
          >
            <FolderOpen className="w-4 h-4 text-primary-500" />
            我的策略
          </button>
          <button
            onClick={() => {
              fetchBacktestResults();
              setIsHistoryOpen(true);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition"
          >
            <Clock className="w-4 h-4 text-primary-500" />
            回测历史
          </button>
          <button
            onClick={() => setSelectedStrategyId('new')}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition"
          >
            <Plus className="w-4 h-4" />
            新建策略
          </button>
          {backtestResult && (
            <button
              onClick={() => { setViewMode('results'); setResultTab('overview'); }}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-primary-200 rounded-lg text-sm text-primary-600 hover:bg-primary-50 transition"
            >
              <Eye className="w-4 h-4" />
              回测详情
            </button>
          )}
        </div>
      </div>

      {/* 主工作区：上方左右分栏占满首屏，下方回测+日志自然滚动到第二屏 */}
      <div className="flex flex-col gap-4">
        {/* 上半区：AI生成(左) + 代码编辑器(右) —— 占满首屏剩余高度 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4" style={{ height: 'calc(100vh - 160px)' }}>
          {/* 左侧：AI 策略生成面板 */}
          <div className="lg:col-span-6 flex flex-col bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm h-full">
            <AIChatPanel
              mode="generate"
              strategyContext={{
                name: strategyName,
                description: strategyDesc,
                parameters,
                code,
              }}
              onCodeGenerated={handleCodeGenerated}
            />
          </div>

          {/* 右侧：代码编辑器 */}
          <div className="lg:col-span-6 flex flex-col bg-[#1e1e1e] border border-gray-800 rounded-xl overflow-hidden shadow-lg h-full">
            {/* 编辑器状态栏 */}
            <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 text-gray-400 text-xs">
              <div className="flex items-center gap-3">
                <span className="flex items-center gap-1 text-gray-300 font-medium">
                  <FileCode2 className="w-3.5 h-3.5 text-yellow-500" />
                  <input
                    type="text"
                    value={strategyName}
                    onChange={(e) => setStrategyName(e.target.value)}
                    className="bg-transparent border-b border-transparent hover:border-gray-600 focus:border-primary-500 focus:outline-none px-1 py-0.5 rounded font-mono text-gray-200 w-44 font-semibold"
                  />
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="font-mono text-gray-500">Python 3</span>
                <button
                  onClick={handleSaveStrategy}
                  disabled={saving}
                  className="flex items-center gap-1 px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded transition disabled:opacity-50"
                >
                  <Save className="w-3 h-3" />
                  {saving ? '保存中...' : '保存'}
                </button>
              </div>
            </div>

            {/* 编辑器主体 */}
            <div className="flex-1 flex overflow-hidden font-mono text-sm leading-relaxed relative">
              <div
                ref={lineRef}
                className="w-12 bg-[#1a1a1a] text-gray-600 py-3 text-right pr-3 select-none border-r border-[#2d2d2d] overflow-hidden"
                style={{ userSelect: 'none' }}
              >
                {lineNumbers.map((n) => (
                  <div key={n} style={{ height: '24px' }}>
                    {n}
                  </div>
                ))}
              </div>
              <textarea
                ref={textareaRef}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onScroll={handleScroll}
                className="flex-1 bg-[#1e1e1e] text-gray-200 p-3 h-full outline-none resize-none overflow-y-auto overflow-x-hidden font-mono whitespace-pre-wrap break-all"
                style={{ lineHeight: '24px', tabSize: 4 }}
                spellCheck={false}
                placeholder="编写您的交易策略代码..."
              />
            </div>
          </div>
        </div>

        {/* 下半区：回测设置 + 控制台 —— 自然排列到第二屏 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* 回测配置 */}
          <div className="lg:col-span-6 bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
            <div className="flex items-center justify-between border-b border-gray-100 pb-2 mb-3">
              <div className="flex items-center gap-2">
                <Settings className="w-4 h-4 text-primary-600" />
                <h3 className="font-semibold text-gray-800 text-sm">回测设置</h3>
              </div>
              <button
                onClick={handleRunBacktest}
                disabled={running}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-xs font-medium transition shadow-sm disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5" />
                {running ? '编译中...' : '编译运行'}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div>
                <label className="block text-gray-500 font-medium mb-0.5">标的</label>
                <StockSearchInput value={symbol} onChange={setSymbol} />
              </div>
              <div>
                <label className="block text-gray-500 font-medium mb-0.5">频率</label>
                <select value={period} onChange={(e) => setPeriod(e.target.value)} className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500 text-xs">
                  <option value="daily">日线</option>
                  <option value="5m">5分钟</option>
                  <option value="1m">1分钟</option>
                </select>
              </div>
              <div>
                <label className="block text-gray-500 font-medium mb-0.5">起始日期</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500 text-xs" />
              </div>
              <div>
                <label className="block text-gray-500 font-medium mb-0.5">结束日期</label>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500 text-xs" />
              </div>
              <div>
                <label className="block text-gray-500 font-medium mb-0.5">初始资金</label>
                <input type="number" value={initialCapital} onChange={(e) => setInitialCapital(Number(e.target.value))} className="w-full px-2 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary-500 text-xs font-mono" />
              </div>
            </div>
            {Object.keys(parameters).length > 0 && (
              <div className="mt-2 bg-gray-50 p-2 rounded-lg border border-gray-150">
                <span className="text-[9px] text-gray-500 font-bold uppercase tracking-wider block mb-1">调优参数</span>
                <div className="flex flex-wrap gap-2 text-xs">
                  {Object.entries(parameters).map(([key, item]: [string, any]) => (
                    <div key={key} className="flex items-center gap-1 bg-white border border-gray-200 rounded px-2 py-1">
                      <span className="text-gray-600 text-[10px] truncate max-w-[60px]" title={item.label || key}>{item.label || key}</span>
                      <input
                        type="number"
                        step={item.type === 'float' ? '0.01' : '1'}
                        value={item.value}
                        onChange={(e) => {
                          const val = item.type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value);
                          setParameters((prev) => ({
                            ...prev,
                            [key]: { ...prev[key], value: isNaN(val) ? '' : val },
                          }));
                        }}
                        className="w-12 text-right border-b border-dashed border-gray-300 outline-none focus:border-primary-500 font-mono text-gray-800 text-xs"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 终端控制台 */}
          <div className="lg:col-span-6 bg-black border border-gray-900 rounded-xl overflow-hidden flex flex-col h-[500px]">
            <div className="flex items-center justify-between px-3 py-1.5 bg-[#141414] border-b border-gray-900 text-xs">
              <div className="flex gap-4">
                <button
                  onClick={() => setConsoleTab('log')}
                  className={`flex items-center gap-1.5 font-bold uppercase transition ${
                    consoleTab === 'log' ? 'text-primary-500 border-b-2 border-primary-500 pb-0.5 -mb-1.5' : 'text-gray-500 hover:text-gray-400'
                  }`}
                >
                  <Terminal className="w-3 h-3" />
                  日志
                </button>
                <button
                  onClick={() => setConsoleTab('error')}
                  className={`flex items-center gap-1.5 font-bold uppercase transition ${
                    consoleTab === 'error' ? 'text-red-500 border-b-2 border-red-500 pb-0.5 -mb-1.5' : 'text-gray-500 hover:text-gray-400'
                  }`}
                >
                  <AlertTriangle className="w-3 h-3" />
                  错误
                  {errorLog && <span className="w-1.5 h-1.5 rounded-full bg-red-500 block" />}
                </button>
              </div>
              <span className="text-[10px] text-gray-600 font-mono">CONSOLE</span>
            </div>
            <div className="flex-1 p-3 overflow-y-auto font-mono text-xs leading-relaxed text-[#c5c5c5] select-text">
              {consoleTab === 'log' ? (
                logs.length === 0 ? (
                  <div className="text-gray-700 h-full flex items-center justify-center text-xs">等待编译运行以打印输出...</div>
                ) : (
                  <div className="space-y-0.5">
                    {logs.map((log, i) => (
                      <div key={i} className="whitespace-pre-wrap break-all text-green-400/90">{log}</div>
                    ))}
                  </div>
                )
              ) : errorLog ? (
                <div className="space-y-2">
                  <div className="text-red-500 font-bold flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    回测执行失败：
                  </div>
                  <pre className="text-red-400/90 whitespace-pre-wrap break-all bg-red-950/20 p-3 border border-red-950/50 rounded-lg leading-relaxed">{errorLog}</pre>
                </div>
              ) : (
                <div className="text-gray-700 h-full flex items-center justify-center">暂无编译与执行错误。</div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 我的策略管理模态框 */}
      {isMyStrategiesOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setIsMyStrategiesOpen(false)}>
          <div className="bg-white rounded-xl w-full max-w-5xl max-h-[80vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-gray-100">
              <div>
                <h2 className="text-lg font-bold text-gray-900">我的策略管理</h2>
                <p className="text-xs text-gray-400 mt-0.5">查看、加载或删除您编写的自定义策略</p>
              </div>
              <button
                onClick={() => setIsMyStrategiesOpen(false)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* 批量操作栏 */}
            {selectedStrategyIds.size > 0 && (
              <div className="flex items-center justify-between bg-primary-50 border-b border-primary-100 px-5 py-2.5">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-primary-700 font-medium">已选择 {selectedStrategyIds.size} 个策略</span>
                  <button
                    onClick={() => setSelectedStrategyIds(new Set())}
                    className="text-xs text-primary-500 hover:text-primary-700 underline"
                  >
                    取消选择
                  </button>
                </div>
                <button
                  onClick={() => setBatchDeleteConfirm({ type: 'strategy', count: selectedStrategyIds.size })}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition text-sm"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  批量删除
                </button>
              </div>
            )}

            <div className="flex-1 overflow-y-auto p-5">
              {customStrategies.length === 0 ? (
                <div className="text-center py-12 text-gray-400 text-sm">
                  暂无自定义策略，您可以在编辑器中编写并保存新策略。
                </div>
              ) : (
                <div className="border border-gray-150 rounded-lg overflow-hidden">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-gray-50 border-b border-gray-150 text-xs font-semibold text-gray-500 uppercase">
                      <tr>
                        <th className="px-4 py-3 w-10">
                          <button
                            onClick={() => {
                              if (selectedStrategyIds.size === customStrategies.length) {
                                setSelectedStrategyIds(new Set());
                              } else {
                                setSelectedStrategyIds(new Set(customStrategies.map((s) => s.id)));
                              }
                            }}
                            className="text-primary-600 hover:text-primary-700 transition"
                          >
                            {selectedStrategyIds.size === customStrategies.length
                              ? <CheckSquare className="w-4 h-4" />
                              : <Square className="w-4 h-4 text-gray-300" />
                            }
                          </button>
                        </th>
                        <th className="px-4 py-3">策略名称</th>
                        <th className="px-4 py-3">策略描述</th>
                        <th className="px-4 py-3">修改时间</th>
                        <th className="px-4 py-3 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-150">
                      {customStrategies.map((s) => (
                        <tr key={s.id} className={`hover:bg-gray-50 transition-colors ${selectedStrategyIds.has(s.id) ? 'bg-primary-50/50' : ''}`}>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => {
                                setSelectedStrategyIds((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(s.id)) next.delete(s.id); else next.add(s.id);
                                  return next;
                                });
                              }}
                              className="text-primary-600 hover:text-primary-700 transition"
                            >
                              {selectedStrategyIds.has(s.id)
                                ? <CheckSquare className="w-4 h-4" />
                                : <Square className="w-4 h-4 text-gray-300" />
                              }
                            </button>
                          </td>
                          <td className="px-4 py-3 font-semibold text-gray-900">{s.name}</td>
                          <td className="px-4 py-3 text-gray-500 max-w-xs truncate" title={s.description}>
                            {s.description || '无描述'}
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                            {formatDateTime(s.updated_at || s.created_at)}
                          </td>
                          <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                            <button
                              onClick={() => {
                                setSelectedStrategyId(s.id);
                                setIsMyStrategiesOpen(false);
                                addLog(`【系统】已成功载入策略「${s.name}」`);
                              }}
                              className="px-2.5 py-1 bg-primary-50 hover:bg-primary-100 text-primary-600 text-xs font-semibold rounded transition"
                            >
                              载入
                            </button>
                            <button
                              onClick={async () => {
                                if (confirm(`确定要删除策略「${s.name}」吗？此操作不可恢复。`)) {
                                  await deleteStrategy(s.id);
                                  if (selectedStrategyId === s.id) {
                                    setSelectedStrategyId('new');
                                  }
                                  addLog(`【系统】已成功删除策略「${s.name}」`);
                                }
                              }}
                              className="p-1 text-red-500 hover:bg-red-50 rounded transition inline-flex items-center justify-center align-middle"
                              title="删除策略"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 回测历史模态框 */}
      {isHistoryOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setIsHistoryOpen(false)}>
          <div className="bg-white rounded-xl w-full max-w-[90vw] max-h-[85vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-gray-100">
              <div>
                <h2 className="text-lg font-bold text-gray-900">回测历史记录</h2>
                <p className="text-xs text-gray-400 mt-0.5">查看、分析历史回测表现，载入回测参数</p>
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={filterCurrentOnly}
                    onChange={(e) => setFilterCurrentOnly(e.target.checked)}
                    className="rounded text-primary-600 focus:ring-primary-500 w-3.5 h-3.5"
                  />
                  仅显示当前选中的策略
                </label>
                <button
                  onClick={() => setIsHistoryOpen(false)}
                  className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* 批量操作栏 */}
            {selectedResultIds.size > 0 && (
              <div className="flex items-center justify-between bg-primary-50 border-b border-primary-100 px-5 py-2.5">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-primary-700 font-medium">已选择 {selectedResultIds.size} 条记录</span>
                  <button
                    onClick={() => setSelectedResultIds(new Set())}
                    className="text-xs text-primary-500 hover:text-primary-700 underline"
                  >
                    取消选择
                  </button>
                </div>
                <button
                  onClick={() => setBatchDeleteConfirm({ type: 'backtest', count: selectedResultIds.size })}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition text-sm"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  批量删除
                </button>
              </div>
            )}

            <div className="flex-1 overflow-y-auto p-5">
              {filteredBacktestResults.length === 0 ? (
                <div className="text-center py-12 text-gray-400 text-sm">
                  没有找到匹配的回测历史记录。
                </div>
              ) : (
                <div className="border border-gray-150 rounded-lg overflow-hidden">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-gray-50 border-b border-gray-150 text-xs font-semibold text-gray-500 uppercase">
                      <tr>
                        <th className="px-4 py-3 w-10">
                          <button
                            onClick={() => {
                              if (selectedResultIds.size === filteredBacktestResults.length) {
                                setSelectedResultIds(new Set());
                              } else {
                                setSelectedResultIds(new Set(filteredBacktestResults.map((r) => r.id)));
                              }
                            }}
                            className="text-primary-600 hover:text-primary-700 transition"
                          >
                            {selectedResultIds.size === filteredBacktestResults.length
                              ? <CheckSquare className="w-4 h-4" />
                              : <Square className="w-4 h-4 text-gray-300" />
                            }
                          </button>
                        </th>
                        <th className="px-4 py-3">策略</th>
                        <th className="px-4 py-3">标的</th>
                        <th className="px-4 py-3">数据周期</th>
                        <th className="px-4 py-3">回测区间</th>
                        <th className="px-4 py-3 text-right">总收益率</th>
                        <th className="px-4 py-3 text-right">夏普比率</th>
                        <th className="px-4 py-3 text-right">最大回撤</th>
                        <th className="px-4 py-3">创建时间</th>
                        <th className="px-4 py-3 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-150">
                      {filteredBacktestResults.map((r) => {
                        const sName = strategies.find((s) => s.id === r.strategy_id)?.name || '未知策略';
                        const returnColor = r.total_return >= 0 ? 'text-red-500' : 'text-green-500';
                        return (
                          <tr key={r.id} className={`hover:bg-gray-50 transition-colors ${selectedResultIds.has(r.id) ? 'bg-primary-50/50' : ''}`}>
                            <td className="px-4 py-3">
                              <button
                                onClick={() => {
                                  setSelectedResultIds((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(r.id)) next.delete(r.id); else next.add(r.id);
                                    return next;
                                  });
                                }}
                                className="text-primary-600 hover:text-primary-700 transition"
                              >
                                {selectedResultIds.has(r.id)
                                  ? <CheckSquare className="w-4 h-4" />
                                  : <Square className="w-4 h-4 text-gray-300" />
                                }
                              </button>
                            </td>
                            <td className="px-4 py-3 font-medium text-gray-900">{sName}</td>
                            <td className="px-4 py-3 font-mono">{r.symbol}</td>
                            <td className="px-4 py-3">{r.period === 'daily' ? '日线' : r.period === '5m' ? '5m' : r.period === '1m' ? '1m' : r.period}</td>
                            <td className="px-4 py-3 text-xs text-gray-500 font-mono">
                              {r.start_date} ~ {r.end_date}
                            </td>
                            <td className={`px-4 py-3 text-right font-semibold font-mono ${returnColor}`}>
                              {r.total_return >= 0 ? '+' : ''}{(r.total_return * 100).toFixed(2)}%
                            </td>
                            <td className="px-4 py-3 text-right font-mono">{r.sharpe_ratio.toFixed(2)}</td>
                            <td className="px-4 py-3 text-right font-mono text-green-500">{(r.max_drawdown * 100).toFixed(2)}%</td>
                            <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                              {formatDateTime(r.created_at)}
                            </td>
                            <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                              <button
                                onClick={() => {
                                  setBacktestResult(r);
                                  setViewMode('results');
                                  setResultTab('overview');
                                  setIsHistoryOpen(false);
                                  addLog(`【系统】载入回测结果：策略「${sName}」，标的「${r.symbol}」`);
                                }}
                                className="px-2 py-0.5 bg-primary-50 hover:bg-primary-100 text-primary-600 text-xs font-semibold rounded transition"
                              >
                                查看结果
                              </button>
                              <button
                                onClick={() => {
                                  // 载入回测参数到当前编辑框
                                  setSymbol(r.symbol);
                                  setPeriod(r.period || 'daily');
                                  setStartDate(r.start_date);
                                  setEndDate(r.end_date);
                                  setInitialCapital(r.initial_capital);

                                  // 载入参数配置值
                                  const currentS = strategies.find(s => s.id === r.strategy_id);
                                  if (currentS) {
                                    setSelectedStrategyId(r.strategy_id);
                                  }

                                  // 更新调优参数的值
                                  const loadedParams: Record<string, any> = {};
                                  Object.entries(parameters).forEach(([k, v]) => {
                                    if (r.params && r.params[k] !== undefined) {
                                      loadedParams[k] = { ...v, value: r.params[k] };
                                    } else {
                                      loadedParams[k] = v;
                                    }
                                  });
                                  setParameters(loadedParams);

                                  setIsHistoryOpen(false);
                                  addLog(`【系统】已将回测配置载入工作区！`);
                                }}
                                className="px-2 py-0.5 bg-blue-50 hover:bg-blue-100 text-blue-600 text-xs font-semibold rounded transition"
                                title="将当时的回测参数和区间载入编辑区"
                              >
                                载入参数
                              </button>
                              <button
                                onClick={async () => {
                                  if (confirm('确认删除该条回测记录吗？')) {
                                    await deleteBacktestResult(r.id);
                                    addLog(`【系统】已删除该条回测历史记录`);
                                  }
                                }}
                                className="p-1 text-red-500 hover:bg-red-50 rounded transition inline-flex items-center justify-center align-middle"
                                title="删除记录"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 批量删除确认弹窗 */}
      {batchDeleteConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={() => setBatchDeleteConfirm(null)}>
          <div className="bg-white rounded-xl shadow-lg p-6 w-80" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-900">确认批量删除</h3>
            <p className="mt-2 text-sm text-gray-500">
              确定要删除选中的 {batchDeleteConfirm.count} 条{batchDeleteConfirm.type === 'strategy' ? '策略' : '回测记录'}吗？此操作不可撤销。
            </p>
            <div className="mt-4 flex justify-end gap-3">
              <button
                onClick={() => setBatchDeleteConfirm(null)}
                className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition"
              >
                取消
              </button>
              <button
                onClick={async () => {
                  if (batchDeleteConfirm.type === 'strategy') {
                    await batchDeleteStrategies([...selectedStrategyIds]);
                    addLog(`【系统】已批量删除 ${selectedStrategyIds.size} 个策略`);
                    setSelectedStrategyIds(new Set());
                  } else {
                    await batchDeleteBacktestResults([...selectedResultIds]);
                    addLog(`【系统】已批量删除 ${selectedResultIds.size} 条回测记录`);
                    setSelectedResultIds(new Set());
                  }
                  setBatchDeleteConfirm(null);
                }}
                className="px-4 py-2 text-sm text-white bg-red-500 rounded-lg hover:bg-red-600 transition"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
