# 量化交易平台 (Quant Trading Platform) 技术文档

> **版本**: 1.0.0  
> **更新日期**: 2026-06-12  
> **文档类型**: 系统架构与接口技术文档

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [模块详解](#3-模块详解)
   - [3.1 stock_data — 行情数据微服务](#31-stock_data--行情数据微服务)
   - [3.2 stock_trade — 交易微服务](#32-stock_trade--交易微服务)
   - [3.3 stock_filters — 智能选股系统](#33-stock_filters--智能选股系统)
   - [3.4 backend — 核心后端服务](#34-backend--核心后端服务)
   - [3.5 frontend — Web 前端](#35-frontend--web-前端)
4. [数据流与交互](#4-数据流与交互)
5. [部署架构](#5-部署架构)
6. [API 接口汇总](#6-api-接口汇总)
7. [数据库设计](#7-数据库设计)
8. [策略体系](#8-策略体系)
9. [安全与认证](#9-安全与认证)
10. [技术栈总览](#10-技术栈总览)

---

## 1. 项目概述

本项目是一套完整的 **A 股量化交易平台**，采用微服务架构，覆盖行情数据获取、策略选股、回测验证、模拟交易、实盘交易全链路。系统由 5 个独立子项目组成，通过 REST API 和 WebSocket 进行服务间通信。

### 核心能力

| 能力 | 说明 |
|------|------|
| **行情数据** | 基于 MiniQMT (xtquant) 的 A 股全市场数据服务，支持 K 线、Tick、实时行情 |
| **策略选股** | 多策略自动扫描（四维擒龙、六脉神剑、RSI+KDJ 共振），结果推送钉钉 |
| **策略回测** | 基于 vnpy CTA 引擎的回测系统，支持日线/分钟线，含沪深300基准对比 |
| **模拟交易** | 全仿真交易环境，支持策略自动运行与信号生成 |
| **实盘交易** | 对接 stock_trade 微服务，支持 QMT/XTP/华泰/同花顺/国泰君安/恒生等多家券商 |
| **AI 分析** | 集成 DeepSeek AI，提供智能市场分析 |
| **Web 前端** | React + TypeScript 单页应用，K 线图、权益曲线、策略管理 |

### 子项目仓库

| 项目 | 说明 | 运行环境 |
|------|------|----------|
| `stock_data` | 行情数据微服务，连接 xtquant 提供数据查询 | Windows (MiniQMT) |
| `stock_trade` | 交易微服务，连接 xtquant 提供交易服务 | Windows (MiniQMT) |
| `stock_filters` | 策略选股系统，基于新浪财经 API 的自动化选股 | Linux/Windows |
| `backend` | 核心后端，依赖 stock_data/stock_trade，提供回测/模拟/实盘 | Linux/Windows |
| `frontend` | React Web 前端 | 浏览器 |

---

## 2. 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Frontend (React)                          │
│                    http://localhost:5173 (Vite)                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP REST + WebSocket
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Backend (FastAPI)                            │
│                      http://localhost:8000                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ 回测引擎  │ │ 模拟交易  │ │ 实盘交易  │ │ 策略管理  │ │ AI 分析  │ │
│  │ (vnpy)   │ │ (vnpy)   │ │ (gateway)│ │          │ │(DeepSeek)│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│                         │ SQLite                                    │
└───────────┬──────────────┼──────────────────────────────────────────┘
            │              │
    ┌───────▼──────┐  ┌───▼──────────┐
    │  stock_data  │  │  stock_trade │
    │  (Port 8000) │  │  (Port 8800) │
    │  FastAPI     │  │  FastAPI     │
    └───────┬──────┘  └───┬──────────┘
            │              │
    ┌───────▼──────────────▼──────┐
    │     MiniQMT (xtquant)       │
    │   QMT 极简模式客户端 (Windows) │
    └─────────────────────────────┘

┌─────────────────────────────────┐
│       stock_filters (独立)       │
│  新浪财经 API → 策略扫描 → 钉钉通知 │
└─────────────────────────────────┘
```

### 服务端口规划

| 服务 | 端口 | 协议 |
|------|------|------|
| stock_data | 8000 | HTTP/HTTPS + WebSocket |
| stock_trade | 8800 | HTTP/HTTPS + WebSocket |
| backend | 8000 (可配置) | HTTP + WebSocket |
| frontend (dev) | 5173 | HTTP (Vite) |

---

## 3. 模块详解

### 3.1 stock_data — 行情数据微服务

**定位**: 独立行情数据服务，封装 xtquant SDK，对外暴露统一的 REST API 和 WebSocket 实时行情推送。

**核心设计**: **xtdata 优先，本地文件回退**。当 MiniQMT 服务在线时通过 xtquant SDK 获取数据；服务不可用时直接解析 QMT 本地 `.DAT` 二进制文件。

#### 目录结构

```
stock_data/
├── main.py              # 入口，启动 uvicorn + 定时调度
├── config.py            # 全局配置
├── api/
│   ├── routes.py        # FastAPI app 定义
│   └── v1_routes.py     # v1 版本路由（REST + WebSocket）
├── data/
│   ├── xtdata_client.py # xtdata 连接管理 + 数据读取 + .DAT 回退
│   └── sync.py          # K线下载同步（增量 + 断点续传）
├── scheduler/
│   └── jobs.py          # APScheduler 定时任务
├── scripts/
│   └── trigger_sync.py  # 手动触发同步脚本
├── db_data/             # SSL 证书 + 同步进度
├── start.ps1            # PowerShell 启动脚本
└── requirements.txt
```

#### 数据读取三级回退策略

1. **xtdata.get_local_data（复权数据）** — 优先使用，支持前/后复权
2. **xtdata.get_local_data（不复权）** — 复权失败时自动回退
3. **_read_qmt_dat()（本地 .DAT 文件）** — xtdata 不可用时直接解析 QMT 二进制文件

`.DAT` 文件结构：8 字节头 + 64 字节/条记录，包含时间戳、OHLC、成交量。

#### 数据同步机制

- **定时同步**: APScheduler 每日 15:05（收盘后）自动执行增量下载
- **增量过滤**: 同步前检查本地数据，跳过已更新到最近交易日的股票
- **断点续传**: 进度保存在 `db_data/sync_progress.json`，服务重启后自动继续
- **连接容错**: 30 秒连接复用、端口扫描、连续超时 3 次自动重连

#### 核心 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 服务健康检查 |
| GET | `/api/v1/klines` | K 线数据查询 |
| GET | `/api/v1/tick/{symbol}` | 实时 Tick 快照 |
| GET | `/api/v1/stocks` | 股票列表 |
| GET | `/api/v1/instruments/{symbol}` | 合约详情 |
| GET | `/api/v1/sync/status` | 同步状态查询 |
| POST | `/api/v1/sync/trigger` | 手动触发同步 |
| WS | `/api/v1/ws/quote` | 实时行情推送（每 3 秒） |

#### 配置项

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `API_KEY` | `STOCK_DATA_API_KEY` | 空 | API 认证密钥 |
| `HTTP_HOST` | - | `0.0.0.0` | 监听地址 |
| `HTTP_PORT` | - | `8000` | 监听端口 |
| `DOWNLOAD_HOUR` | - | `15` | 定时下载小时 |
| `DOWNLOAD_MINUTE` | - | `5` | 定时下载分钟 |
| `DOWNLOAD_PERIODS` | - | `("1d","5m","1m")` | 下载的K线周期 |
| `BATCH_SIZE` | - | `{"1d":10,"5m":3,"1m":2}` | 各周期每批下载股票数 |

---

### 3.2 stock_trade — 交易微服务

**定位**: 基于 xtquant 的实盘交易 HTTP 服务，自动管理 QMT 连接，提供 RESTful API 和 WebSocket 实时推送。

#### 目录结构

```
stock_trade/
├── main.py              # 入口，lifespan/中间件/重连
├── config.yaml          # 配置文件
├── core/
│   ├── config.py        # 配置加载
│   ├── auth.py          # API Key 认证
│   ├── gateway.py       # xtquant 交易网关（连接/下单/查询）
│   └── callback.py      # xtquant 回调（委托/成交/断线）
├── routers/
│   ├── health.py        # 健康检查
│   ├── queries.py       # 资金/持仓/委托/成交查询
│   ├── orders.py        # 下单/撤单
│   └── ws.py            # WebSocket 实时推送
├── models/
│   ├── request.py       # 请求模型
│   └── response.py      # 响应模型
└── docs/
    └── stock-trade-api.md
```

#### 稳定性机制

| 机制 | 说明 |
|------|------|
| 自动连接 | 服务启动时自动连接 QMT |
| 自动重连 | 断线后每 5 秒自动重试 |
| 断线回调 | xtquant 的 `on_disconnected` 回调自动更新状态 |
| 心跳维持 | trader 线程独立运行，维持与 QMT 的心跳 |
| 连接锁 | `threading.Lock` 防止并发连接冲突 |
| 账户自动发现 | 连接成功后自动查询并注册 QMT 账户 |

#### 核心 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/asset` | 查询资金 |
| GET | `/api/v1/positions` | 查询持仓 |
| GET | `/api/v1/orders` | 查询委托 |
| GET | `/api/v1/trades` | 查询成交 |
| POST | `/api/v1/orders` | 下单 |
| DELETE | `/api/v1/orders/{order_id}` | 撤单 |
| WS | `/api/v1/ws/trade` | 实时事件推送 |

---

### 3.3 stock_filters — 智能选股系统

**定位**: 基于多策略的 A 股自动化筛选系统，通过新浪财经 API 获取全市场数据，结合技术指标和基本面条件进行初筛与策略扫描，结果通过钉钉通知推送。

#### 目录结构

```
stock_filters/
├── main.py              # 入口，命令行参数解析与调度
├── scheduler.py         # 定时任务调度（APScheduler）
├── engine.py            # 核心引擎，编排初筛/策略/通知流程
├── screener.py          # 初筛过滤（ST/市值/成交额/行业/代码前缀等）
├── notifier.py          # 钉钉通知（加签安全模式）
├── config.yaml          # 配置文件
├── strategies/
│   ├── __init__.py      # 策略自动发现与加载
│   ├── base.py          # 策略基类
│   ├── four_dimension.py # 四维擒龙
│   ├── six_sword.py     # 六脉神剑
│   └── rsi_kdj.py       # RSI+KDJ 共振
├── data/
│   ├── interface.py     # 数据源接口定义
│   ├── akshare_source.py # 新浪财经 API 实现
│   ├── test_source.py   # 测试用模拟数据源
│   └── cache_manager.py # 缓存管理
├── deploy/              # 部署相关
├── docs/                # 文档
└── tests/               # 测试
```

#### 核心流程

**1. 初筛 (run_screener)**
1. 调用新浪 `stock_zh_a_spot()` 获取全市场实时行情
2. 并发请求新浪 `_i` 接口补充详情：市值、PE、PB、行业、EPS、营收、净利润等
3. 按条件过滤：
   - 排除 ST 股
   - 排除科创板(688)、创业板(30)、北交所(920)
   - 市值 < 50 亿
   - 日成交额 < 1 亿
   - 行业黑名单（银行、房地产等）
4. 数据质量校验通过后替换缓存，异常时回退旧缓存

**2. 策略扫描 (run_strategies_and_notify)**
对通过初筛的股票池逐策略扫描，命中结果推送钉钉通知。

#### 策略列表

| 策略 | 最少命中条件 | 核心逻辑 |
|------|------------|------|
| **四维擒龙** | 3/4 | 放量 + MACD 金叉/零轴上方 + 均线多头 + 突破前高 |
| **六脉神剑** | 4/6 | 放量 + MACD 金叉 + KDJ 金叉 + RSI<70 + 站上 5 日线 + 5 日均量放大 |
| **RSI+KDJ 共振** | 全部 | RSI 超卖回弹 + KDJ 低位金叉 + 当日涨幅达标 + 放量 |

#### 定时任务

| 任务 | 默认时间 | 说明 |
|------|---------|------|
| `screener` | 工作日 14:15 | 初筛并缓存股票池 |
| `strategy_1428` | 工作日 14:28 | 策略扫描 + 钉钉通知 |

#### 命令行参数

| 选项 | 说明 |
|------|------|
| `--schedule` | 启动定时调度（阻塞运行） |
| `--run-screener` | 手动执行初筛 |
| `--run-strategies` | 手动执行策略扫描 |
| `--run` | 手动执行完整流程 |
| `--force` | 强制刷新忽略缓存 |
| `--config PATH` | 指定配置文件路径 |

---

### 3.4 backend — 核心后端服务

**定位**: 量化交易平台的核心后端，依赖 stock_data 和 stock_trade 微服务，提供策略回测、模拟交易、实盘交易、AI 分析等完整功能。

#### 目录结构

```
backend/app/
├── main.py              # FastAPI 入口，lifespan 管理
├── config.py            # 全局配置（Pydantic Settings）
├── database.py          # SQLAlchemy 数据库连接
├── api/                 # REST API 路由
│   ├── __init__.py      # 路由注册
│   ├── auth.py          # 用户认证
│   ├── strategies.py    # 策略管理
│   ├── backtest.py      # 回测
│   ├── simulation.py    # 模拟交易
│   ├── trading.py       # 实盘交易
│   ├── positions.py     # 持仓管理
│   ├── market.py        # 行情查询
│   ├── stocks.py        # 股票查询
│   ├── dashboard.py     # 仪表盘
│   ├── simulation_test.py # 模拟测试
│   └── ai.py            # AI 分析
├── core/                # 核心引擎
│   ├── engine.py        # vnpy MainEngine 封装
│   ├── event_handler.py # 事件处理
│   ├── data_bridge.py   # 数据源 → vnpy BarData 桥接
│   ├── data_source.py   # 数据源抽象接口
│   ├── data_source_akshare.py   # AKShare 数据源
│   ├── data_source_baostock.py  # Baostock 数据源
│   ├── data_source_xtquant.py   # Xtquant 数据源
│   ├── data_source_efinance.py  # Efinance 数据源
│   ├── data_source_sina.py      # 新浪数据源
│   ├── data_source_tencent.py   # 腾讯数据源
│   ├── broker_bridge.py  # 券商网关工厂
│   ├── broker_provider.py # 券商抽象接口
│   ├── broker_qmt.py     # QMT 券商
│   ├── broker_xtp.py     # XTP 券商（长江/中泰/东方/财通/华鑫等）
│   ├── broker_ht.py      # 华泰证券
│   ├── broker_ths.py     # 同花顺 iFinD
│   ├── broker_gtja.py    # 国泰君安
│   ├── broker_hundsun.py # 恒生 PTrade
│   ├── live_gateway.py   # 实盘交易网关（对接 stock_trade）
│   ├── risk_manager.py   # 风控管理
│   └── strategy_adapter.py # vnpy 策略适配器
├── models/
│   └── models.py        # ORM 数据模型（11 张表）
├── schemas/             # Pydantic 请求/响应模型
│   ├── account.py, auth.py, ai.py, backtest.py
│   ├── live.py, order.py, strategy.py, trade.py, trading.py
├── services/            # 业务服务层
│   ├── market_service.py       # 行情服务（对接 stock_data）
│   ├── auth_service.py         # 认证服务
│   ├── ai_service.py           # AI 服务（DeepSeek）
│   ├── vnpy_backtest_service.py # vnpy CTA 回测引擎
│   ├── vnpy_strategy_runner.py  # vnpy 策略运行器
│   ├── trade_sync_service.py    # 交易同步服务
│   ├── trading_calendar_service.py # 交易日历
│   └── simulation_test_service.py  # 模拟测试
├── strategies/          # 策略实现
│   ├── base.py          # 策略基类
│   └── __init__.py
└── ws/                  # WebSocket
    ├── handlers.py      # WS 消息处理
    └── manager.py       # WS 连接管理
```

#### 核心引擎架构

**vnpy 引擎封装** (`core/engine.py`):
- `VnpyEngineManager` — MainEngine 单例管理器
- 自动注册 CTP/XTP 网关
- vnpy 不可用时降级为模拟模式

**数据桥接** (`core/data_bridge.py`):
- `XtquantDataBridge` — 将行情数据转换为 vnpy BarData 列表
- 支持 6 种数据源：akshare / efinance / baostock / sina / tencent / xtquant
- 代码格式自动转换（6 位代码 ↔ vt_symbol ↔ xt_symbol）

**券商网关** (`core/broker_bridge.py`):
- 支持 10+ 券商：QMT、XTP（长江/中泰/东方/财通/华鑫/国盛/粤开）、华泰、同花顺、国泰君安、恒生 PTrade
- 统一 `BrokerProvider` 抽象接口
- 工厂模式 + 缓存

**实盘交易网关** (`core/live_gateway.py`):
- 通过 HTTP 与 stock_trade 微服务通信
- 自动连接（启动重试 3 次）+ 断线重连守护
- 30 秒心跳检测

#### 回测引擎 (`services/vnpy_backtest_service.py`)

自建 CTA 回测引擎，基于 vnpy 核心对象（BarData, TradeData, OrderData）：

- **撮合规则**: 信号在 bar[i] 收盘产生 → 委托在 bar[i+1] 以 open_price 成交
- **T+1 限制**: 当日买入不可卖出
- **涨跌停检查**: 涨停不买、跌停不卖
- **费用模型**: 佣金（最低 5 元）+ 卖出印花税（0.1%）
- **多周期支持**: 日线 / 1m / 5m / 15m / 30m / 1h / 周线
- **信号预计算**: 避免每根 K 线重复计算（O(n²) → O(n)）
- **日内策略**: 日线指标 + 细颗粒度信号检测（布林带/ATR 通道）
- **盈亏匹配**: 网格策略 LIFO，其他策略 FIFO
- **基准对比**: 沪深 300 指数同期收益率
- **5 项验算**: 资金守恒、逐日盈亏、权益曲线、最大回撤、交易盈亏

#### 行情服务 (`services/market_service.py`)

- HTTP 客户端封装，对接 stock_data 微服务
- WebSocket 实时行情订阅（自动重连）
- 合约详情缓存
- 批量查询 + 逐个回退

---

### 3.5 frontend — Web 前端

**定位**: React + TypeScript 单页应用，提供量化交易平台的可视化操作界面。

#### 目录结构

```
frontend/src/
├── main.tsx             # 入口
├── App.tsx              # 路由配置（HashRouter）
├── index.css            # 全局样式（Tailwind CSS）
├── api/                 # API 客户端
│   ├── client.ts        # Axios 实例
│   ├── request.ts       # 请求封装
│   ├── auth.ts          # 认证 API
│   ├── strategies.ts    # 策略 API
│   ├── dashboard.ts     # 仪表盘 API
│   ├── trading.ts       # 交易 API
│   ├── simulation.ts    # 模拟交易 API
│   └── ai.ts            # AI API
├── components/          # 通用组件
│   ├── Layout.tsx       # 主布局
│   ├── KlineChart.tsx   # K 线图（lightweight-charts）
│   ├── AIChatPanel.tsx  # AI 对话面板
│   ├── StockSearchInput.tsx # 股票搜索
│   ├── WebSocketProvider.tsx # WebSocket 上下文
│   └── trading/         # 交易组件
│       ├── AutoTradePanel.tsx  # 自动交易面板
│       ├── GatewayPanel.tsx    # 网关状态面板
│       ├── OrderPanel.tsx      # 委托面板
│       ├── SignalPanel.tsx     # 信号面板
│       └── TradeHistoryPanel.tsx # 成交历史
├── pages/               # 页面
│   ├── Dashboard.tsx    # 仪表盘
│   ├── Strategies.tsx   # 策略列表
│   ├── StrategyDetail.tsx # 策略详情
│   ├── Backtest.tsx     # 回测
│   ├── SimulationTrading.tsx # 模拟交易
│   ├── Trading.tsx      # 实盘交易
│   ├── QuantEducation.tsx # 量化教学
│   ├── EducationDetail.tsx # 教学详情
│   ├── Settings.tsx     # 设置
│   └── Login.tsx        # 登录
├── stores/              # 状态管理（Zustand）
│   ├── authStore.ts     # 认证状态
│   ├── strategyStore.ts # 策略状态
│   ├── dashboardStore.ts # 仪表盘状态
│   ├── simulationStore.ts # 模拟交易状态
│   ├── liveTradingStore.ts # 实盘交易状态
│   ├── aiChatStore.ts   # AI 对话状态
│   └── stockCacheStore.ts # 股票缓存
└── types/
    └── index.ts         # TypeScript 类型定义
```

#### 路由表

| 路径 | 页面 | 说明 |
|------|------|------|
| `/login` | Login | 登录页 |
| `/` | Dashboard | 仪表盘（需登录） |
| `/strategies` | Strategies | 策略列表 |
| `/strategies/:id` | StrategyDetail | 策略详情 |
| `/backtest` | Backtest | 回测 |
| `/simulation` | SimulationTrading | 模拟交易 |
| `/trading` | Trading | 实盘交易 |
| `/education` | QuantEducation | 量化教学 |
| `/settings` | Settings | 设置 |

#### 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite 5 |
| 路由 | react-router-dom v6 |
| 状态管理 | Zustand |
| 样式 | Tailwind CSS |
| 图表 | lightweight-charts v5 + Recharts |
| 图标 | Lucide React |
| HTTP | Axios |
| 日期 | date-fns |

---

## 4. 数据流与交互

### 行情数据流

```
MiniQMT (xtquant)
    │
    ▼
stock_data (FastAPI :8000)
    │  GET /api/v1/klines
    │  WS  /api/v1/ws/quote
    ▼
backend/market_service.py
    │  HTTP Client + WebSocket Client
    ▼
backend 各模块 (回测/模拟/实盘)
    │
    ▼
frontend (WebSocket / HTTP)
```

### 交易数据流

```
frontend
    │  POST /api/trading/orders
    ▼
backend/live_gateway.py
    │  POST /api/v1/orders
    ▼
stock_trade (FastAPI :8800)
    │  xtquant API
    ▼
MiniQMT → 券商交易系统
```

### 选股数据流（独立）

```
新浪财经 API (AKShare)
    │
    ▼
stock_filters/engine.py
    │  初筛 → 策略扫描
    ▼
钉钉 Webhook 通知
```

---

## 5. 部署架构

### 推荐部署拓扑

```
┌──────────────────────────────────────────────┐
│              Windows 主机 (QMT)               │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │  MiniQMT     │  │  stock_data (:8000)  │  │
│  │  (xtquant)   │  │  stock_trade (:8800) │  │
│  └──────────────┘  └──────────────────────┘  │
└──────────────────────────────────────────────┘
            │ HTTP/WS
            ▼
┌──────────────────────────────────────────────┐
│            Linux/Windows 主机                  │
│  ┌──────────────────────────────────────┐    │
│  │  backend (:8000)                     │    │
│  │  - 回测引擎                           │    │
│  │  - 模拟交易                           │    │
│  │  - 实盘交易网关                        │    │
│  │  - AI 分析 (DeepSeek)                 │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  stock_filters (定时任务)              │    │
│  │  - 14:15 初筛                        │    │
│  │  - 14:28 策略扫描 + 钉钉通知           │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
            │ HTTP/WS
            ▼
┌──────────────────────────────────────────────┐
│              浏览器 (用户)                     │
│  frontend (Vite dev / Nginx static)          │
└──────────────────────────────────────────────┘
```

### 环境变量

| 变量 | 服务 | 说明 |
|------|------|------|
| `STOCK_DATA_API_KEY` | stock_data | API 认证密钥 |
| `STOCK_TRADE_API_KEY` | stock_trade | API 认证密钥 |
| `STOCK_DATA_URL` | backend | stock_data 服务地址 |
| `STOCK_TRADE_URL` | backend | stock_trade 服务地址 |
| `STOCK_DATA_API_KEY` | backend | stock_data API 密钥 |
| `STOCK_TRADE_API_KEY` | backend | stock_trade API 密钥 |
| `LLM_API_KEY` | backend | LLM API 密钥 |
| `LLM_BASE_URL` | backend | LLM 网关地址 |
| `LLM_MODEL` | backend | LLM 模型名称 |
| `DINGTALK_WEBHOOK` | stock_filters | 钉钉 Webhook 地址 |
| `DINGTALK_SECRET` | stock_filters | 钉钉加签密钥 |

---

## 6. API 接口汇总

### backend 核心 API (`/api`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| GET | `/api/auth/me` | 获取当前用户 |
| GET | `/api/strategies` | 策略列表 |
| GET | `/api/strategies/{id}` | 策略详情 |
| POST | `/api/strategies` | 创建策略 |
| PUT | `/api/strategies/{id}` | 更新策略 |
| DELETE | `/api/strategies/{id}` | 删除策略 |
| POST | `/api/backtest/run` | 运行回测 |
| GET | `/api/backtest/results` | 回测结果列表 |
| GET | `/api/backtest/results/{id}` | 回测结果详情 |
| GET | `/api/simulation/instances` | 模拟交易实例 |
| POST | `/api/simulation/instances` | 创建模拟实例 |
| POST | `/api/simulation/instances/{id}/start` | 启动模拟 |
| POST | `/api/simulation/instances/{id}/stop` | 停止模拟 |
| GET | `/api/trading/accounts` | 交易账户 |
| POST | `/api/trading/orders` | 下单 |
| DELETE | `/api/trading/orders/{id}` | 撤单 |
| GET | `/api/trading/positions` | 持仓查询 |
| GET | `/api/trading/signals` | 信号查询 |
| POST | `/api/trading/signals/{id}/confirm` | 确认信号 |
| GET | `/api/market/klines` | K 线查询 |
| GET | `/api/market/tick/{symbol}` | Tick 查询 |
| GET | `/api/stocks` | 股票列表 |
| GET | `/api/stocks/{code}` | 股票详情 |
| GET | `/api/dashboard/summary` | 仪表盘汇总 |
| POST | `/api/ai/chat` | AI 对话 |
| GET | `/api/ai/market-analysis/{symbol}` | AI 市场分析 |
| WS | `/ws` | WebSocket 实时推送 |

### stock_data API (`/api/v1`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/klines` | K 线数据 |
| GET | `/api/v1/tick/{symbol}` | Tick 快照 |
| GET | `/api/v1/stocks` | 股票列表 |
| GET | `/api/v1/instruments/{symbol}` | 合约详情 |
| GET | `/api/v1/sync/status` | 同步状态 |
| POST | `/api/v1/sync/trigger` | 触发同步 |
| WS | `/api/v1/ws/quote` | 实时行情推送 |

### stock_trade API (`/api/v1`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/asset` | 资金查询 |
| GET | `/api/v1/positions` | 持仓查询 |
| GET | `/api/v1/orders` | 委托查询 |
| GET | `/api/v1/trades` | 成交查询 |
| POST | `/api/v1/orders` | 下单 |
| DELETE | `/api/v1/orders/{order_id}` | 撤单 |
| WS | `/api/v1/ws/trade` | 实时事件推送 |

---

## 7. 数据库设计

backend 使用 SQLite 数据库（`stock_quant.db`），共 11 张表：

### 表结构总览

| 表名 | 说明 | 主要字段 |
|------|------|------|
| `users` | 用户表 | id, username, email, hashed_password, is_active |
| `accounts` | 交易账户 | id, user_id, type(real/virtual), broker, balance, profit_rate |
| `strategies` | 策略定义 | id, user_id, name, category, code, parameters, is_system |
| `strategy_states` | 策略运行状态 | id, strategy_name, vt_symbol, grid_states_json, signal_state |
| `backtest_results` | 回测结果 | id, user_id, strategy_id, symbol, total_return, sharpe_ratio, max_drawdown, daily_results(JSON), trades(JSON) |
| `orders` | 委托记录 | id, user_id, account_id, symbol, side, type, quantity, price, status, source |
| `positions` | 持仓记录 | id, account_id, symbol, quantity, avg_cost, current_price, profit_rate |
| `trading_instances` | 交易实例 | id, user_id, name, symbol, strategy_id, mode(simulation/live), status, current_equity |
| `auto_trade_configs` | 自动交易配置 | id, user_id, account_id, auto_trade_enabled, max_order_amount, daily_loss_limit |
| `signals` | 交易信号 | id, user_id, instance_id, symbol, side, price, quantity, status, reason |
| `strategy_logs` | 策略日志 | id, instance_id, side, message, price, quantity, pnl |

### ER 关系

```
User (1) ──< (N) Account
User (1) ──< (N) Strategy
User (1) ──< (N) BacktestResult
User (1) ──< (N) Order
User (1) ──< (N) TradingInstance
User (1) ──< (N) AutoTradeConfig
User (1) ──< (N) Signal

Account (1) ──< (N) Order
Account (1) ──< (N) Position
Account (1) ──< (N) TradingInstance

TradingInstance (1) ──< (N) Signal
TradingInstance (1) ──< (N) StrategyLog

Strategy (1) ──< (N) BacktestResult
Strategy (1) ──< (N) TradingInstance
```

---

## 8. 策略体系

### 策略分类

#### backend 内置策略（vnpy CTA 策略模板）

| 策略类 | 说明 | 适用周期 |
|--------|------|----------|
| `BollingerStrategy` | 布林带策略 | 日线/分钟线 |
| `AtrChannelStrategy` | ATR 通道突破 | 日线/分钟线 |
| `DualThrustStrategy` | 双推力策略 | 分钟线 |
| `GridStrategy` | 网格交易策略 | 分钟线 |
| `DoubleMaStrategy` | 双均线交叉 | 日线 |
| `KamaStrategy` | 考夫曼自适应均线 | 日线 |
| `RsiStrategy` | RSI 超买超卖 | 日线 |
| `MacdStrategy` | MACD 金叉死叉 | 日线 |

#### stock_filters 选股策略

| 策略 | 类型 | 信号条件 |
|------|------|------|
| 四维擒龙 | 趋势跟踪 | 放量 + MACD + 均线多头 + 突破前高 |
| 六脉神剑 | 多因子 | 放量 + MACD + KDJ + RSI + 均线 + 量能 |
| RSI+KDJ 共振 | 反转 | RSI 超卖 + KDJ 低位金叉 + 涨幅 + 放量 |

### 策略开发流程

1. 继承 `app/strategies/base.py` 中的策略基类
2. 实现 `generate_signals()` 方法生成交易信号
3. 在 `VNPY_STRATEGY_MAP` 中注册策略类
4. 通过前端或 API 创建策略实例
5. 运行回测验证策略表现
6. 模拟交易 → 实盘交易

---

## 9. 安全与认证

### API 认证

| 层级 | 方式 | 说明 |
|------|------|------|
| stock_data | `X-API-Key` Header | 环境变量 `STOCK_DATA_API_KEY` 配置 |
| stock_trade | `X-API-Key` Header | 环境变量 `STOCK_TRADE_API_KEY` 配置 |
| backend | JWT Bearer Token | 用户登录后获取，24 小时有效 |
| WebSocket | `?apikey=` 查询参数 | stock_data/stocketrade WS 认证 |

### 通信安全

- stock_data / stock_trade 支持 HTTPS（SSL 证书放入 `db_data/` 目录自动启用）
- backend 与微服务间通信支持自签名证书
- JWT 使用 HS256 算法签名
- 密码使用 bcrypt 哈希存储

### 风控机制

| 机制 | 配置项 | 说明 |
|------|--------|------|
| 单笔最大金额 | `max_order_amount` | 默认 100,000 元 |
| 最大持仓比例 | `max_position_ratio` | 默认 30% |
| 日内亏损限额 | `daily_loss_limit` | 默认 5,000 元 |
| 信号确认 | `confirm_required` | 可选人工确认后再下单 |

---

## 10. 技术栈总览

### 后端

| 类别 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.115.6 |
| ASGI 服务器 | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| 数据验证 | Pydantic | 2.10.3 |
| 认证 | python-jose (JWT) + passlib (bcrypt) | 3.3.0 / 1.7.4 |
| 量化引擎 | vnpy | 4.3.0 |
| CTP 网关 | vnpy-ctp | 6.7.11.4 |
| XTP 网关 | vnpy-xtp | 2.2.32.2.3 |
| 数据处理 | Polars | ≥0.20.0 |
| HTTP 客户端 | httpx | ≥0.27.0 |
| AI | OpenAI SDK (DeepSeek) | ≥1.0.0 |
| 实时通信 | websockets | 14.1 |
| 定时任务 | APScheduler | - |
| 数据库 | SQLite | - |

### 前端

| 类别 | 技术 | 版本 |
|------|------|------|
| 框架 | React | 18.2 |
| 语言 | TypeScript | 5.2 |
| 构建 | Vite | 5.0 |
| 路由 | react-router-dom | 6.21 |
| 状态管理 | Zustand | 4.4 |
| 样式 | Tailwind CSS | 3.3 |
| K 线图 | lightweight-charts | 5.2 |
| 统计图 | Recharts | 2.10 |
| 图标 | Lucide React | 0.294 |
| 日期 | date-fns | 3.0 |

### 数据与交易

| 类别 | 技术 | 说明 |
|------|------|------|
| 行情数据源 | MiniQMT (xtquant) | QMT 极简模式，本地数据 |
| 备选数据源 | AKShare / Baostock / Efinance / 新浪 / 腾讯 | 多源回退 |
| 选股数据源 | 新浪财经 API (via AKShare) | stock_filters 专用 |
| 交易通道 | QMT / XTP / 华泰 / 同花顺 / 国泰君安 / 恒生 | 多券商支持 |
| 通知 | 钉钉机器人 (加签模式) | stock_filters 推送 |

---

## 附录

### A. 股票代码格式

| 后缀 | 交易所 | 示例 |
|------|--------|------|
| `.SH` | 上海证券交易所 | `600519.SH`（贵州茅台） |
| `.SZ` | 深圳证券交易所 | `000001.SZ`（平安银行） |
| `.BJ` | 北京证券交易所 | `830799.BJ` |

### B. K 线周期支持

| 周期 | 标识 | 说明 |
|------|------|------|
| 1 分钟 | `1m` | 细颗粒度 |
| 5 分钟 | `5m` | 常用短线 |
| 15 分钟 | `15m` | 日内波段 |
| 30 分钟 | `30m` | 日内波段 |
| 60 分钟 | `60m` / `1h` | 日内趋势 |
| 日线 | `1d` | 默认周期 |
| 周线 | `1w` | 中长线 |
| 月线 | `1mon` | 长线 |

### C. 复权方式

| 标识 | 说明 |
|------|------|
| `none` | 不复权 |
| `front` | 前复权（默认推荐） |
| `back` | 后复权 |

### D. 错误码

| HTTP 状态码 | 场景 |
|-------------|------|
| 401 | API Key 无效或 JWT 过期 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 500 | 服务器内部错误 |
| 503 | 数据源/交易网关不可用 |

---

> **文档维护**: 本文档随项目迭代更新，各子项目的详细 API 文档见各自目录下的 `README.md` 和 `*_api.md` 文件。
