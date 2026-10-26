import { useState, useMemo } from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { PickResultCard } from './PickResultCard';
import { BarChart3, Clock } from 'lucide-react';
import type { StockPickResult } from '@/types/agent';

type SortKey = 'match' | 'change';

export function PickResultList() {
  const { pickResults } = useAgentStore();
  const [sortKey, setSortKey] = useState<SortKey>('match');

  // 最近一次选股时间
  const lastPickTime = useMemo(() => {
    if (pickResults.length === 0) return null;
    return pickResults.reduce((latest, r) => {
      const t = new Date(r.pickedAt).getTime();
      return t > latest ? t : latest;
    }, 0);
  }, [pickResults]);

  const sorted = useMemo(() => {
    const arr = [...pickResults];
    if (sortKey === 'match') {
      arr.sort((a, b) => b.matchScore - a.matchScore);
    } else {
      arr.sort((a, b) => b.changePct - a.changePct);
    }
    return arr;
  }, [pickResults, sortKey]);

  if (pickResults.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 py-8">
        <BarChart3 className="w-8 h-8 mb-2" />
        <p className="text-xs">确认策略后将展示选股结果</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-50 border-b border-gray-100">
        <span className="flex items-center gap-1 text-xs text-gray-500 min-w-0">
          <Clock className="w-3 h-3 flex-shrink-0" />
          <span className="truncate">
            {lastPickTime
              ? `选股 ${pickResults.length} 只 · ${new Date(lastPickTime).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
              : `选股结果 (${pickResults.length})`}
          </span>
        </span>
        <div className="flex items-center gap-1 flex-shrink-0">
          {(['match', 'change'] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortKey(k)}
              className={`px-1.5 py-0.5 text-[10px] rounded transition ${
                sortKey === k
                  ? 'bg-primary-100 text-primary-600'
                  : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              {k === 'match' ? '匹配度' : '涨跌幅'}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {sorted.map((result: StockPickResult) => (
          <PickResultCard key={result.id} result={result} />
        ))}
      </div>
    </div>
  );
}
