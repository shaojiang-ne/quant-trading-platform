import { useState } from 'react';
import { Check, ArrowRight, Loader2 } from 'lucide-react';
import type { PickRuleProgram, PickFilter, PickScoring } from '@/types/agent';

interface StrategyCardProps {
  original: string;
  optimized: string;
  reason: string;
  onAdopt: () => void;
  /** 确认后后端编译出的规则程序；确认中为 null */
  rules?: PickRuleProgram | null;
}

// 规则字段 → 中文名（对齐后端 _RULE_FIELDS）
const FIELD_LABELS: Record<string, string> = {
  pe_ttm: 'PE(TTM)',
  pb: 'PB',
  vol_ratio: '量比',
  turnover_pct: '换手率(%)',
  change_pct: '涨跌幅(%)',
  float_mcap_yi: '流通市值(亿)',
  amount_wan: '成交额(万)',
  price: '现价',
};

// 股池代码 → 中文名（对齐后端 POOL_INDEX_MAP）
const POOL_LABELS: Record<string, string> = {
  hs300: '沪深300',
  sse50: '上证50',
  star50: '科创50',
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

function poolLabel(pool: string): string {
  return POOL_LABELS[pool] || pool;
}

function describeFilter(f: PickFilter): string {
  return `${fieldLabel(f.field)} ${f.op} ${f.value}`;
}

function describeScoring(s: PickScoring): string {
  const dir = s.direction === 'high' ? '越高越好' : '越低越好';
  return `${fieldLabel(s.field)}（${dir}，权重 ${s.weight}）`;
}

export function StrategyCard({ original, optimized, reason, onAdopt, rules }: StrategyCardProps) {
  const [adopted, setAdopted] = useState(false);

  const handleAdopt = () => {
    setAdopted(true);
    onAdopt();
  };

  // 已确认态：展示后端编译出的规则程序（filters 硬筛 + scoring 打分 + top_n）
  if (adopted) {
    const filters = (rules?.filters as PickFilter[] | undefined) || [];
    const scoring = (rules?.scoring as PickScoring[] | undefined) || [];
    const topN = rules?.top_n;
    const pool = rules?.pool;
    const ruleReady = !!rules && (!!filters.length || !!scoring.length);

    return (
      <div className="my-2 p-3 bg-green-50 border border-green-200 rounded-lg space-y-2">
        <div className="flex items-center gap-1.5 text-green-700 text-xs font-medium">
          <Check className="w-3.5 h-3.5" />
          策略已确认，已用于选股
        </div>

        {/* 优化后的策略描述（流式文本，供参考）*/}
        <p className="text-xs text-green-800 whitespace-pre-wrap">{optimized}</p>

        {/* 后端编译出的结构化规则程序 */}
        <div className="pt-1.5 border-t border-green-200">
          <div className="text-[11px] font-medium text-green-700 mb-1">生效规则程序</div>
          {!ruleReady ? (
            <div className="flex items-center gap-1.5 text-[11px] text-green-600">
              <Loader2 className="w-3 h-3 animate-spin" />
              规则生成中…
            </div>
          ) : (
            <div className="space-y-1 text-[11px] text-green-900">
              {pool && (
                <div>
                  <span className="text-green-600 font-medium">股池：</span>
                  {poolLabel(pool)}
                </div>
              )}
              {filters.length > 0 && (
                <div>
                  <span className="text-green-600 font-medium">硬筛条件：</span>
                  {filters.map(describeFilter).join('，')}
                </div>
              )}
              {scoring.length > 0 && (
                <div>
                  <span className="text-green-600 font-medium">打分项：</span>
                  {scoring.map(describeScoring).join('；')}
                </div>
              )}
              {topN != null && (
                <div>
                  <span className="text-green-600 font-medium">取前：</span>
                  {topN} 只
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="my-2 p-3 bg-blue-50 border border-blue-200 rounded-lg space-y-2">
      <div className="text-xs font-medium text-blue-700">策略优化建议</div>
      <div className="flex items-start gap-2 text-xs">
        <div className="flex-1 p-2 bg-white rounded border border-gray-200">
          <div className="text-gray-400 mb-1 text-[10px] font-medium">原始策略</div>
          <p className="text-gray-700 whitespace-pre-wrap">{original}</p>
        </div>
        <ArrowRight className="w-4 h-4 text-blue-400 flex-shrink-0 mt-4" />
        <div className="flex-1 p-2 bg-white rounded border border-blue-200">
          <div className="text-blue-500 mb-1 text-[10px] font-medium">优化策略</div>
          <p className="text-gray-900 whitespace-pre-wrap font-medium">{optimized}</p>
        </div>
      </div>
      {reason && (
        <p className="text-[11px] text-blue-600 bg-blue-100/50 px-2 py-1 rounded">💡 {reason}</p>
      )}
      <div className="flex gap-2">
        <button
          onClick={handleAdopt}
          className="flex items-center gap-1 px-3 py-1 bg-primary-600 text-white rounded text-xs hover:bg-primary-700 transition"
        >
          <Check className="w-3 h-3" /> 采纳优化
        </button>
      </div>
    </div>
  );
}
