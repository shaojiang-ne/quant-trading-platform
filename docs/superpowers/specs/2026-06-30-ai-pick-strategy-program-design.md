# AI 选股策略规则程序化设计

- **日期**:2026-06-30
- **状态**:已认可,待写实现计划
- **关联记忆**:[[agent-background-loops]] [[ai-pick-auto-data-source]] [[xunfei-llm-tool-calling]]

## 1. 背景与问题

当前 AI 选股(`agent_service.execute_pick_strategy`)的流程是「执行时现解析 + 硬编码打分」:
- 每次执行都调 `_ai_json` 把策略描述解析成筛选条件 JSON;
- 用写死在 Python 里的 `_match_score`(PE 加10、量比加12…)打分。

`PickStrategy.rules` 字段(`models.py:268`)虽存在却是空壳——创建时写 `rules=[]`(`agent.py:129`),执行时完全没读它。这与盯盘侧已有 `MonitorRule.program_code`（固化规则程序）的成熟做法不一致。

## 2. 目标流程

把选股改为「确认后固化规则程序,执行时跑程序」:

```
1. 输入想法   POST /pick/strategy { description }
              → AI 多轮迭代深度思考 → 产出 optimized_description
              → 存库 status=draft, rules=[]
2. 用户确认   POST /pick/strategy/{id}/confirm
              → AI 把 optimized_description 编译成结构化规则 JSON
              → 严格校验 → 存 PickStrategy.rules → status: draft → confirmed
3. 选股执行   POST /pick/execute/{id} 或 定时调度触发
              → 取成分股行情 → 跑 rules 程序(filters 硬筛 + scoring 加权排序)→ top_n 落库 PickResult
4. 定时执行   scheduled_pick_loop 命中 schedule_time → 同步骤3
5. 结果查看   GET /pick/results/{id}
```

**关键差异**:
- `rules` 从空壳变为真正承载规则程序(借鉴盯盘 `program_code`)。
- `execute_pick_strategy` 不再每次调 `_ai_json` 现解析,而是读 `strategy.rules` 跑解释器——快、可复现、可审计、执行时零 LLM 调用。
- 新增 `confirm` 端点作为「生成规则程序」的明确时机。
- `/ai/research-chat` 完全不动。

## 3. 数据模型与状态机

### 3.1 复用现有表,不加字段

`PickStrategy.rules`(JSON)与 `status`(draft/confirmed/scheduled)已存在,直接复用。

### 3.2 `PickStrategy.rules` 结构

```json
{
  "pool": "hs300",
  "filters": [
    {"field": "pe_ttm", "op": "<=", "value": 30},
    {"field": "pe_ttm", "op": ">",  "value": 0},
    {"field": "vol_ratio", "op": ">=", "value": 1.5}
  ],
  "scoring": [
    {"field": "vol_ratio", "weight": 12, "direction": "high"},
    {"field": "turnover_pct", "weight": 6, "direction": "high"},
    {"field": "change_pct", "weight": 8, "direction": "high"}
  ],
  "top_n": 6
}
```

- `field` 白名单(对齐 `_fetch_pool_quotes` 产出字段,`agent_service.py:153-164`):
  `pe_ttm / pb / vol_ratio / turnover_pct / change_pct / float_mcap_yi / amount_wan / price`。
- `op`:`> / >= / < / <= / ==`。
- `direction`:`high`(越高分越高)/ `low`(越低分越高)。
- `rules=[]` = 草稿未确认;非空 = 已固化规则程序。

### 3.3 `pool` 多指数(分阶段)

| pool 值 | 指数 | 取数 | 本期 |
|---|---|---|---|
| `hs300` | 沪深300 | `get_index_constituents("000300")` | ✅ |
| `sse50` | 上证50 | `get_index_constituents("000016")` | ✅ |
| `star50` | 科创50 | `get_index_constituents("000688")` | ✅ |
| `csi_a50` | 中证A50 | 待验证 akshare 接口 | 后续 |
| `csi_a100` | 中证A100 | 待验证 | 后续 |
| `csi_a500` | 中证A500 | 待验证 | 后续 |
| `csi100` | 中证100 | 待验证 | 后续 |

`data_source_akshare.py` 的 `get_index_constituents` 从写死 `000300` 改为按 `index_code` 参数取,加 `pool → index_code` 映射表。未支持的 pool 在校验阶段直接拒绝(不造假)。

### 3.4 状态机

```
draft ──confirm──▶ confirmed ──schedule──▶ scheduled
  │                   │
  │ rules=[]          │ rules={规则程序}
  └─可编辑/删除        └─可执行/可重新confirm
```

- **编辑即清空**:用户确认后又改 `description` → 自动清空 `rules`、`status` 退回 `draft`。规则始终与描述一致。
- **draft 拒绝执行**:`execute_pick_strategy` 执行前若 `rules` 为空,直接拒绝(422),不再 fallback 现解析。

## 4. AI 深度思考与规则编译

### 4.1 阶段一:多轮迭代生成优化策略(创建时)

用户输入想法后,跑 2~3 轮单轮纯文本 LLM 调用,每轮基于上一轮产出深化:

```
轮1(理解+初稿):  想法 → 策略初稿描述 + 关键筛选维度清单
轮2(细化+量化):  初稿 → 维度量化为阈值(PE≤30、量比≥1.5…)+ 风险提示
轮3(收敛):      细化版 → 最终 optimized_description
```

- 每轮一次 `_ai_json` 单轮调用(system+user,无 tools)。
- **退避重试**:每轮 4 次,0.8/1.6/3.2s(`plan_and_fetch_data` 同款,`agent_service.py:812-818`),`_ai_json` 返回 None 即重试。
- **降级**:某轮重试仍失败,用上一轮产出作为最终结果;LLM 完全不可用退化为现有单轮 `optimize_pick_strategy` 行为。
- 只产出文本描述,不产出规则 JSON(与「确认后才生成规则」一致)。
- 最终 `optimized_description` 存库,`status=draft`,`rules=[]`。

### 4.2 阶段二:规则编译(确认时)

用户确认后,一次单轮纯文本 LLM 调用,把 `optimized_description` 编译成规则 JSON:

```
输入: optimized_description + 可用字段白名单 + pool 枚举 + JSON schema 说明
输出: { pool, filters[], scoring[], top_n } → 校验 → 存 PickStrategy.rules
```

- 复用 `_ai_json` + 退避重试。
- **严格校验**(`validate_pick_rules`):
  - `pool` 在枚举内(本期 `hs300/sse50/star50`;其余报「该指数暂不支持」);
  - `filters[].field` 在白名单,`op` 合法,`value` 可转 float;
  - `scoring[].field` 在白名单,`direction` ∈ {high,low},`weight` 可转 float;
  - `top_n` 限 1~20,默认 6。
  - 校验失败 → 退避重试;仍失败 → confirm 返回 503,策略保持 draft,**不存非法规则**。

### 4.3 不走 function calling

两阶段都用「单轮纯文本 + JSON 解析」,不用 `chat_stream_with_tools` 多轮 tool 消息。理由:多轮 tool 消息回灌最易撞讯飞 1105([[xunfei-llm-tool-calling]])。`PICK_TOOLS`/`execute_pick_tool` 保留给 `/ai/research-chat`,不在本链路。

## 5. 规则程序解释器与选股执行

### 5.1 新增 `run_pick_program(rules, quotes) -> list[(score, reason, stock)]`

纯函数,无副作用。步骤:

1. **校验 rules**(复用 `validate_pick_rules`)。非法 → 抛 `PickRuleError`,上层捕获返回错误。
2. **filters 硬筛**:所有 filter 都满足才保留;任一不满足淘汰。`field` 经 `_metric_value`(`agent_service.py:566`)取值;取不到值视为不满足(淘汰),避免 NaN 混入。
3. **scoring 加权打分**:基准 60 分;每项按 `direction` 在候选集内相对位置归一化(越高/越低 → 越加分)× `weight`。产出 `(score, reason)`,夹 `[0,100]`。
4. **排序 + top_n**:按分降序取 `top_n`(默认6)。

打分用「候选集内相对位置归一化」而非绝对阈值加减分,使不同策略/行情下打分自适应,权重由规则程序决定。

### 5.2 改造 `execute_pick_strategy`(`agent_service.py:213`)

```
async def execute_pick_strategy(db, strategy, user_id):
    rules = strategy.rules
    if not rules:
        raise PickRuleError("策略未确认,无法执行")
    quotes = _fetch_pool_quotes(rules["pool"])   # pool 传入,按指数取股池
    if not quotes:
        return []
    scored = run_pick_program(rules, quotes)     # 跑解释器,不再 _ai_json 现解析
    # top_n 落库 PickResult(沿用现有逻辑)
```

- 执行时零 LLM 调用。
- `_fetch_pool_quotes` 签名加 `pool` 参数,内部按 pool→index_code 取成分股。
- `PickResult` 落库逻辑不变(清旧→写新,`agent.py:218-223`)。

### 5.3 旧函数处置

- `_match_score`(`168`):被解释器取代,**删除**(避免两套打分逻辑并存)。
- `_ai_json` / `_json_from_ai`:保留,§4 两阶段仍用。
- `optimize_pick_strategy`(`71`):改造为 `think_and_optimize_strategy`(多轮+退避),旧单轮逻辑作为其降级路径。

## 6. API 端点与错误处理

### 6.1 端点变更(`backend/app/api/agent.py`)

| 方法 | 端点 | 变更 |
|---|---|---|
| POST | `/pick/strategy` | 改为调 `think_and_optimize_strategy`(多轮+退避),存 draft `rules=[]` |
| POST | `/pick/strategy/{id}/confirm` | **新增**:AI 编译规则→校验→存 `rules`,`status→confirmed` |
| PUT | `/pick/strategy/{id}` | 编辑描述时清空 `rules`、`status` 退回 draft |
| POST | `/pick/execute/{id}` | 改为读 `rules` 跑解释器;`rules` 空 → 422 拒绝 |
| POST | `/pick/schedule` | 不变 |
| GET | `/pick/results/{id}` | 不变 |
| GET | `/pick/strategies` | 不变(`strategy_to_dict` 已含 `rules`) |

### 6.2 错误处理

| 场景 | 处理 |
|---|---|
| execute 时 `rules` 空(draft) | 422,「策略未确认,请先确认生成规则」 |
| confirm 时 AI 编译失败/重试耗尽 | 503,策略保持 draft,「规则生成失败,请修改描述后重试」,不存非法规则 |
| `pool` 不在支持枚举 | confirm 校验阶段 422,「该指数暂不支持,当前支持 hs300/sse50/star50」 |
| 取成分股失败(akshare 异常) | execute 返回空 list + 日志,不造假 |
| 取行情失败 | 同上,返回空 list |
| 解释器校验异常(`PickRuleError`) | execute 422 + 错误明细(confirm 已校验的兜底) |
| LLM 1105 风暴 | 退避重试;某轮失败用上一轮产出降级;全失败退化为单轮/返回错误 |

### 6.3 事务性

- confirm:校验通过后才 `db.commit()` 写 `rules`+`status`;失败不写。
- execute:沿用「先清旧 PickResult 再写新结果」于一个事务。

## 7. 测试策略

### 7.1 解释器单测(核心)

`run_pick_program` 纯函数,伪造行情测:
- filters:多 filter AND、取不到字段值被淘汰、边界值(恰好等于阈值)。
- scoring:`high`/`low` 方向正确、权重生效、归一化自适应。
- top_n:超候选数返回全部、默认6。
- 校验:非法 `pool`/`field`/`op`/`direction` 抛 `PickRuleError`。
- 空规则:空 filters+空 scoring → 全部保留、统一基准分。

### 7.2 规则校验单测

`validate_pick_rules`:合法通过;缺字段、op 非法、value 非数字、pool 未支持 被拒。

### 7.3 取数链路

- `get_index_constituents` 多指数:本期三指数各自取到非空成分股。
- ⚠️ [[ai-pick-auto-data-source]] 记录的坑:独立验证脚本会被 `app/core/__init__.py` 导入 vnpy 阻断(开发机未装 vnpy)。测试需绕过 app 包导入或用最小自包含脚本。

### 7.4 端到端(可选)

- confirm:伪造 LLM 返回合法/非法规则,验证存库与拒绝。
- execute:draft 拒绝、confirmed 跑通、取数失败返回空。
- LLM 真实调用因讯飞 1105 不稳定,不纳入必须 CI,仅本地手测。

### 7.5 不测

- `/ai/research-chat` 链路(未改动)。
- 定时循环调度(已有 [[agent-background-loops]] 覆盖,本期只改其调用的 `execute_pick_strategy` 内部)。

## 8. 影响面

- 改:`backend/app/services/agent_service.py`、`backend/app/api/agent.py`、`backend/app/core/data_source_akshare.py`(多指数取数)。
- 新增:`validate_pick_rules`、`run_pick_program`、`PickRuleError`、`confirm` 端点、`think_and_optimize_strategy`。
- 删:`_match_score`。
- 不动:`/ai/research-chat`、定时循环挂载(`main.py`)、数据模型字段(复用 `rules`)。
- 前端:需配合新增「确认」按钮交互(本 spec 聚焦后端,前端交互另行处理)。
