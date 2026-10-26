import { useCallback, useRef, useState, useEffect } from 'react';
import { useAgentStore } from '@/stores/agentStore';
import { ResizeHandle } from './ResizeHandle';
import type { ReactNode } from 'react';
import type { PanelKey } from '@/types/agent';

const MIN_WIDTH = 280;
const COLLAPSED_WIDTH = 48;

interface ResizableLayoutProps {
  pick: ReactNode;
  watch: ReactNode;
  monitor: ReactNode;
}

export function ResizableLayout({ pick, watch, monitor }: ResizableLayoutProps) {
  const { panelLayout, setPanelWidths, togglePanelCollapse } = useAgentStore();
  const { widths, collapsed } = panelLayout;
  const containerRef = useRef<HTMLDivElement>(null);
  const [viewportWidth, setViewportWidth] = useState(window.innerWidth);
  const [mobileTab, setMobileTab] = useState<PanelKey>('pick');
  const prevViewportWidth = useRef(viewportWidth);
  const didInitCollapse = useRef(false);

  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Below 1280px: auto-collapse monitor panel — only when crossing the
  // threshold from above, so a user who manually re-expands it isn't fought.
  useEffect(() => {
    const prev = prevViewportWidth.current;
    const crossedDown = prev >= 1280 && viewportWidth < 1280;
    const initial = !didInitCollapse.current && viewportWidth < 1280;
    if ((crossedDown || initial) && !panelLayout.collapsed.monitor) {
      togglePanelCollapse('monitor');
    }
    didInitCollapse.current = true;
    prevViewportWidth.current = viewportWidth;
  }, [viewportWidth, panelLayout.collapsed.monitor, togglePanelCollapse]);

  const getContainerWidth = useCallback(() => {
    return containerRef.current?.offsetWidth || 1200;
  }, []);

  // Mobile mode: < 768px
  const isMobile = viewportWidth < 768;
  if (isMobile) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-hidden">
          {mobileTab === 'pick' && <div className="flex flex-col h-full overflow-hidden border-r border-gray-200 bg-white">{pick}</div>}
          {mobileTab === 'watch' && <div className="flex flex-col h-full overflow-hidden border-r border-gray-200 bg-white">{watch}</div>}
          {mobileTab === 'monitor' && <div className="flex flex-col h-full overflow-hidden bg-white">{monitor}</div>}
        </div>
        <div className="flex border-t border-gray-200 bg-white">
          {(['pick', 'watch', 'monitor'] as PanelKey[]).map((key) => (
            <button
              key={key}
              onClick={() => setMobileTab(key)}
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                mobileTab === key ? 'text-primary-600 border-t-2 border-primary-600' : 'text-gray-500'
              }`}
            >
              {key === 'pick' ? 'AI选股' : key === 'watch' ? '自选股' : '智能盯盘'}
            </button>
          ))}
        </div>
      </div>
    );
  }

  // 折叠列固定为 COLLAPSED_WIDTH；未折叠列按各自 widths[i] 在「未折叠列总和」
  // 中的占比分配剩余空间。这样折叠一列后，它让出的空间按原比例补给其他列。
  const collapsedFlags = [collapsed.pick, collapsed.watch, collapsed.monitor];
  const totalCollapsed = collapsedFlags.filter(Boolean).length;
  const availableWidth = getContainerWidth() - totalCollapsed * COLLAPSED_WIDTH - 2 * 6;
  const expandedWidthSum = widths.reduce((sum, w, i) => sum + (collapsedFlags[i] ? 0 : w), 0) || 1;
  const pixelWidths: [number, number, number] = [
    collapsed.pick
      ? COLLAPSED_WIDTH
      : Math.max(MIN_WIDTH, (widths[0] / expandedWidthSum) * availableWidth),
    collapsed.watch
      ? COLLAPSED_WIDTH
      : Math.max(MIN_WIDTH, (widths[1] / expandedWidthSum) * availableWidth),
    collapsed.monitor
      ? COLLAPSED_WIDTH
      : Math.max(MIN_WIDTH, (widths[2] / expandedWidthSum) * availableWidth),
  ];

  // 把三列像素宽度反算为 store 存储的百分比。折叠列保留原 widths 值，
  // 未折叠列按各自像素在「未折叠像素总和」中的占比换算（与渲染公式互逆）。
  const persistFromPixels = useCallback(
    (px: [number, number, number]) => {
      const expandedPxSum =
        px.reduce((sum, w, i) => sum + (collapsedFlags[i] ? 0 : w), 0) || 1;
      const next = widths.slice() as [number, number, number];
      for (let i = 0; i < 3; i++) {
        if (!collapsedFlags[i]) {
          next[i] = (px[i] / expandedPxSum) * 100;
        }
      }
      // 归一化未折叠列之和为 100（折叠列不参与，保持原值不影响渲染）
      const expandedSum = next.reduce((s, w, i) => s + (collapsedFlags[i] ? 0 : w), 0) || 1;
      for (let i = 0; i < 3; i++) {
        if (!collapsedFlags[i]) next[i] = (next[i] / expandedSum) * 100;
      }
      setPanelWidths(next);
    },
    [widths, collapsedFlags, setPanelWidths]
  );

  // handle0：pick / watch 分界。pick 和 watch 共享一个像素池，monitor 不动。
  const handleResize0 = useCallback(
    (clientX: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      // pick 目标像素 = 鼠标相对容器左边的距离
      let pickPx = clientX - rect.left;
      const pool = pixelWidths[0] + pixelWidths[1]; // pick+watch 共享池
      pickPx = Math.max(MIN_WIDTH, Math.min(pool - MIN_WIDTH, pickPx));
      const watchPx = pool - pickPx;
      persistFromPixels([pickPx, watchPx, pixelWidths[2]]);
    },
    [pixelWidths, persistFromPixels]
  );

  // handle1：watch / monitor 分界。watch 和 monitor 共享一个像素池，pick 不动。
  const handleResize1 = useCallback(
    (clientX: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      // pick 展开时 watch 左边界 = pick宽 + handle0(6px)；pick 折叠时 handle0 不渲染
      const leftHandle = collapsed.pick ? 0 : 6;
      let watchPx = clientX - rect.left - pixelWidths[0] - leftHandle;
      const pool = pixelWidths[1] + pixelWidths[2]; // watch+monitor 共享池
      watchPx = Math.max(MIN_WIDTH, Math.min(pool - MIN_WIDTH, watchPx));
      const monitorPx = pool - watchPx;
      persistFromPixels([pixelWidths[0], watchPx, monitorPx]);
    },
    [pixelWidths, persistFromPixels, collapsed.pick]
  );

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden">
      <div
        className="flex flex-col overflow-hidden border-r border-gray-200 bg-white"
        style={{ width: pixelWidths[0], minWidth: collapsed.pick ? COLLAPSED_WIDTH : MIN_WIDTH }}
      >
        {pick}
      </div>

      {!collapsed.pick && !collapsed.watch && <ResizeHandle onResize={handleResize0} />}

      <div
        className="flex flex-col overflow-hidden border-r border-gray-200 bg-white"
        style={{ width: pixelWidths[1], minWidth: collapsed.watch ? COLLAPSED_WIDTH : MIN_WIDTH }}
      >
        {watch}
      </div>

      {!collapsed.watch && !collapsed.monitor && <ResizeHandle onResize={handleResize1} />}

      <div
        className="flex flex-col overflow-hidden bg-white"
        style={{ width: pixelWidths[2], minWidth: collapsed.monitor ? COLLAPSED_WIDTH : MIN_WIDTH }}
      >
        {monitor}
      </div>
    </div>
  );
}
