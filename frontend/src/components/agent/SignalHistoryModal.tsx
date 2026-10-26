import { useState, useMemo } from 'react';
import { X, Calendar, Trash2, Loader2 } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import { SignalCard } from './SignalCard';

interface SignalHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SignalHistoryModal({ isOpen, onClose }: SignalHistoryModalProps) {
  const { signals, fetchSignals, batchDeleteSignals } = useAgentStore();
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  // 按规则聚合统计：触发数 / 已确认 / 准确率
  const ruleStats = useMemo(() => {
    const map = new Map<string, { total: number; confirmed: number; ignored: number }>();
    for (const s of signals) {
      const key = s.ruleDescription || '（未命名规则）';
      const cur = map.get(key) || { total: 0, confirmed: 0, ignored: 0 };
      cur.total += 1;
      if (s.status === 'confirmed') cur.confirmed += 1;
      if (s.status === 'ignored') cur.ignored += 1;
      map.set(key, cur);
    }
    return Array.from(map.entries())
      .map(([rule, v]) => ({
        rule,
        ...v,
        accuracy: v.confirmed + v.ignored > 0
          ? Math.round((v.confirmed / (v.confirmed + v.ignored)) * 100)
          : null,
      }))
      .sort((a, b) => b.total - a.total);
  }, [signals]);

  if (!isOpen) return null;

  const handleDateChange = (d: string) => {
    setDate(d);
    setSelectedIds(new Set()); // 切日期清空选择
    fetchSignals(d);
  };

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectAll = () => setSelectedIds(new Set(signals.map((s) => s.id)));
  const invertSelection = () =>
    setSelectedIds((prev) => {
      const next = new Set<string>();
      for (const s of signals) if (!prev.has(s.id)) next.add(s.id);
      return next;
    });
  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除选中的 ${ids.length} 条信号记录？`)) return;
    setBatchDeleting(true);
    const ok = await batchDeleteSignals(ids);
    setBatchDeleting(false);
    if (ok) setSelectedIds(new Set());
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-900">信号历史</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-gray-400" />
              <input
                type="date"
                value={date}
                onChange={(e) => handleDateChange(e.target.value)}
                className="px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>
            <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg transition">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 规则准确率统计 */}
        {ruleStats.length > 0 && (
          <div className="p-3 border-b border-gray-100">
            <div className="text-xs font-medium text-gray-600 mb-2">规则准确率统计</div>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {ruleStats.map((rs) => (
                <div key={rs.rule} className="flex items-center gap-2 text-[11px] bg-gray-50 px-2 py-1 rounded">
                  <span className="flex-1 truncate text-gray-700" title={rs.rule}>{rs.rule}</span>
                  <span className="text-gray-400">触发 {rs.total}</span>
                  <span className="text-green-600">确认 {rs.confirmed}</span>
                  <span className={`font-medium ${rs.accuracy === null ? 'text-gray-400' : rs.accuracy >= 60 ? 'text-green-600' : 'text-orange-500'}`}>
                    {rs.accuracy === null ? '准确率 —' : `准确率 ${rs.accuracy}%`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 批量选择工具栏 */}
        {signals.length > 0 && (
          <div className="px-4 py-1.5 border-b border-gray-100 flex items-center gap-2 text-[11px]">
            <button onClick={selectAll} className="text-gray-500 hover:text-primary-600">全选</button>
            <button onClick={invertSelection} className="text-gray-500 hover:text-primary-600">反选</button>
            {selectedIds.size > 0 && (
              <>
                <span className="text-primary-600 font-medium">已选 {selectedIds.size}</span>
                <button
                  onClick={handleBatchDelete}
                  disabled={batchDeleting}
                  className="flex items-center gap-1 ml-auto px-2 py-0.5 bg-red-50 text-red-500 rounded hover:bg-red-100 transition disabled:opacity-50"
                >
                  {batchDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                  批量删除
                </button>
              </>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {signals.length === 0 ? (
            <div className="text-center py-12 text-gray-400 text-sm">暂无信号记录</div>
          ) : (
            signals.map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                selected={selectedIds.has(signal.id)}
                onToggleSelect={toggleSelect}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
