# 自选股 + 盯盘交互重构 设计

- 日期:2026-07-01
- 范围:前端 `AIAgent` 页面三栏布局重构 + 盯盘信号 WebSocket 推送
- 关联记忆:[[agent-background-loops]] [[ai-pick-strategy-program]] [[xunfei-llm-tool-calling]]

## 1. 背景与目标

当前 `AIAgent.tsx` 三栏布局为:**左=AI选股 / 中=自选股 / 右=盯盘(聊天区+信号列表)**。

问题:
- 盯盘配置藏在右栏聊天区,要先点中栏自选股「切到右栏」再对话设规则,链路绕。
- 右栏上半是盯盘聊天,下半才是信号,信号被挤占。
- agent 模块信号**无前端轮询**,后台 `monitor_engine_loop` 每分钟生成的 pending 信号,前端只在少数动作后才拉取,体验不实时。

目标(用户需求):
1. 盯盘策略改为**弹框**设置,在自选股列表里逐只配置,不再切右栏。
2. 右栏从「盯盘」改成「信号列」,按自选股分组对应左侧盯盘股列表。
3. 信号实时推送到前端。

## 2. 决策汇总(brainstorming 已确认)

| 议题 | 选择 | 备选 |
|---|---|---|
| 整体布局 | **C:三栏 选股 \| 自选股 \| 信号** | A(两栏去选股)/B(信号内联) |
| 盯盘弹框 | **A:AI对话式,复用 `createMonitorRules`** | B(纯表单)/C(AI+可编辑表单) |
| 信号列对应 | **C:按自选股分组,只显 pending** | A(全部平铺+高亮)/B(单股跟随) |
| 信号刷新 | **5-C:WebSocket 推送** | A(setInterval)/B(动作触发拉取) |

## 3. 布局与组件结构

### 3.1 三栏重组

```
左:AI选股(StockPickingPanel)   ← 不动
中:自选股(WatchlistPanel)       ← 卡片点「设盯盘」改开弹框,不再切右栏
右:信号(SignalPanel,新)        ← 替换原 MonitoringPanel 的盯盘聊天,改成信号分组列表
```

### 3.2 组件改动清单

| 组件 | 改动 |
|---|---|
| `MonitoringPanel.tsx` | **重做为 `SignalPanel`**:去掉上半 `MonitorChatArea` 聊天区,整栏改为信号分组列表 + `SignalStatsBar`。保留头部「信号历史」按钮;去掉「盯盘规则」按钮(规则管理移入弹框)。挂载时 `fetchSignals()` 兜底拉取 |
| `MonitorChatArea.tsx` | **删除**。其 AI 对话能力搬进 `MonitorRulesModal` |
| `MonitorRulesModal.tsx` | **保留并增强**:从"只看规则"升级为"AI 对话生成 + 确认激活 + 规则管理"一体的设盯盘弹框(A 方案载体)。模板按钮 `MONITOR_TEMPLATES` 搬入 |
| `WatchlistCard.tsx` | 点卡片/「设盯盘」按钮 → 打开 `MonitorRulesModal`(传 stockCode),**不再** `setCurrentMonitorStockCode` 切右栏 |
| `WatchlistPanel.tsx` | `handleSetMonitor` 改为开弹框(局部 state 控制 modal 开合) |
| `SignalCard.tsx` | 保留,作为分组下的信号项 |
| 新增 `SignalGroupList.tsx` | 右栏主体:按自选股分组渲染,有 pending 信号的股置顶,无信号的不显示;组内按 `trigger_time` 倒序 |
| `WebSocketProvider.tsx` | 新增 `msg.type === 'agent_signal'` 分支 → `agentStore.addSignal(signal)` |
| `agentStore.ts` | 删盯盘聊天相关状态;`MonitorRulesModal` 直接调 `agentApi.createMonitorRules` |

### 3.3 关键边界

- `currentMonitorStockCode` 这个"切右栏盯盘"的概念**整体删除**——右栏不再依赖"当前选中的股",而是显示全部自选股的分组信号。盯盘配置完全本地化到弹框(针对某只股)。
- 右栏批量入口(「全部盯盘」「取消全部盯盘」)保留在 `WatchlistSummary`(中栏底部),不挪。

## 4. 数据流

### 4.1 设盯盘(弹框内,AI 对话式,复用现有后端)

```
WatchlistCard 点「设盯盘」
  → MonitorRulesModal 打开(stockCode 入参)
  → 弹框内小聊天:用户输入"跌破1650止损..."
  → agentApi.createMonitorRules(stockCode, description)   [现有端点,后端 AI 解析 → MonitorRule]
  → 返回 rules[] 展示在弹框内(条件/动作/目标价)
  → 用户「确认激活」:规则创建即 active=true
  → 弹框关闭,刷新 watchlist(该股 monitoringStatus → active)+ fetchSignals
```

后端**零改动**:`createMonitorRules` 已返回结构化规则。弹框只是把原 `MonitorChatArea` + `confirmMonitorRules` 的逻辑搬进 modal。

### 4.2 信号生成与推送(WS)

```
后台 monitor_engine_loop 每分钟评估 MonitorRule
  → evaluate_monitor_rules 生成 pending AgentSignal(已有逻辑)
  → 【新增】生成信号后 ws_manager.send_to_user(user_id, {type:'agent_signal', data: signal})
  → 前端 WebSocketProvider 收到 → agentStore.addSignal(signal)
  → 右栏 SignalGroupList 实时出现该股分组下的新信号
```

`evaluate_monitor_rules` 已知每条信号的 `user_id`(`rule.user_id`),定向推送,不广播给无关用户。

### 4.3 信号处理(确认/忽略)

```
SignalCard 点「确认/忽略」
  → agentApi.updateSignalStatus(id, status)   [现有]
  → 该信号 status 离开 pending → 从右栏分组列表消失(只显 pending)
  → SignalStatsBar 计数更新
```

### 4.4 选股 → 自选(不变)

左栏选股 → `PickResultCard`「加入自选」→ `addToWatchlist` 写 `agent_watchlist`。完全不动。

### 4.5 store 状态变化

`agentStore` **删除**:`currentMonitorStockCode`、`currentMonitorAdopted`、`monitorMessages`、`monitorLoading`、`monitorError`、`sendMonitorMessage`、`confirmMonitorRules`、`clearMonitorChat`、`setCurrentMonitorStockCode`。

**保留**:`signals`、`fetchSignals`、`updateSignalStatus`、`batchDeleteSignals`、`monitoringRules`(弹框查看用)、`fetchMonitorRules`、`toggleMonitorRule`、`deleteMonitorRule`、`batchDeleteMonitorRules`、`cancelAllMonitorRules`。

**新增**:`addSignal(signal: MonitoringSignal)`——WS 推送时调用,插入 pending;重复 id 跳过。

## 5. 错误处理与边界

### 5.1 WS 推送可靠性
- **离线/断连兜底**:`SignalPanel` 挂载时 `fetchSignals()` 拉当前 pending;WS `onopen`(重连)后也调一次 `fetchSignals` 全量对齐,避免漏单。
- **去重**:WS 收到信号若 `signals` 已有同 `id` 则跳过。
- **顺序**:同一股多条信号按 `trigger_time` 倒序(新在上)。

### 5.2 弹框 AI 生成失败
- `createMonitorRules` 失败(讯飞 1105/超时,见 [[xunfei-llm-tool-calling]] [[xunfei-transient-retry-bug]]):弹框内显示错误条,规则列表不更新,可重试。后端 `_ai_json` 已有退避重试,前端只兜 UI。
- AI 不可用时后端 `parse_monitor_rules` 已有**回退单条 alert 规则**逻辑,弹框照常展示,用户可确认或改描述重试。

### 5.3 信号处理并发
- 用户确认信号、同时后台引擎给同规则生成信号:后端 `evaluate_monitor_rules` 已有"每规则至多一条 pending"去重,不堆积。前端 `updateSignalStatus` 成功后本地立即移出 pending;WS 增量推送的新信号再进入。

### 5.4 盯盘状态同步
- 弹框确认激活规则 → 该股 `monitoringStatus=active`,中栏卡片状态点变绿。
- 删光某股所有规则 / 「取消全部盯盘」→ 状态回 `none`。`cancelAllMonitorRules` 已有刷新逻辑,保留。

### 5.5 空态
- 中栏空:显示"暂无自选股"(已有)。
- 右栏无 pending 信号:显示空态"确认盯盘规则后将接收实时信号"(复用现有空态文案)。

## 6. 测试策略

### 6.1 后端(WS 推送为唯一新增后端逻辑)
- `evaluate_monitor_rules` 生成信号后调 `ws_manager.send_to_user` —— 单测:mock `ws_manager`,构造触发规则,断言 `send_to_user` 以正确 `user_id` 和 `{type:'agent_signal', data:{...}}` 被调用一次;未触发时不调用;WS 无该用户连接时不报错(静默返回)。
- 复用 `test_pick_rules.py` 风格,新增 `tests/test_monitor_signal_push.py`。
- 不改 AI 解析/规则评估逻辑,既有覆盖不变。

### 6.2 前端
- `WebSocketProvider` 新增 `agent_signal` 分支:mock WS 消息,断言 `agentStore.addSignal` 被调,重复 id 不重复插入。
- `SignalGroupList`:分组渲染单测——3 只股 + 5 条信号(含 1 条 confirmed),断言只渲染 pending、按股分组、有信号的股置顶、组内按时间倒序。
- `MonitorRulesModal`:交互单测——输入描述 → 调 `createMonitorRules` → 展示返回规则 → 「确认激活」关闭并刷新 watchlist status。
- `WatchlistCard`:点「设盯盘」开 modal(而非切右栏)。

### 6.3 手测验收清单
1. 中栏点「设盯盘」→ 弹框开,右栏不切换。
2. 弹框内 AI 对话生成规则 → 确认 → 中栏该股变"盯盘中"。
3. 后台引擎触发(临时把某规则 `target_price` 设成当前价)→ 右栏实时冒出该股分组下信号(不刷新页面)。
4. 点信号「确认」→ 从右栏消失。
5. 断 WS → 刷新页面 → 右栏仍能拉到 pending(兜底)。

## 7. 不做的事(YAGNI)

- 不改左栏 AI 选股任何逻辑。
- 不改后端 AI 解析 / 规则评估 / 信号生成逻辑(只加 WS 推送一行)。
- 不引入 setInterval 轮询(用 WS 推送 + 挂载/重连兜底)。
- 不做表单式手动配规则(B 方案)或 AI+可编辑表单(C 方案)——本次只做 A。
- 不动 Trading 页面 `SignalPanel`(那是 `liveTradingStore` 的另一套信号)。
