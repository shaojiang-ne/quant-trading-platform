import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  Search, Loader2, RefreshCw, Wifi, WifiOff, TrendingUp, Calendar,
  Building2, Scale, FileText, Coins, Banknote,
} from 'lucide-react';
import { marketApi, researchApi } from '@/api';
import type { DataSourceInfo, KlineBar } from '@/api/market';
import { useStockCacheStore, type StockInfo } from '@/stores/stockCacheStore';
import KlineChart from '@/components/KlineChart';

// ── 股票搜索输入框 ────────────────────────────────────────────────────────────
interface StockSelection {
  code: string;
  name: string;
  exchange: string;
}

function SymbolInput({ value, onChange }: { value: string; onChange: (info: StockSelection | null) => void }) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<StockInfo[]>([]);
  const [showDrop, setShowDrop] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const { loaded, fetchAll, search, lookup } = useStockCacheStore();

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // 外部 value 变化时同步输入框显示（非聚焦状态），但 value 为空时不覆盖用户输入
  useEffect(() => {
    if (!isFocused) {
      if (value) {
        const pureCode = value.split('.')[0];
        const stock = lookup(pureCode);
        setQuery(stock ? `${stock.code} ${stock.name}` : value);
      } else if (!query.trim()) {
        setQuery('');
      }
    }
  }, [value, isFocused, lookup, query]);

  // 输入时展示搜索建议（不再自动同步给父组件）
  useEffect(() => {
    if (!query.trim() || !loaded) {
      setResults([]);
      setShowDrop(false);
      return;
    }
    const timer = setTimeout(() => {
      const m = query.trim().match(/\b(\d{6})\b/);
      const searchKey = m ? m[1] : query.trim();
      const res = search(searchKey);
      setResults(res);
      if (res.length > 0 && inputRef.current) {
        const rect = inputRef.current.getBoundingClientRect();
        setPos({ top: rect.bottom + 4, left: rect.left, width: rect.width });
      }
      setShowDrop(isFocused && res.length > 0);
    }, 150);
    return () => clearTimeout(timer);
  }, [query, loaded, search, isFocused]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current?.contains(e.target as Node)) return;
      if (inputRef.current?.contains(e.target as Node)) return;
      setShowDrop(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = (stock: StockInfo) => {
    setQuery(`${stock.code} ${stock.name}`);
    onChange({ code: stock.code, name: stock.name, exchange: stock.exchange });
    setShowDrop(false);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setQuery(v);
    if (!v.trim()) {
      onChange(null);
    }
  };

  const handleBlur = () => {
    setIsFocused(false);
    setShowDrop(false);
  };

  const dropdown = showDrop && results.length > 0 ? (
    <div ref={dropRef} style={{ position: 'fixed', top: pos.top, left: pos.left, width: pos.width, zIndex: 9999 }}
      className="bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto">
      {results.map((s) => (
        <button key={s.code} onClick={() => handleSelect(s)}
          className="w-full px-3 py-2 text-left flex items-center justify-between hover:bg-primary-50 transition-colors">
          <span className="font-mono text-gray-900">{s.code}</span>
          <span className="text-gray-600">{s.name}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div className="relative">
      <input ref={inputRef} type="text" value={query} onChange={handleChange}
        onFocus={() => setIsFocused(true)}
        onBlur={handleBlur}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            inputRef.current?.blur();
          }
        }}
        placeholder="输入代码、名称或拼音"
        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
      {dropdown && createPortal(dropdown, document.body)}
    </div>
  );
}

// ── 股票基本信息卡片 ────────────────────────────────────────────────────────
interface BasicInfoData {
  name: string;
  code: string;
  industry: string;
  price: number;
  pe_ttm: number;
  pb: number;
  mcap_yi: number;
  float_mcap_yi: number;
  total_shares_yi: number;
  float_shares_yi: number;
  turnover_pct: number;
  list_date: string;
  change_pct: number;
}

function StockBasicInfoCard({ info, loading }: { info: BasicInfoData | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="bg-gray-50 rounded-lg p-4 animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-1/3 mb-2" />
        <div className="h-3 bg-gray-200 rounded w-1/2" />
      </div>
    );
  }
  if (!info) return null;
  const up = info.change_pct >= 0;
  return (
    <div className="bg-gray-50 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-2">
        <h3 className="text-lg font-semibold text-gray-900">{info.name}</h3>
        <span className="font-mono text-sm text-gray-500">{info.code}</span>
        {info.industry && <span className="text-xs px-2 py-0.5 bg-white border border-gray-200 rounded text-gray-600">{info.industry}</span>}
        <span className={`ml-auto text-sm font-medium ${up ? 'text-red-500' : 'text-green-500'}`}>
          {up ? '+' : ''}{info.change_pct.toFixed(2)}%
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4 text-sm">
        <div><span className="text-gray-500">现价</span><div className="font-mono font-medium">{info.price.toFixed(2)}</div></div>
        <div><span className="text-gray-500">PE(TTM)</span><div className="font-mono font-medium">{info.pe_ttm?.toFixed(2) || '-'}</div></div>
        <div><span className="text-gray-500">PB</span><div className="font-mono font-medium">{info.pb?.toFixed(2) || '-'}</div></div>
        <div><span className="text-gray-500">总市值</span><div className="font-mono font-medium">{(info.mcap_yi / 1e8).toFixed(2)}亿</div></div>
        <div><span className="text-gray-500">流通市值</span><div className="font-mono font-medium">{(info.float_mcap_yi / 1e8).toFixed(2)}亿</div></div>
        <div><span className="text-gray-500">总股本</span><div className="font-mono font-medium">{info.total_shares_yi.toFixed(2)}亿</div></div>
        <div><span className="text-gray-500">流通股</span><div className="font-mono font-medium">{info.float_shares_yi.toFixed(2)}亿</div></div>
        <div><span className="text-gray-500">上市日期</span><div className="font-mono font-medium">{info.list_date || '-'}</div></div>
      </div>
    </div>
  );
}

// ── 数据源优先级徽章 ────────────────────────────────────────────────────────
function PriorityBadge({ priority, label }: { priority: number | null; label: string }) {
  if (priority === null || priority === undefined) {
    return <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-400 rounded">{label}-</span>;
  }
  const colors = ['bg-yellow-100 text-yellow-700', 'bg-gray-100 text-gray-600', 'bg-orange-100 text-orange-700', 'bg-blue-100 text-blue-700', 'bg-purple-100 text-purple-700'];
  const cls = colors[priority - 1] || colors[1];
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{label}#{priority}</span>;
}

// ── 主页面 ──────────────────────────────────────────────────────────────────
const periodOptions = [
  { value: '1m', label: '1分钟' },
  { value: '5m', label: '5分钟' },
  { value: '15m', label: '15分钟' },
  { value: '30m', label: '30分钟' },
  { value: '60m', label: '60分钟' },
  { value: '1d', label: '日线' },
  { value: '1w', label: '周线' },
  { value: '1M', label: '月线' },
];

const sourceOptions = [
  { value: 'auto', label: '自动降级' },
  { value: 'akshare', label: 'akshare' },
  { value: 'efinance', label: 'efinance' },
  { value: 'baostock', label: 'baostock' },
  { value: 'sina', label: 'sina' },
  { value: 'tencent', label: 'tencent' },
  { value: 'xtquant', label: 'xtquant' },
  { value: 'mootdx', label: 'mootdx' },
];

const sourceColors: Record<string, string> = {
  mootdx: 'bg-blue-50 border-blue-200',
  akshare: 'bg-green-50 border-green-200',
  efinance: 'bg-indigo-50 border-indigo-200',
  baostock: 'bg-purple-50 border-purple-200',
  sina: 'bg-orange-50 border-orange-200',
  tencent: 'bg-cyan-50 border-cyan-200',
  xtquant: 'bg-slate-50 border-slate-200',
};

const sourceDotColors: Record<string, string> = {
  mootdx: 'bg-blue-400',
  akshare: 'bg-green-400',
  efinance: 'bg-indigo-400',
  baostock: 'bg-purple-400',
  sina: 'bg-orange-400',
  tencent: 'bg-cyan-400',
  xtquant: 'bg-slate-400',
};

export function TradingData() {
  const [sources, setSources] = useState<DataSourceInfo[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState('');

  const [symbol, setSymbol] = useState('');
  const [stockSelection, setStockSelection] = useState<StockSelection | null>(null);
  const { search: searchStock, loaded: stockCacheLoaded, loading: stockCacheLoading, fetchAll: fetchStockCache } = useStockCacheStore();

  const [activeTab, setActiveTab] = useState('kline');
  const [basicInfo, setBasicInfo] = useState<BasicInfoData | null>(null);
  const [basicInfoLoading, setBasicInfoLoading] = useState(false);

  const [period, setPeriod] = useState('1d');
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [dataSource, setDataSource] = useState('auto');

  const [klines, setKlines] = useState<KlineBar[]>([]);
  const [klinesSource, setKlinesSource] = useState('');
  const [klinesLoading, setKlinesLoading] = useState(false);
  const [klinesError, setKlinesError] = useState('');
  const [klinePage, setKlinePage] = useState(0);
  const pageSize = 20;

  // 为每个基本面 tab 单独缓存数据（避免切换时重复请求）
  const [fundDataMap, setFundDataMap] = useState<Record<string, Record<string, any>[]>>({});
  const [fundColumnsMap, setFundColumnsMap] = useState<Record<string, string[]>>({});
  const [fundLoadingMap, setFundLoadingMap] = useState<Record<string, boolean>>({});
  const [fundErrorMap, setFundErrorMap] = useState<Record<string, string>>({});

  const fundTabs = ['abstract', 'indicators', 'income', 'balance', 'cashflow', 'dividend'];
  const fundData = fundDataMap[activeTab] || [];
  const fundColumns = fundColumnsMap[activeTab] || [];
  const fundLoading = fundLoadingMap[activeTab] || false;
  const fundError = fundErrorMap[activeTab] || '';

  const fetchSources = useCallback(async () => {
    setSourcesLoading(true);
    setSourcesError('');
    try {
      const data = await marketApi.getDataSources();
      setSources(data);
    } catch (e: any) {
      setSourcesError(e.message || '获取数据源状态失败');
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  useEffect(() => {
    if (!stockSelection?.code) {
      setBasicInfo(null);
      return;
    }
    const code = stockSelection.code;
    setBasicInfoLoading(true);
    Promise.all([
      researchApi.stockInfo(code).catch(() => ({})),
      researchApi.quote(code).catch(() => ({})),
    ]).then(([info, quoteData]) => {
      const q = (quoteData as any)[code] || quoteData || {};
      setBasicInfo({
        name: stockSelection.name || (info as any).name || q.name || code,
        code,
        industry: (info as any).industry || '',
        price: q.price || (info as any).price || 0,
        pe_ttm: q.pe_ttm || 0,
        pb: q.pb || 0,
        mcap_yi: q.mcap_yi || 0,
        float_mcap_yi: q.float_mcap_yi || 0,
        total_shares_yi: ((info as any).total_shares || 0) / 1e8,
        float_shares_yi: ((info as any).float_shares || 0) / 1e8,
        turnover_pct: q.turnover_pct || 0,
        list_date: (info as any).list_date || '',
        change_pct: q.change_pct || 0,
      });
      setBasicInfoLoading(false);
    }).catch(() => {
      setBasicInfo(null);
      setBasicInfoLoading(false);
    });
  }, [stockSelection]);

  const handleStockSelect = (info: StockSelection | null) => {
    setStockSelection(info);
    if (info?.code && info?.exchange) {
      setSymbol(`${info.code}.${info.exchange}`);
    } else {
      setSymbol(info?.code || '');
    }
  };

  // 点击查询时从输入框 DOM 实时解析股票代码
  const parseSymbolFromInput = (): string => {
    const el = document.querySelector<HTMLInputElement>('input[placeholder="输入代码、名称或拼音"]');
    const raw = el?.value?.trim() || '';
    console.log('[parseSymbolFromInput] raw input:', raw, 'stockCacheLoaded:', stockCacheLoaded);
    if (!raw || !stockCacheLoaded) return '';

    // 检查股票缓存是否有数据
    const allStocks = useStockCacheStore.getState().stocks;
    console.log('[parseSymbolFromInput] total stocks in cache:', allStocks.length, 'first 3:', allStocks.slice(0, 3));

    // 尝试提取6位数字代码
    const m = raw.match(/\b(\d{6})\b/);
    if (m) {
      // 如果找到数字代码，直接用代码精确查找
      const code = m[1];
      const res = searchStock(code);
      console.log('[parseSymbolFromInput] search by code:', code, 'results:', res.length, 'first result:', res[0]);
      if (res.length > 0) {
        const stock = res[0];
        const fullSymbol = stock.exchange ? `${stock.code}.${stock.exchange}` : stock.code;
        setSymbol(fullSymbol);
        setStockSelection({ code: stock.code, name: stock.name, exchange: stock.exchange });
        return fullSymbol;
      }
    } else {
      // 如果没有数字代码，可能是股票名称或拼音
      // 尝试精确匹配名称
      const exactMatch = allStocks.find(s => s.name === raw);
      if (exactMatch) {
        console.log('[parseSymbolFromInput] exact name match:', exactMatch);
        const fullSymbol = exactMatch.exchange ? `${exactMatch.code}.${exactMatch.exchange}` : exactMatch.code;
        setSymbol(fullSymbol);
        setStockSelection({ code: exactMatch.code, name: exactMatch.name, exchange: exactMatch.exchange });
        return fullSymbol;
      }

      // 如果没有精确匹配，使用模糊搜索
      const res = searchStock(raw);
      console.log('[parseSymbolFromInput] fuzzy search results:', res.length);
      if (res.length > 0) {
        const stock = res[0];
        const fullSymbol = stock.exchange ? `${stock.code}.${stock.exchange}` : stock.code;
        setSymbol(fullSymbol);
        setStockSelection({ code: stock.code, name: stock.name, exchange: stock.exchange });
        return fullSymbol;
      }
    }

    console.log('[parseSymbolFromInput] no stock found');
    return '';
  };

  const handleQueryKlines = async () => {
    const querySymbol = symbol || parseSymbolFromInput();
    if (!querySymbol) {
      setKlinesError('请先输入并选择股票');
      return;
    }
    setKlinesLoading(true);
    setKlinesError('');
    setKlines([]);
    setKlinePage(0);
    try {
      const res = await marketApi.getKlines({
        symbol: querySymbol, period, start_time: startDate, end_time: endDate, source: dataSource,
      });
      setKlines(res.klines);
      setKlinesSource(res.source);
    } catch (e: any) {
      setKlinesError(e.message || '查询K线数据失败');
    } finally {
      setKlinesLoading(false);
    }
  };

  const loadFundamentalForTab = async (querySymbol: string, tab: string) => {
    setFundLoadingMap((prev) => ({ ...prev, [tab]: true }));
    setFundErrorMap((prev) => ({ ...prev, [tab]: '' }));
    try {
      let res: any;
      let cols: string[] = [];
      switch (tab) {
        case 'abstract':
          res = await marketApi.getFinancialAbstract(querySymbol);
          cols = ['date', 'net_profit', 'net_profit_yoy', 'total_revenue', 'total_revenue_yoy', 'basic_eps', 'bps', 'gross_margin', 'net_margin', 'roe', 'debt_ratio', 'current_ratio'];
          break;
        case 'indicators':
          res = await marketApi.getFinancialIndicators(querySymbol, '2023');
          cols = res.columns?.slice(0, 15) || [];
          break;
        case 'income':
          res = await marketApi.getIncomeStatement(querySymbol);
          cols = res.columns?.slice(0, 15) || [];
          break;
        case 'balance':
          res = await marketApi.getBalanceSheet(querySymbol);
          cols = res.columns?.slice(0, 15) || [];
          break;
        case 'cashflow':
          res = await marketApi.getCashflowStatement(querySymbol);
          cols = res.columns?.slice(0, 15) || [];
          break;
        case 'dividend':
          res = await marketApi.getDividendHistory(querySymbol);
          cols = ['announce_date', 'dividend_type', 'bonus_share_ratio', 'conversion_ratio', 'cash_dividend_ratio', 'record_date', 'ex_dividend_date', 'payment_date', 'description', 'report_period'];
          break;
        default:
          res = { data: [] };
      }
      setFundDataMap((prev) => ({ ...prev, [tab]: res.data || [] }));
      setFundColumnsMap((prev) => ({ ...prev, [tab]: cols }));
    } catch (e: any) {
      setFundErrorMap((prev) => ({ ...prev, [tab]: e.message || '查询基本面数据失败' }));
    } finally {
      setFundLoadingMap((prev) => ({ ...prev, [tab]: false }));
    }
  };

  const handleQueryAll = async () => {
    // 如果股票缓存还没加载完成，先等待加载
    if (!stockCacheLoaded) {
      await fetchStockCache();
    }

    const querySymbol = symbol || parseSymbolFromInput();
    if (!querySymbol) {
      setKlinesError('请先输入并选择股票');
      setFundErrorMap((prev) => {
        const next = { ...prev };
        fundTabs.forEach((t) => { next[t] = '请先输入并选择股票'; });
        return next;
      });
      return;
    }

    // 同时查询 K 线和所有基本面 tab
    handleQueryKlines();
    await Promise.all(fundTabs.map((tab) => loadFundamentalForTab(querySymbol, tab)));
  };

  const tabs = [
    { key: 'kline', label: 'K线行情', icon: TrendingUp },
    { key: 'abstract', label: '财务摘要', icon: FileText },
    { key: 'indicators', label: '财务指标', icon: Scale },
    { key: 'income', label: '利润表', icon: Coins },
    { key: 'balance', label: '资产负债表', icon: Building2 },
    { key: 'cashflow', label: '现金流量表', icon: Banknote },
    { key: 'dividend', label: '分红送股', icon: Calendar },
  ];

  // 表格表头中文映射
  const columnNameMap: Record<string, string> = {
    // 财务摘要
    date: '报告期',
    net_profit: '净利润',
    net_profit_yoy: '净利润同比',
    total_revenue: '营业总收入',
    total_revenue_yoy: '营收同比',
    basic_eps: '每股收益',
    bps: '每股净资产',
    gross_margin: '毛利率',
    net_margin: '净利率',
    roe: 'ROE',
    debt_ratio: '资产负债率',
    current_ratio: '流动比率',
    // 分红送股
    announce_date: '公告日期',
    dividend_type: '分红类型',
    bonus_share_ratio: '送股比例',
    conversion_ratio: '转增比例',
    cash_dividend_ratio: '派息比例',
    record_date: '股权登记日',
    ex_dividend_date: '除权除息日',
    payment_date: '派息日',
    description: '说明',
    report_period: '报告期',
    // 财务指标
    roe_diluted: 'ROE(摊薄)',
    roe_weighted: 'ROE(加权)',
    gross_profit_margin: '毛利率',
    net_profit_margin: '净利率',
    operating_margin: '营业利润率',
    eps: '每股收益',
    bps_value: '每股净资产',
    // 利润表
    operating_revenue: '营业收入',
    operating_cost: '营业成本',
    operating_profit: '营业利润',
    total_profit: '利润总额',
    income_tax: '所得税',
    // 资产负债表
    total_assets: '总资产',
    total_liabilities: '总负债',
    equity: '股东权益',
    cash_equivalents: '货币资金',
    accounts_receivable: '应收账款',
    inventory: '存货',
    fixed_assets: '固定资产',
    // 现金流量表
    net_cash_flow: '现金净流量',
    operating_cash_flow: '经营活动现金流',
    investing_cash_flow: '投资活动现金流',
    financing_cash_flow: '筹资活动现金流',
    // K线
    open: '开盘',
    high: '最高',
    low: '最低',
    close: '收盘',
    volume: '成交量',
    amount: '成交额',
  };

  const visibleKlines = klines.slice(klinePage * pageSize, (klinePage + 1) * pageSize);
  const totalPages = Math.ceil(klines.length / pageSize) || 1;

  return (
    <div className="p-6 space-y-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">数据源</h1>
          <p className="text-sm text-gray-500">数据源状态监控与股票数据查询，共 {sources.length} 个数据源，{sources.filter(s => s.available).length} 个可用</p>
        </div>
        <button onClick={fetchSources} disabled={sourcesLoading}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 hover:text-primary-600 hover:bg-gray-50 rounded-lg transition-colors disabled:opacity-50">
          {sourcesLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          刷新状态
        </button>
      </div>

      {/* 数据源状态 */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">数据源状态</h2>
        {sourcesError && <div className="text-sm text-red-500 mb-3">{sourcesError}</div>}
        {sourcesLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {Array.from({ length: 7 }).map((_, i) => <div key={i} className="h-24 bg-gray-100 rounded-lg animate-pulse" />)}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {sources.map((s) => (
              <div key={s.name} className={`p-3 rounded-lg border ${s.available ? sourceColors[s.name] || 'bg-gray-50 border-gray-200' : 'bg-gray-50 border-gray-200 opacity-60'}`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`w-2 h-2 rounded-full ${s.available ? (sourceDotColors[s.name] || 'bg-green-400') : 'bg-gray-300'}`} />
                  <span className="font-mono text-sm font-bold">{s.name}</span>
                  {s.available ? <Wifi className="w-3.5 h-3.5 ml-auto opacity-60" /> : <WifiOff className="w-3.5 h-3.5 ml-auto opacity-40" />}
                </div>
                <p className="text-xs text-gray-500 line-clamp-2 mb-2" title={s.description}>{s.description}</p>
                <div className="flex items-center gap-3">
                  <PriorityBadge priority={s.priority_min} label="分钟" />
                  <PriorityBadge priority={s.priority_daily} label="日线" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 数据查询区域 */}
      <div className="bg-white rounded-xl border border-gray-200">
        {/* 公共查询栏 */}
        <div className="px-5 pt-5 pb-3 border-b border-gray-100">
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-56">
              <label className="block text-xs text-gray-500 mb-1">股票代码 / 名称</label>
              <SymbolInput value={symbol} onChange={handleStockSelect} />
            </div>
            {activeTab === 'kline' && (
              <>
                <div className="w-32">
                  <label className="block text-xs text-gray-500 mb-1">周期</label>
                  <select value={period} onChange={(e) => setPeriod(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                    {periodOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div className="w-36">
                  <label className="block text-xs text-gray-500 mb-1">开始日期</label>
                  <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                </div>
                <div className="w-36">
                  <label className="block text-xs text-gray-500 mb-1">结束日期</label>
                  <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                </div>
                <div className="w-44">
                  <label className="block text-xs text-gray-500 mb-1">数据源</label>
                  <select value={dataSource} onChange={(e) => setDataSource(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                    {sourceOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </>
            )}
            <button
              onClick={handleQueryAll}
              disabled={klinesLoading || stockCacheLoading || Object.values(fundLoadingMap).some(Boolean)}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary-600 text-white rounded-lg text-sm font-medium hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {(klinesLoading || stockCacheLoading || Object.values(fundLoadingMap).some(Boolean)) ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              查询
            </button>
          </div>

          {(basicInfo || basicInfoLoading) && (
            <div className="mt-3">
              <StockBasicInfoCard info={basicInfo} loading={basicInfoLoading} />
            </div>
          )}
        </div>

        {/* Tab 切换 */}
        <div className="px-5 border-b border-gray-200">
          <nav className="flex gap-1 -mb-px">
            {tabs.map((t) => {
              const Icon = t.icon;
              return (
                <button key={t.key} onClick={() => setActiveTab(t.key)}
                  className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === t.key
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}>
                  <Icon className="w-4 h-4" />
                  {t.label}
                </button>
              );
            })}
          </nav>
        </div>

        {/* 内容区 */}
        <div className="p-5">
          {activeTab === 'kline' && (
            <div className="space-y-4">
              {klinesError && <div className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3">{klinesError}</div>}
              {klines.length === 0 && !klinesLoading && !klinesError && (
                <div className="text-center py-16 text-gray-400">
                  <TrendingUp className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p>选择股票代码和查询条件，点击查询获取K线数据</p>
                </div>
              )}
              {klinesLoading && (
                <div className="flex items-center justify-center py-16 text-gray-500">
                  <Loader2 className="w-6 h-6 animate-spin mr-2" />
                  正在加载K线数据...
                </div>
              )}
              {klines.length > 0 && !klinesLoading && (
                <>
                  <div className="flex items-center justify-between text-sm text-gray-500">
                    <span>数据源：{klinesSource || 'auto'}</span>
                    <span>共 {klines.length} 条</span>
                  </div>
                  <KlineChart data={klines} trades={[]} height={420} />
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="text-gray-500 border-b border-gray-200">
                          <th className="text-left py-2 px-3">日期</th>
                          <th className="text-right py-2 px-3">开盘</th>
                          <th className="text-right py-2 px-3">最高</th>
                          <th className="text-right py-2 px-3">最低</th>
                          <th className="text-right py-2 px-3">收盘</th>
                          <th className="text-right py-2 px-3">成交量</th>
                          <th className="text-right py-2 px-3">成交额</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {visibleKlines.map((k) => (
                          <tr key={k.date} className="text-gray-700">
                            <td className="py-2 px-3 font-mono">{k.date}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.open.toFixed(2)}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.high.toFixed(2)}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.low.toFixed(2)}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.close.toFixed(2)}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.volume.toLocaleString()}</td>
                            <td className="text-right py-2 px-3 font-mono">{k.amount.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {klines.length > pageSize && (
                    <div className="flex items-center justify-center gap-2 pt-2">
                      <button onClick={() => setKlinePage((p) => Math.max(0, p - 1))} disabled={klinePage === 0}
                        className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50">上一页</button>
                      <span className="text-sm text-gray-600">第 {klinePage + 1} / {totalPages} 页</span>
                      <button onClick={() => setKlinePage((p) => Math.min(totalPages - 1, p + 1))} disabled={klinePage >= totalPages - 1}
                        className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50">下一页</button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {activeTab !== 'kline' && (
            <div className="space-y-4">
              {fundError && <div className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3">{fundError}</div>}
              {fundLoading && (
                <div className="flex items-center justify-center py-16 text-gray-500">
                  <Loader2 className="w-6 h-6 animate-spin mr-2" />
                  正在加载基本面数据...
                </div>
              )}
              {!fundLoading && fundData.length === 0 && !fundError && (
                <div className="text-center py-16 text-gray-400">
                  <FileText className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p>选择股票代码，点击查询获取基本面数据</p>
                </div>
              )}
              {fundData.length > 0 && !fundLoading && (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-200">
                        {fundColumns.map((col) => (
                          <th key={col} className="text-left py-2 px-3 whitespace-nowrap">{columnNameMap[col] || col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {fundData.map((row, idx) => (
                        <tr key={idx} className="text-gray-700">
                          {fundColumns.map((col) => (
                            <td key={col} className="py-2 px-3 whitespace-nowrap">{row[col] ?? '-'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
