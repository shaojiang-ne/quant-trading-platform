import { useAgentStore } from '@/stores/agentStore';

export function WatchlistSummary() {
  const { watchlist } = useAgentStore();

  const total = watchlist.length;
  const up = watchlist.filter((w) => w.changePct > 0).length;
  const down = watchlist.filter((w) => w.changePct < 0).length;
  const flat = total - up - down;
  const monitored = watchlist.filter((w) => w.monitoringStatus === 'active').length;
  const unmonitored = total - monitored;

  return (
    <div className="p-3 bg-gray-50 border-t border-gray-200 space-y-2">
      <div className="flex items-center gap-2 text-xs">
        <div className="flex-1 flex items-center justify-between bg-white px-2 py-1.5 rounded border border-gray-200">
          <span className="text-gray-500">总数</span>
          <span className="font-semibold text-gray-800">{total}</span>
        </div>
        <div className="flex-1 flex items-center justify-between bg-white px-2 py-1.5 rounded border border-gray-200">
          <span className="text-red-400">涨</span>
          <span className="font-semibold text-red-500">{up}</span>
        </div>
        <div className="flex-1 flex items-center justify-between bg-white px-2 py-1.5 rounded border border-gray-200">
          <span className="text-gray-400">平</span>
          <span className="font-semibold text-gray-600">{flat}</span>
        </div>
        <div className="flex-1 flex items-center justify-between bg-white px-2 py-1.5 rounded border border-gray-200">
          <span className="text-green-400">跌</span>
          <span className="font-semibold text-green-500">{down}</span>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] text-gray-500">
        <span>已盯盘 {monitored} / 未设 {unmonitored}</span>
      </div>
    </div>
  );
}
