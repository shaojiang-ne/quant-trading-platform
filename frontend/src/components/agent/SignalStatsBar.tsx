import { useAgentStore } from '@/stores/agentStore';

export function SignalStatsBar() {
  const { signals } = useAgentStore();
  const today = new Date().toDateString();
  const todaySignals = signals.filter(
    (s) => new Date(s.triggerTime).toDateString() === today
  );
  const pending = todaySignals.filter((s) => s.status === 'pending').length;
  const confirmed = todaySignals.filter((s) => s.status === 'confirmed').length;
  const ignored = todaySignals.filter((s) => s.status === 'ignored').length;
  const total = todaySignals.length;
  // 准确率：已确认 / (已确认 + 已忽略)，即用户认可的比例
  const resolved = confirmed + ignored;
  const accuracy = resolved > 0 ? Math.round((confirmed / resolved) * 100) : null;

  return (
    <div className="px-3 py-1.5 bg-gray-50 border-t border-gray-200 flex items-center gap-3 text-[10px] text-gray-500">
      <span>今日信号 <strong className="text-gray-800">{total}</strong></span>
      <span className="text-green-600">已确认 {confirmed}</span>
      <span className="text-gray-400">已忽略 {ignored}</span>
      <span className="text-primary-600">准确率 {accuracy === null ? '—' : `${accuracy}%`}</span>
      {pending > 0 && <span className="text-yellow-600 animate-pulse">待处理 {pending}</span>}
    </div>
  );
}
