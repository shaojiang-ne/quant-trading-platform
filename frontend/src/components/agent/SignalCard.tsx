import { Check, X, Clock, CheckSquare, Square } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAgentStore } from '@/stores/agentStore';
import type { MonitoringSignal, SignalStatus } from '@/types/agent';

interface SignalCardProps {
  signal: MonitoringSignal;
  /** 批量选择模式：选中状态 */
  selected?: boolean;
  /** 批量选择模式：切换选中 */
  onToggleSelect?: (id: string) => void;
}

const typeConfig = {
  buy: { icon: '🟢', label: '买入信号', color: 'bg-green-50 border-green-200', labelColor: 'text-green-700' },
  sell: { icon: '🔴', label: '卖出信号', color: 'bg-red-50 border-red-200', labelColor: 'text-red-700' },
  alert: { icon: '⚠️', label: '预警', color: 'bg-yellow-50 border-yellow-200', labelColor: 'text-yellow-700' },
};

const statusStyle: Record<SignalStatus, string> = {
  pending: 'border-l-4 border-l-yellow-400',
  confirmed: 'border-l-4 border-l-green-400 opacity-80',
  ignored: 'border-l-4 border-l-gray-300 opacity-50',
  expired: 'border-l-4 border-l-gray-400 opacity-40',
};

export function SignalCard({ signal, selected, onToggleSelect }: SignalCardProps) {
  const { updateSignalStatus } = useAgentStore();
  const navigate = useNavigate();
  const config = typeConfig[signal.type];
  const selectable = !!onToggleSelect;

  const handleConfirm = () => {
    updateSignalStatus(signal.id, 'confirmed');
    // 跳转交易页面并预填该股票代码
    navigate(`/trading?symbol=${encodeURIComponent(signal.stockCode)}`);
  };
  const handleIgnore = () => updateSignalStatus(signal.id, 'ignored');

  return (
    <div className={`p-2.5 ${config.color} ${statusStyle[signal.status]} rounded-lg text-xs`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {selectable && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggleSelect!(signal.id); }}
              className="text-gray-400 hover:text-primary-600"
              title={selected ? '取消选择' : '选择'}
            >
              {selected ? <CheckSquare className="w-3.5 h-3.5 text-primary-600" /> : <Square className="w-3.5 h-3.5" />}
            </button>
          )}
          <span className={`font-medium ${config.labelColor}`}>
            {config.icon} {config.label}
          </span>
        </div>
        <span className="text-gray-400 flex items-center gap-0.5">
          <Clock className="w-3 h-3" />
          {new Date(signal.triggerTime).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
      </div>

      <div className="mt-1 text-gray-700">
        {signal.ruleDescription}
      </div>

      <div className="mt-1.5 flex items-center gap-3 text-[11px]">
        <span>
          {signal.type === 'buy' ? '买入' : signal.type === 'sell' ? '卖出' : '预警'} |
          ¥{signal.targetPrice.toFixed(2)}
          {signal.suggestedPositionPct > 0
            ? ` | 仓位${signal.suggestedPositionPct}%`
            : signal.suggestedQuantity > 0
            ? ` | ${signal.suggestedQuantity}股`
            : ''}
        </span>
      </div>

      {signal.advanceMinutes > 0 && (
        <div className="mt-0.5 text-[10px] text-gray-400">
          ⏱ 提前{signal.advanceMinutes}分钟预警
        </div>
      )}

      <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-500">
        <span>{signal.stockName} 现价 ¥{signal.currentPrice.toFixed(2)}</span>
      </div>

      {signal.status === 'pending' && (
        <div className="mt-2 flex gap-2">
          <button
            onClick={handleConfirm}
            className="flex items-center gap-1 px-2 py-0.5 bg-primary-600 text-white rounded text-[11px] hover:bg-primary-700 transition"
          >
            <Check className="w-3 h-3" /> 确认操作
          </button>
          <button
            onClick={handleIgnore}
            className="flex items-center gap-1 px-2 py-0.5 bg-white text-gray-500 border border-gray-200 rounded text-[11px] hover:bg-gray-50 transition"
          >
            <X className="w-3 h-3" /> 忽略
          </button>
        </div>
      )}
    </div>
  );
}
