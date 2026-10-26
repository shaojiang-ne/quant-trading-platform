# 初筛流程完善计划

## 目标
参考 `fetch_stock_info.py` 的方式，重构初筛数据获取流程，用东方财富接口一次性获取全市场行情+基本面数据，再逐只补充上市日期和行业。

## 核心变更

### 1. 重构 `data/akshare_source.py` - 新增 EM 数据源方法
- `fetch_spot_em()`: 调用 `stock_zh_a_spot_em()` 获取全市场行情（含总市值、PE、PB、成交额等）
- `fetch_individual_info_em(code)`: 调用 `stock_individual_info_em()` 获取单只股票的上市日期、行业
- 列名映射：EM列名 → 项目标准字段名（参考 fetch_stock_info.py 的映射逻辑）

### 2. 重构 `data/interface.py` - DataSource 接口新增方法
- `get_spot_with_fundamentals()`: 返回含基本面字段的行情数据
- `get_stock_detail(code)`: 返回单只股票详情（上市日期、行业）

### 3. 重构 `screener.py` - 初筛流程
- **步骤1**: 调用 `get_spot_with_fundamentals()` 获取全市场行情（含市值、PE、PB、成交额）
- **步骤2**: 快速过滤（ST、代码前缀、市值、成交额）— 无需额外请求
- **步骤3**: 对通过快速过滤的股票，批量调用 `get_stock_detail()` 补充上市日期和行业
- **步骤4**: 新股过滤、行业过滤
- **步骤5**: 输出初筛结果 + 排除原因统计

### 4. 更新 `data/test_source.py` - 测试数据源适配
- 补充 `get_spot_with_fundamentals()` 和 `get_stock_detail()` 方法
- 测试数据包含市值、PE、PB、行业、上市日期等字段

### 5. 更新 `engine.py` - 适配新接口
- 使用新的初筛流程

### 6. 更新测试 `tests/test_screener.py`
- 适配新接口和流程

## 关键设计决策
- EM 接口作为主数据源，新浪作为 fallback（EM无基本面字段时降级）
- 行业映射不再遍历板块，改为逐只获取（只对通过快速过滤的股票，数量少）
- 上市日期同理，只对少量候选股票获取
- 保留原有缓存机制

## 字段映射（EM → 项目标准）
```
代码 → code
名称 → name
最新价 → price
涨跌幅 → change_pct
成交额 → amount
总市值 → market_cap
市盈率-动态 → pe
市净率 → pb
换手率 → turnover_rate
60日涨跌幅 → change_pct_60d
年初至今涨跌幅 → ytd_change_pct
```

## 实施顺序
1. interface.py - 新增接口方法
2. akshare_source.py - 实现 EM 数据获取
3. test_source.py - 适配测试数据源
4. screener.py - 重构初筛流程
5. engine.py - 适配新流程
6. tests/test_screener.py - 更新测试
