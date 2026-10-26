"""
策略自动化测试 — 公共 fixture

提供合成K线数据工厂，覆盖各种走势场景。
"""

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta


# ── 合成K线数据工厂 ──────────────────────────────────────────────────────

def _make_df(dates: list[str], closes: list[float], opens: list[float] = None,
             highs: list[float] = None, lows: list[float] = None,
             volumes: list[float] = None) -> pd.DataFrame:
    """构造标准K线 DataFrame"""
    n = len(closes)
    if opens is None:
        opens = [c * 0.999 for c in closes]
    if highs is None:
        highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
    if lows is None:
        lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
    if volumes is None:
        volumes = [10000.0] * n
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "turnover": [c * v for c, v in zip(closes, volumes)],
    })


@pytest.fixture
def trend_up_data():
    """趋势上升：线性递增 + 小噪声，确保快线上穿慢线"""
    n = 60
    base = list(range(n))
    closes = [100 + i * 0.5 + np.random.uniform(-0.1, 0.1) for i in base]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def trend_down_data():
    """趋势下降：线性递减 + 小噪声，确保快线下穿慢线"""
    n = 60
    closes = [130 - i * 0.5 + np.random.uniform(-0.1, 0.1) for i in range(n)]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def oscillation_data():
    """震荡行情：正弦波，产生反复交叉"""
    n = 200
    t = np.linspace(0, 6 * np.pi, n)
    closes = 100 + 10 * np.sin(t)
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes.tolist())


@pytest.fixture
def gap_up_data():
    """跳空高开数据"""
    n = 40
    closes = [100.0] * 15 + [110.0] * 25  # 第15根跳空
    opens = [100.0] * 15 + [112.0] + [110.0] * 24
    highs = [100.5] * 15 + [113.0] + [110.5] * 24
    lows = [99.5] * 15 + [109.0] + [109.5] * 24
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes, opens, highs, lows)


@pytest.fixture
def constant_data():
    """价格不变数据"""
    n = 60
    closes = [100.0] * n
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def random_data():
    """随机游走数据，1000根bar"""
    np.random.seed(42)
    n = 1000
    returns = np.random.normal(0, 0.02, n)
    closes = [100.0]
    for r in returns[1:]:
        closes.append(closes[-1] * (1 + r))
    dates = [(date(2023, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def extreme_rally_data():
    """连续上涨（模拟涨停）"""
    n = 30
    closes = [100.0 * (1.1 ** i) for i in range(n)]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def minimal_data():
    """最短数据（5根bar），不足以计算多数指标"""
    n = 5
    closes = [100.0, 101.0, 102.0, 101.5, 103.0]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def single_bar_data():
    """单根bar"""
    return _make_df(["2024-01-02"], [100.0])


@pytest.fixture
def two_bar_data():
    """两根bar"""
    return _make_df(["2024-01-02", "2024-01-03"], [100.0, 101.0])


def make_crossover_data(fast_window: int, slow_window: int, n: int = 200,
                        seed: int = 0) -> pd.DataFrame:
    """构造必然产生金叉和死叉的数据

    先下跌让快线在慢线下方，再上涨让快线穿越慢线（金叉），
    再下跌让快线穿越回下方（死叉）。
    """
    np.random.seed(seed)
    half = n // 2
    # 下降段
    down = [100 - i * 0.3 for i in range(half)]
    # 上升段
    up = [down[-1] + i * 0.4 for i in range(n - half)]
    closes = down + up
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


def make_rsi_oversold_data(rsi_window: int = 14, n: int = 60) -> pd.DataFrame:
    """构造RSI进入超卖区再回升的数据"""
    # 先连续下跌让RSI低于30，再连续上涨让RSI回升
    down_len = rsi_window + 5
    up_len = n - down_len
    closes = [100 - i * 1.5 for i in range(down_len)] + \
             [100 - down_len * 1.5 + i * 2.0 for i in range(1, up_len + 1)]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


def make_bollinger_touch_lower_data(boll_window: int = 20, n: int = 60) -> pd.DataFrame:
    """构造价格触及布林下轨再回升的数据"""
    # 先稳定再急跌再回升
    stable = [100.0] * (boll_window + 5)
    drop = [100 - i * 3 for i in range(1, 6)]
    recover = [drop[-1] + i * 2 for i in range(1, n - len(stable) - len(drop) + 1)]
    closes = stable + drop + recover
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(len(closes))]
    return _make_df(dates, closes)


# ── vnpy BarData 转换 ──────────────────────────────────────────────────
# 回测引擎测试用：把 _make_df 产出的 DataFrame 转成 vnpy BarData 列表，
# 直接注入 engine.history_data，跳过 load_data()（零网络零真实行情）。

try:
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Exchange as VnpyExchange, Interval
    _VNPY_AVAILABLE = True
except ImportError:  # vnpy 未安装时，相关测试用 importorskip 自行跳过
    BarData = None
    VnpyExchange = None
    Interval = None
    _VNPY_AVAILABLE = False


def df_to_bars(df: pd.DataFrame, symbol: str = "600000",
               exchange=None, interval=None, pre_close_col=None) -> list:
    """把 _make_df 产出的 DataFrame 转成 BarData list

    Args:
        df: 含 date/open/high/low/close/volume/turnover 列的 DataFrame
        symbol: 证券代码，默认 600000
        exchange: vnpy Exchange，默认 Exchange.SSE
        interval: vnpy Interval，默认 Interval.DAILY
        pre_close_col: df 中昨收列名；设置后通过 setattr 写到 BarData.pre_close
                       动态属性，供适配器 _is_limit_up 的 getattr(bar,'pre_close',None) 读取。
                       （vnpy BarData 构造函数无 pre_close 字段，但 dataclass 允许动态属性。）
    """
    if not _VNPY_AVAILABLE:
        raise RuntimeError("vnpy 未安装，无法构造 BarData")
    if exchange is None:
        exchange = VnpyExchange.SSE
    if interval is None:
        interval = Interval.DAILY

    bars = []
    for _, row in df.iterrows():
        dt = row["date"]
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        kwargs = dict(
            symbol=symbol, exchange=exchange, datetime=dt, interval=interval,
            open_price=float(row["open"]), high_price=float(row["high"]),
            low_price=float(row["low"]), close_price=float(row["close"]),
            volume=float(row["volume"]), turnover=float(row.get("turnover", 0.0)),
            gateway_name="TEST",
        )
        pre_close = None
        if pre_close_col and pre_close_col in df.columns:
            pre_close = float(row[pre_close_col])
        bar = BarData(**kwargs)
        if pre_close is not None:
            bar.pre_close = pre_close  # 动态属性，供适配器 getattr(bar,'pre_close',None)
        bars.append(bar)
    return bars


def make_bar_with_pre_close(symbol, exchange, dt, open_price, high_price,
                            low_price, close_price, pre_close, volume=10000.0,
                            interval=None) -> "BarData":
    """构造单根带昨收的BarData（涨跌停测试用，精确控制pre_close）

    昨收通过 setattr 写到 BarData.pre_close 动态属性（vnpy BarData 构造函数无该字段，
    但 dataclass 允许动态属性，适配器 _is_limit_up 用 getattr 读取）。
    """
    if not _VNPY_AVAILABLE:
        raise RuntimeError("vnpy 未安装，无法构造 BarData")
    if interval is None:
        interval = Interval.DAILY
    bar = BarData(
        symbol=symbol, exchange=exchange, datetime=dt, interval=interval,
        open_price=open_price, high_price=high_price, low_price=low_price,
        close_price=close_price, volume=volume,
        turnover=0.0, gateway_name="TEST",
    )
    bar.pre_close = float(pre_close)
    return bar


def make_bar(symbol: str, exchange, dt, open_price: float, high_price: float,
             low_price: float, close_price: float, volume: float = 10000.0,
             interval=None) -> "BarData":
    """构造单根 BarData（撮合层单测用，精确控制 OHLC）"""
    if not _VNPY_AVAILABLE:
        raise RuntimeError("vnpy 未安装，无法构造 BarData")
    if interval is None:
        interval = Interval.DAILY
    return BarData(
        symbol=symbol, exchange=exchange, datetime=dt, interval=interval,
        open_price=open_price, high_price=high_price, low_price=low_price,
        close_price=close_price, volume=volume, turnover=0.0,
        gateway_name="TEST",
    )


# ── 实盘资金安全测试用工厂 ──────────────────────────────────────────────

def make_known_pnl_data(buy_price: float, sell_price: float, shares: int = 100,
                        hold_days: int = 5) -> pd.DataFrame:
    """构造已知盈亏的完整买卖配对序列

    行情：先平坦到buy_price，某日买入信号可触发（快线上穿），
    持仓hold_days后到sell_price触发卖出。供佣金精确对拍。
    简化：直接返回平坦+两段价格，由测试控制信号注入。
    """
    flat_len = 30
    pre = [buy_price] * flat_len
    hold = [buy_price] * hold_days
    post = [sell_price] * 20
    closes = pre + hold + post
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(len(closes))]
    return _make_df(dates, closes)


def make_limit_seq(scenario: str, base_price: float = 10.0) -> pd.DataFrame:
    """按场景构造精确涨跌停序列

    scenario:
        "limit_up_continuous": 连续涨停板（每日+10%）
        "one_word_limit_up": 一字涨停（开=收=涨停）
        "limit_down_with_position": 持仓中跌停（先平稳后跌停）
    """
    if scenario == "limit_up_continuous":
        n = 10
        closes = [base_price * (1.1 ** i) for i in range(n)]
        pre_closes = [base_price] + closes[:-1]
    elif scenario == "one_word_limit_up":
        n = 8
        closes = [base_price * (1.1 ** i) for i in range(n)]
        # 一字：open=high=low=close=涨停价
        opens = list(closes)
        highs = list(closes)
        lows = list(closes)
        pre_closes = [base_price] + closes[:-1]
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        df = _make_df(dates, closes, opens, highs, lows)
        df["pre_close"] = pre_closes
        return df
    elif scenario == "limit_down_with_position":
        n = 20
        closes = [base_price] * 15 + [base_price * 0.9] + [base_price * 0.9] * 4
        pre_closes = [base_price] + closes[:-1]
    else:
        raise ValueError(f"未知场景: {scenario}")
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(len(closes))]
    df = _make_df(dates, closes)
    df["pre_close"] = pre_closes
    return df


def load_real_bars(symbol: str, start: str, end: str, period: str = "1d"):
    """从 data_bridge 加载真实K线并转BarData，网络失败返回None供fixture skip

    Returns:
        (bars, df) 或 None
    """
    if not _VNPY_AVAILABLE:
        return None
    try:
        from app.core.data_bridge import data_bridge
        df = data_bridge.load_bars_df(symbol, start, end, period=period)
        if df is None or df.empty:
            return None
        bars = df_to_bars(df, symbol=symbol)
        return bars, df
    except Exception:
        return None