import { useState, useEffect } from 'react';
import { X, Clock, Loader2, Check } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';

interface ScheduleModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ScheduleModal({ isOpen, onClose }: ScheduleModalProps) {
  const { strategies, scheduleStrategy } = useAgentStore();
  const confirmed = strategies.filter((s) => s.status === 'confirmed' || s.status === 'scheduled');

  const [strategyId, setStrategyId] = useState('');
  const [scheduleTime, setScheduleTime] = useState('09:15');
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Sync default strategy when the list loads or changes
  useEffect(() => {
    if (!strategyId && confirmed.length > 0) {
      setStrategyId(confirmed[0].id);
    }
  }, [confirmed, strategyId]);

  // Reset transient state when reopened
  useEffect(() => {
    if (isOpen) setSaved(false);
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSave = async () => {
    if (!strategyId) return;
    setSaving(true);
    const ok = await scheduleStrategy(strategyId, scheduleTime, enabled);
    setSaving(false);
    if (ok) {
      setSaved(true);
      setTimeout(onClose, 800);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl w-80 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-900">定时选股配置</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <div>
            <label className="block text-xs text-gray-500 font-medium mb-1">选择策略</label>
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              {confirmed.length === 0 ? (
                <option value="">暂无已确认的策略</option>
              ) : (
                confirmed.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))
              )}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 font-medium mb-1">执行时间</label>
            <input
              type="time"
              value={scheduleTime}
              onChange={(e) => setScheduleTime(e.target.value)}
              className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-600">启用定时选股</span>
            <button
              onClick={() => setEnabled(!enabled)}
              aria-pressed={enabled}
              className={`relative w-10 h-5 rounded-full transition-colors ${enabled ? 'bg-primary-600' : 'bg-gray-300'}`}
            >
              <span
                className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${enabled ? 'left-5' : 'left-0.5'}`}
              />
            </button>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-gray-100">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={!strategyId || saving}
            className="px-3 py-1.5 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition disabled:opacity-50 flex items-center gap-1"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : saved ? <Check className="w-3 h-3" /> : <Clock className="w-3 h-3" />}
            {saved ? '已保存' : '保存配置'}
          </button>
        </div>
      </div>
    </div>
  );
}
