# 替换 stock_data 实时行情与实盘下单数据源设计

**日期**: 2026-07-05
**状态**: 已确认，待写实现计划
**分支**: feat/replace-stock-data-akshare

## 背景与动机

当前实时 tick 与实盘下单依赖两个外部微服务：

- **stock_data 微服务**（`STOCK_DATA_URL`，默认 `http://localhost:8000`）：实时行情，HTTP + WebSocket。底层用 xtquant/QMT。
- **stock_trade 微服务**（`STOCK_TRADE_URL`，默认 `http://localhost:8800`）：实盘账户与下单，底层接 QMT 等券商。

**问题**：stock_data 微服务目前不可用，实时行情链路断裂；stock_trade 也无可用券商对接。

**目标**：用公开 HTTP 数据源（akshare/东财）替换 stock_data 做实时 tick；实盘下单改为模拟成交（不再走 stock_trade、不接真券商）；保持 `market_service` 与 `live_gateway` 的对外接口不变，调用方零改动。

## 决策摘要

经 brainstorming 确认的关键决策：

1. **行情数据源**：akshare/东财公开 HTTP 接口（`stock_zh_a_spot_em` 全市场快照）。
2. **实盘下单**：改为模拟成交，复用 `vnpy_strategy_runner._sim_accounts` 内存账户体系。live 与 simulation 共用同一套模拟账户。
3. **接口兼容**：`market_service` / `live_gateway` 类名与方法签名全保留，只换底层。
4. **代码去留**：新增 akshare/sim 后端实现 + 配置切换，保留旧 stock_data/stock_trade 后端作 fallback，可回退。
5. **tick 轮询策略**：3 秒轮询全市场快照，按订阅 symbol 过滤分发；五档盘口字段置空。
6. **live 账户来源**：live 模式 account_id 改用 `sim-{instance_id}`，与 simulation 统一。
7. **live 信号执行**：保留 AutoTradeConfig 的 confirm 流程，成交从真券商改为模拟。

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  调用方（不变）                                                │
│  vnpy_strategy_runner / simulation.py / trading.py /         │
│  dashboard.py / api/health / main.py lifespan                │
└──────────────┬───────────────────────────┬──────────────────┘
               │                           │
   market_service (同步接口)        live_gateway (异步接口)
   旧类名/方法签名全保留            旧类名/方法签名全保留
        │ 委托                          │ 委托
        ▼                               ▼
┌─────────────────────┐         ┌──────────────────────┐
│ MarketBackend(抽象) │         │ TradeBackend(抽象)   │
│  - AkshareMarketBackend │      │  - SimTradeBackend   │
│  - StockDataMarketBackend │     │  - StockTradeBackend │
└─────────────────────┘         └──────────────────────┘
        │                               │
        │ akshare 轮询                  │ 包装 _sim_accounts
        │                               │ （vnpy_strategy_runner 持有）
        ▼                               ▼
   akshare HTTP                   _sim_accounts / _sim_positions
   stock_zh_a_spot_em             _update_sim_account_buy/sell
```

## 新增/改造组件

### 新增文件

1. **`app/core/market_backend.py`**
   - 抽象基类 `MarketBackend`：方法签名与现有 `MarketService` 同名方法一致——`is_available()` / `check_health()` / `get_klines(symbol, period, ...)` / `get_full_tick(symbol)` / `get_stock_list(sector)` / `get_stock_list_full(sector)` / `get_instrument_detail(symbol)` / `get_instruments_batch(symbols)` / `subscribe_quote(symbol, period, callback)→seq` / `unsubscribe_quote(seq)` / `close()`。
   - `AkshareMarketBackend`：3 秒轮询引擎 + tick 缓存 + 订阅分发。
   - `StockDataMarketBackend`：把现有 `market_service.py` 的 HTTP/WS 实现搬过来，原样不动。

2. **`app/core/trade_backend.py`**
   - 抽象基类 `TradeBackend`：方法签名与现有 `LiveGateway` 一致（异步）——`is_connected` 属性 / `auto_connect()` / `auto_connect_background()` / `check_health()` / `get_account()` / `get_positions()` / `get_orders()` / `get_trades()` / `place_order(symbol, side, quantity, price, order_type)` / `cancel_order(order_id)` / `get_quote(symbol)` / `disconnect()`。
   - `SimTradeBackend`：模拟成交，通过延迟导入 `vnpy_strategy_runner` 操作 `_sim_accounts`/`_sim_positions`。
   - `StockTradeBackend`：把现有 `live_gateway.py` 的 HTTP 实现搬过来。

### 改造文件

3. **`app/services/market_service.py`**
   - `MarketService` 类保留，方法签名不变，内部委托给 `self._backend`（按 `settings.MARKET_BACKEND` 实例化对应后端）。
   - 后端选择逻辑：`MARKET_BACKEND="akshare"` → `AkshareMarketBackend`，`"stock_data"` → `StockDataMarketBackend`，未知值 fallback 到 `akshare`。

4. **`app/core/live_gateway.py`**
   - `LiveGateway` 类保留，方法签名不变，内部委托给 `self._backend`（按 `settings.TRADE_BACKEND` 实例化）。
   - 后端选择逻辑：`TRADE_BACKEND="sim"` → `SimTradeBackend`，`"stock_trade"` → `StockTradeBackend`，未知值 fallback 到 `sim`。

5. **`app/config.py`**
   - 新增 `MARKET_BACKEND: str = "akshare"`。
   - 新增 `TRADE_BACKEND: str = "sim"`。
   - 保留 `STOCK_DATA_URL` / `STOCK_TRADE_URL`（fallback 后端用）。

### `vnpy_strategy_runner.py` 改造点

- **`_get_account_id`**（line 736-740）：去掉 live 模式的券商 account_id 分支，live 与 simulation 统一返回 `sim-{instance_id}`。
- **`_execute_signal` 的 live 分支**（line 1076-1082）：原本调 `_execute_live_signal`（查 AutoTradeConfig、风控、自动下单 or 建 Signal 待确认）。改为：
  - 仍查 AutoTradeConfig 决定 `auto_trade_enabled` / `confirm_required`。
  - 仍执行 `risk_manager.check_order` 风控。
  - `auto_trade_enabled and not confirm_required`：直接调 `_update_sim_account_buy/sell` 模拟成交（与 simulation 分支对称，不绕道 `SimTradeBackend`），落 `Order` 表（source=`"signal_auto_sim"`），WS 推 strategy_trade。
  - 否则：建 `Signal` 待确认记录（保留现有逻辑），WS 推 strategy_signal。
- **`_place_order_via_vnpy`**（line 1290）模拟分支不变；live 分支实际不再被 `_execute_signal` 调用（live 信号直接走模拟成交），仅保留给可能的 API 层手动下单路径。
- **`SimTradeBackend.place_order` 的职责**：只服务 API 层手动下单（`trading.py` / `simulation.py` 的 `/order` 端点），内部调 `_update_sim_account_buy/sell`。`_execute_signal` 的 live 分支不经过它，直接调 `_update_sim_account_buy/sell`，与 simulation 分支对称。

## 数据流

### 实时 tick（AkshareMarketBackend）

```
subscribe_quote(symbol, callback)
   ├─ 注册 callback 到 _sub_callbacks[seq] = (symbol, callback)
   ├─ symbol 加入 _subscribed_symbols
   └─ _ensure_poll_loop()  ← 首次订阅启动轮询任务

_poll_loop（asyncio task，每 3 秒）:
   ├─ trading_calendar.is_trading_time()?  ← 否则跳过本轮（省请求、避限流）
   ├─ AkshareDataSource.get_snapshot(subscribed_symbols)  ← 复用已有实现
   │    └─ 内部 _rate_limit()（≥1.5s + jitter）+ stock_zh_a_spot_em()
   ├─ 遍历快照结果，转成兼容 tick 格式:
   │    {lastPrice, open, high, low, lastClose, volume, amount,
   │     bidPrice=[], bidVol=[], askPrice=[], askVol=[], timetag}
   │    （五档置空，pre_close 用快照昨收）
   ├─ 更新 _tick_cache[symbol] = tick
   └─ for each subscribed symbol: callback(tick)  ← 触发 vnpy_strategy_runner._on_tick

get_full_tick(symbol):
   └─ return _tick_cache.get(symbol)  ← 同步读缓存，无网络调用

unsubscribe_quote(seq):
   ├─ 移除 callback
   └─ 无订阅时 _close_poll_loop()
```

**要点**：
- `get_snapshot` 复用 `AkshareDataSource` 现有实现（已有限流），拉全市场后本地按 `codes` 过滤。
- 轮询节流：3 秒间隔 + akshare 内部 ≥1.5s 限流，满足频控。
- 非交易时间跳过轮询（`is_trading_time()` 为假时只 sleep 不请求）。
- 首次订阅立即补拉一次快照（不等 3 秒），保证 `get_full_tick` 有初值——对齐现有 `_subscribe` 行为。
- akshare 快照无五档盘口，`bidPrice`/`bidVol`/`askPrice`/`askVol` 置空数组。

### 下单（SimTradeBackend，live + simulation 统一）

```
live_gateway.place_order(symbol, side, quantity, price, order_type)
   └─ SimTradeBackend.place_order(...):
        ├─ 取 account_id（live 模式也用 sim-{instance_id}）
        ├─ buy: 检查 _sim_accounts[account_id].available ≥ cost + commission
        │       → vnpy_strategy_runner._update_sim_account_buy(account_id, symbol, qty, price)
        ├─ sell: 检查 _sim_positions 持仓 ≥ quantity
        │       → _update_sim_account_sell(account_id, symbol, qty, price, avg_cost)
        ├─ 落 Order 表（source="sim_live"）
        ├─ WS 推送 strategy_trade
        └─ return {"order_id": 生成UUID, "success": True, ...}

live_gateway.get_account():
   └─ 读 _sim_accounts[account_id]，返回 {cash, available_cash, total_assets, market_value}

live_gateway.get_positions():
   └─ 读 _sim_positions[account_id]，转成 [{symbol, volume, cost_price, ...}]
```

### 启动/关闭（main.py lifespan）

```
启动:
  market_service.is_available()  → AkshareMarketBackend.is_available() 检测 akshare 可装
  live_gateway.auto_connect_background()  → SimTradeBackend.auto_connect() 直接置 connected=True

关闭:
  market_service.close()  → 停轮询任务
  live_gateway.disconnect()  → SimTradeBackend 置 connected=False
```

`SimTradeBackend.auto_connect()` 不连任何服务，直接成功置 `is_connected=True`，跳过现有 3 次重试 + 30 秒守护空转（那套逻辑只在 `StockTradeBackend` 里有意义）。

## 错误处理

### 行情侧（AkshareMarketBackend）

| 场景 | 处理 |
|------|------|
| akshare 未安装 | `is_available()`=False；`check_health()` 返回 `status:"offline"`；轮询不启动；`get_full_tick` 返回 None。`_run_loop` 走现有降级（random 波动造价） |
| 单次轮询抛异常 | 捕获记日志，保留上一轮 `_tick_cache` 不清空，sleep 3 秒重试。不向 callback 推空数据 |
| 单次轮询返回空 | 同上，保留旧缓存，不推送 |
| 订阅 symbol 不在快照结果 | 跳过该 symbol，其他正常分发。记 debug 日志 |
| akshare 限流被封 | 按"单次轮询异常"处理，下一轮重试 |
| 轮询任务意外退出 | `try/except` 包住 while，异常记 error 后 sleep 5 秒重启循环 |
| 订阅 symbol 为空 | `_close_poll_loop()` 停任务，不发请求 |

**原则**：行情失败不阻塞策略运行循环，表现为"价格不更新"而非"抛异常中断"。

### 交易侧（SimTradeBackend）

| 场景 | 处理 |
|------|------|
| `place_order` 时 account 不存在 | 返回 `{"success": False, "error": "模拟账户不存在"}`，不抛异常 |
| 买入资金不足 | 返回 `{"success": False, "error": "可用资金不足"}`，不记 Order |
| 卖出持仓不足 | 返回 `{"success": False, "error": "持仓不足"}` |
| `get_account`/`get_positions` 账户未初始化 | 返回空结构 `{"cash":0,...}` / `[]`，不抛异常 |
| 风控拒绝 | 不记模拟成交，返回 `{"success": False, "error": reason}`，WS 推 risk 日志 |
| `vnpy_strategy_runner` 未初始化 | `auto_connect()` 仍置 `is_connected=True`，`place_order`/`get_account` 返回空/失败 |
| live 信号执行异常 | 复用 `_execute_signal` 现有 `try/except RuntimeError`：失败时 stop 实例 + WS 推 strategy_error + DB 置 stopped |

**原则**：模拟成交无网络故障，错误主要是业务校验（资金/持仓/风控）。所有失败返回结构化结果而非抛异常，与现有 `_update_sim_account_buy` 静默 return 不同——下单需要明确失败反馈。

### 配置切换容错

| 场景 | 处理 |
|------|------|
| `MARKET_BACKEND="akshare"` 但 akshare 不可用 | 启动 warning，行情降级到 random 波动。不回退到 stock_data |
| 未知 `MARKET_BACKEND` 值 | warning，fallback 到 `akshare` |
| 未知 `TRADE_BACKEND` 值 | fallback 到 `sim` |

### 已知坑规避

- **东财 null vs missing key**（memory: eastmoney-cninfo-null-vs-missing-key）：akshare 快照字段可能返回 `None`，tick 转换时每字段做 `None → 0` 转换，不能只 `.get(key, default)`。复用 `AkshareDataSource.get_snapshot` 的 `_f()` 辅助函数模式。
- **非交易时段快照为 0**（memory: akshare-constituents-column-bug）：`is_trading_time()` 为假时跳过请求，避免推 0 价格污染缓存。

## 测试策略

测试在 venv 跑（非 anaconda，见 memory: backtest-test-suite），pytest 标记 slow。

### 第一层：单元测试（纯逻辑，无网络）

| 测试对象 | 测试点 |
|---------|--------|
| `AkshareMarketBackend` tick 格式转换 | mock `get_snapshot` 返回，验证 tick 字段完整、None 转 0/[] |
| `AkshareMarketBackend` 订阅分发 | mock `get_snapshot`，订阅 3 symbol，验证只对订阅的调 callback |
| `AkshareMarketBackend` 非交易时间跳过 | mock `is_trading_time()`=False，验证不调 `get_snapshot`、缓存不清空 |
| `AkshareMarketBackend` 异常保留缓存 | mock `get_snapshot` 抛异常，验证旧缓存保留、不调 callback |
| `SimTradeBackend` 买入 | 预置资金，下单买入，验证 balance 减少、持仓增加、返回 success |
| `SimTradeBackend` 资金不足 | 预置低资金，验证返回 `success:False`，不改账户 |
| `SimTradeBackend` 卖出持仓不足 | 预置空持仓，验证返回失败 |
| `SimTradeBackend` get_account 空账户 | 未初始化，验证返回空结构不抛异常 |

### 第二层：集成测试（mock 网络，验链路）

| 测试点 | 方法 |
|--------|------|
| 订阅→轮询→callback→`_on_tick` 链路 | mock `get_snapshot`，订阅一个 symbol，等一轮轮询，验证 `_current_prices` 被更新 |
| 信号→`_execute_signal`→SimTradeBackend→账户更新 | 复用 `simulation_test_service` 回放框架，强制注入买卖信号，验证 live 模式账户变化与 simulation 一致 |
| live 与 simulation 账户统一 | 同一 instance 切换 mode，验证 account_id 都是 `sim-{instance_id}`、状态延续 |
| 配置切换 | `MARKET_BACKEND` 切换，验证 `market_service` 委托到正确后端 |

### 第三层：冒烟测试（真实 akshare，标 slow）

| 测试点 | 标记 |
|--------|------|
| akshare 真实拉一次 `stock_zh_a_spot_em`，验证返回非空、字段齐全 | `@pytest.mark.slow` |
| 订阅真实 symbol（如 600519），跑 2 轮轮询，验证 callback 触发 | slow |
| 非交易时段跑轮询，验证跳过请求不报错 | slow |

### 测试复用

- `simulation_test_service.py` 已有"回放分钟K线→驱动策略→验证账户"框架（`run_trade_flow_test`），sim 后端集成测试复用它，对照 `SimulatedStockGateway.send_order` vs `SimTradeBackend.place_order`。
- akshare 网络调用通过 monkeypatch `AkshareDataSource.get_snapshot` / `_rate_limit` mock，slow 测试除外。

### 回归覆盖

- akshare 不可用时 `_run_loop` 仍能跑（random 波动模式）。
- `main.py` lifespan：akshare 后端下 `market_service.close()` 停轮询、`live_gateway.disconnect()` 不报错。

### 不测的

- akshare 限流行为（依赖东财服务端，不可控）。
- 五档盘口（akshare 后端置空）。
- stock_data/stock_trade 旧后端（保留代码作 fallback，不再加测试覆盖）。

## 影响面

### 调用方零改动（接口不变）

`vnpy_strategy_runner`、`simulation.py`、`trading.py`、`dashboard.py`、`api/health`、`main.py` lifespan 中对 `market_service.*` / `live_gateway.*` 的调用全部保持不变。

### 需改动的调用方

- `vnpy_strategy_runner._get_account_id`：live 分支统一为 `sim-{instance_id}`。
- `vnpy_strategy_runner._execute_signal` live 分支 + `_execute_live_signal`：成交改模拟。
- `main.py`：日志文案微调（"stock_data 行情服务" → 按后端显示）。

### 废弃配置

`STOCK_DATA_URL` / `STOCK_TRADE_URL` 保留但仅在 fallback 后端启用时生效。

## 非目标（YAGNI）

- 不做 akshare 五档盘口补全（`stock_bid_ask_em` 按标的拉取）——3 秒全市场快照已够驱动策略。
- 不做行情多源降级（realtime tick 只走 akshare，历史 K 线的 auto 降级链不动）。
- 不做实盘真券商对接（live 下单就是模拟成交，不接 QMT/XTP）。
- 不删除旧 stock_data/stock_trade 后端代码（保留作 fallback）。
