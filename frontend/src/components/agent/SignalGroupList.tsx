import { useMemo } from 'react';
import { Target } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import { SignalCard } from './SignalCard';
import type { MonitoringSignal } from '@/types/agent';

/**
 * 右栏主体:按自选股分组展示 pending 信号。
 * - 只显示 status==='pending' 的信号
 * - 按自选股分组;有信号的股置顶(按最新信号时间倒序)
 * - 组内信号按 triggerTime 倒序(新在上)
 */
export function SignalGroupList() {
  const { signals, watchlist } = useAgentStore();

  const groups = useMemo(() => {
    const pending = signals.filter((s) => s.status === 'pending');
    const map = new Map<string, MonitoringSignal[]>();
    for (const s of pending) {
      const arr = map.get(s.stockCode) ?? [];
      arr.push(s);
      map.set(s.stockCode, arr);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => new Date(b.triggerTime).getTime() - new Date(a.triggerTime).getTime());
    }
    const entries = Array.from(map.entries()).map(([code, sigs]) => ({
      code,
      name: sigs[0]?.stockName || watchlist.find((w) => w.code === code)?.name || code,
      signals: sigs,
      latest: new Date(sigs[0].triggerTime).getTime(),
    }));
    entries.sort((a, b) => b.latest - a.latest);
    return entries;
  }, [signals, watchlist]);

  if (groups.length === 0) {
    return (
      <div className="text-center py-6 text-gray-400 text-xs">
        <Target className="w-8 h-8 mx-auto mb-2" />
        <p>确认盯盘规则后将接收实时信号</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {groups.map((g) => (
        <div key={g.code}>
          <div className="flex items-center gap-1.5 px-1 py-1 text-xs">
            <span className="font-mono text-gray-500">{g.code}</span>
            <span className="font-medium text-gray-800">{g.name}</span>
            <span className="ml-auto text-[10px] text-gray-400">{g.signals.length}</span>
          </div>
          <div className="space-y-1.5">
            {g.signals.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
