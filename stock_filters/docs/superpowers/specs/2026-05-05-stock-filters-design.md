# Stock Filters - 股票筛选系统设计

## 概述

一款 Python 股票筛选系统，支持插件式策略，通过配置文件驱动初筛条件和策略参数，在交易时间自动扫描并通过钉钉机器人发送通知。

## 核心流程

1. **初筛建池**：根据基本面条件（市值、成交额、排除ST/科创板/创业板等）从全市场筛选，形成关注股票池（每周一执行）
2. **策略筛选**：在股票池上运行启用的策略插件，找出符合条件的股票（交易日每10分钟执行）
3. **钉钉通知**：汇总所有策略命中结果，通过钉钉机器人发送简洁摘要

## 项目结构

```text
stock_filters/
├── config.yaml              # 全局配置
├── strategies/              # 策略插件目录
│   ├── __init__.py          # 自动发现注册策略
│   ├── base.py              # 策略基类
│   ├── six_sword.py         # 六脉神剑策略
│   └── four_dimension.py    # 四维擒龙策略
├── data/
│   ├── __init__.py
│   ├── interface.py         # 数据源抽象接口
│   └── mock.py              # Mock 数据实现
├── scheduler.py             # 调度器（APScheduler）
├── notifier.py              # 钉钉通知
├── screener.py              # 初筛逻辑
├── engine.py                # 主引擎
└── main.py                  # 入口
```

## 数据源接口

开发阶段使用 Mock 数据，后续替换为 AKShare 实现。共 7 个接口：

### get_stock_list()

获取全市场股票列表。

返回字段：`code, name, industry, list_date, is_st`

### get_stock_basic(code)

获取个股基本面数据。

返回字段：`code, market_cap, pe, pb, total_shares, float_shares`

### get_daily_quote(code, days=60)

获取日K线数据。

返回字段：`date, open, high, low, close, volume, amount, turnover`

### get_realtime_quote(codes)

获取实时行情（盘中用）。

返回字段：`code, name, price, change_pct, volume, amount`

### get_money_flow(code, days=10)

获取资金流向数据。

返回字段：`date, net_inflow, main_inflow, main_outflow`

### is_trading_day() -> bool

判断今天是否为交易日。

### is_trading_time() -> bool

判断当前是否在交易时间（9:30-11:30, 13:00-15:00）。

## 配置文件

```yaml
schedule:
  pool_update: "0 9 * * 1"
  strategy_scan: "*/10 9-11,13-14 * * 1-5"
  trading_hours:
    morning: ["09:30", "11:30"]
    afternoon: ["13:00", "15:00"]

screener:
  min_market_cap: 50
  min_daily_amount: 1
  exclude_st: true
  exclude_new_stock_days: 60
  exclude_code_prefix: ["688", "30"]
  industries: []

strategies:
  six_sword:
    enabled: true
    params:
      macd_fast: 12
      macd_slow: 26
      macd_signal: 9
      kdj_k_period: 9
      kdj_d_period: 3
      rsi_period: 14
      rsi_lower: 30
      rsi_upper: 70
      ma_periods: [5, 10, 20, 60]
      volume_ratio: 1.5
  four_dimension:
    enabled: true
    params:
      volume_ratio: 2.0
      breakout_period: 20
      consolidation_days: 10
      consolidation_range: 0.05
      upside_space_pct: 20

dingtalk:
  webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
  secret: ""
```

## 策略插件机制

### 基类

```python
class BaseStrategy(ABC):
    name: str
    description: str
    params: dict

    @abstractmethod
    def scan(self, pool: pd.DataFrame, data: DataSourceInterface) -> list[dict]:
        """扫描股票池，返回命中结果
        返回: [{"code": "000001", "name": "平安银行", "reason": "...", "details": {...}}]
        """
```

### 自动发现

- 扫描 `strategies/` 目录下继承 `BaseStrategy` 的类
- 根据 `config.yaml` 中 `strategies.<name>.enabled` 决定是否加载
- 启用时将 `params` 注入策略实例

### 添加新策略

1. 在 `strategies/` 下创建新文件，继承 `BaseStrategy`
2. 在 `config.yaml` 的 `strategies` 下添加对应配置
3. 设置 `enabled: true` 即可启用

### 六脉神剑策略 (six_sword)

六个条件同时满足时触发：

1. **MACD金叉**：MACD的DIF线上穿DEA线
2. **KDJ金叉**：K线上穿D线
3. **RSI适中**：RSI在30-70之间，未超买超卖
4. **均线多头排列**：5日>10日>20日>60日均线
5. **放量**：当日成交量 > 均量的1.5倍
6. **突破前高**：收盘价突破近20日最高价

### 四维擒龙策略 (four_dimension)

四个维度同时满足时触发：

1. **量能放大**：当日成交量 > 20日均量的2倍
2. **价格突破**：收盘价突破近20日最高价
3. **横盘整理**：近10日振幅（最高/最低-1）< 5%
4. **上涨空间**：当前价距近60日高点仍有20%以上空间

## 调度

- 使用 APScheduler CronTrigger
- 股票池更新：每周一 9:00
- 策略扫描：交易日交易时间每 10 分钟
- 扫描前校验 `is_trading_day()` 和 `is_trading_time()`
- 手动触发：`python main.py --run-screener` / `--run-strategies`

## 钉钉通知

格式示例：

```text
📊 选股提醒 (2026-05-05 10:30)

【六脉神剑】
• 000001 平安银行 - MACD金叉+KDJ金叉+均线多头+放量1.8倍+突破前高
• 600036 招商银行 - MACD金叉+KDJ金叉+RSI55+均线多头+放量2.1倍+突破前高

【四维擒龙】
• 601318 中国平安 - 放量2.3倍+突破20日高点+横盘10日+距高点25%空间

共筛选出 3 只股票
```

## 错误处理

- 数据获取失败：记录日志，跳过该股票，不中断整体流程
- 通知发送失败：重试 3 次，间隔 5 秒
- 策略执行异常：记录日志，跳过该策略，继续执行其他策略

## 技术栈

- Python 3.10+
- pandas（数据处理）
- APScheduler（定时调度）
- PyYAML（配置解析）
- requests（钉钉通知）
