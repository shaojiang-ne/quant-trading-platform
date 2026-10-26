# 策略与回测模块完整性测试设计

**日期**: 2026-07-04
**状态**: 待审核
**目标**: 对策略与回测模块做完整性测试，覆盖 AI 策略生成（需求理解→生成代码→自动测试）与策略回测全链路。策略代码后期上实盘，务必准确真实，不能有 BUG——实盘资金安全命门。

## 1. 背景与现有覆盖

### 1.1 模块链路

**AI 策略生成链路**：
- `app/api/ai.py` 三步流式端点 `generate-stream`（understand/generate/fix）+ `generate-strategy`（一次性出 JSON：name/code/parameters）+ `test-code`（沙箱 exec 跑模拟数据 + 信号值域校验 + create_adapter 兼容性）
- `app/services/ai_service.py` 提示词与讯飞重试兜底（1105/503/过载退避）
- `app/core/strategy_adapter.py:resolve_strategy_class` 动态编译用户代码（exec → 发现 CtaStrategy 子类或 generate_signals 函数 → 包装注册）

**回测链路**：
- `app/services/vnpy_backtest_service.py:CtaBacktestingEngine`（预计算/增量两模式 + 5 项 `_verify_result` 验算 + `verification_failed` 标志）+ `run_vnpy_backtest` 入口
- `app/core/strategy_adapter.py:CtaSignalAdapter`（T+1/涨跌停/网格/save_state/load_state）

### 1.2 现有测试（18 文件 / 315 例）

| 文件 | 覆盖点 |
|---|---|
| test_strategies_signal.py | 14 策略信号逻辑正确性 |
| test_strategies_edge.py | 边界（单 bar/两 bar/极短/常数价） |
| test_strategies_onbar.py | 增量 on_bar 与批量 generate_signals 一致 |
| test_strategies_stability.py | 信号稳定性 + 信号层无未来函数 |
| test_indicators.py | 技术指标计算 |
| test_strategy_adapter.py | 适配器状态转换 |
| test_no_lookahead.py | 回测层无未来函数（截断 vs 全量）+ 预计算/增量一致 |
| test_engine_invariants.py | 引擎不变量 |
| test_engine_end_to_end.py | 端到端 |
| test_verify_result.py | 5 项验算 + 篡改检测 + 末尾持仓误报已知缺陷 |
| test_backtest_crosscheck.py | 回测交叉校验 |
| test_dynamic_strategy.py | 动态编译 resolve_strategy_class |
| test_cross_order.py | 网格交叉订单 |
| test_non_daily_precompute.py | 非日频预计算 |
| test_monitor_signal_push.py | 监控信号推送 |
| test_trade_flow_sim.py | 交易流模拟 |
| test_pick_rules.py | 选股规则 |
| test_data_source_constituents.py | 数据源成分股 |

### 1.3 实盘资金安全盲区清单

| 薄弱环节 | 现有覆盖 | 处理 |
|---|---|---|
| T+1 当天不卖 | 无 | ✅ 新建 test_t_plus_1_and_limits.py |
| 涨停买不进 / 跌停卖不出 | 无 | ✅ 同上 |
| 佣金/印花税精确对拍 | 仅篡改检测，未手算 | ✅ 新建 test_commission_capital.py |
| 最小 100 股整手 | 无 | ✅ 同上（先测试再定是否 BUG） |
| 持仓状态持久化 | 无（save/load_state 全无测试） | ✅ 新建 test_state_persistence.py |
| 三沙箱注入一致性 | 仅 resolve 一条路径 | ✅ 新建 test_sandbox_consistency.py |
| 无未来函数 | 已覆盖 | 不补 |
| 验算篡改检测 | 已覆盖 | 不补 |
| 网格交叉订单 | 已覆盖 | 不补 |
| 验算第5项末尾持仓误报 | 如实记录 | 🔧 修复（本次） |

## 2. 总体架构

### 2.1 三层测试金字塔

```
tests/
├─ test_t_plus_1_and_limits.py      [新] 层1: T+1 / 涨停买不进 / 跌停卖不出  (合成数据, CI必跑)
├─ test_commission_capital.py       [新] 层1: 佣金/印花税/资金守恒精确对拍   (合成数据, CI必跑)
├─ test_state_persistence.py        [新] 层1: save_state→load_state 半段续跑==全量 (合成数据, CI必跑)
├─ test_sandbox_consistency.py      [新] 层1: test-code/resolve/backtest 三沙箱信号逐bar相等 (合成数据, CI必跑)
├─ test_e2e_real_data.py            [新] 层2: 预录策略×5年多股→run_vnpy_backtest+5项验算+无未来函数 (真实行情, CI必跑, 较慢)
├─ test_llm_generate_smoke.py       [新] 层3: 真实讯飞生成2-3策略→test-code+回测 (slow, CI跳过, 本地手动)
├─ conftest.py                      [改] 新增精确构造fixture(涨停序列/已知盈亏序列/5年真实行情loader)
└─ (现有18文件保持不动)
```

### 2.2 层级职责

| 层 | 数据源 | LLM | CI | 目的 |
|---|---|---|---|---|
| 1 确定性核心 | 合成 K 线 | 无 | 必跑 | 用可手算的精确场景钉死四个薄弱环节的逻辑正确性 |
| 2 端到端集成 | 真实 5 年多股 | 无（预录代码） | 必跑 | 暴露真实数据格式/指标在真实序列下的行为，验算全过 |
| 3 真实 LLM 冒烟 | 真实或合成 | 真实讯飞 | 跳过(slow) | 验证"AI生成→自动测试"链路通，容忍 LLM 过载 |

### 2.3 关键设计决策

- 层1用合成数据——四个薄弱环节需要精确可控输入才能断言"T+1当天没卖"。真实数据涨停序列难找且不可复现。
- 层2用预录代码而非 LLM——真实行情已引入足够不确定性，代码必须确定才能定位是策略错还是引擎错。
- 层3单独隔离——LLM 是最大不稳定源，标 `slow` 让 CI 永远绿，真实失败由本地手动捕捉。
- 真实 LLM 生成纳入（用户明确要求）但隔离在 slow 层。
- 真实行情数据范围：近 5 年多股（用户明确要求）。

## 3. 层 1 确定性核心层

四个文件，每个用精确合成的、可手算的数据断言引擎行为。全部基于 conftest 的 `_make_df`/`df_to_bars`，新增工厂见 §6。

### 3.1 test_t_plus_1_and_limits.py — T+1 与涨跌停

精确构造 K 线序列（不用随机），手算预期：

- **T+1 当天不卖**：买入信号@D1 → D1 当天出现卖出信号，断言 D1 无卖出成交，最早 D2 才卖。验证 `_buy_date != current_date` 守卫。
- **涨停买不进**：`pre_close=10.00, close=11.00`（+10%涨停），买入信号命中，断言无买单 + 写了"涨停买不进"日志。验证 `_is_limit_up`。
- **跌停卖不出**：持仓中，`pre_close=10.00, close=9.00`（-10%跌停），卖出信号命中，断言无卖单 + "跌停卖不出"日志。验证 `_is_limit_down`。
- **T+1 + 跌停叠加**：D1 买入，D2 跌停且本该平仓 → D2 不卖，D3 正常才卖。覆盖两约束交互。
- **连续涨停**：买入信号连续命中涨停板，断言全程不建仓，资金不变。
- **一字涨停**：开=收=涨停价，验证不破。

实现关键：`BarData` 需注入 `pre_close`（`_is_limit_up` 读 `bar.pre_close`）。conftest 的 `df_to_bars` 当前不设 `pre_close`，新增 `make_bar_with_pre_close` 工具（§6.1）。

### 3.2 test_commission_capital.py — 佣金与资金账

构造已知盈亏的完整买卖配对，手算预期，与引擎对拍：

- **佣金精度**：买 100 股 @10 元 = 1000 元，佣金 = max(1000×0.0003, 5) = 5 元（最低5元）；卖同价，佣金5元 + 印花税 1000×0.001 = 1 元。断言 cash 变化 = −(1000+5) 买 / +(1000−5−1) 卖。
- **资金守恒**：零盈亏场景（同价买卖）`initial_total_assets − final_total_assets` 应仅为佣金+税。验证 `_verify_result` 第1项。
- **印花税只卖出收**：买入无印花税，卖出收 0.1%。构造不对称买卖价验证。
- **最小100股整手**：`shares_100 = int(buy_amount/(price*100))*100`，构造资金只够买 99 股的场景，断言走 `int(buy_amount/price)` 回退分支或干脆不买。**先测试暴露当前行为，再判断是 BUG 还是设计**（用户决策）。
- **不足一手不买**：资金不够100股时断言不建仓、不报错（视上一条测试结果而定）。

### 3.3 test_state_persistence.py — 持仓状态持久化

验证实盘重启后状态恢复正确（save_state/load_state）：

- **普通策略半段续跑**：跑 0~500 bar → save_state → 新引擎 load_state → 注入剩余 500~1000 bar → 总交易序列 == 一次跑完 0~1000 的后半段。
- **网格策略持久化**：grid_states_json 的层状态（EMPTY/HOLDING）恢复正确，重启后穿越已 HOLDING 的层不重复买入。
- **bar_index 恢复**：预计算模式 `_bar_index` 必须恢复，否则重启信号错位（用未来函数方式检测：续跑 == 全量）。
- **prev_price 恢复**：网格依赖 `_prev_price` 判断穿越区间，恢复错会导致跳空层误判。
- **空状态保存/加载**：未持仓时 save/load 不抛、字段为默认值。

### 3.4 test_sandbox_consistency.py — 三沙箱一致性

"测试过但实盘崩"的根因防护。同一份 AI 风格代码分别走三条 exec 路径，信号必须逐 bar 相等：

- **三条路径**：
  1. `api/ai.py:test_code` 的 exec_ns（测试沙箱）
  2. `strategy_adapter.resolve_strategy_class` 的 exec_ns（动态编译沙箱）
  3. `run_vnpy_backtest` 间接通过 resolve 走的沙箱
- **断言**：同一份代码 + 同一 df，三路径 `generate_signals(df, setting)` 返回的 Series 逐元素 `.equals`。
- **注入依赖对拍**：代码用到 sma/ema/rsi/macd/bollinger/atr/donchian/kdj/cci/math/pd/np/logger，逐一用最小代码片段确认三沙箱都能解析、结果一致。
- **已知差异暴露**：若 test_code 沙箱注入了某依赖而 resolve 没注入（或反之），**这是真实 BUG，要修**——修法是抽公共 `build_strategy_ns()` 函数让三处共用（§7.1）。

## 4. 层 2 端到端集成层 — 真实 5 年多股

用真实历史 K 线跑完整 `run_vnpy_backtest`，代码用预录样本（确定性），不调 LLM。

### 4.1 数据矩阵

| 维度 | 取值 | 理由 |
|---|---|---|
| 个股 | 600519(贵州茅台,高价大盘)、000001(平安银行,低价大盘)、300750(宁德时代,中小盘科技)、002594(比亚迪) | 覆盖高价/低价/中小盘，佣金占比、整手约束差异大 |
| 时间 | 2021-07-04 ~ 2026-07-04（近5年） | 覆盖一轮牛熊、2024 初小盘股崩跌等极端行情 |
| 数据源 | `data_bridge.load_bars_df`（auto 降级链路，与实盘一致） | 真实暴露 akshare/腾讯/mootdx 字段适配问题 |

**数据获取失败兜底**：`pytest.fixture(scope="module")` + `try/except`，取数失败时该模块所有用例 skip 并打印原因，不让 CI 因网络红。

### 4.2 预录策略代码样本

4 份代表性代码，字符串常量写在测试文件里（不调 LLM、不读 DB）：

1. **双均线**（趋势）— 等价内置 DoubleMaStrategy，用于与内置结果对拍
2. **RSI 超买卖**（均值回归）— 用 rsi 指标
3. **布林触轨**（震荡）— 用 bollinger
4. **网格**（多仓加减）— 用 GridStrategy 等价逻辑，验证元组返回 (signals, grid_states)

每份代码刻意写成"AI 风格"——带 logger.info 日志、setting.get 读参、用预置指标不 import——以验证沙箱约束在真实长序列下成立。

### 4.3 断言矩阵（每个策略×每只个股）

| 断言 | 含义 | 失败意味着 |
|---|---|---|
| `verification_failed is False` | 5项验算全过 | 引擎资金/盈亏计算错——实盘致命 |
| `verification.overall.passed is True` | 同上结构化 | 同上 |
| 前4项 `passed` 全 True | 资金守恒/逐日盈亏和/权益一致/最大回撤 | 引擎核心计算错 |
| 第5项 trade_pnl_consistency | 末尾空仓必过；末尾持仓修复后也过（§7.2） | 若 diff 远超佣金 → 真BUG |
| `total_trades > 0` | 5年必有交易 | 数据/信号链路断 |
| **无未来函数**：截断前半段(2021-07~2023-12)交易 ⊂ 全量(2021-07~2026-07)，逐笔(datetime,direction,price,volume)相等 | 引擎没偷看未来 | 实盘回测失真 |
| **预计算 vs 增量一致**：同数据两模式交易笔数+内容相等 | 两模式一致 | 实盘(增量)与回测(预计算)行为分叉 |

### 4.4 性能

4策略 × 4个股 × (全量+半段+预计算+增量) ≈ 64 次回测 × 每次5年日线 ≈ 单模块几分钟。CI 必跑。

## 5. 层 3 真实 LLM 冒烟层

### 5.1 test_llm_generate_smoke.py

**目的**：验证"AI 生成代码 → 自动测试 → 回测"整条链路在真实 LLM 下能跑通。**不是验证 LLM 质量**。

**用例**：
- 3 个策略想法 prompt："双均线金叉买入死叉卖出"、"RSI 超卖买入超买卖出"、"布林下轨触轨买入"。
- 真实调 `ai_service.generate_stream`（phase=generate）或 `generate_strategy` 端点，收集 LLM 输出的 ```python``` 代码块。
- 喂给 test_code 核心逻辑（抽成可复用函数，§7.3），断言：
  1. 能 exec 编译不抛
  2. generate_signals 返回 pd.Series
  3. 信号值域 ∈ {1,-1,0}
  4. create_adapter + precompute_signals 不抛
- 再用合成 crossover 数据跑 CtaBacktestingEngine，断言 5 项验算前 4 项过。

### 5.2 稳定性兜底（核心）

- 全文件 `@pytest.mark.slow`，CI 用 `-m "not slow"` 跳过。
- LLM 调用 `try/except`：若 `_is_transient_llm_error`（1105/503/过载）或网络错，该用例 `pytest.skip("讯飞过载/网络不可达")`，不算失败。
- 复用 ai_service 现有退避重试。
- **断言"链路通"而非"LLM 输出正确"**：LLM 生成策略平庸（如5年无信号）只要能编译跑通验算过即通过。LLM 输出垃圾属预期，不记为测试失败。
- LLM 未配置 LLM_API_KEY 时全模块 skip。

## 6. conftest 扩展

### 6.1 新增工厂

- `make_bar_with_pre_close(symbol, exchange, dt, o, h, l, c, pre_close, volume, interval)`：构造带 pre_close 的 BarData，供涨跌停测试。df_to_bars 增加可选 pre_close_col 参数。
- `make_known_pnl_data(buy_price, sell_price, shares, n_bars)`：构造已知盈亏完整买卖配对序列，供佣金对拍。
- `make_limit_seq(scenario)`：按场景（连续涨停/一字涨停/T+1+跌停叠加）构造精确序列。
- `load_real_bars(symbol, start, end, period="1d")`：调 data_bridge.load_bars_df + df_to_bars，带网络兜底（失败返回 None 供 fixture skip）。

### 6.2 复用

四个工厂层1/层2/层3共用。现有 fixture（trend_up_data/oscillation_data 等）保持不动。

## 7. 重构与 BUG 修复

测试先行（TDD），发现真实 BUG 即修，修法遵循"抽公共函数"而非"打补丁"。

### 7.1 三沙箱注入不一致（最可能实盘致命 BUG）

**问题**：`api/ai.py:test_code`、`strategy_adapter.resolve_strategy_class`、`run_vnpy_backtest` 三处各自 exec 用户代码，注入的依赖（pd/np/math/logger/sma 等）若有不一致，会导致"测试过实盘崩"。

**修法**：抽 `app/core/strategy_sandbox.py:build_strategy_ns(logger=None)` 公共函数，返回统一的 exec 命名空间。三处共用。层1 test_sandbox_consistency 先写失败测试暴露差异，再抽函数修。

### 7.2 验算第5项末尾持仓误报（确定修复，用户决策）

**问题**：`_verify_result` 第5项 `trade_pnl_consistency` 的 `holding_pnl` 用成交价当持仓成本（未扣佣金），而 `reported_profit` 是扣过佣金的净盈亏，两者差一笔佣金，tolerance*2=2.0 元扛不住大额佣金 → 末尾持仓误报。

**修法**：
1. `holding_pnl` 的 avg_cost 计算扣佣金（买入佣金摊入成本）。
2. tolerance 从 2.0 调宽到与佣金规模匹配（按 capital 比例或绝对值，如 max(2.0, capital*0.0001)）。
3. 保留 `test_verify_result.TestKnownLimitation` 改为断言"修复后末尾持仓也通过"。
4. 新增回归测试：末尾持仓场景 5 项全过，防倒退。

### 7.3 整手回退分支（先测试再定，用户决策）

**问题**：`_handle_normal_signal` 的 `shares_100 if shares_100 > 0 else int(buy_amount/price)` —— 资金不够买100股时买零股。

**处理**：先写 test_commission_capital 用例暴露当前行为（构造资金够买 99 股的场景，记录实际买了几股）。根据测试结果再判断：
- 若当前回退买零股 → 评估是否符合 A 股实盘规则，若不符则移除回退改"不足100股不买"。
- 不预设改不改代码，测试结果驱动决策。

### 7.4 test_code 核心逻辑抽函数

`api/ai.py:test_code` 的沙箱 exec + 信号校验逻辑抽成 `app/services/strategy_test_service.py:test_strategy_code(code, parameters, df=None) -> dict`，供层3 LLM 冒烟复用，避免重复实现。

## 8. 运行与 CI 策略

```bash
# CI 默认：层1+层2，跳过 slow
/d/MyProj/stock/backend/venv/Scripts/python -m pytest tests/ -m "not slow" -v

# 本地手动：全量含真实 LLM
/d/MyProj/stock/backend/venv/Scripts/python -m pytest tests/ -v
```

沿用现有 `pytest.ini` 的 `slow` marker，无需改配置。venv 而非 anaconda（与记忆 backtest-test-suite 一致）。

## 9. 不做（YAGNI）

- 不重写现有 18 个测试文件。
- 不加 ST/退市风险股（4 只代表性个股已够，异常数据由层2网络兜底覆盖）。
- 不验证 LLM 生成策略的盈亏质量（只验证链路通）。
- 不做实盘撮合网关测试（vnpy_live_gateway/xtp/ hundsun）——超出本次范围，本次聚焦策略代码与回测引擎。
- 不改 ai_service 提示词与重试逻辑（已稳定）。

## 10. 验收标准

- 层1 四个新文件全部通过，四个薄弱环节无盲区。
- 层2 4策略×4个股×5年真实数据，5项验算全过 + 无未来函数 + 两模式一致。
- 层3 slow 标记，本地手动跑真实 LLM 能生成可编译可回测的代码。
- §7.1 三沙箱抽公共函数，三路径信号逐 bar 相等。
- §7.2 第5项验算修复，末尾持仓 5 项全过 + 回归测试防倒退。
- §7.3 整手回退测试先行，行为记录在案。
- CI `-m "not slow"` 全绿，不依赖网络/LLM。
