import { useState } from 'react';
import { Plus, Check, Loader2 } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import type { StockPickResult } from '@/types/agent';

interface PickResultCardProps {
  result: StockPickResult;
}

export function PickResultCard({ result }: PickResultCardProps) {
  const { addToWatchlist, addPickResultToWatchlist, watchlist } = useAgentStore();
  const [adding, setAdding] = useState(false);
  const alreadyInWatchlist = watchlist.some((w) => w.code === result.code);
  const isAdded = result.addedToWatchlist || alreadyInWatchlist;

  const handleAddToWatchlist = async () => {
    setAdding(true);
    await addToWatchlist(result.code, result.name);
    setAdding(false);
    // Only mark after a successful add (store swallowed errors are logged)
    addPickResultToWatchlist(result.id);
  };

  return (
    <div className="p-2.5 bg-white border border-gray-200 rounded-lg hover:shadow-sm transition">
      <div className="flex items-center justify-between">
        <div>
          <span className="font-mono text-xs text-gray-500">{result.code}</span>
          <span className="ml-1.5 text-sm font-medium text-gray-900">{result.name}</span>
        </div>
        {isAdded ? (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <Check className="w-3 h-3" /> 已添加
          </span>
        ) : (
          <button
            onClick={handleAddToWatchlist}
            disabled={adding}
            className="flex items-center gap-0.5 px-2 py-0.5 text-xs bg-primary-50 text-primary-600 rounded hover:bg-primary-100 transition disabled:opacity-50"
          >
            {adding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />} 加入自选
          </button>
        )}
      </div>
      <div className="flex items-center justify-between mt-1.5 text-xs">
        <span className="font-mono text-gray-800">¥{result.price.toFixed(2)}</span>
        <span className={result.changePct >= 0 ? 'text-red-500' : 'text-green-500'}>
          {result.changePct >= 0 ? '+' : ''}{result.changePct.toFixed(2)}%
        </span>
        <span className="text-gray-400">匹配度 {result.matchScore}</span>
      </div>
      {result.matchReason && (
        <p className="mt-1 text-[11px] text-gray-500 truncate" title={result.matchReason}>
          {result.matchReason}
        </p>
      )}
    </div>
  );
}
