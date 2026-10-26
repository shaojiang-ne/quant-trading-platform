import { useState } from 'react';
import { Eye, EyeOff, Trash2, Loader2, ListChecks, CheckSquare, Square } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import type { WatchlistStock } from '@/types/agent';

interface WatchlistCardProps {
  stock: WatchlistStock;
  onSetMonitor: (code: string, name: string) => void;
  /** 批量选择模式：选中状态 */
  selected?: boolean;
  /** 批量选择模式：切换选中 */
  onToggleSelect?: (id: string) => void;
}

export function WatchlistCard({ stock, onSetMonitor, selected, onToggleSelect }: WatchlistCardProps) {
  const { removeFromWatchlist, cancelStockMonitor } = useAgentStore();
  const selectable = !!onToggleSelect;
  // active 视为已盯盘;none / pending 视为未盯盘(点盯盘去设规则)
  const isMonitored = stock.monitoringStatus === 'active';
  const [cancelling, setCancelling] = useState(false);

  const handleToggleMonitor = async () => {
    if (isMonitored) {
      if (!window.confirm(`确认取消 ${stock.name} 的盯盘?\n将清空该股的盯盘规则,股票仍保留在自选股。`)) return;
      setCancelling(true);
      await cancelStockMonitor(stock.code, stock.id);
      setCancelling(false);
    } else {
      onSetMonitor(stock.code, stock.name);
    }
  };

  return (
    <div
      className={`p-2.5 bg-white border rounded-lg hover:shadow-sm transition cursor-default group ${
        selected
          ? 'border-primary-400 ring-1 ring-primary-300'
          : isMonitored
            ? 'border-green-300 bg-green-50/30'
            : 'border-gray-200'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {selectable && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggleSelect!(stock.id); }}
              className="text-gray-400 hover:text-primary-600"
              title={selected ? '取消选择' : '选择'}
            >
              {selected ? <CheckSquare className="w-3.5 h-3.5 text-primary-600" /> : <Square className="w-3.5 h-3.5" />}
            </button>
          )}
          <span className="font-mono text-xs text-gray-500">{stock.code}</span>
          <span className="text-sm font-medium text-gray-900">{stock.name}</span>
          {/* 已盯盘:醒目绿色徽章 */}
          {isMonitored && (
            <span className="flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] text-green-700 bg-green-100 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> 盯盘中
            </span>
          )}
        </div>
        {/* 两个按钮:[管理/设置]开弹框 + [盯盘/取消盯盘]双态开关 */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => onSetMonitor(stock.code, stock.name)}
            className="flex items-center gap-0.5 px-2 py-0.5 text-[11px] bg-gray-50 text-gray-600 rounded hover:bg-gray-100 transition"
            title={isMonitored ? '管理盯盘规则' : '设置盯盘策略'}
          >
            <ListChecks className="w-3 h-3" /> {isMonitored ? '管理' : '设置'}
          </button>
          <button
            onClick={handleToggleMonitor}
            disabled={cancelling}
            title={isMonitored ? '取消盯盘' : '开启盯盘'}
            className={`flex items-center gap-0.5 px-2 py-0.5 text-[11px] rounded transition disabled:opacity-50 ${
              isMonitored
                ? 'bg-gray-100 text-gray-500 hover:bg-red-50 hover:text-red-500'
                : 'bg-primary-50 text-primary-600 hover:bg-primary-100'
            }`}
          >
            {isMonitored
              ? (cancelling ? <Loader2 className="w-3 h-3 animate-spin" /> : <EyeOff className="w-3 h-3" />)
              : <Eye className="w-3 h-3" />}
            {isMonitored ? '取消盯盘' : '盯盘'}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between mt-1.5 text-xs">
        <span className="font-mono text-gray-800">¥{stock.price.toFixed(2)}</span>
        <span className={stock.changePct >= 0 ? 'text-red-500' : 'text-green-500'}>
          {stock.changePct >= 0 ? '+' : ''}{stock.changePct.toFixed(2)}%
        </span>
      </div>

      <div className="flex items-center gap-3 mt-1 text-[10px] text-gray-400">
        <span>量{(stock.volume / 10000).toFixed(0)}万</span>
        <span>换手{stock.turnoverRate.toFixed(2)}%</span>
        <span>流通{stock.floatMarketCap.toFixed(1)}亿</span>
      </div>

      <div className="flex items-center gap-1.5 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => removeFromWatchlist(stock.id)}
          className="flex items-center gap-0.5 px-2 py-0.5 text-xs bg-red-50 text-red-500 rounded hover:bg-red-100 transition"
        >
          <Trash2 className="w-3 h-3" /> 移除
        </button>
      </div>
    </div>
  );
}
