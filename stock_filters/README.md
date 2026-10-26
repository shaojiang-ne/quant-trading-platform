# Stock Filters - A股智能选股系统

基于多策略的A股自动化筛选系统，通过新浪财经API获取全市场数据，结合技术指标和基本面条件进行初筛与策略扫描，结果通过钉钉通知推送。

## 系统架构

```
main.py              入口，命令行参数解析与调度
scheduler.py         定时任务调度（APScheduler）
engine.py            核心引擎，编排初筛/策略/通知流程
screener.py          初筛过滤（ST/市值/成交额/行业/代码前缀等）
notifier.py          钉钉通知（加签安全模式）
config.yaml          配置文件
```

### 策略模块

```
strategies/
├── __init__.py          策略自动发现与加载
├── base.py              策略基类
├── four_dimension.py    四维擒龙
├── six_sword.py         六脉神剑
└── rsi_kdj.py           RSI+KDJ共振
```

### 数据层

```
data/
├── interface.py       数据源接口定义
├── akshare_source.py  新浪财经API实现（主数据源，实时获取K线）
├── test_source.py     测试用模拟数据源
└── cache_manager.py   缓存管理（股票池CSV/行业映射JSON）
```

## 核心流程

### 1. 初筛 (`run_screener`)

1. 调用新浪 `stock_zh_a_spot()` 获取全市场实时行情
2. 并发请求新浪 `_i` 接口补充详情：市值、PE、PB、行业、EPS、营收、净利润等
3. 按条件过滤：
   - 排除ST股
   - 排除科创板(688)、创业板(30)、北交所(920)
   - 市值 < 50亿
   - 日成交额 < 1亿
   - 行业黑名单（银行、房地产等）
4. 新数据质量校验通过后替换缓存，异常时回退旧缓存
5. 完成后发送钉钉通知（成功/失败均通知）

### 2. 策略扫描 (`run_strategies_and_notify`)

对通过初筛的股票池逐策略扫描，命中结果推送钉钉通知。

**放量判断**：策略运行时直接从K线数据实时计算（最新成交量 > 前5日均量×1.5），无需依赖外部缓存。

### 策略列表

| 策略 | 最少命中条件 | 说明 |
|------|------------|------|
| 四维擒龙 | 3/4 | 放量、MACD金叉/零轴上方、均线多头、突破前高 |
| 六脉神剑 | 4/6 | 放量、MACD金叉、KDJ金叉、RSI<70、站上5日线、5日均量放大 |
| RSI+KDJ共振 | 全部 | RSI超卖回弹、KDJ低位金叉、当日涨幅达标、放量 |

## 数据源

### 新浪财经API

| 接口 | 用途 |
|------|------|
| `stock_zh_a_spot()` | 全市场实时行情 |
| `hq.sinajs.cn/list={code},{code}_i` | 个股详情（市值/PE/PB/行业/财务指标） |
| `vip.stock.finance.sina.com.cn/corp/...` | 上市日期 |

### `_i` 接口字段

| 索引 | 字段 | 说明 |
|------|------|------|
| 2 | eps | 每股收益-本报告期 |
| 3 | eps_yoy | 每股收益-上年同期 |
| 5 | bvps | 每股净资产 |
| 7 | totalcapital | 总股本(万股) |
| 13 | profit_ytd | 净利润-年初至报告期(亿元) |
| 14 | profit_yoy | 净利润同比增长率(%) |
| 17 | revenue | 营业收入(亿元) |
| 18 | net_profit | 归母净利润(亿元) |
| 19 | revenue_yoy | 营业收入同比增长率(%) |
| 34 | industry | 行业板块(申万) |
| 37 | total_market_cap | 总市值(元) |
| 39 | f39子字段 | 报告期/扣非净利润/营业成本/总资产 |

### K线数据

- 策略执行时实时从AKShare获取，不缓存
- 并发获取（ThreadPoolExecutor, 10线程）

## 缓存

| 文件 | 说明 |
|------|------|
| `stock_pool.csv` | 初筛股票池（24小时有效） |
| `industry_map_*.json` | 行业映射缓存 |

## 定时任务

由 `scheduler.py` 硬编码注册：

| 任务 | 默认时间 | 说明 |
|------|---------|------|
| `screener` | 工作日 14:15 | 初筛并缓存股票池 |
| `strategy_1428` | 工作日 14:28 | 策略扫描+钉钉通知 |

## 配置

所有配置集中在 `config.yaml`，主要包含以下部分：

```yaml
# 初筛条件
screener:
  min_market_cap: 50           # 最小市值(亿)
  min_daily_amount: 1          # 最小日成交额(亿)
  exclude_st: true             # 排除ST股
  exclude_new_stock_days: 60   # 排除上市N天内的新股
  exclude_code_prefix: ["688", "30", "920"]  # 排除的代码前缀
  exclude_industries: [...]    # 行业黑名单
  industries: []               # 行业白名单（空=不限）

# 策略配置（每个策略可单独启用/调参）
strategies:
  six_sword:
    enabled: true
    params: { min_conditions: 4, ... }
  four_dimension:
    enabled: true
    params: { min_conditions: 3, ... }
  rsi_kdj:
    enabled: true
    params: { rsi_period: 6, ... }

# 钉钉通知（也可通过环境变量覆盖）
dingtalk:
  webhook: "https://oapi.dingtalk.com/robot/send?access_token=..."
  secret: "SEC..."
```

钉钉配置支持环境变量覆盖：`DINGTALK_WEBHOOK`、`DINGTALK_SECRET`。

## 运行

### 安装依赖

```bash
pip3 install -r requirements.txt
```

### 命令行参数

```bash
python3 main.py [选项]
```

| 选项 | 说明 |
|------|------|
| `--schedule` | 启动定时调度（阻塞运行） |
| `--run-screener` | 手动执行初筛 |
| `--run-strategies` | 手动执行策略扫描（使用缓存股票池） |
| `--run` | 手动执行完整流程（初筛→策略→通知） |
| `--force` | 配合 `--run-screener` 使用，强制刷新忽略缓存 |
| `--config PATH` | 指定配置文件路径（默认 `config.yaml`） |

### 常用命令

```bash
# 启动定时调度（阻塞运行，Ctrl+C 停止）
# 工作日 14:15 自动初筛，14:28 自动策略扫描+钉钉通知
python3 main.py --schedule

# 手动执行完整流程：初筛 → 策略扫描 → 钉钉通知
# 适合盘后一次性运行
python3 main.py --run

# 手动执行初筛
# 不加 --force 时，若缓存未过期（24h内）则直接使用缓存
python3 main.py --run-screener

# 手动执行初筛（强制刷新，忽略缓存重新获取全市场数据）
python3 main.py --run-screener --force

# 手动执行策略扫描
# 使用已缓存的股票池，若无缓存则先自动执行初筛
# 命中结果自动推送钉钉通知
python3 main.py --run-strategies

# 使用自定义配置文件
python3 main.py --run --config my_config.yaml
```

> 无参数运行 `python3 main.py` 将打印帮助信息。

### 运行测试

```bash
pytest tests/ -v
```
