import { ResizableLayout } from '@/components/agent/ResizableLayout';
import { StockPickingPanel } from '@/components/agent/StockPickingPanel';
import { WatchlistPanel } from '@/components/agent/WatchlistPanel';
import { MonitoringPanel } from '@/components/agent/MonitoringPanel';

export function AIAgent() {
  return (
    <div className="h-full -m-8 overflow-hidden">
      <ResizableLayout
        pick={<StockPickingPanel />}
        watch={<WatchlistPanel />}
        monitor={<MonitoringPanel />}
      />
    </div>
  );
}
