import { useState } from 'react';
import { X, Search, Plus } from 'lucide-react';
import { useStockCacheStore } from '@/stores/stockCacheStore';
import { useAgentStore } from '@/stores/agentStore';
import type { StockInfo } from '@/stores/stockCacheStore';

interface AddStockModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AddStockModal({ isOpen, onClose }: AddStockModalProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<StockInfo[]>([]);
  const { loaded, search } = useStockCacheStore();
  const { addToWatchlist } = useAgentStore();

  const handleSearch = (val: string) => {
    setQuery(val);
    if (val.trim() && loaded) {
      setResults(search(val.trim()).slice(0, 10));
    } else {
      setResults([]);
    }
  };

  const handleAdd = (stock: StockInfo) => {
    addToWatchlist(stock.code, stock.name);
    setResults((prev) => prev.filter((s) => s.code !== stock.code));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl w-80 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-3 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-900">添加自选股</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="输入代码或名称搜索"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
              autoFocus
            />
          </div>

          {results.length > 0 && (
            <div className="mt-2 max-h-48 overflow-y-auto divide-y divide-gray-100">
              {results.map((stock) => (
                <div key={stock.code} className="flex items-center justify-between py-2 px-1">
                  <div>
                    <span className="font-mono text-xs text-gray-500">{stock.code}</span>
                    <span className="ml-1.5 text-sm text-gray-900">{stock.name}</span>
                  </div>
                  <button
                    onClick={() => handleAdd(stock)}
                    className="flex items-center gap-0.5 px-2 py-0.5 text-xs bg-primary-50 text-primary-600 rounded hover:bg-primary-100 transition"
                  >
                    <Plus className="w-3 h-3" /> 添加
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
