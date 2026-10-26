# 自选股+盯盘交互重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AIAgent 页面右栏从「盯盘聊天」重做为「按自选股分组的 pending 信号列」,盯盘配置移入 AI 对话式弹框,信号由后端 WebSocket 定向推送。

**Architecture:** 三栏布局保留(选股|自选股|信号)。右栏 `MonitoringPanel` 重做为 `SignalPanel`,删除 `MonitorChatArea`;`MonitorRulesModal` 增强为「AI 对话生成 + 规则管理」一体弹框(复用现有 `createMonitorRules` 后端,后端零改动);后端 `evaluate_monitor_rules` 生成信号后经 `ws_manager.send_to_user` 定向推送,前端 `WebSocketProvider` 新增 `agent_signal` 分支写入 `agentStore.signals`,挂载/重连时 `fetchSignals` 兜底。

**Tech Stack:** React + TypeScript + Zustand(前端);FastAPI + SQLAlchemy + websockets(后端);pytest(后端测试)。

**注意:** 本项目**非 git 仓库**(`git rev-parse` 返回 fatal not a git repository)。所有"Commit"步骤改为**保存检查点**——在该任务末尾运行相关测试确认通过即可,不执行 `git` 命令。

**设计依据:** `docs/superpowers/specs/2026-07-01-watchlist-monitor-refactor-design.md`

---

## 文件结构

### 后端(仅新增 WS 推送,1 处改动)
- Modify: `backend/app/services/agent_service.py` — `evaluate_monitor_rules` 末尾,commit 后批量 WS 推送生成的信号

### 后端测试(新增)
- Create: `backend/tests/test_monitor_signal_push.py` — WS 推送单测

### 前端 store
- Modify: `frontend/src/stores/agentStore.ts` — 删盯盘聊天状态,新增 `addSignal`/`clearSignals`

### 前端组件
- Create: `frontend/src/components/agent/SignalGroupList.tsx` — 右栏分组信号列表
- Modify: `frontend/src/components/agent/MonitoringPanel.tsx` → 重做为 `SignalPanel`(去聊天区,挂载拉取,渲染 `SignalGroupList`)
- Modify: `frontend/src/components/agent/MonitorRulesModal.tsx` — 增强为 AI 对话生成 + 规则管理
- Modify: `frontend/src/components/agent/WatchlistPanel.tsx` — `handleSetMonitor` 改开弹框
- Modify: `frontend/src/components/agent/WatchlistCard.tsx` — 点卡片/按钮开弹框(不切右栏)
- Delete: `frontend/src/components/agent/MonitorChatArea.tsx`
- Modify: `frontend/src/components/WebSocketProvider.tsx` — 新增 `agent_signal` 分支
- Modify: `frontend/src/pages/AIAgent.tsx` — 右栏用 `SignalPanel`

---

## Task 1: 后端 — 盯盘信号生成后 WS 推送

**Files:**
- Modify: `backend/app/services/agent_service.py`(`evaluate_monitor_rules` 函数,约 774-872 行)
- Test: `backend/tests/test_monitor_signal_push.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_monitor_signal_push.py`:

```python
"""盯盘引擎生成信号后经 WebSocket 定向推送给该信号所属用户。"""
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app.services import agent_service
from app.services.agent_service import evaluate_monitor_rules, MonitorRule, AgentSignal


def _make_rule(stock_code="600519", action="buy", target_price=1600.0, user_id="u1"):
    return MonitorRule(
        id="r1",
        user_id=user_id,
        stock_code=stock_code,
        condition="跌破1600买入",
        action=action,
        target_price=target_price,
        quantity=100,
        position_pct=None,
        advance_minutes=0,
        program_code="",
        active=True,
        created_at=datetime.utcnow(),
    )


def test_signal_pushed_to_user_on_trigger(monkeypatch):
    """规则触发时,生成的信号经 ws_manager.send_to_user 推送给 rule.user_id。"""
    rule = _make_rule()
    # 行情:现价 1590 ≤ 目标价 1600 → buy 触发
    quotes = {"600519": {"price": 1590.0, "name": "贵州茅台"}}

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *conds):
            return self

        def all(self):
            return [rule]

        def first(self):
            return None  # 无已存在 pending 信号

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

        def add(self, obj):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        mock_ws.send_to_user = AsyncMock()
        # evaluate_monitor_rules 是同步函数,内部 await send_to_user 需要事件循环
        import asyncio
        asyncio.run(_run_eval(FakeDb()))

        mock_ws.send_to_user.assert_called()
        # 最后一次调用的 user_id 应为规则所属用户
        call_args = mock_ws.send_to_user.call_args
        assert call_args.args[0] == "u1"
        msg = call_args.args[1]
        assert msg["type"] == "agent_signal"
        assert msg["data"]["stockCode"] == "600519"  # signal_to_dict 输出 camelCase
        assert msg["data"]["status"] == "pending"


async def _run_eval(db):
    await evaluate_monitor_rules.__wrapped__(db) if hasattr(evaluate_monitor_rules, "__wrapped__") else None
    # 退化:直接调同步函数,推送在内部用 asyncio.ensure_future 安排
    evaluate_monitor_rules(db)


def test_no_push_when_not_triggered(monkeypatch):
    """规则未触发时不推送。"""
    rule = _make_rule(target_price=1600.0)
    quotes = {"600519": {"price": 1700.0, "name": "贵州茅台"}}  # 现价 1700 > 1600,buy 不触发

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *conds):
            return self

        def all(self):
            return [rule]

        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

        def add(self, obj):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        mock_ws.send_to_user = AsyncMock()
        evaluate_monitor_rules(FakeDb())
        mock_ws.send_to_user.assert_not_called()
```

> 说明:`evaluate_monitor_rules` 当前是**同步**函数(`def`,非 `async def`),却要调用 `await ws_manager.send_to_user`(异步)。解决办法见 Step 3:用 `asyncio.create_task` 把推送安排到事件循环(函数本身仍同步,在 `monitor_engine_loop` 的 async 上下文里运行)。测试里用 `asyncio.run` 提供事件循环,`create_task` 的推送会在循环结束前完成。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_monitor_signal_push.py -v`
Expected: FAIL —— `AttributeError: module 'app.services.agent_service' has no attribute 'ws_manager'`(尚未 import)或推送未被调用。

- [ ] **Step 3: 实现最小代码**

Modify `backend/app/services/agent_service.py`:

(a) 在文件顶部 import 区(已有 `import asyncio` 等附近)加:

```python
from app.ws.manager import ws_manager
```

> 若 `ws_manager` import 在 lifespan 启动时才初始化导致循环引用,改为函数内延迟 import:`from app.ws.manager import ws_manager` 写在 `evaluate_monitor_rules` 函数体内顶部。优先试顶部 import,失败则移入函数内。

(b) 改 `evaluate_monitor_rules` 末尾(当前是 `if generated: db.commit()` 然后 `return generated`)。在 `db.commit()` 后收集已生成的信号并推送。需要先把生成的 `sig` 对象收集到列表(当前是 `db.add(sig)` 后直接 `generated += 1`,没留存)。

把循环内的:
```python
        db.add(sig)
        generated += 1
        logger.info(f"[盯盘引擎] {rule.stock_code} 触发 {rule.action} 信号 ({trigger_desc})")
    if generated:
        db.commit()
    return generated
```

改为:
```python
        db.add(sig)
        generated_signals.append(sig)
        generated += 1
        logger.info(f"[盯盘引擎] {rule.stock_code} 触发 {rule.action} 信号 ({trigger_desc})")
    if generated:
        db.commit()
        # 推送给各信号所属用户(定向,不广播)。本函数在 monitor_engine_loop 的 async
        # 上下文里运行,用 create_task 安排推送,不阻塞评估循环。
        _schedule_signal_push(generated_signals)
    return generated
```

并在函数开头(`generated = 0` 那行附近)加 `generated_signals: list = []`。

(c) 在 `evaluate_monitor_rules` 函数**之后**新增辅助函数:

```python
def _schedule_signal_push(signals: list) -> None:
    """把生成的 AgentSignal 序列化后,经 WS 定向推送给各自的 user_id。

    在事件循环中安排为后台任务;若当前无运行中的循环(如同步单测直接调用),
    则跳过推送——真实运行环境(monitor_engine_loop 是 async)总有循环。
    """
    if not signals:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无事件循环,跳过(单测里由测试自行 mock 验证)

    # 延迟 import 避免循环引用,并复用 API 层的序列化函数
    from app.api.agent import signal_to_dict

    async def _push():
        # 按 user_id 分组,每用户一次推送其全部新信号
        by_user: dict[str, list] = {}
        for sig in signals:
            by_user.setdefault(sig.user_id, []).append(sig)
        for user_id, user_sigs in by_user.items():
            for sig in user_sigs:
                try:
                    await ws_manager.send_to_user(
                        user_id,
                        {"type": "agent_signal", "data": signal_to_dict(sig)},
                    )
                except Exception as e:
                    logger.warning(f"[盯盘引擎] 推送信号给 {user_id} 失败: {e}")

    loop.create_task(_push())
```

> 测试里 `evaluate_monitor_rules(FakeDb())` 同步调用,`_schedule_signal_push` 走 `try/except RuntimeError` 分支会直接 return,不会推送——这与测试期望(断言被调用)冲突。**因此测试用 `asyncio.run(_run_eval(db))` 包一层事件循环**。修正测试里的 `_run_eval`:让它真正在循环里调 `evaluate_monitor_rules`:

把测试中的 `_run_eval` 与 `test_signal_pushed_to_user_on_trigger` 主体改为:
```python
async def _run_eval(db):
    evaluate_monitor_rules(db)
    # 让 create_task 安排的推送执行完
    await asyncio.sleep(0)
```
并在 `test_signal_pushed_to_user_on_trigger` 里用 `asyncio.run(_run_eval(FakeDb()))` 调用(替换原来的 `asyncio.run(_run_eval(FakeDb()))` 那行——保持不变即可,关键是 `_run_eval` 要 await sleep 让 task 跑完)。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_monitor_signal_push.py -v`
Expected: 2 passed。

- [ ] **Step 5: 检查点**

Run: `cd backend && python -m pytest tests/ -v -k "monitor or pick" --tb=short`
Expected: 既有测试不被破坏,新测试通过。

---

## Task 2: 前端 store — 删盯盘聊天状态,加信号增删

**Files:**
- Modify: `frontend/src/stores/agentStore.ts`

- [ ] **Step 1: 删除盯盘聊天相关 state 与 action**

在 `frontend/src/stores/agentStore.ts` 中:

(a) `AgentStore` interface 里删除这些字段/方法声明(约 113-128 行):
```
currentMonitorStockCode
currentMonitorAdopted
monitorMessages
monitorLoading
monitorError
setCurrentMonitorStockCode
sendMonitorMessage
confirmMonitorRules
clearMonitorChat
```
保留:`monitoringRules`、`fetchMonitorRules`、`toggleMonitorRule`、`deleteMonitorRule`、`batchDeleteMonitorRules`、`cancelAllMonitorRules`、`signals`、`fetchSignals`、`updateSignalStatus`、`batchDeleteSignals`。

(b) 删除 import 里只被盯盘聊天用的 `streamResearchChat`、`AIChatMessage`(若选股仍用 `AIChatMessage` 则保留)。检查:`sendPickMessage` 用的是 `agentApi.streamPickOptimize`,不用 `streamResearchChat`;`AIChatMessage` 类型在 store 里只用于 `sendMonitorMessage`。删除两处 import:
```typescript
// 删除: import { streamResearchChat } from '@/api/ai';
// 删除: import type { AIChatMessage } from '@/api/ai';
```

(c) store 实现里删除 `currentMonitorStockCode`、`currentMonitorAdopted`、`monitorMessages`、`monitorLoading`、`monitorError` 初始 state 块(约 426-431 行),以及 `setCurrentMonitorStockCode`、`sendMonitorMessage`、`confirmMonitorRules`、`clearMonitorChat` 四个方法实现(约 433-533 行)。

- [ ] **Step 2: 新增 addSignal 与 clearSignals**

在 `AgentStore` interface 的 Monitoring 区段加声明(放在 `signals` 附近):
```typescript
  /** WS 推送收到新 pending 信号时调用;重复 id 跳过 */
  addSignal: (signal: MonitoringSignal) => void;
```

在 store 实现的 Monitoring 区段(原 `signals: []` 之后)加实现:
```typescript
  addSignal: (signal) => {
    set((state) => {
      if (state.signals.some((s) => s.id === signal.id)) return state;  // 去重
      // 只保留 pending;若新信号非 pending(理论上不会)也加入由列表自筛
      const next = [signal, ...state.signals];
      return { signals: next };
    });
  },
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无 TS 报错(可能因组件尚未改而报"MonitorChatArea 被引用"等,先记下,后续 Task 删除引用后消除)。

- [ ] **Step 4: 检查点**

store 改动完成,暂不运行(等组件改完一起验证)。

---

## Task 3: 前端组件 — 新增 SignalGroupList(右栏主体)

**Files:**
- Create: `frontend/src/components/agent/SignalGroupList.tsx`

- [ ] **Step 1: 实现 SignalGroupList**

Create `frontend/src/components/agent/SignalGroupList.tsx`:

```typescript
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
    // 按 stockCode 分组
    const map = new Map<string, MonitoringSignal[]>();
    for (const s of pending) {
      const arr = map.get(s.stockCode) ?? [];
      arr.push(s);
      map.set(s.stockCode, arr);
    }
    // 每组内按 triggerTime 倒序
    for (const arr of map.values()) {
      arr.sort((a, b) => new Date(b.triggerTime).getTime() - new Date(a.triggerTime).getTime());
    }
    // 组排序:按该组最新信号时间倒序
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
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 新文件无报错(`SignalCard` props 已存在)。

- [ ] **Step 3: 检查点**

组件就绪,待 Task 4 接入。

---

## Task 4: 前端组件 — MonitoringPanel 重做为 SignalPanel

**Files:**
- Modify: `frontend/src/components/agent/MonitoringPanel.tsx`

- [ ] **Step 1: 重写为 SignalPanel**

把 `frontend/src/components/agent/MonitoringPanel.tsx` 整体替换为:

```typescript
import { useState, useRef, useCallback, useEffect } from 'react';
import { Target, Volume2, VolumeX, History } from 'lucide-react';
import { PanelHeader } from './PanelHeader';
import { SignalGroupList } from './SignalGroupList';
import { SignalStatsBar } from './SignalStatsBar';
import { SignalHistoryModal } from './SignalHistoryModal';
import { ResizeHandle } from './ResizeHandle';
import { useAgentStore } from '@/stores/agentStore';

export function MonitoringPanel() {
  const { panelLayout, togglePanelCollapse, signals, setPanelSplit, fetchSignals } = useAgentStore();
  const isCollapsed = panelLayout.collapsed.monitor;
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const topPct = panelLayout.monitorSplit;

  // 挂载时拉一次 pending 作兜底(WS 掉线期间漏的信号)
  useEffect(() => {
    fetchSignals();
  }, [fetchSignals]);

  // 有新 pending 信号时声音提示(可选,简单实现)
  const prevCount = useRef(0);
  useEffect(() => {
    const pending = signals.filter((s) => s.status === 'pending').length;
    if (soundEnabled && pending > prevCount.current && prevCount.current !== 0) {
      // 浏览器蜂鸣:用 AudioContext 生成短促提示音,不依赖音频文件
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

  const handleVResize = useCallback(
    (clientY: number) => {
      const rect = bodyRef.current?.getBoundingClientRect();
      if (!rect) return;
      const pct = ((clientY - rect.top) / rect.height) * 100;
      setPanelSplit('monitor', pct);
    },
    [setPanelSplit]
  );

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
        <div ref={bodyRef} className="flex-1 flex flex-col overflow-hidden">
          <div style={{ height: `${topPct}%` }} className="min-h-0 overflow-y-auto p-2">
            <SignalGroupList />
          </div>
          <ResizeHandle orientation="vertical" onResize={handleVResize} />
          <div style={{ height: `${100 - topPct}%` }} className="min-h-0 overflow-hidden">
            <SignalStatsBar />
          </div>
        </div>
      )}
      <SignalHistoryModal isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    </>
  );
}
```

> 说明:删掉了原 `MonitorChatArea`、`currentMonitorStockCode`、`MonitorRulesModal` 头部按钮(规则管理移到中栏弹框)、`currentStock`/`currentSignals` 派生。整栏不再依赖"当前选中股"。`monitorSplit` 默认值 45 保留,但现在上半是信号列表、下半是统计条,可由用户拖拽。

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: `MonitoringPanel.tsx` 自身无报错。

- [ ] **Step 3: 检查点**

待 Task 5/6/7 完成后整体验证。

---

## Task 5: 前端组件 — MonitorRulesModal 增强(AI 对话生成)

**Files:**
- Modify: `frontend/src/components/agent/MonitorRulesModal.tsx`

- [ ] **Step 1: 在弹框顶部加 AI 对话生成区**

在 `frontend/src/components/agent/MonitorRulesModal.tsx` 中:

(a) 修改 import,加入 `createMonitorRules` API、`MONITOR_TEMPLATES`、`fetchWatchlist`、`fetchSignals`:
```typescript
import { useEffect, useState } from 'react';
import { X, ListChecks, Trash2, Loader2, Power, CheckSquare, Square, Bot, Plus } from 'lucide-react';
import { useAgentStore, MONITOR_TEMPLATES } from '@/stores/agentStore';
import * as agentApi from '@/api/agent';
import type { MonitoringRule, MonitoringAction } from '@/types/agent';
```

(b) 在组件函数内(现有 `const { monitoringRules, ... } = useAgentStore();` 行附近)增强解构,并加生成相关 state:
```typescript
  const { monitoringRules, fetchMonitorRules, toggleMonitorRule, deleteMonitorRule, batchDeleteMonitorRules,
          fetchWatchlist, fetchSignals, setWatchlistMonitoringStatus, watchlist } = useAgentStore();
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  // AI 对话生成
  const [draftDesc, setDraftDesc] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
```

(c) 加 `handleGenerate`(调 `createMonitorRules`,成功后刷新规则列表与自选股状态):
```typescript
  const handleGenerate = async () => {
    if (!stockCode || !draftDesc.trim()) return;
    setGenerating(true);
    setGenError(null);
    try {
      await agentApi.createMonitorRules(stockCode, draftDesc.trim());
      setDraftDesc('');
      // 刷新本股规则列表
      await fetchMonitorRules(stockCode);
      // 该股 monitoringStatus → active
      const stock = watchlist.find((w) => w.code === stockCode);
      if (stock) setWatchlistMonitoringStatus(stock.id, 'active');
      await fetchWatchlist();
      await fetchSignals();
    } catch (e) {
      setGenError(e instanceof Error ? e.message : 'AI 解析失败,可重试');
    } finally {
      setGenerating(false);
    }
  };
```

(d) 在弹框 body 顶部(现有 `<div className="flex-1 overflow-y-auto p-3 space-y-2">` **之前**)插入 AI 对话区:
```tsx
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
```

(e) 把原空态文案("该股票暂无盯盘规则,在上方对话中描述策略并采纳即可创建。")保留,它现在与上面对话区呼应,无需改。

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: `MonitorRulesModal.tsx` 无报错。

- [ ] **Step 3: 检查点**

弹框增强完成。

---

## Task 6: 前端组件 — WatchlistPanel/Card 改为开弹框

**Files:**
- Modify: `frontend/src/components/agent/WatchlistPanel.tsx`
- Modify: `frontend/src/components/agent/WatchlistCard.tsx`

- [ ] **Step 1: WatchlistPanel 持有 modal 开合 state**

在 `frontend/src/components/agent/WatchlistPanel.tsx`:

(a) 加 import 与 state(在现有 `const [addStockOpen, setAddStockOpen] = useState(false);` 附近):
```typescript
import { MonitorRulesModal } from './MonitorRulesModal';
// ...
  const [monitorStock, setMonitorStock] = useState<{ code: string; name: string } | null>(null);
```

(b) 改 `handleSetMonitor`(原是 `setCurrentMonitorStockCode(code)`):
```typescript
  const handleSetMonitor = (code: string, name: string) => {
    setMonitorStock({ code, name });
  };
```
并从 store 解构里**移除** `setCurrentMonitorStockCode`(若还在解构列表里)。

(c) 在组件 return 末尾(现有 `<AddStockModal .../>` 旁边)加:
```tsx
      <MonitorRulesModal
        isOpen={monitorStock !== null}
        onClose={() => setMonitorStock(null)}
        stockCode={monitorStock?.code ?? null}
        stockName={monitorStock?.name}
      />
```

- [ ] **Step 2: WatchlistCard 保持原 onSetMonitor 调用(无需改)**

`WatchlistCard.tsx` 已通过 `onSetMonitor(stock.code, stock.name)` 调用,接口不变(`onSetMonitor: (code, name) => void`),只是父组件行为变了。无需改动。确认 `WatchlistCard` 仍 import 自 `@/stores/agentStore` 的只有 `removeFromWatchlist`(已是),没有引用已删的 `setCurrentMonitorStockCode`。

- [ ] **Step 3: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无 `setCurrentMonitorStockCode` 相关报错。

- [ ] **Step 4: 检查点**

中栏→弹框链路接通。

---

## Task 7: 前端 — 删 MonitorChatArea,改 AIAgent 入口,接 WS

**Files:**
- Delete: `frontend/src/components/agent/MonitorChatArea.tsx`
- Modify: `frontend/src/pages/AIAgent.tsx`
- Modify: `frontend/src/components/WebSocketProvider.tsx`

- [ ] **Step 1: 删除 MonitorChatArea**

删除文件 `frontend/src/components/agent/MonitorChatArea.tsx`。
全局搜索确认无残留引用:`grep -r "MonitorChatArea" frontend/src`(应为空)。

- [ ] **Step 2: AIAgent 右栏换 SignalPanel**

`frontend/src/pages/AIAgent.tsx` 当前:
```tsx
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
```

`MonitoringPanel` 已重做为信号面板(组件名保留 `MonitoringPanel` 避免改 `ResizableLayout` 的 `monitor` slot 和 `PanelKey`),所以 **AIAgent.tsx 无需改动**。确认 `ResizableLayout` 接收 `monitor` prop 不变。

> 若希望语义清晰,可在 Task 4 把组件名改为 `SignalPanel` 并同步 `AIAgent.tsx` import。为减少改动面,本计划保留 `MonitoringPanel` 名字,只改其内部实现。**采用保留名字方案,AIAgent.tsx 不动。**

- [ ] **Step 3: WebSocketProvider 加 agent_signal 分支**

在 `frontend/src/components/WebSocketProvider.tsx` 的 `ws.onmessage` 处理里(`if (msg.type === 'trade_sync')` 分支之后、`catch` 之前)加:

```typescript
          if (msg.type === 'agent_signal') {
            const data = msg.data;
            if (data) {
              useAgentStore.getState().addSignal(data);
            }
          }
```

并在文件顶部 import 区加:
```typescript
import { useAgentStore } from '@/stores/agentStore';
```

同时在 `ws.onopen`(现有「Re-send subscriptions after reconnect」注释块之后)加重连兜底拉取:
```typescript
        // 重连后全量对齐 pending 信号,补掉线期间漏的
        useAgentStore.getState().fetchSignals();
```

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无报错。

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 5: 检查点**

前端整体编译通过。

---

## Task 8: 手测验收

**Files:** 无(手动验证)

- [ ] **Step 1: 启动前后端**

Run(分两个终端):
- 后端:`cd backend && python -m uvicorn app.main:app --reload --port 8000`
- 前端:`cd frontend && npm run dev`

打开前端 AIAgent 页面,登录。

- [ ] **Step 2: 验收弹框设盯盘**

1. 中栏自选股卡片点「设盯盘」→ 弹框打开,**右栏不切换**(右栏始终是信号列表)。
2. 弹框内选模板或输入"跌破1650止损"→ 点「生成」→ AI 解析出规则展示在下方列表,该规则 active。
3. 关闭弹框 → 中栏该股状态点变绿(盯盘中)。

- [ ] **Step 3: 验收信号实时推送**

1. 给某只已盯盘股临时设一条 `target_price` 等于当前现价的规则(或用规则管理改目标价贴近现价)。
2. 等待交易时段 `monitor_engine_loop` 下一分钟评估(或手动在 backend 触发一次 `evaluate_monitor_rules`)。
3. 右栏信号列表**不刷新页面**即冒出该股分组下的 pending 信号。
4. 若开了声音,有提示音。

- [ ] **Step 4: 验收信号处理**

1. 右栏点某信号「确认」→ 该信号从列表消失(因只显 pending)。
2. `SignalStatsBar` 计数更新。

- [ ] **Step 5: 验收 WS 断连兜底**

1. 停掉后端(断 WS)→ 前端控制台显示 `[WS] closed` 并重连。
2. 重启后端 → WS `onopen` 触发 `fetchSignals` 全量对齐。
3. 刷新页面 → 右栏仍能拉到 pending 信号。

- [ ] **Step 6: 检查点**

全部验收通过,重构完成。

---

## 自审

**1. Spec 覆盖:** 逐条核对 spec:
- §3.1 三栏重组 → Task 4(右栏重做)+ Task 6(中栏开弹框)+ Task 2(删 currentMonitorStockCode)。✓
- §3.2 组件改动清单 → Task 3(SignalGroupList)/4(MonitoringPanel)/5(MonitorRulesModal)/6(WatchlistCard/Panel)/7(删 MonitorChatArea+WS)/2(store)。✓ `ResizableLayout`/`PanelHeader`/`SignalCard`/`SignalStatsBar`/`SignalHistoryModal` 复用未改,符合。
- §4.1 设盯盘数据流 → Task 5。✓
- §4.2 信号生成与推送 → Task 1(后端)+ Task 7 Step 3(前端 WS)。✓
- §4.3 信号处理 → 复用现有 `updateSignalStatus`,Task 3 的 `SignalGroupList` 只显 pending 实现"处理完消失"。✓
- §4.4 选股→自选不变 → 无任务(明确不动)。✓
- §4.5 store 状态变化 → Task 2。✓
- §5 错误处理 → Task 1(WS 无连接静默)/Task 5(AI 失败重试)/Task 3(去重靠 addSignal)/Task 7 Step 3(重连兜底)。✓
- §6 测试 → Task 1(后端单测)/Task 8(手测)。前端单测(spec §6.2)本计划未含代码级单测——见下方说明。

**2. 占位扫描:** 无 TBD/TODO/"add error handling"等。所有代码块完整。

**3. 类型一致:** `addSignal(signal: MonitoringSignal)` 在 Task 2 声明/实现,Task 7 Step 3 调用 `useAgentStore.getState().addSignal(data)`——`data` 来自 `msg.data`,与后端 `signal_to_dict` 返回的 camelCase 字段(`stockCode` 等)对齐(`MonitoringSignal` 接口)。`MonitoringPanel` 组件名保留不与 `SignalPanel` 冲突。`handleSetMonitor(code, name)` 签名在 WatchlistCard(现有)与 WatchlistPanel(Task 6)一致。✓

**说明 — 前端代码级单测:** spec §6.2 列了前端单测(WebSocketProvider/SignalGroupList/MonitorRulesModal/WatchlistCard)。本项目前端目前**无测试框架配置**(无 vitest/jest 依赖,`package.json` 无 test 脚本),引入测试框架超出本次重构范围。故以 Task 8 手测替代前端代码级单测,后端仍用 pytest(TDD)。若后续要补前端单测,另立计划引入 vitest。
