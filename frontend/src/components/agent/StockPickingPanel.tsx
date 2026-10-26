import { useState, useRef, useCallback } from 'react';
import { Brain, Clock, History } from 'lucide-react';
import { PanelHeader } from './PanelHeader';
import { PickChatArea } from './PickChatArea';
import { PickResultList } from './PickResultList';
import { ScheduleModal } from './ScheduleModal';
import { PickHistoryModal } from './PickHistoryModal';
import { ResizeHandle } from './ResizeHandle';
import { useAgentStore } from '@/stores/agentStore';

export function StockPickingPanel() {
  const { panelLayout, togglePanelCollapse, setPanelSplit } = useAgentStore();
  const isCollapsed = panelLayout.collapsed.pick;
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const topPct = panelLayout.pickSplit;

  // 拖拽横条：把鼠标 clientY 换算为顶部区域占容器高度的百分比
  const handleVResize = useCallback(
    (clientY: number) => {
      const rect = bodyRef.current?.getBoundingClientRect();
      if (!rect) return;
      const pct = ((clientY - rect.top) / rect.height) * 100;
      setPanelSplit('pick', pct);
    },
    [setPanelSplit]
  );

  return (
    <>
      <PanelHeader
        title="AI选股"
        icon={<Brain className="w-4 h-4" />}
        panelKey="pick"
        isCollapsed={isCollapsed}
        onToggleCollapse={() => togglePanelCollapse('pick')}
        actions={
          !isCollapsed ? (
            <>
              <button
                onClick={() => setScheduleOpen(true)}
                className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
                title="定时选股"
              >
                <Clock className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setHistoryOpen(true)}
                className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
                title="历史记录"
              >
                <History className="w-3.5 h-3.5" />
              </button>
            </>
          ) : undefined
        }
      />
      {!isCollapsed && (
        <div ref={bodyRef} className="flex-1 flex flex-col overflow-hidden">
          <div style={{ height: `${topPct}%` }} className="min-h-0 overflow-hidden">
            <PickChatArea />
          </div>
          <ResizeHandle orientation="vertical" onResize={handleVResize} />
          <div style={{ height: `${100 - topPct}%` }} className="min-h-0 overflow-hidden">
            <PickResultList />
          </div>
        </div>
      )}
      <ScheduleModal isOpen={scheduleOpen} onClose={() => setScheduleOpen(false)} />
      <PickHistoryModal isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    </>
  );
}
