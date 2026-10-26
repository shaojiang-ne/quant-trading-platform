import { useEffect, useState } from 'react';
import { X, ListChecks, Trash2, Loader2, Power, CheckSquare, Square, Bot, Plus } from 'lucide-react';
import { useAgentStore, MONITOR_TEMPLATES } from '@/stores/agentStore';
import * as agentApi from '@/api/agent';
import type { MonitoringRule } from '@/types/agent';

interface MonitorRulesModalProps {
  isOpen: boolean;
  onClose: () => void;
  stockCode: string | null;
  stockName?: string;
}

const ACTION_LABEL: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  alert: '预警',
};

const METRIC_LABEL: Record<string, string> = {
  price: '现价',
  change_pct: '涨跌幅',
  vol_ratio: '量比',
  turnover_pct: '换手率',
};

/**
 * 展示规则的「可触发性」：
 * - 有 trigger（指标型）：引擎按实时行情自动判定 → 绿色徽章
 * - 有 target_price（目标价型）：引擎按现价触及目标价判定 → 蓝色徽章
 * - 两者皆无（纯语义，如「突破均线」）：引擎无法自动判定 → 黄色提示需手动关注
 */
function TriggerBadge({ rule }: { rule: MonitoringRule }) {
  const { trigger, targetPrice } = rule;
  if (trigger) {
    const label = METRIC_LABEL[trigger.metric] || trigger.metric;
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] text-green-700 bg-green-50 px-1.5 py-0.5 rounded">
        ✓ 自动触发 · {label} {trigger.op} {trigger.threshold}
      </span>
    );
  }
  if (targetPrice != null) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
        ✓ 自动触发 · 现价触及 ¥{targetPrice.toFixed(2)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
      ⚠ 无自动触发条件 · 需手动关注
    </span>
  );
}

export function MonitorRulesModal({ isOpen, onClose, stockCode, stockName }: MonitorRulesModalProps) {
  const { monitoringRules, fetchMonitorRules, toggleMonitorRule, deleteMonitorRule, batchDeleteMonitorRules,
          fetchWatchlist, fetchSignals, setWatchlistMonitoringStatus, watchlist } = useAgentStore();
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  // 批量选择
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  // AI 对话生成
  const [draftDesc, setDraftDesc] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && stockCode) {
      setLoading(true);
      fetchMonitorRules(stockCode).finally(() => setLoading(false));
    }
  }, [isOpen, stockCode, fetchMonitorRules]);

  // 切换股票/关闭时清空选择
  useEffect(() => {
    setSelectedIds(new Set());
  }, [stockCode, isOpen]);

  if (!isOpen) return null;

  const handleToggle = async (rule: MonitoringRule) => {
    setBusyId(rule.id);
    await toggleMonitorRule(rule.id, !rule.active);
    setBusyId(null);
  };

  const handleDelete = async (rule: MonitoringRule) => {
    if (!window.confirm('确认删除该盯盘规则？')) return;
    setBusyId(rule.id);
    await deleteMonitorRule(rule.id);
    setBusyId(null);
    setSelectedIds((prev) => {
      if (!prev.has(rule.id)) return prev;
      const next = new Set(prev);
      next.delete(rule.id);
      return next;
    });
  };

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectAll = () => setSelectedIds(new Set(rules.map((r) => r.id)));
  const invertSelection = () =>
    setSelectedIds((prev) => {
      const next = new Set<string>();
      for (const r of rules) if (!prev.has(r.id)) next.add(r.id);
      return next;
    });
  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    if (!window.confirm(`确认删除选中的 ${ids.length} 条盯盘规则？`)) return;
    setBatchDeleting(true);
    const ok = await batchDeleteMonitorRules(ids);
    setBatchDeleting(false);
    if (ok) setSelectedIds(new Set());
  };

  const rules = stockCode ? monitoringRules.filter((r) => r.stockCode === stockCode) : [];

  // 可触发性汇总：有 trigger 或 target_price 的规则引擎会自动评估
  const autoCount = rules.filter((r) => r.trigger || r.targetPrice != null).length;
  const manualCount = rules.length - autoCount;

  const handleGenerate = async () => {
    if (!stockCode || !draftDesc.trim()) return;
    setGenerating(true);
    setGenError(null);
    try {
      await agentApi.createMonitorRules(stockCode, draftDesc.trim());
      setDraftDesc('');
      await fetchMonitorRules(stockCode);
      const stock = watchlist.find((w) => w.code === stockCode);
      if (stock) setWatchlistMonitoringStatus(stock.id, 'active');
      await fetchWatchlist();
      await fetchSignals(undefined, 'pending');
    } catch (e) {
      setGenError(e instanceof Error ? e.message : 'AI 解析失败,可重试');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl w-[26rem] max-h-[80vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
            <ListChecks className="w-4 h-4 text-primary-500" />
            盯盘规则{stockName ? ` · ${stockName}` : ''}
          </h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        {!loading && rules.length > 0 && (
          <div className="px-3 py-1.5 border-b border-gray-100 flex items-center gap-3 text-[10px]">
            <span className="text-green-700">✓ 自动 {autoCount}</span>
            <span className="text-amber-700">⚠ 手动 {manualCount}</span>
            <span className="ml-auto flex items-center gap-2">
              <button onClick={selectAll} className="text-gray-500 hover:text-primary-600">全选</button>
              <button onClick={invertSelection} className="text-gray-500 hover:text-primary-600">反选</button>
              {selectedIds.size > 0 && (
                <>
                  <span className="text-primary-600 font-medium">已选 {selectedIds.size}</span>
                  <button
                    onClick={handleBatchDelete}
                    disabled={batchDeleting}
                    className="flex items-center gap-1 px-2 py-0.5 bg-red-50 text-red-500 rounded hover:bg-red-100 transition disabled:opacity-50"
                  >
                    {batchDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                    批量删除
                  </button>
                </>
              )}
            </span>
          </div>
        )}

        {/* AI 对话生成区 */}
        <div className="p-3 border-b border-gray-100 space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
            <Bot className="w-3.5 h-3.5 text-primary-500" />
            AI 生成盯盘策略
          </div>
          <div className="flex flex-wrap gap-1">
            {MONITOR_TEMPLATES.map((t) => (
              <button
                key={t.label}
                onClick={() => setDraftDesc(t.prompt)}
                className={`px-1.5 py-0.5 text-[10px] border rounded-full transition hover:shadow-sm ${t.color}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1.5">
            <input
              type="text"
              value={draftDesc}
              onChange={(e) => setDraftDesc(e.target.value)}
              placeholder="如:跌破1650止损,涨到1750减半仓"
              className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary-500"
              onKeyDown={(e) => { if (e.key === 'Enter') handleGenerate(); }}
              disabled={generating}
            />
            <button
              onClick={handleGenerate}
              disabled={generating || !draftDesc.trim()}
              className="flex items-center gap-0.5 px-2 py-1 text-xs bg-primary-50 text-primary-600 rounded hover:bg-primary-100 transition disabled:opacity-50"
            >
              {generating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
              生成
            </button>
          </div>
          {genError && (
            <div className="px-2 py-1 bg-red-50 text-red-600 text-[11px] rounded">{genError}</div>
          )}
          <p className="text-[10px] text-gray-400">
            描述策略后点「生成」,AI 解析为结构化规则并激活;引擎交易时段每分钟评估,触发即推送信号。
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="w-5 h-5 text-primary-500 animate-spin" />
            </div>
          ) : rules.length === 0 ? (
            <div className="text-center py-8 text-gray-400 text-xs">
              该股票暂无盯盘规则，在上方对话中描述策略并采纳即可创建。
            </div>
          ) : (
            rules.map((rule) => {
              const isSelected = selectedIds.has(rule.id);
              return (
              <div
                key={rule.id}
                className={`p-2.5 rounded-lg border transition ${
                  rule.active ? (isSelected ? 'bg-primary-50/40 border-primary-200' : 'bg-green-50/40 border-green-200') : 'bg-gray-50 border-gray-200 opacity-70'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => toggleSelect(rule.id)}
                      className="text-gray-400 hover:text-primary-600"
                      title={isSelected ? '取消选择' : '选择'}
                    >
                      {isSelected ? <CheckSquare className="w-3.5 h-3.5 text-primary-600" /> : <Square className="w-3.5 h-3.5" />}
                    </button>
                    <span className="text-[10px] text-gray-400">
                      {new Date(rule.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <span className={`text-[10px] font-medium ${rule.active ? 'text-green-600' : 'text-gray-400'}`}>
                    {rule.active ? '● 盯盘中' : '○ 已停用'}
                  </span>
                </div>

                <p className="mt-1 text-xs text-gray-700">{rule.condition || '（无描述）'}</p>

                <div className="mt-1.5 flex items-center gap-1.5 flex-wrap text-[10px]">
                  <span className="text-gray-500">
                    动作：<span className="font-medium text-gray-700">{ACTION_LABEL[rule.action] || rule.action}</span>
                  </span>
                  {rule.targetPrice != null && (
                    <span className="text-gray-500">目标价 ¥{rule.targetPrice.toFixed(2)}</span>
                  )}
                  {rule.positionPct != null && rule.positionPct > 0 && (
                    <span className="text-gray-500">仓位 {rule.positionPct}%</span>
                  )}
                  {rule.quantity != null && rule.quantity > 0 && (
                    <span className="text-gray-500">{rule.quantity}股</span>
                  )}
                  {rule.advanceMinutes > 0 && (
                    <span className="text-gray-500">提前{rule.advanceMinutes}分</span>
                  )}
                </div>

                <div className="mt-1.5">
                  <TriggerBadge rule={rule} />
                </div>

                <div className="mt-2 flex items-center gap-1.5">
                  <button
                    onClick={() => handleToggle(rule)}
                    disabled={busyId === rule.id}
                    className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition disabled:opacity-50"
                    title={rule.active ? '停用规则' : '启用规则'}
                  >
                    {busyId === rule.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Power className="w-3 h-3" />}
                    {rule.active ? '停用' : '启用'}
                  </button>
                  <button
                    onClick={() => handleDelete(rule)}
                    disabled={busyId === rule.id}
                    className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-red-50 text-red-500 rounded hover:bg-red-100 transition disabled:opacity-50"
                    title="删除规则"
                  >
                    <Trash2 className="w-3 h-3" />
                    删除
                  </button>
                </div>
              </div>
              );
            })
          )}
        </div>

        <div className="px-3 py-2 border-t border-gray-100 text-[10px] text-gray-400">
          引擎在交易时段每分钟评估启用的规则；带触发条件（如「量比 ≥ 2」）的规则会自动生成信号。
        </div>
      </div>
    </div>
  );
}
