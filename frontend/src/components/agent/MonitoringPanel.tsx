import { useState, useRef, useEffect } from 'react';
import { Target, Volume2, VolumeX, History } from 'lucide-react';
import { PanelHeader } from './PanelHeader';
import { SignalGroupList } from './SignalGroupList';
import { SignalStatsBar } from './SignalStatsBar';
import { SignalHistoryModal } from './SignalHistoryModal';
import { useAgentStore } from '@/stores/agentStore';

export function MonitoringPanel() {
  const { panelLayout, togglePanelCollapse, signals, fetchSignals } = useAgentStore();
  const isCollapsed = panelLayout.collapsed.monitor;
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);

  // 挂载时拉一次 pending 作兜底(WS 掉线期间漏的信号)
  useEffect(() => {
    fetchSignals(undefined, 'pending');
  }, [fetchSignals]);

  // 有新 pending 信号时声音提示
  const prevCount = useRef<number | null>(null);
  useEffect(() => {
    const pending = signals.filter((s) => s.status === 'pending').length;
    if (prevCount.current === null) {
      // 首次 hydrate:记录基线,不响铃
      prevCount.current = pending;
      return;
    }
    if (soundEnabled && pending > prevCount.current) {
      try {
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        const osc = ctx.createOscillator();
        osc.frequency.value = 880;
        osc.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.15);
      } catch { /* ignore */ }
    }
    prevCount.current = pending;
  }, [signals, soundEnabled]);

  return (
    <>
      <PanelHeader
        title="信号"
        icon={<Target className="w-4 h-4" />}
        panelKey="monitor"
        isCollapsed={isCollapsed}
        onToggleCollapse={() => togglePanelCollapse('monitor')}
        actions={
          !isCollapsed ? (
            <>
              <button
                onClick={() => setHistoryOpen(true)}
                className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
                title="信号历史"
              >
                <History className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setSoundEnabled(!soundEnabled)}
                className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
                title={soundEnabled ? '关闭声音提示' : '开启声音提示'}
              >
                {soundEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
              </button>
            </>
          ) : undefined
        }
      />
      {!isCollapsed && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* 信号列表:整栏一个连续滚动区,不分区 */}
          <div className="flex-1 min-h-0 overflow-y-auto p-2">
            <SignalGroupList />
          </div>
          {/* 统计条固定底部 */}
          <SignalStatsBar />
        </div>
      )}
      <SignalHistoryModal isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    </>
  );
}
