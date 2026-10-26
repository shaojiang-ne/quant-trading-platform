import { useState, useEffect, useMemo, useRef } from 'react';
import { Star, Plus, Search, Trash2, Loader2 } from 'lucide-react';
import { PanelHeader } from './PanelHeader';
import { WatchlistCard } from './WatchlistCard';
import { WatchlistSummary } from './WatchlistSummary';
import { AddStockModal } from './AddStockModal';
import { MonitorRulesModal } from './MonitorRulesModal';
import { useAgentStore } from '@/stores/agentStore';

type SortMode = 'manual' | 'change' | 'status';

const STATUS_ORDER: Record<string, number> = { active: 0, pending: 1, none: 2 };

export function WatchlistPanel() {
  const {
    panelLayout, togglePanelCollapse, watchlist,
    fetchWatchlist, reorderWatchlist,
    batchRemoveFromWatchlist,
  } = useAgentStore();
  const isCollapsed = panelLayout.collapsed.watch;
  const [addStockOpen, setAddStockOpen] = useState(false);
  const [monitorStock, setMonitorStock] = useState<{ code: string; name: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('manual');
  const dragIndex = useRef<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  useEffect(() => { fetchWatchlist(); }, [fetchWatchlist]);

  const filteredWatchlist = useMemo(() => {
    const q = searchQuery.trim();
    let list = q
      ? watchlist.filter((w) => w.code.includes(q) || w.name.includes(q))
      : [...watchlist];
    if (sortMode === 'change') {
      list.sort((a, b) => b.changePct - a.changePct);
    } else if (sortMode === 'status') {
      list.sort((a, b) =>
        (STATUS_ORDER[a.monitoringStatus] ?? 9) - (STATUS_ORDER[b.monitoringStatus] ?? 9)
      );
    }
    // manual 模式保持原顺序（watchlist 已按 order 排序）
    return list;
  }, [watchlist, searchQuery, sortMode]);

  const handleSetMonitor = (code: string, name: string) => {
    setMonitorStock({ code, name });
  };

  // 批量选择
  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectAll = () => setSelectedIds(new Set(filteredWatchlist.map((w) => w.id)));
  const invertSelection = () =>
    setSelectedIds((prev) => {
      const next = new Set<string>();
      for (const w of filteredWatchlist) if (!prev.has(w.id)) next.add(w.id);
      return next;
    });
  const handleBatchRemove = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认移除选中的 ${ids.length} 只自选股？`)) return;
    setBatchDeleting(true);
    const ok = await batchRemoveFromWatchlist(ids);
    setBatchDeleting(false);
    if (ok) setSelectedIds(new Set());
  };

  // ── 拖拽排序（仅 manual 模式 + 无搜索 + 无选中时生效）──
  const canDrag = sortMode === 'manual' && !searchQuery.trim() && selectedIds.size === 0;

  const handleDragStart = (index: number) => {
    if (!canDrag) return;
    dragIndex.current = index;
  };
  const handleDragOver = (e: React.DragEvent, index: number) => {
    if (!canDrag || dragIndex.current === null) return;
    e.preventDefault();
    if (dragOverIndex !== index) setDragOverIndex(index);
  };
  const handleDrop = (index: number) => {
    if (!canDrag || dragIndex.current === null || dragIndex.current === index) {
      dragIndex.current = null;
      setDragOverIndex(null);
      return;
    }
    const ids = filteredWatchlist.map((w) => w.id);
    const [moved] = ids.splice(dragIndex.current, 1);
    ids.splice(index, 0, moved);
    reorderWatchlist(ids);
    dragIndex.current = null;
    setDragOverIndex(null);
  };
  const handleDragEnd = () => {
    dragIndex.current = null;
    setDragOverIndex(null);
  };

  const sortOptions: Array<{ key: SortMode; label: string }> = [
    { key: 'manual', label: '手动' },
    { key: 'change', label: '涨跌' },
    { key: 'status', label: '状态' },
  ];

  return (
    <>
      <PanelHeader
        title="自选股"
        icon={<Star className="w-4 h-4" />}
        panelKey="watch"
        isCollapsed={isCollapsed}
        onToggleCollapse={() => togglePanelCollapse('watch')}
        actions={
          !isCollapsed ? (
            <>
              <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">
                {watchlist.length}
              </span>
              <button
                onClick={() => setAddStockOpen(true)}
                className="p-1 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-gray-100 transition"
                title="添加自选股"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </>
          ) : undefined
        }
      />
      {!isCollapsed && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-3 py-1.5 border-b border-gray-100 space-y-1.5">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索代码/名称"
                className="w-full pl-7 pr-3 py-1 border border-gray-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-gray-400 mr-0.5">排序</span>
              {sortOptions.map((o) => (
                <button
                  key={o.key}
                  onClick={() => setSortMode(o.key)}
                  className={`px-1.5 py-0.5 text-[10px] rounded transition ${
                    sortMode === o.key
                      ? 'bg-primary-100 text-primary-600'
                      : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {o.label}
                </button>
              ))}
              {canDrag && (
                <span className="ml-auto text-[10px] text-gray-300">可拖拽排序</span>
              )}
            </div>
            {filteredWatchlist.length > 0 && (
              <div className="flex items-center gap-2 text-[10px]">
                <button onClick={selectAll} className="text-gray-500 hover:text-primary-600">全选</button>
                <button onClick={invertSelection} className="text-gray-500 hover:text-primary-600">反选</button>
                {selectedIds.size > 0 && (
                  <>
                    <span className="text-primary-600 font-medium">已选 {selectedIds.size}</span>
                    <button
                      onClick={handleBatchRemove}
                      disabled={batchDeleting}
                      className="flex items-center gap-1 ml-auto px-2 py-0.5 bg-red-50 text-red-500 rounded hover:bg-red-100 transition disabled:opacity-50"
                    >
                      {batchDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                      批量移除
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          <div className="flex-[7] min-h-0 overflow-y-auto p-2 space-y-2">
            {filteredWatchlist.length === 0 ? (
              <div className="text-center py-8 text-gray-400 text-xs">
                {watchlist.length === 0 ? '暂无自选股' : '无匹配结果'}
              </div>
            ) : (
              filteredWatchlist.map((stock, index) => (
                <div
                  key={stock.id}
                  draggable={canDrag}
                  onDragStart={() => handleDragStart(index)}
                  onDragOver={(e) => handleDragOver(e, index)}
                  onDrop={() => handleDrop(index)}
                  onDragEnd={handleDragEnd}
                  className={`rounded-lg transition ${
                    dragOverIndex === index && canDrag
                      ? 'ring-2 ring-primary-400 ring-offset-1'
                      : ''
                  } ${canDrag ? 'cursor-grab active:cursor-grabbing' : ''}`}
                >
                  <WatchlistCard
                    stock={stock}
                    onSetMonitor={handleSetMonitor}
                    selected={selectedIds.has(stock.id)}
                    onToggleSelect={toggleSelect}
                  />
                </div>
              ))
            )}
          </div>
          <WatchlistSummary />
        </div>
      )}
      <AddStockModal isOpen={addStockOpen} onClose={() => setAddStockOpen(false)} />
      <MonitorRulesModal
        isOpen={monitorStock !== null}
        onClose={() => setMonitorStock(null)}
        stockCode={monitorStock?.code ?? null}
        stockName={monitorStock?.name}
      />
    </>
  );
}
