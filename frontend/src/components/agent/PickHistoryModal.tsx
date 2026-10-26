import { useEffect, useState } from 'react';
import {
  X, RefreshCw, Clock, Loader2, Trash2, Pencil, BellOff, ListTree, Info,
  CheckSquare, Square,
} from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import * as agentApi from '@/api/agent';
import { PickResultCard } from './PickResultCard';
import { MarkdownContent } from './MarkdownContent';
import type { StockPickResult, StockPickingStrategy } from '@/types/agent';

interface PickHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'text-gray-400' },
  confirmed: { text: '已确认', color: 'text-blue-500' },
  scheduled: { text: '已定时', color: 'text-green-500' },
};

// 从 markdown 策略描述中提取标题：取首个非空行，去掉 markdown 标题/列表符号。
// 列表项只展示这个标题，完整描述在详情弹框查看。
function extractTitle(md: string | undefined | null): string {
  if (!md) return '未命名策略';
  const line = md.split('\n').map((l) => l.trim()).find((l) => l.length > 0) || '';
  // 去掉行首 # 标题符号、- * 列表符号、** 加粗标记
  const cleaned = line.replace(/^#{1,6}\s*/, '').replace(/^[-*]\s*/, '').replace(/\*\*/g, '').trim();
  return cleaned || md.slice(0, 20);
}

// 详情弹框内 markdown 渲染的字号覆盖：prose-sm 默认偏大，压到 11~12px 与详情一致
const DETAIL_MD_CLASS =
  '[&_p]:text-[11px] [&_p]:leading-snug [&_p]:my-0.5 [&_li]:text-[11px] [&_li]:my-0 [&_ul]:my-1 [&_ol]:my-1 ' +
  '[&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-[12px] [&_h4]:text-[12px] [&_h1]:my-1 [&_h2]:my-1 [&_h3]:my-1 ' +
  '[&_strong]:text-inherit [&_code]:text-[11px]';

export function PickHistoryModal({ isOpen, onClose }: PickHistoryModalProps) {
  const {
    strategies, fetchStrategies, executeStrategy,
    deleteStrategy, updateStrategy, scheduleStrategy,
    batchDeleteStrategies,
  } = useAgentStore();

  const [executingId, setExecutingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  // 行内编辑
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  // 策略详情子弹窗（含选股结果）
  const [detailStrategy, setDetailStrategy] = useState<StockPickingStrategy | null>(null);
  const [results, setResults] = useState<StockPickResult[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);
  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  useEffect(() => {
    if (isOpen) fetchStrategies();
  }, [isOpen, fetchStrategies]);

  if (!isOpen) return null;

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelectedIds(new Set(strategies.map((s) => s.id)));
  const invertSelection = () =>
    setSelectedIds((prev) => {
      const all = new Set(strategies.map((s) => s.id));
      const next = new Set<string>();
      for (const id of all) if (!prev.has(id)) next.add(id);
      return next;
    });

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除选中的 ${ids.length} 条策略？历史选股结果将保留。`)) return;
    setBatchDeleting(true);
    const ok = await batchDeleteStrategies(ids);
    setBatchDeleting(false);
    if (ok) {
      setSelectedIds(new Set());
      // 若详情子弹窗展示的策略已被删，关闭它
      if (detailStrategy && ids.includes(detailStrategy.id)) setDetailStrategy(null);
    }
  };

  const handleReExecute = async (id: string) => {
    setExecutingId(id);
    try {
      await executeStrategy(id);
    } finally {
      setExecutingId(null);
      onClose();
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除该策略？历史选股结果将保留，但无法再通过该策略查看。')) return;
    setDeletingId(id);
    try {
      await deleteStrategy(id);
    } finally {
      setDeletingId(null);
    }
  };

  const handleStartEdit = (id: string, desc: string) => {
    setEditingId(id);
    setEditText(desc);
  };

  const handleSaveEdit = async (id: string) => {
    if (!editText.trim()) return;
    setSavingEdit(true);
    const ok = await updateStrategy(id, editText.trim());
    setSavingEdit(false);
    if (ok) setEditingId(null);
  };

  const handleCancelSchedule = async (id: string, scheduleTime?: string) => {
    setCancelingId(id);
    const ok = await scheduleStrategy(id, scheduleTime || '00:00', false);
    setCancelingId(null);
    if (ok) fetchStrategies();
  };

  const handleViewDetail = async (s: StockPickingStrategy) => {
    setDetailStrategy(s);
    setResults([]);
    setResultsLoading(true);
    try {
      const rs = await agentApi.fetchPickResults(s.id);
      setResults(rs);
    } catch {
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl w-[44rem] max-w-[92vw] max-h-[80vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-900">选股历史记录</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        {strategies.length > 0 && (
          <div className="px-3 py-1.5 border-b border-gray-100 flex items-center gap-2 text-[11px]">
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

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {strategies.length === 0 ? (
            <div className="text-center py-8 text-gray-400 text-xs">暂无历史策略</div>
          ) : (
            strategies.map((s) => {
              const st = STATUS_LABEL[s.status] || STATUS_LABEL.draft;
              const isEditing = editingId === s.id;
              const isSelected = selectedIds.has(s.id);
              return (
                <div key={s.id} className={`p-2.5 rounded-lg border ${isSelected ? 'bg-primary-50/50 border-primary-200' : 'bg-gray-50 border-gray-100'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => toggleSelect(s.id)}
                        className="text-gray-400 hover:text-primary-600"
                        title={isSelected ? '取消选择' : '选择'}
                      >
                        {isSelected ? <CheckSquare className="w-3.5 h-3.5 text-primary-600" /> : <Square className="w-3.5 h-3.5" />}
                      </button>
                      <span className={`text-[10px] ${st.color}`}>{st.text}</span>
                    </div>
                    <span className="flex items-center gap-0.5 text-[10px] text-gray-400">
                      <Clock className="w-2.5 h-2.5" />
                      {new Date(s.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>

                  {isEditing ? (
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={3}
                      autoFocus
                      className="mt-1 w-full px-2 py-1 text-xs text-gray-700 border border-primary-300 rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  ) : (
                    <p className="mt-1 text-xs text-gray-700 line-clamp-2">{extractTitle(s.description)}</p>
                  )}
                  {/* 列表只展示标题，完整 AI 优化描述在详情弹框查看 */}

                  <div className="mt-2 flex items-center gap-1 flex-wrap">
                    {isEditing ? (
                      <>
                        <button
                          onClick={() => handleSaveEdit(s.id)}
                          disabled={savingEdit || !editText.trim()}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-primary-600 text-white rounded hover:bg-primary-700 transition disabled:opacity-50"
                        >
                          {savingEdit ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                          保存
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="px-2 py-0.5 text-[11px] text-gray-600 bg-gray-200 rounded hover:bg-gray-300 transition"
                        >
                          取消
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => handleReExecute(s.id)}
                          disabled={executingId === s.id}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-primary-50 text-primary-600 rounded hover:bg-primary-100 transition disabled:opacity-50"
                        >
                          {executingId === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                          重新执行
                        </button>
                        <button
                          onClick={() => handleViewDetail(s)}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition"
                          title="查看策略详情"
                        >
                          <Info className="w-3 h-3" />
                          详情
                        </button>
                        <button
                          onClick={() => handleStartEdit(s.id, s.description)}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition"
                          title="编辑策略描述"
                        >
                          <Pencil className="w-3 h-3" />
                          编辑
                        </button>
                        {s.scheduleEnabled && (
                          <button
                            onClick={() => handleCancelSchedule(s.id, s.scheduleTime)}
                            disabled={cancelingId === s.id}
                            className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition disabled:opacity-50"
                            title="取消定时"
                          >
                            {cancelingId === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <BellOff className="w-3 h-3" />}
                            取消定时
                          </button>
                        )}
                        {s.scheduleEnabled && s.scheduleTime && (
                          <span className="text-[10px] text-green-500">定时 {s.scheduleTime}</span>
                        )}
                        <button
                          onClick={() => handleDelete(s.id)}
                          disabled={deletingId === s.id}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-red-50 text-red-500 rounded hover:bg-red-100 transition disabled:opacity-50 ml-auto"
                          title="删除策略"
                        >
                          {deletingId === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* 策略详情子弹窗 */}
      {detailStrategy && (() => {
        const s = detailStrategy;
        const st = STATUS_LABEL[s.status] || STATUS_LABEL.draft;
        const fmtTime = (t?: string) =>
          t ? new Date(t).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-';
        return (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]"
            onClick={() => setDetailStrategy(null)}
          >
            <div
              className="bg-white rounded-xl w-[48rem] max-w-[92vw] max-h-[85vh] flex flex-col shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-4 border-b border-gray-100">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
                  <ListTree className="w-4 h-4 text-primary-500" />
                  策略详情 · {s.name || '未命名策略'}
                </h3>
                <button onClick={() => setDetailStrategy(null)} className="p-1 text-gray-400 hover:text-gray-600 rounded">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3 text-xs">
                {/* 基本信息 */}
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${st.color} bg-gray-100`}>{st.text}</span>
                  {s.scheduleEnabled && s.scheduleTime && (
                    <span className="text-[10px] text-green-600">定时 {s.scheduleTime}</span>
                  )}
                </div>

                {/* 最终优化后的策略描述（优先 optimizedDescription，无则回退 description） */}
                <div>
                  <div className="text-[11px] text-gray-400 mb-0.5">策略描述</div>
                  <div className={`text-gray-700 break-words ${DETAIL_MD_CLASS}`}>
                    <MarkdownContent content={(s.optimizedDescription || s.description) || '（无）'} />
                  </div>
                </div>

                {/* 规则程序 */}
                <div>
                  <div className="text-[11px] text-gray-400 mb-0.5">策略规则</div>
                  {(() => {
                    const rp = s.rules;
                    if (!rp || Array.isArray(rp)) {
                      return <p className="text-gray-400">无结构化规则（基于自然语言描述选股）</p>;
                    }
                    return (
                      <div className="space-y-1 text-[11px] text-gray-600">
                        <div>股票池：{rp.pool || '—'}</div>
                        {rp.filters && rp.filters.length > 0 && (
                          <div>
                            筛选：
                            {rp.filters.map((f, i) => (
                              <span key={i} className="ml-1">
                                {f.field}{f.op}{f.value}{i < rp.filters!.length - 1 ? '、' : ''}
                              </span>
                            ))}
                          </div>
                        )}
                        {rp.scoring && rp.scoring.length > 0 && (
                          <div>
                            评分：
                            {rp.scoring.map((sc, i) => (
                              <span key={i} className="ml-1">
                                {sc.field}({sc.weight}{sc.direction === 'high' ? '↑' : '↓'})
                                {i < rp.scoring!.length - 1 ? '、' : ''}
                              </span>
                            ))}
                          </div>
                        )}
                        {rp.top_n != null && <div>取前 {rp.top_n} 名</div>}
                      </div>
                    );
                  })()}
                </div>

                {/* 时间与定时 */}
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div>
                    <span className="text-gray-400">创建时间</span>
                    <div className="text-gray-600">{fmtTime(s.createdAt)}</div>
                  </div>
                  <div>
                    <span className="text-gray-400">更新时间</span>
                    <div className="text-gray-600">{fmtTime(s.updatedAt)}</div>
                  </div>
                </div>

                {/* 选股结果 */}
                <div className="pt-2 border-t border-gray-100">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] text-gray-400">选股结果</span>
                    {!resultsLoading && results.length > 0 && (
                      <span className="text-[10px] text-gray-400">共 {results.length} 只</span>
                    )}
                  </div>
                  {resultsLoading ? (
                    <div className="flex justify-center py-6">
                      <Loader2 className="w-5 h-5 text-primary-500 animate-spin" />
                    </div>
                  ) : results.length === 0 ? (
                    <div className="text-center py-6 text-gray-400 text-xs">该策略暂无选股结果</div>
                  ) : (
                    <div className="space-y-2">
                      {results.map((r) => <PickResultCard key={r.id} result={r} />)}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
