# Stock Filters 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个插件式股票筛选系统，支持配置驱动的初筛、多策略扫描、钉钉通知和定时调度。

**Architecture:** 数据层抽象为接口（Mock实现+后续AKShare替换），策略以插件形式自动发现注册，APScheduler驱动定时任务，引擎串联初筛→策略→通知的完整流程。

**Tech Stack:** Python 3.10+, pandas, APScheduler, PyYAML, requests, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `config.yaml` | 全局配置：调度、初筛条件、策略参数、钉钉 |
| `data/interface.py` | 数据源抽象接口，7个方法 |
| `data/mock.py` | Mock数据实现，返回模拟DataFrame |
| `strategies/base.py` | 策略基类，定义scan接口 |
| `strategies/__init__.py` | 自动发现并注册策略插件 |
| `strategies/six_sword.py` | 六脉神剑策略实现 |
| `strategies/four_dimension.py` | 四维擒龙策略实现 |
| `screener.py` | 初筛逻辑，根据配置过滤股票池 |
| `notifier.py` | 钉钉机器人通知，含重试 |
| `engine.py` | 主引擎：串联初筛→策略→通知 |
| `scheduler.py` | APScheduler调度器 |
| `main.py` | CLI入口，支持手动触发 |
| `tests/test_data_interface.py` | 数据接口测试 |
| `tests/test_screener.py` | 初筛逻辑测试 |
| `tests/test_strategies.py` | 策略测试 |
| `tests/test_notifier.py` | 通知测试 |
| `tests/test_engine.py` | 引擎集成测试 |
| `tests/test_scheduler.py` | 调度器测试 |
| `requirements.txt` | 依赖清单 |

---

### Task 1: 项目初始化与配置文件

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`

- [ ] **Step 1: 创建 requirements.txt**

```text
pandas>=2.0
APScheduler>=3.10
PyYAML>=6.0
requests>=2.31
pytest>=7.0
```

- [ ] **Step 2: 创建 config.yaml**

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

- [ ] **Step 3: 安装依赖**

Run: `pip install -r requirements.txt`
Expected: 所有包安装成功

- [ ] **Step 4: Commit**

```bash
git add requirements.txt config.yaml
git commit -m "feat: init project with config and dependencies"
```

---

### Task 2: 数据源抽象接口与Mock实现

**Files:**
- Create: `data/__init__.py`
- Create: `data/interface.py`
- Create: `data/mock.py`
- Create: `tests/test_data_interface.py`

- [ ] **Step 1: 写数据接口的失败测试**

```python
# tests/test_data_interface.py
import pandas as pd
import pytest
from data.mock import MockDataSource


@pytest.fixture
def ds():
    return MockDataSource()


def test_get_stock_list_returns_dataframe(ds):
    result = ds.get_stock_list()
    assert isinstance(result, pd.DataFrame)
    required = {"code", "name", "industry", "list_date", "is_st"}
    assert required.issubset(set(result.columns))
    assert len(result) > 0


def test_get_stock_basic_returns_dataframe(ds):
    result = ds.get_stock_basic("000001")
    assert isinstance(result, pd.DataFrame)
    required = {"code", "market_cap", "pe", "pb", "total_shares", "float_shares"}
    assert required.issubset(set(result.columns))


def test_get_daily_quote_returns_dataframe(ds):
    result = ds.get_daily_quote("000001", days=60)
    assert isinstance(result, pd.DataFrame)
    required = {"date", "open", "high", "low", "close", "volume", "amount", "turnover"}
    assert required.issubset(set(result.columns))
    assert len(result) == 60


def test_get_realtime_quote_returns_dataframe(ds):
    result = ds.get_realtime_quote(["000001", "600036"])
    assert isinstance(result, pd.DataFrame)
    required = {"code", "name", "price", "change_pct", "volume", "amount"}
    assert required.issubset(set(result.columns))
    assert len(result) == 2


def test_get_money_flow_returns_dataframe(ds):
    result = ds.get_money_flow("000001", days=10)
    assert isinstance(result, pd.DataFrame)
    required = {"date", "net_inflow", "main_inflow", "main_outflow"}
    assert required.issubset(set(result.columns))
    assert len(result) == 10


def test_is_trading_day_returns_bool(ds):
    result = ds.is_trading_day()
    assert isinstance(result, bool)


def test_is_trading_time_returns_bool(ds):
    result = ds.is_trading_time()
    assert isinstance(result, bool)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_data_interface.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 data/__init__.py**

```python
# data/__init__.py
```

- [ ] **Step 4: 实现 data/interface.py**

```python
# data/interface.py
from abc import ABC, abstractmethod
import pandas as pd


class DataSourceInterface(ABC):
    """数据源抽象接口 - 后续对接 AKShare"""

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """获取全市场股票列表
        返回: code, name, industry, list_date, is_st
        """

    @abstractmethod
    def get_stock_basic(self, code: str) -> pd.DataFrame:
        """获取个股基本面数据
        返回: code, market_cap, pe, pb, total_shares, float_shares
        """

    @abstractmethod
    def get_daily_quote(self, code: str, days: int = 60) -> pd.DataFrame:
        """获取日K线数据
        返回: date, open, high, low, close, volume, amount, turnover
        """

    @abstractmethod
    def get_realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        """获取实时行情（盘中用）
        返回: code, name, price, change_pct, volume, amount
        """

    @abstractmethod
    def get_money_flow(self, code: str, days: int = 10) -> pd.DataFrame:
        """获取资金流向数据
        返回: date, net_inflow, main_inflow, main_outflow
        """

    @abstractmethod
    def is_trading_day(self) -> bool:
        """判断今天是否为交易日"""

    @abstractmethod
    def is_trading_time(self) -> bool:
        """判断当前是否在交易时间（9:30-11:30, 13:00-15:00）"""
```

- [ ] **Step 5: 实现 data/mock.py**

```python
# data/mock.py
import datetime
import numpy as np
import pandas as pd
from data.interface import DataSourceInterface


class MockDataSource(DataSourceInterface):
    """Mock数据源 - 开发阶段使用"""

    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame({
            "code": ["000001", "000002", "600036", "601318", "688001", "300001"],
            "name": ["平安银行", "万科A", "招商银行", "中国平安", "华兴源创", "特锐德"],
            "industry": ["银行", "房地产", "银行", "保险", "半导体", "电气设备"],
            "list_date": ["1991-04-03", "1991-01-29", "2002-04-09", "2007-03-01", "2019-06-14", "2009-10-30"],
            "is_st": [False, False, False, False, False, False],
        })

    def get_stock_basic(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({
            "code": [code],
            "market_cap": [np.random.uniform(30, 500)],
            "pe": [np.random.uniform(5, 50)],
            "pb": [np.random.uniform(0.5, 5)],
            "total_shares": [np.random.uniform(1e9, 5e10)],
            "float_shares": [np.random.uniform(5e8, 3e10)],
        })

    def get_daily_quote(self, code: str, days: int = 60) -> pd.DataFrame:
        dates = pd.bdate_range(end=datetime.date.today(), periods=days)
        base_price = np.random.uniform(10, 100)
        close = base_price * np.cumprod(1 + np.random.normal(0, 0.02, days))
        return pd.DataFrame({
            "date": dates,
            "open": close * (1 + np.random.uniform(-0.02, 0.02, days)),
            "high": close * (1 + np.random.uniform(0, 0.03, days)),
            "low": close * (1 - np.random.uniform(0, 0.03, days)),
            "close": close,
            "volume": np.random.uniform(1e6, 1e8, days).astype(int),
            "amount": np.random.uniform(1e7, 1e9, days),
            "turnover": np.random.uniform(0.5, 5, days),
        })

    def get_realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        names = {"000001": "平安银行", "600036": "招商银行", "601318": "中国平安"}
        return pd.DataFrame({
            "code": codes,
            "name": [names.get(c, f"股票{c}") for c in codes],
            "price": np.random.uniform(10, 100, len(codes)),
            "change_pct": np.random.uniform(-5, 5, len(codes)),
            "volume": np.random.uniform(1e6, 1e8, len(codes)).astype(int),
            "amount": np.random.uniform(1e7, 1e9, len(codes)),
        })

    def get_money_flow(self, code: str, days: int = 10) -> pd.DataFrame:
        dates = pd.bdate_range(end=datetime.date.today(), periods=days)
        return pd.DataFrame({
            "date": dates,
            "net_inflow": np.random.uniform(-1e8, 1e8, days),
            "main_inflow": np.random.uniform(0, 5e7, days),
            "main_outflow": np.random.uniform(0, 5e7, days),
        })

    def is_trading_day(self) -> bool:
        return datetime.date.today().weekday() < 5

    def is_trading_time(self) -> bool:
        now = datetime.datetime.now().time()
        morning = (datetime.time(9, 30) <= now <= datetime.time(11, 30))
        afternoon = (datetime.time(13, 0) <= now <= datetime.time(15, 0))
        return morning or afternoon
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_data_interface.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add data/ tests/test_data_interface.py
git commit -m "feat: add data source interface and mock implementation"
```

---

### Task 3: 策略基类与自动发现机制

**Files:**
- Create: `strategies/__init__.py`
- Create: `strategies/base.py`
- Create: `tests/test_strategies.py` (基类部分)

- [ ] **Step 1: 写策略自动发现的失败测试**

```python
# tests/test_strategies.py
import pytest
from strategies.base import BaseStrategy
from strategies import discover_strategies


class FakeStrategy(BaseStrategy):
    name = "fake"
    description = "fake strategy"

    def scan(self, pool, data):
        return []


def test_base_strategy_is_abstract():
    """BaseStrategy不能直接实例化"""
    with pytest.raises(TypeError):
        BaseStrategy()


def test_discover_strategies_returns_dict():
    """自动发现返回 {name: class} 字典"""
    result = discover_strategies()
    assert isinstance(result, dict)
    assert "six_sword" in result
    assert "four_dimension" in result


def test_discover_strategies_all_inherit_base():
    """所有发现的策略都继承BaseStrategy"""
    result = discover_strategies()
    for name, cls in result.items():
        assert issubclass(cls, BaseStrategy)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 strategies/base.py**

```python
# strategies/base.py
from abc import ABC, abstractmethod
import pandas as pd
from data.interface import DataSourceInterface


class BaseStrategy(ABC):
    name: str
    description: str
    params: dict = {}

    def __init__(self, params: dict | None = None):
        if params:
            self.params = params

    @abstractmethod
    def scan(self, pool: pd.DataFrame, data: DataSourceInterface) -> list[dict]:
        """扫描股票池，返回命中结果
        返回: [{"code": "000001", "name": "平安银行", "reason": "...", "details": {...}}]
        """
```

- [ ] **Step 4: 实现 strategies/__init__.py（自动发现）**

```python
# strategies/__init__.py
import importlib
import pkgutil
from strategies.base import BaseStrategy


def discover_strategies() -> dict[str, type[BaseStrategy]]:
    """扫描 strategies/ 目录，发现所有 BaseStrategy 子类"""
    strategies = {}
    package = importlib.import_module("strategies")
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"strategies.{name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and hasattr(attr, "name")):
                strategies[attr.name] = attr
    return strategies


def load_strategies(config: dict) -> list[BaseStrategy]:
    """根据配置加载启用的策略实例"""
    all_strategies = discover_strategies()
    loaded = []
    strategy_configs = config.get("strategies", {})
    for name, cls in all_strategies.items():
        cfg = strategy_configs.get(name, {})
        if cfg.get("enabled", False):
            params = cfg.get("params", {})
            loaded.append(cls(params=params))
    return loaded
```

- [ ] **Step 5: 运行测试确认失败（因为还没创建具体策略）**

Run: `python -m pytest tests/test_strategies.py::test_discover_strategies_returns_dict -v`
Expected: FAIL - "six_sword" not in result

- [ ] **Step 6: Commit**

```bash
git add strategies/ tests/test_strategies.py
git commit -m "feat: add strategy base class and auto-discovery"
```

---

### Task 4: 六脉神剑策略

**Files:**
- Create: `strategies/six_sword.py`
- Modify: `tests/test_strategies.py` (追加测试)

- [ ] **Step 1: 写六脉神剑策略的失败测试**

追加到 `tests/test_strategies.py`：

```python
import pandas as pd
import numpy as np
from data.mock import MockDataSource


@pytest.fixture
def mock_data():
    return MockDataSource()


def _make_daily_quote_with_signals(days=60):
    """构造满足六脉神剑所有条件的K线数据"""
    dates = pd.bdate_range(end="2026-05-05", periods=days)
    # 均线多头：价格持续上涨
    close = np.linspace(10, 20, days)
    # 最后一天放量
    volume = np.full(days, 1000000)
    volume[-1] = 2000000  # 2倍放量
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": volume,
        "amount": volume * close,
        "turnover": np.full(days, 1.0),
    })


def test_six_sword_scan_returns_hits():
    from strategies.six_sword import SixSwordStrategy
    strategy = SixSwordStrategy(params={
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "kdj_k_period": 9, "kdj_d_period": 3,
        "rsi_period": 14, "rsi_lower": 30, "rsi_upper": 70,
        "ma_periods": [5, 10, 20, 60],
        "volume_ratio": 1.5,
    })
    pool = pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
    result = strategy.scan(pool, mock_data())
    assert isinstance(result, list)
    # 每个结果包含必要字段
    for item in result:
        assert "code" in item
        assert "name" in item
        assert "reason" in item


def test_six_sword_name():
    from strategies.six_sword import SixSwordStrategy
    assert SixSwordStrategy.name == "six_sword"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategies.py::test_six_sword_name -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 strategies/six_sword.py**

```python
# strategies/six_sword.py
import numpy as np
import pandas as pd
from strategies.base import BaseStrategy
from data.interface import DataSourceInterface


class SixSwordStrategy(BaseStrategy):
    """六脉神剑策略：MACD金叉 + KDJ金叉 + RSI适中 + 均线多头 + 放量 + 突破前高"""
    name = "six_sword"
    description = "六脉神剑：MACD金叉+KDJ金叉+RSI适中+均线多头+放量+突破前高"

    def scan(self, pool: pd.DataFrame, data: DataSourceInterface) -> list[dict]:
        results = []
        for _, row in pool.iterrows():
            code = row["code"]
            name = row["name"]
            try:
                quote = data.get_daily_quote(code, days=60)
                if len(quote) < 30:
                    continue
                reasons = []
                # 1. MACD金叉
                if self._check_macd_golden_cross(quote):
                    reasons.append("MACD金叉")
                # 2. KDJ金叉
                if self._check_kdj_golden_cross(quote):
                    reasons.append("KDJ金叉")
                # 3. RSI适中
                rsi_val = self._calc_rsi(quote)
                rsi_lower = self.params.get("rsi_lower", 30)
                rsi_upper = self.params.get("rsi_upper", 70)
                if rsi_lower < rsi_val < rsi_upper:
                    reasons.append(f"RSI{rsi_val:.0f}")
                # 4. 均线多头
                if self._check_ma_bullish(quote):
                    reasons.append("均线多头")
                # 5. 放量
                vol_ratio = self._calc_volume_ratio(quote)
                threshold = self.params.get("volume_ratio", 1.5)
                if vol_ratio > threshold:
                    reasons.append(f"放量{vol_ratio:.1f}倍")
                # 6. 突破前高
                if self._check_breakout(quote):
                    reasons.append("突破前高")

                if len(reasons) >= 4:  # 至少满足4个条件
                    results.append({
                        "code": code,
                        "name": name,
                        "reason": "+".join(reasons),
                        "details": {"reasons": reasons, "rsi": rsi_val, "volume_ratio": vol_ratio},
                    })
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"六脉神剑扫描 {code} 失败: {e}")
        return results

    def _check_macd_golden_cross(self, quote: pd.DataFrame) -> bool:
        fast = self.params.get("macd_fast", 12)
        slow = self.params.get("macd_slow", 26)
        signal = self.params.get("macd_signal", 9)
        ema_fast = quote["close"].ewm(span=fast).mean()
        ema_slow = quote["close"].ewm(span=slow).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal).mean()
        if len(dif) < 2:
            return False
        return dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1]

    def _check_kdj_golden_cross(self, quote: pd.DataFrame) -> bool:
        k_period = self.params.get("kdj_k_period", 9)
        d_period = self.params.get("kdj_d_period", 3)
        low_min = quote["low"].rolling(k_period).min()
        high_max = quote["high"].rolling(k_period).max()
        rsv = (quote["close"] - low_min) / (high_max - low_min) * 100
        k = rsv.ewm(com=d_period - 1).mean()
        d = k.ewm(com=d_period - 1).mean()
        if len(k) < 2:
            return False
        return k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1]

    def _calc_rsi(self, quote: pd.DataFrame) -> float:
        period = self.params.get("rsi_period", 14)
        delta = quote["close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not rsi.empty else 50.0

    def _check_ma_bullish(self, quote: pd.DataFrame) -> bool:
        ma_periods = self.params.get("ma_periods", [5, 10, 20, 60])
        mas = [quote["close"].rolling(p).mean().iloc[-1] for p in ma_periods]
        if any(np.isnan(mas)):
            return False
        return all(mas[i] > mas[i + 1] for i in range(len(mas) - 1))

    def _calc_volume_ratio(self, quote: pd.DataFrame) -> float:
        avg_vol = quote["volume"].iloc[:-1].mean()
        if avg_vol == 0:
            return 0.0
        return quote["volume"].iloc[-1] / avg_vol

    def _check_breakout(self, quote: pd.DataFrame) -> bool:
        period = 20
        if len(quote) < period + 1:
            return False
        prev_high = quote["high"].iloc[-period - 1:-1].max()
        return quote["close"].iloc[-1] > prev_high
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add strategies/six_sword.py tests/test_strategies.py
git commit -m "feat: add six sword strategy"
```

---

### Task 5: 四维擒龙策略

**Files:**
- Create: `strategies/four_dimension.py`
- Modify: `tests/test_strategies.py` (追加测试)

- [ ] **Step 1: 写四维擒龙策略的失败测试**

追加到 `tests/test_strategies.py`：

```python
def test_four_dimension_name():
    from strategies.four_dimension import FourDimensionStrategy
    assert FourDimensionStrategy.name == "four_dimension"


def test_four_dimension_scan_returns_list():
    from strategies.four_dimension import FourDimensionStrategy
    strategy = FourDimensionStrategy(params={
        "volume_ratio": 2.0,
        "breakout_period": 20,
        "consolidation_days": 10,
        "consolidation_range": 0.05,
        "upside_space_pct": 20,
    })
    pool = pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
    result = strategy.scan(pool, mock_data())
    assert isinstance(result, list)
    for item in result:
        assert "code" in item
        assert "name" in item
        assert "reason" in item
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategies.py::test_four_dimension_name -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 strategies/four_dimension.py**

```python
# strategies/four_dimension.py
import numpy as np
import pandas as pd
from strategies.base import BaseStrategy
from data.interface import DataSourceInterface


class FourDimensionStrategy(BaseStrategy):
    """四维擒龙策略：量能放大 + 价格突破 + 横盘整理 + 上涨空间"""
    name = "four_dimension"
    description = "四维擒龙：放量+突破+横盘+上涨空间"

    def scan(self, pool: pd.DataFrame, data: DataSourceInterface) -> list[dict]:
        results = []
        for _, row in pool.iterrows():
            code = row["code"]
            name = row["name"]
            try:
                quote = data.get_daily_quote(code, days=60)
                if len(quote) < 30:
                    continue
                reasons = []
                # 1. 量能放大
                vol_ratio = self._calc_volume_ratio(quote)
                threshold = self.params.get("volume_ratio", 2.0)
                if vol_ratio > threshold:
                    reasons.append(f"放量{vol_ratio:.1f}倍")
                # 2. 价格突破
                breakout_period = self.params.get("breakout_period", 20)
                if self._check_breakout(quote, breakout_period):
                    reasons.append(f"突破{breakout_period}日高点")
                # 3. 横盘整理
                cons_days = self.params.get("consolidation_days", 10)
                cons_range = self.params.get("consolidation_range", 0.05)
                if self._check_consolidation(quote, cons_days, cons_range):
                    reasons.append(f"横盘{cons_days}日")
                # 4. 上涨空间
                space = self._calc_upside_space(quote)
                space_pct = self.params.get("upside_space_pct", 20)
                if space > space_pct:
                    reasons.append(f"距高点{space:.0f}%空间")

                if len(reasons) >= 3:  # 至少满足3个维度
                    results.append({
                        "code": code,
                        "name": name,
                        "reason": "+".join(reasons),
                        "details": {"reasons": reasons, "volume_ratio": vol_ratio, "upside_space": space},
                    })
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"四维擒龙扫描 {code} 失败: {e}")
        return results

    def _calc_volume_ratio(self, quote: pd.DataFrame) -> float:
        period = self.params.get("breakout_period", 20)
        avg_vol = quote["volume"].iloc[-period - 1:-1].mean()
        if avg_vol == 0:
            return 0.0
        return quote["volume"].iloc[-1] / avg_vol

    def _check_breakout(self, quote: pd.DataFrame, period: int) -> bool:
        if len(quote) < period + 1:
            return False
        prev_high = quote["high"].iloc[-period - 1:-1].max()
        return quote["close"].iloc[-1] > prev_high

    def _check_consolidation(self, quote: pd.DataFrame, days: int, max_range: float) -> bool:
        if len(quote) < days + 1:
            return False
        recent = quote.iloc[-days - 1:-1]
        high = recent["high"].max()
        low = recent["low"].min()
        if low == 0:
            return False
        return (high / low - 1) < max_range

    def _calc_upside_space(self, quote: pd.DataFrame) -> float:
        high_60 = quote["high"].max()
        current = quote["close"].iloc[-1]
        if current == 0:
            return 0.0
        return (high_60 - current) / current * 100
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add strategies/four_dimension.py tests/test_strategies.py
git commit -m "feat: add four dimension strategy"
```

---

### Task 6: 初筛逻辑

**Files:**
- Create: `screener.py`
- Create: `tests/test_screener.py`

- [ ] **Step 1: 写初筛逻辑的失败测试**

```python
# tests/test_screener.py
import pandas as pd
import pytest
from screener import Screener
from data.mock import MockDataSource


@pytest.fixture
def screener():
    config = {
        "min_market_cap": 50,
        "min_daily_amount": 1,
        "exclude_st": True,
        "exclude_new_stock_days": 60,
        "exclude_code_prefix": ["688", "30"],
        "industries": [],
    }
    return Screener(config, MockDataSource())


def test_screener_returns_dataframe(screener):
    result = screener.run()
    assert isinstance(result, pd.DataFrame)
    assert "code" in result.columns
    assert "name" in result.columns


def test_screener_excludes_code_prefix(screener):
    result = screener.run()
    for code in result["code"]:
        assert not code.startswith("688")
        assert not code.startswith("30")


def test_screener_excludes_st(screener):
    result = screener.run()
    if "is_st" in result.columns:
        assert not result["is_st"].any()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_screener.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 screener.py**

```python
# screener.py
import datetime
import logging
import pandas as pd
from data.interface import DataSourceInterface

logger = logging.getLogger(__name__)


class Screener:
    """初筛逻辑：根据配置条件过滤全市场股票，形成关注股票池"""

    def __init__(self, config: dict, data: DataSourceInterface):
        self.config = config
        self.data = data

    def run(self) -> pd.DataFrame:
        stocks = self.data.get_stock_list()
        pool = stocks.copy()

        # 排除ST
        if self.config.get("exclude_st", True):
            pool = pool[~pool["is_st"]]

        # 排除指定代码前缀
        prefixes = self.config.get("exclude_code_prefix", [])
        if prefixes:
            mask = ~pool["code"].apply(lambda c: any(c.startswith(p) for p in prefixes))
            pool = pool[mask]

        # 排除新股
        new_days = self.config.get("exclude_new_stock_days", 0)
        if new_days > 0:
            cutoff = datetime.date.today() - datetime.timedelta(days=new_days)
            pool["list_date"] = pd.to_datetime(pool["list_date"]).dt.date
            pool = pool[pool["list_date"] <= cutoff]

        # 限定行业
        industries = self.config.get("industries", [])
        if industries:
            pool = pool[pool["industry"].isin(industries)]

        # 基本面过滤：市值和成交额
        results = []
        for _, row in pool.iterrows():
            try:
                basic = self.data.get_stock_basic(row["code"])
                market_cap = basic["market_cap"].iloc[0]
                if market_cap < self.config.get("min_market_cap", 0):
                    continue
                results.append(row)
            except Exception as e:
                logger.warning(f"初筛 {row['code']} 获取基本面失败: {e}")

        if not results:
            return pd.DataFrame(columns=stocks.columns)

        result_df = pd.DataFrame(results)
        # 重新获取成交额过滤（使用实时行情）
        try:
            codes = result_df["code"].tolist()
            realtime = self.data.get_realtime_quote(codes)
            min_amount = self.config.get("min_daily_amount", 0)
            valid_codes = realtime[realtime["amount"] >= min_amount * 1e8]["code"].tolist()
            result_df = result_df[result_df["code"].isin(valid_codes)]
        except Exception as e:
            logger.warning(f"初筛成交额过滤失败: {e}")

        return result_df.reset_index(drop=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_screener.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add screener.py tests/test_screener.py
git commit -m "feat: add stock screener with basic filters"
```

---

### Task 7: 钉钉通知

**Files:**
- Create: `notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: 写通知的失败测试**

```python
# tests/test_notifier.py
import pytest
from unittest.mock import patch, MagicMock
from notifier import DingTalkNotifier


@pytest.fixture
def notifier():
    config = {
        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
        "secret": "",
    }
    return DingTalkNotifier(config)


def test_format_message(notifier):
    results = {
        "六脉神剑": [
            {"code": "000001", "name": "平安银行", "reason": "MACD金叉+放量1.8倍"},
        ],
        "四维擒龙": [
            {"code": "601318", "name": "中国平安", "reason": "放量2.3倍+突破20日高点"},
        ],
    }
    msg = notifier.format_message(results)
    assert "六脉神剑" in msg
    assert "000001" in msg
    assert "四维擒龙" in msg
    assert "601318" in msg
    assert "共筛选出 2 只股票" in msg


def test_format_message_empty(notifier):
    msg = notifier.format_message({})
    assert "未筛选出符合条件的股票" in msg


@patch("notifier.requests.post")
def test_send_success(mock_post, notifier):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"errcode": 0})
    result = notifier.send("test message")
    assert result is True


@patch("notifier.requests.post")
def test_send_retry_on_failure(mock_post, notifier):
    mock_post.side_effect = [Exception("timeout"), Exception("timeout"), MagicMock(status_code=200, json=lambda: {"errcode": 0})]
    result = notifier.send("test message")
    assert result is True
    assert mock_post.call_count == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 notifier.py**

```python
# notifier.py
import hashlib
import hmac
import base64
import time
import urllib.parse
import logging
import requests

logger = logging.getLogger(__name__)


class DingTalkNotifier:
    """钉钉机器人通知"""

    def __init__(self, config: dict):
        self.webhook = config.get("webhook", "")
        self.secret = config.get("secret", "")

    def format_message(self, results: dict[str, list[dict]]) -> str:
        """格式化通知消息"""
        if not results:
            return "📊 选股提醒\n\n未筛选出符合条件的股票"

        lines = ["📊 选股提醒"]
        total = 0
        for strategy_name, hits in results.items():
            if not hits:
                continue
            lines.append(f"\n【{strategy_name}】")
            for hit in hits:
                lines.append(f"• {hit['code']} {hit['name']} - {hit['reason']}")
                total += 1

        lines.append(f"\n共筛选出 {total} 只股票")
        return "\n".join(lines)

    def send(self, message: str) -> bool:
        """发送钉钉消息，失败重试3次"""
        url = self._build_url()
        payload = {
            "msgtype": "text",
            "text": {"content": message},
        }
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                data = resp.json()
                if data.get("errcode") == 0:
                    return True
                logger.warning(f"钉钉发送失败: {data}")
            except Exception as e:
                logger.warning(f"钉钉发送异常(第{attempt + 1}次): {e}")
            if attempt < 2:
                time.sleep(5)
        return False

    def _build_url(self) -> str:
        """构建带签名的webhook URL"""
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{self.webhook}&timestamp={timestamp}&sign={sign}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: add DingTalk notifier with retry"
```

---

### Task 8: 主引擎

**Files:**
- Create: `engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: 写引擎的失败测试**

```python
# tests/test_engine.py
import pytest
from unittest.mock import MagicMock, patch
from engine import Engine
from data.mock import MockDataSource


@pytest.fixture
def engine():
    config = {
        "screener": {
            "min_market_cap": 50,
            "min_daily_amount": 1,
            "exclude_st": True,
            "exclude_new_stock_days": 60,
            "exclude_code_prefix": ["688", "30"],
            "industries": [],
        },
        "strategies": {
            "six_sword": {"enabled": True, "params": {}},
            "four_dimension": {"enabled": True, "params": {}},
        },
        "dingtalk": {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "secret": "",
        },
    }
    return Engine(config, MockDataSource())


def test_engine_run_screener_returns_pool(engine):
    pool = engine.run_screener()
    assert isinstance(pool, list) or hasattr(pool, "__len__")


def test_engine_run_strategies_returns_results(engine):
    results = engine.run_strategies()
    assert isinstance(results, dict)


@patch("engine.DingTalkNotifier")
def test_engine_run_full(mock_notifier_cls, engine):
    mock_notifier = MagicMock()
    mock_notifier.send.return_value = True
    mock_notifier.format_message.return_value = "test"
    mock_notifier_cls.return_value = mock_notifier
    engine.run()
    mock_notifier.send.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_engine.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 engine.py**

```python
# engine.py
import logging
import pandas as pd
from data.interface import DataSourceInterface
from screener import Screener
from strategies import load_strategies
from notifier import DingTalkNotifier

logger = logging.getLogger(__name__)


class Engine:
    """主引擎：串联初筛→策略→通知"""

    def __init__(self, config: dict, data: DataSourceInterface):
        self.config = config
        self.data = data
        self.screener = Screener(config.get("screener", {}), data)
        self.strategies = load_strategies(config)
        self.notifier = DingTalkNotifier(config.get("dingtalk", {}))
        self._pool: pd.DataFrame | None = None

    def run_screener(self) -> pd.DataFrame:
        """执行初筛，更新股票池"""
        logger.info("开始初筛...")
        self._pool = self.screener.run()
        logger.info(f"初筛完成，股票池共 {len(self._pool)} 只股票")
        return self._pool

    def run_strategies(self) -> dict[str, list[dict]]:
        """在股票池上运行所有启用的策略"""
        if self._pool is None or self._pool.empty:
            self.run_screener()

        results = {}
        for strategy in self.strategies:
            try:
                logger.info(f"运行策略: {strategy.name}")
                hits = strategy.scan(self._pool, self.data)
                if hits:
                    results[strategy.description] = hits
                    logger.info(f"策略 {strategy.name} 命中 {len(hits)} 只股票")
            except Exception as e:
                logger.error(f"策略 {strategy.name} 执行失败: {e}")
        return results

    def run(self):
        """完整流程：初筛→策略→通知"""
        self.run_screener()
        results = self.run_strategies()
        if results:
            message = self.notifier.format_message(results)
            success = self.notifier.send(message)
            if success:
                logger.info("通知发送成功")
            else:
                logger.error("通知发送失败")
        else:
            logger.info("未筛选出符合条件的股票，不发送通知")
        return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_engine.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add engine.py tests/test_engine.py
git commit -m "feat: add main engine orchestrating screener, strategies, notifier"
```

---

### Task 9: 调度器

**Files:**
- Create: `scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: 写调度器的失败测试**

```python
# tests/test_scheduler.py
import pytest
from unittest.mock import MagicMock, patch
from scheduler import StockScheduler


@pytest.fixture
def scheduler():
    config = {
        "schedule": {
            "pool_update": "0 9 * * 1",
            "strategy_scan": "*/10 9-11,13-14 * * 1-5",
            "trading_hours": {
                "morning": ["09:30", "11:30"],
                "afternoon": ["13:00", "15:00"],
            },
        },
        "screener": {
            "min_market_cap": 50,
            "min_daily_amount": 1,
            "exclude_st": True,
            "exclude_new_stock_days": 60,
            "exclude_code_prefix": ["688", "30"],
            "industries": [],
        },
        "strategies": {
            "six_sword": {"enabled": True, "params": {}},
            "four_dimension": {"enabled": True, "params": {}},
        },
        "dingtalk": {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "secret": "",
        },
    }
    return StockScheduler(config)


def test_scheduler_creates_with_config(scheduler):
    assert scheduler.config is not None


def test_scheduler_has_jobs(scheduler):
    scheduler.setup_jobs()
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) >= 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 scheduler.py**

```python
# scheduler.py
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from data.mock import MockDataSource
from engine import Engine

logger = logging.getLogger(__name__)


class StockScheduler:
    """调度器：管理定时任务"""

    def __init__(self, config: dict):
        self.config = config
        self.data = MockDataSource()
        self.engine = Engine(config, self.data)
        self.scheduler = BlockingScheduler()

    def setup_jobs(self):
        """配置定时任务"""
        schedule_cfg = self.config.get("schedule", {})

        # 每周一更新股票池
        pool_cron = schedule_cfg.get("pool_update", "0 9 * * 1")
        parts = pool_cron.split()
        self.scheduler.add_job(
            self._run_screener_job,
            CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]),
            id="pool_update",
            name="更新股票池",
        )

        # 交易日交易时间策略扫描
        scan_cron = schedule_cfg.get("strategy_scan", "*/10 9-11,13-14 * * 1-5")
        parts = scan_cron.split()
        self.scheduler.add_job(
            self._run_strategy_job,
            CronTrigger(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4]),
            id="strategy_scan",
            name="策略扫描",
        )

    def start(self):
        """启动调度器"""
        self.setup_jobs()
        logger.info("调度器启动")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器停止")

    def _run_screener_job(self):
        """定时任务：更新股票池"""
        logger.info("定时任务：更新股票池")
        try:
            self.engine.run_screener()
        except Exception as e:
            logger.error(f"更新股票池失败: {e}")

    def _run_strategy_job(self):
        """定时任务：策略扫描"""
        if not self.data.is_trading_day() or not self.data.is_trading_time():
            logger.info("非交易时间，跳过策略扫描")
            return
        logger.info("定时任务：策略扫描")
        try:
            self.engine.run_strategies()
        except Exception as e:
            logger.error(f"策略扫描失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: add scheduler with APScheduler cron triggers"
```

---

### Task 10: CLI入口

**Files:**
- Create: `main.py`

- [ ] **Step 1: 实现 main.py**

```python
# main.py
import argparse
import logging
import yaml
from data.mock import MockDataSource
from engine import Engine
from scheduler import StockScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="股票筛选系统")
    parser.add_argument("--run-screener", action="store_true", help="手动执行初筛")
    parser.add_argument("--run-strategies", action="store_true", help="手动执行策略扫描")
    parser.add_argument("--run", action="store_true", help="手动执行完整流程（初筛+策略+通知）")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    data = MockDataSource()

    if args.run_screener:
        engine = Engine(config, data)
        pool = engine.run_screener()
        logger.info(f"股票池: {pool[['code', 'name']].to_string(index=False)}")
    elif args.run_strategies:
        engine = Engine(config, data)
        results = engine.run_strategies()
        for strategy_name, hits in results.items():
            logger.info(f"{strategy_name}: {len(hits)} 只")
    elif args.run:
        engine = Engine(config, data)
        engine.run()
    elif args.schedule:
        scheduler = StockScheduler(config)
        scheduler.start()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手动测试CLI**

Run: `python main.py --run-screener`
Expected: 输出股票池列表

Run: `python main.py --help`
Expected: 显示帮助信息

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add CLI entry point with manual trigger support"
```

---

### Task 11: 全量测试与修复

**Files:**
- All test files

- [ ] **Step 1: 运行全量测试**

Run: `python -m pytest tests/ -v`
Expected: All passed

- [ ] **Step 2: 如有失败，修复后重新运行**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: fix test issues and finalize"
```
