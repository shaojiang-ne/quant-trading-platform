import { useState, useEffect } from 'react';
import { useLiveTradingStore } from '@/stores/liveTradingStore';
import { useStrategyStore } from '@/stores/strategyStore';
import type { AutoTradeConfig, TradingInstanceInfo } from '@/api/trading';
import type { StrategyParamResponse } from '@/api/strategies';
import { StockSearchInput } from '@/components/StockSearchInput';

export function AutoTradePanel() {
  const {
    autoTradeConfig, fetchAutoTradeConfig, updateAutoTradeConfig,
    liveInstances, fetchLiveInstances, startLiveInstance, stopLiveInstance, deleteLiveInstance,
    updateLiveInstance,
  } = useLiveTradingStore();
  const [editing, setEditing] = useState(false);
  const [editConfig, setEditConfig] = useState<Partial<AutoTradeConfig>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [newInst, setNewInst] = useState({ name: '', symbol: '', strategy_id: '' });
  const [paramValues, setParamValues] = useState<Record<string, any>>({});
  const [deleteTarget, setDeleteTarget] = useState<TradingInstanceInfo | null>(null);
  const [editParamsTarget, setEditParamsTarget] = useState<TradingInstanceInfo | null>(null);
  const [editParamValues, setEditParamValues] = useState<Record<string, any>>({});
  const { strategies, fetchStrategies } = useStrategyStore();

  useEffect(() => {
    fetchAutoTradeConfig();
    fetchLiveInstances();
    fetchStrategies();
  }, [fetchAutoTradeConfig, fetchLiveInstances, fetchStrategies]);

  const handleSave = async () => {
    await updateAutoTradeConfig(editConfig);
    setEditing(false);
  };

  const config = autoTradeConfig || {
    auto_trade_enabled: false,
    confirm_required: true,
    max_order_amount: 100000,
    max_position_ratio: 0.3,
    daily_loss_limit: 5000,
  } as AutoTradeConfig;

  const currentStrategy = strategies.find((s) => s.id === newInst.strategy_id);

  const handleStrategyChange = (id: string) => {
    setNewInst({ ...newInst, strategy_id: id });
    const s = strategies.find((st) => st.id === id);
    if (s) {
      const defaults: Record<string, any> = {};
      s.parameters.forEach((p: StrategyParamResponse) => { defaults[p.key] = p.default; });
      setParamValues(defaults);
    } else {
      setParamValues({});
    }
  };

  const handleCreate = async () => {
    if (!newInst.name || !newInst.symbol || !newInst.strategy_id) return;
    await useLiveTradingStore.getState().createLiveInstance({
      name: newInst.name,
      symbol: newInst.symbol,
      strategy_id: newInst.strategy_id,
      mode: 'live',
      params: paramValues,
    });
    setShowCreate(false);
    setNewInst({ name: '', symbol: '', strategy_id: '' });
    setParamValues({});
  };

  const handleEditParams = async () => {
    if (!editParamsTarget) return;
    await updateLiveInstance(editParamsTarget.id, { params: editParamValues });
    setEditParamsTarget(null);
    setEditParamValues({});
  };

  const statusBadge = (status: string) => {
    const cls = status === 'running'
      ? 'bg-green-50 text-green-700'
      : status === 'stopped'
        ? 'bg-gray-50 text-gray-600'
        : 'bg-yellow-50 text-yellow-700';
    return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>{status}</span>;
  };

  const getStrategyName = (strategyId: string) => {
    const s = strategies.find((st) => st.id === strategyId);
    return s?.name || strategyId.slice(0, 8);
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm space-y-5">
      {/* 配置区 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-700">自动交易配置</h3>
          <button
            onClick={() => setEditing(!editing)}
            className="text-xs text-primary-600 hover:text-primary-700 font-medium"
          >
            {editing ? '取消' : '编辑'}
          </button>
        </div>

        <div className="space-y-3 text-xs">
          {/* 开关 */}
          <div className="flex items-center justify-between">
            <span className="text-gray-500">自动交易</span>
            {editing ? (
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" checked={editConfig.auto_trade_enabled ?? config.auto_trade_enabled}
                  onChange={(e) => setEditConfig({ ...editConfig, auto_trade_enabled: e.target.checked })}
                  className="sr-only peer" />
                <div className="w-8 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:bg-primary-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:after:translate-x-4"></div>
              </label>
            ) : (
              <span className={`font-medium ${config.auto_trade_enabled ? 'text-green-600' : 'text-gray-400'}`}>
                {config.auto_trade_enabled ? '已开启' : '已关闭'}
              </span>
            )}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-500">需确认下单</span>
            {editing ? (
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" checked={editConfig.confirm_required ?? config.confirm_required}
                  onChange={(e) => setEditConfig({ ...editConfig, confirm_required: e.target.checked })}
                  className="sr-only peer" />
                <div className="w-8 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:bg-primary-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:after:translate-x-4"></div>
              </label>
            ) : (
              <span className={`font-medium ${config.confirm_required ? 'text-yellow-600' : 'text-gray-400'}`}>
                {config.confirm_required ? '需要确认' : '自动执行'}
              </span>
            )}
          </div>

          {/* 风控参数 */}
          <div className="grid grid-cols-3 gap-3 pt-1">
            <div>
              <div className="text-gray-500 mb-1">最大下单金额</div>
              {editing ? (
                <input type="number" step="10000" value={editConfig.max_order_amount ?? config.max_order_amount}
                  onChange={(e) => setEditConfig({ ...editConfig, max_order_amount: Number(e.target.value) })}
                  className="w-full px-2 py-1 border border-gray-300 rounded text-gray-900" />
              ) : (
                <div className="text-gray-900 font-medium">{config.max_order_amount?.toLocaleString()}</div>
              )}
            </div>
            <div>
              <div className="text-gray-500 mb-1">最大持仓比例</div>
              {editing ? (
                <input type="number" step="0.1" value={editConfig.max_position_ratio ?? config.max_position_ratio}
                  onChange={(e) => setEditConfig({ ...editConfig, max_position_ratio: Number(e.target.value) })}
                  className="w-full px-2 py-1 border border-gray-300 rounded text-gray-900" />
              ) : (
                <div className="text-gray-900 font-medium">{((config.max_position_ratio ?? 0) * 100).toFixed(0)}%</div>
              )}
            </div>
            <div>
              <div className="text-gray-500 mb-1">日亏损限额</div>
              {editing ? (
                <input type="number" step="1000" value={editConfig.daily_loss_limit ?? config.daily_loss_limit}
                  onChange={(e) => setEditConfig({ ...editConfig, daily_loss_limit: Number(e.target.value) })}
                  className="w-full px-2 py-1 border border-gray-300 rounded text-gray-900" />
              ) : (
                <div className="text-gray-900 font-medium">{config.daily_loss_limit?.toLocaleString()}</div>
              )}
            </div>
          </div>
        </div>

        {editing && (
          <div className="flex gap-2 mt-3">
            <button onClick={handleSave} className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-xs font-medium transition-colors">保存</button>
            <button onClick={() => setEditing(false)} className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-medium transition-colors">取消</button>
          </div>
        )}
      </div>

      {/* 实盘实例列表 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-700">实盘策略实例</h3>
          <button
            onClick={() => { setNewInst({ name: '', symbol: '', strategy_id: '' }); setParamValues({}); setShowCreate(true); }}
            className="text-xs text-primary-600 hover:text-primary-700 font-medium"
          >
            + 创建
          </button>
        </div>

        {liveInstances.length === 0 ? (
          <div className="text-xs text-gray-400 text-center py-4">暂无实盘实例</div>
        ) : (
          <div className="space-y-2">
            {liveInstances.map((inst: TradingInstanceInfo) => (
              <div key={inst.id} className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg text-xs">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 truncate">{inst.name}</span>
                    {statusBadge(inst.status)}
                  </div>
                  <div className="text-gray-500 mt-0.5">{inst.symbol} · {getStrategyName(inst.strategy_id)}</div>
                </div>
                <div className="flex items-center gap-1.5 ml-2">
                  <button onClick={() => {
                    setEditParamsTarget(inst);
                    setEditParamValues(inst.params || {});
                  }}
                    className="px-2 py-1 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded text-[10px] font-medium transition-colors">参数</button>
                  {inst.status === 'running' ? (
                    <button onClick={() => stopLiveInstance(inst.id)}
                      className="px-2 py-1 bg-yellow-50 hover:bg-yellow-100 text-yellow-700 rounded text-[10px] font-medium transition-colors">停止</button>
                  ) : (
                    <button onClick={() => startLiveInstance(inst.id)}
                      className="px-2 py-1 bg-green-50 hover:bg-green-100 text-green-700 rounded text-[10px] font-medium transition-colors">启动</button>
                  )}
                  <button onClick={() => setDeleteTarget(inst)}
                    className="px-2 py-1 bg-red-50 hover:bg-red-100 text-red-600 rounded text-[10px] font-medium transition-colors">删除</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 删除确认弹窗 */}
        {deleteTarget && (
          <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setDeleteTarget(null)}>
            <div className="bg-white rounded-xl p-5 w-80 shadow-lg" onClick={(e) => e.stopPropagation()}>
              <h4 className="text-sm font-medium text-gray-700 mb-3">确认删除</h4>
              <div className="text-xs text-gray-600 mb-4">
                确定要删除实例 <span className="font-medium text-gray-900">{deleteTarget.name}</span>？
                {deleteTarget.status === 'running' && (
                  <div className="mt-2 text-amber-600 font-medium">该实例正在运行，删除前请先停止</div>
                )}
              </div>
              <div className="flex gap-2">
                <button onClick={() => { deleteLiveInstance(deleteTarget.id); setDeleteTarget(null); }}
                  className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-medium transition-colors">删除</button>
                <button onClick={() => setDeleteTarget(null)}
                  className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-medium transition-colors">取消</button>
              </div>
            </div>
          </div>
        )}

        {/* 编辑参数弹窗 */}
        {editParamsTarget && (
          <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setEditParamsTarget(null)}>
            <div className="bg-white rounded-xl p-5 w-[500px] max-h-[80vh] overflow-y-auto shadow-lg" onClick={(e) => e.stopPropagation()}>
              <h4 className="text-sm font-medium text-gray-700 mb-3">
                编辑策略参数 — {editParamsTarget.name}
              </h4>
              <div className="text-xs text-gray-500 mb-3">
                {editParamsTarget.symbol} · {getStrategyName(editParamsTarget.strategy_id)}
              </div>
              <div className="space-y-3">
                {(() => {
                  const strategy = strategies.find((s) => s.id === editParamsTarget.strategy_id);
                  if (!strategy || strategy.parameters.length === 0) {
                    return (
                      <div className="text-xs text-gray-400 text-center py-4">
                        该策略无可配置参数
                      </div>
                    );
                  }
                  return strategy.parameters.map((param: StrategyParamResponse) => (
                    <div key={param.key}>
                      <label className="block text-xs text-gray-700 mb-1">
                        {param.name}
                        {param.min !== undefined && param.max !== undefined && (
                          <span className="text-gray-400 ml-1">({param.min}~{param.max})</span>
                        )}
                      </label>
                      {param.description && (
                        <p className="text-xs text-gray-400 mb-1">{param.description}</p>
                      )}
                      {param.type === 'boolean' ? (
                        <button type="button" onClick={() => setEditParamValues((prev) => ({ ...prev, [param.key]: !prev[param.key] }))}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${editParamValues[param.key] ? 'bg-primary-600' : 'bg-gray-300'}`}>
                          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${editParamValues[param.key] ? 'translate-x-6' : 'translate-x-1'}`} />
                        </button>
                      ) : param.type === 'string' ? (
                        <input type="text" value={editParamValues[param.key] ?? param.default}
                          onChange={(e) => setEditParamValues((prev) => ({ ...prev, [param.key]: e.target.value }))}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-xs" />
                      ) : (
                        <input type="number" value={editParamValues[param.key] ?? param.default}
                          min={param.min} max={param.max} step="any"
                          onChange={(e) => setEditParamValues((prev) => ({ ...prev, [param.key]: Number(e.target.value) }))}
                          className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-xs" />
                      )}
                    </div>
                  ));
                })()}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={handleEditParams}
                  className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-xs font-medium transition-colors">保存</button>
                <button onClick={() => { setEditParamsTarget(null); setEditParamValues({}); }}
                  className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-medium transition-colors">取消</button>
              </div>
            </div>
          </div>
        )}

        {/* 创建弹窗 */}
        {showCreate && (
          <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
            <div className="bg-white rounded-xl p-5 w-[500px] max-h-[80vh] overflow-y-auto shadow-lg" onClick={(e) => e.stopPropagation()}>
              <h4 className="text-sm font-medium text-gray-700 mb-3">创建实盘策略实例</h4>
              <div className="space-y-3 text-xs">
                <div>
                  <label className="text-gray-500 mb-1 block">名称</label>
                  <input value={newInst.name} onChange={(e) => setNewInst({ ...newInst, name: e.target.value })}
                    className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900" placeholder="例：茅台网格" />
                </div>
                <div>
                  <label className="text-gray-500 mb-1 block">股票代码</label>
                  <StockSearchInput
                    value={newInst.symbol}
                    onChange={(code) => setNewInst({ ...newInst, symbol: code })}
                    placeholder="输入代码、名称或拼音首字母"
                  />
                </div>
                <div>
                  <label className="text-gray-500 mb-1 block">策略</label>
                  <select value={newInst.strategy_id} onChange={(e) => handleStrategyChange(e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900">
                    <option value="">选择策略</option>
                    {strategies.map((s) => (<option key={s.id} value={s.id}>{s.name}</option>))}
                  </select>
                </div>

                {/* 策略参数 */}
                {currentStrategy && currentStrategy.parameters.length > 0 && (
                  <div className="bg-gray-50 rounded-lg border border-gray-200 p-3 space-y-3">
                    <h4 className="text-xs font-medium text-gray-700">策略参数</h4>
                    {currentStrategy.parameters.map((param: StrategyParamResponse) => (
                      <div key={param.key}>
                        <label className="block text-xs text-gray-700 mb-1">
                          {param.name}
                          {param.min !== undefined && param.max !== undefined && (
                            <span className="text-gray-400 ml-1">({param.min}~{param.max})</span>
                          )}
                        </label>
                        {param.description && (
                          <p className="text-xs text-gray-400 mb-1">{param.description}</p>
                        )}
                        {param.type === 'boolean' ? (
                          <button type="button" onClick={() => setParamValues((prev) => ({ ...prev, [param.key]: !prev[param.key] }))}
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${paramValues[param.key] ? 'bg-primary-600' : 'bg-gray-300'}`}>
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${paramValues[param.key] ? 'translate-x-6' : 'translate-x-1'}`} />
                          </button>
                        ) : param.type === 'string' ? (
                          <input type="text" value={paramValues[param.key] ?? param.default}
                            onChange={(e) => setParamValues((prev) => ({ ...prev, [param.key]: e.target.value }))}
                            className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-xs" />
                        ) : (
                          <input type="number" value={paramValues[param.key] ?? param.default}
                            min={param.min} max={param.max} step="any"
                            onChange={(e) => setParamValues((prev) => ({ ...prev, [param.key]: Number(e.target.value) }))}
                            className="w-full px-2 py-1.5 border border-gray-300 rounded text-gray-900 text-xs" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={handleCreate} disabled={!newInst.name || !newInst.symbol || !newInst.strategy_id}
                  className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors">创建</button>
                <button onClick={() => setShowCreate(false)}
                  className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-medium transition-colors">取消</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}