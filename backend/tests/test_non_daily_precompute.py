"""
非日线预计算分支测试

interval != DAILY 时，run_backtesting 走两条分支：
- _precompute_with_daily_signals：日K线算信号，映射到分钟K线（每日首根保留信号）
- _precompute_with_intraday_detection（布林带/ATR）：日K线算指标，分钟K线检测触轨回归

两条分支内部都调 data_bridge.load_bars(interval=DAILY) 取日K → 用 monkeypatch mock。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
import numpy as np
from vnpy.trader.constant import Exchange, Interval

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.services import vnpy_backtest_service as vbs_mod
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars, make_bar

VTSYM = "600000.SSE"


def _minute_df_from_daily(daily_df, bars_per_day=4):
    """把日K展开成分钟K（每日 bars_per_day 根，close 在日内线性插值）"""
    rows = []
    for _, d in daily_df.iterrows():
        base_close = float(d["close"])
        for k in range(bars_per_day):
            # 日内小幅波动
            close = base_close * (1 + (k - bars_per_day / 2) * 0.001)
            dt = d["date"].to_pydatetime() + timedelta(minutes=10 * (k + 1))
            rows.append({
                "date": dt,
                "open": close, "high": close * 1.001, "low": close * 0.999,
                "close": close, "volume": 1000.0, "turnover": close * 1000,
            })
    return pd_df_from_rows(rows)


def pd_df_from_rows(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _make_engine(strategy_name, setting, interval):
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=interval,
        start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=1_000_000.0,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP[strategy_name], setting)
    return engine


def _inject_minute_bars(engine, minute_df):
    bars = []
    for _, row in minute_df.iterrows():
        bar = make_bar(
            "600000", Exchange.SSE, row["date"].to_pydatetime(),
            float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
            volume=float(row["volume"]), interval=Interval.MINUTE,
        )
        bars.append(bar)
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    engine.strategy.on_init()
    return bars


def _make_fake_load_bars(daily_bars):
    """构造 mock：interval=DAILY 返回日K，其他返回空（分钟数据已注入 history_data）"""
    def fake_load_bars(symbol, exchange, interval, start, end, data_source=None):
        if interval == Interval.DAILY:
            return daily_bars
        return []
    return fake_load_bars


class TestDailySignalsMapping:
    """_precompute_with_daily_signals：每日首根分钟bar保留信号，其余0"""

    def test_signal_only_on_first_bar_of_day(self, monkeypatch):
        # 日K：完整周期，产生金叉死叉
        np.random.seed(0)
        n = 80
        down = [100 - i * 0.3 for i in range(40)]
        up = [down[-1] + i * 0.4 for i in range(40)]
        closes = down + up
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        daily_df = _make_df(dates, closes)
        daily_bars = df_to_bars(daily_df, symbol="600000", exchange=Exchange.SSE,
                                interval=Interval.DAILY)

        minute_df = _minute_df_from_daily(daily_df, bars_per_day=4)

        engine = _make_engine("DoubleMaStrategy", {"fast_window": 5, "slow_window": 20},
                              Interval.MINUTE)
        monkeypatch.setattr(vbs_mod.data_bridge, "load_bars",
                            _make_fake_load_bars(daily_bars))
        _inject_minute_bars(engine, minute_df)

        engine.run_backtesting()
        stats = engine.calculate_result()

        sigs = engine.strategy._precomputed_signals
        assert sigs is not None
        assert len(sigs) == len(minute_df)
        # 每日 4 根：非零信号只应出现在每日第 1 根
        for i, s in enumerate(sigs):
            if i % 4 != 0:
                assert s == 0, f"非首根bar出现信号: idx={i} sig={s}"

    def test_backtest_runs_and_verifies(self, monkeypatch):
        np.random.seed(1)
        n = 120
        down = [100 - i * 0.3 for i in range(40)]
        up = [down[-1] + i * 0.4 for i in range(40)]
        down2 = [up[-1] - i * 0.5 for i in range(40)]
        closes = down + up + down2
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        daily_df = _make_df(dates, closes)
        daily_bars = df_to_bars(daily_df, exchange=Exchange.SSE, interval=Interval.DAILY)
        minute_df = _minute_df_from_daily(daily_df, bars_per_day=4)

        engine = _make_engine("DoubleMaStrategy", {"fast_window": 5, "slow_window": 20},
                              Interval.MINUTE)
        monkeypatch.setattr(vbs_mod.data_bridge, "load_bars",
                            _make_fake_load_bars(daily_bars))
        _inject_minute_bars(engine, minute_df)
        engine.run_backtesting()
        stats = engine.calculate_result()
        if stats and stats.get("total_trades", 0) > 0:
            v = stats["verification"]
            # 前4项必须通过
            for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
                assert v[key]["passed"] is True, f"{key}: {v[key]}"


class TestIntradayDetection:
    """_precompute_with_intraday_detection：布林带，信号长度 == 分钟bar数"""

    def test_signal_length_matches_minute_bars(self, monkeypatch):
        n = 80
        closes = [100.0] * 25 + [100 - i * 3 for i in range(1, 6)] + \
                 [85 + i * 2 for i in range(1, n - 25 - 5 + 1)]
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        daily_df = _make_df(dates, closes)
        daily_bars = df_to_bars(daily_df, exchange=Exchange.SSE, interval=Interval.DAILY)
        minute_df = _minute_df_from_daily(daily_df, bars_per_day=4)

        engine = _make_engine("BollingerStrategy",
                              {"boll_window": 20, "boll_dev": 2.0}, Interval.MINUTE)
        monkeypatch.setattr(vbs_mod.data_bridge, "load_bars",
                            _make_fake_load_bars(daily_bars))
        _inject_minute_bars(engine, minute_df)
        engine.run_backtesting()

        sigs = engine.strategy._precomputed_signals
        assert sigs is not None
        assert len(sigs) == len(minute_df), (
            f"信号长度 {len(sigs)} != 分钟bar数 {len(minute_df)}"
        )
