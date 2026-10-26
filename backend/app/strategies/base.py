"""
策略基类与实现

每个策略同时支持：
- 回测模式：generate_signals() 批量向量化计算
- 实盘模式：on_bar() 增量逐K线计算（5秒一次）
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── 技术指标 ──────────────────────────────────────────────────────────────────

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()


def donchian(high: pd.Series, low: pd.Series, window: int):
    upper = high.rolling(window=window, min_periods=window).max()
    lower = low.rolling(window=window, min_periods=window).min()
    return upper, lower


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3):
    lowest_low = low.rolling(window=n, min_periods=n).min()
    highest_high = high.rolling(window=n, min_periods=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def cci(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    ma = tp.rolling(window=window, min_periods=window).mean()
    md = tp.rolling(window=window, min_periods=window).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - ma) / (0.015 * md)


# ── 策略基类 ──────────────────────────────────────────────────────────────────

class CtaStrategy:
    """策略基类，同时支持回测和实盘"""

    class_name: str = ""
    signal_period: str = "daily"
    # signal_period 说明：
    #   "daily"  - 日K线策略，信号基于日K线生成（如均线、MACD等）
    #   "5m"     - 5分钟K线策略
    #   "1m"     - 1分钟K线策略
    #   "tick"   - 逐笔策略，信号基于每个tick价格触发（如网格交易）

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        """回测用：一次性计算所有信号（向量化）

        Returns:
            Series: 1=买入, -1=卖出, 0=持有
        """
        raise NotImplementedError

    def __init__(self, setting: dict):
        self.setting = setting
        self._bars: list[dict] = []
        self._prev_signal: int = 0  # 上一根K线的信号状态，用于检测状态转换

    def on_bar(self, bar: dict) -> int:
        """实盘用：每收到一根新K线调用

        Args:
            bar: {"date": str, "open": float, "high": float, "low": float,
                  "close": float, "volume": float, "turnover": float}

        Returns:
            1=买入, -1=卖出, 0=持有
        """
        self._bars.append(bar)
        df = pd.DataFrame(self._bars)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], format="mixed")
        result = self.generate_signals(df, self.setting)
        signals = result[0] if isinstance(result, tuple) else result
        return int(signals.iloc[-1])

    def reset(self):
        """重置策略状态"""
        self._bars = []
        self._prev_signal = 0


# ── 策略实现 ──────────────────────────────────────────────────────────────────

class DoubleMaStrategy(CtaStrategy):
    class_name = "DoubleMaStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        fast_window = setting.get("fast_window", 10)
        slow_window = setting.get("slow_window", 20)
        fast_ma = sma(df["close"], fast_window)
        slow_ma = sma(df["close"], slow_window)
        cross_over = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        cross_below = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        signals[cross_over] = 1
        signals[cross_below] = -1
        return signals


class MacdStrategy(CtaStrategy):
    class_name = "MacdStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        fast_p = setting.get("fast_period", 12)
        slow_p = setting.get("slow_period", 26)
        signal_p = setting.get("signal_period", 9)
        dif, dea, hist = macd(df["close"], fast_p, slow_p, signal_p)
        cross_over = (dif > dea) & (dif.shift(1) <= dea.shift(1))
        cross_below = (dif < dea) & (dif.shift(1) >= dea.shift(1))
        signals[cross_over] = 1
        signals[cross_below] = -1
        return signals


class BollingerStrategy(CtaStrategy):
    class_name = "BollingerStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        boll_window = setting.get("boll_window", 20)
        boll_dev = setting.get("boll_dev", 2.0)
        mid, upper, lower = bollinger(df["close"], boll_window, boll_dev)
        # 状态转换：价格从下轨外穿入下轨内 → 买入，从上轨外穿入上轨内 → 卖出
        below_lower = df["close"] < lower
        above_upper = df["close"] > upper
        # 买入：前一天在下轨外，今天回到下轨内（触及或上穿下轨）
        touch_lower = below_lower.shift(1).fillna(False) & ~below_lower
        # 卖出：前一天在上轨外，今天回到上轨内（触及或下穿上轨）
        touch_upper = above_upper.shift(1).fillna(False) & ~above_upper
        signals[touch_lower] = 1
        signals[touch_upper] = -1
        return signals


class RsiStrategy(CtaStrategy):
    class_name = "RsiStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        rsi_window = setting.get("rsi_window", 14)
        rsi_overbought = setting.get("rsi_overbought", 70)
        rsi_oversold = setting.get("rsi_oversold", 30)
        rsi_val = rsi(df["close"], rsi_window)
        oversold_cross = (rsi_val > rsi_oversold) & (rsi_val.shift(1) <= rsi_oversold)
        overbought_cross = (rsi_val < rsi_overbought) & (rsi_val.shift(1) >= rsi_overbought)
        signals[oversold_cross] = 1
        signals[overbought_cross] = -1
        return signals


class TurtleStrategy(CtaStrategy):
    class_name = "TurtleStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        entry_window = setting.get("entry_window", 20)
        exit_window = setting.get("exit_window", 10)
        entry_up, entry_down = donchian(df["high"], df["low"], entry_window)
        exit_up, exit_down = donchian(df["high"], df["low"], exit_window)
        breakout_up = df["close"] > entry_up.shift(1)
        breakout_up = breakout_up & ~breakout_up.shift(1).fillna(False)
        breakout_down = df["close"] < exit_down.shift(1)
        breakout_down = breakout_down & ~breakout_down.shift(1).fillna(False)
        signals[breakout_up] = 1
        signals[breakout_down] = -1
        return signals


class KdjStrategy(CtaStrategy):
    class_name = "KdjStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        kdj_window = setting.get("kdj_window", 9)
        k_smooth = setting.get("k_smooth", 3)
        d_smooth = setting.get("d_smooth", 3)
        k, d, j = kdj(df["high"], df["low"], df["close"], kdj_window, k_smooth, d_smooth)
        # 买入：K线上穿D线，且发生在超卖区（K<30）
        cross_over = (k > d) & (k.shift(1) <= d.shift(1)) & (k < 30)
        # 卖出：K线下穿D线，且从超买区发生（前一根K值>70即可，不要求当前K值>70）
        cross_below = (k < d) & (k.shift(1) >= d.shift(1)) & (k.shift(1) > 70)
        signals[cross_over] = 1
        signals[cross_below] = -1
        return signals


class CciStrategy(CtaStrategy):
    class_name = "CciStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        cci_window = setting.get("cci_window", 14)
        cci_overbought = setting.get("cci_overbought", 100)
        cci_oversold = setting.get("cci_oversold", -100)
        cci_val = cci(df["high"], df["low"], df["close"], cci_window)
        oversold_cross = (cci_val > cci_oversold) & (cci_val.shift(1) <= cci_oversold)
        overbought_cross = (cci_val < cci_overbought) & (cci_val.shift(1) >= cci_overbought)
        signals[oversold_cross] = 1
        signals[overbought_cross] = -1
        return signals


class TripleMaStrategy(CtaStrategy):
    class_name = "TripleMaStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        fast_window = setting.get("fast_window", 5)
        mid_window = setting.get("mid_window", 20)
        slow_window = setting.get("slow_window", 60)
        fast_ma = sma(df["close"], fast_window)
        mid_ma = sma(df["close"], mid_window)
        slow_ma = sma(df["close"], slow_window)
        bull_align = (fast_ma > mid_ma) & (mid_ma > slow_ma)
        prev_bull = (fast_ma.shift(1) > mid_ma.shift(1)) & (mid_ma.shift(1) > slow_ma.shift(1))
        buy_signal = bull_align & ~prev_bull
        bear_align = (fast_ma < mid_ma) & (mid_ma < slow_ma)
        prev_bear = (fast_ma.shift(1) < mid_ma.shift(1)) & (mid_ma.shift(1) < slow_ma.shift(1))
        sell_signal = bear_align & ~prev_bear
        signals[buy_signal] = 1
        signals[sell_signal] = -1
        return signals


class EmaCrossStrategy(CtaStrategy):
    class_name = "EmaCrossStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        fast_window = setting.get("fast_window", 12)
        slow_window = setting.get("slow_window", 26)
        fast_ema = ema(df["close"], fast_window)
        slow_ema = ema(df["close"], slow_window)
        cross_over = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        cross_below = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))
        signals[cross_over] = 1
        signals[cross_below] = -1
        return signals


class VolumeMaStrategy(CtaStrategy):
    class_name = "VolumeMaStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        ma_window = setting.get("ma_window", 20)
        vol_window = setting.get("vol_window", 20)
        vol_ratio = setting.get("vol_ratio", 1.5)
        price_ma = sma(df["close"], ma_window)
        vol_ma = sma(df["volume"], vol_window)
        price_cross_up = (df["close"] > price_ma) & (df["close"].shift(1) <= price_ma.shift(1))
        vol_expand = df["volume"] > vol_ma * vol_ratio
        buy_signal = price_cross_up & vol_expand
        price_cross_down = (df["close"] < price_ma) & (df["close"].shift(1) >= price_ma.shift(1))
        signals[buy_signal] = 1
        signals[price_cross_down] = -1
        return signals


class MomentumStrategy(CtaStrategy):
    class_name = "MomentumStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        mom_window = setting.get("mom_window", 10)
        mom_threshold = setting.get("mom_threshold", 0.03)
        ma_window = setting.get("ma_window", 20)
        momentum = df["close"] / df["close"].shift(mom_window) - 1
        price_ma = sma(df["close"], ma_window)
        # 状态转换：动量从阈值下方穿越到上方 → 买入，从上方穿越到下方 → 卖出
        above_threshold = momentum > mom_threshold
        below_threshold = momentum < -mom_threshold
        # 买入：动量上穿阈值，且价格在均线之上（趋势确认）
        buy_signal = above_threshold & ~above_threshold.shift(1).fillna(False) & (df["close"] > price_ma)
        # 卖出：动量下穿负阈值
        sell_signal = below_threshold & ~below_threshold.shift(1).fillna(False)
        signals[buy_signal] = 1
        signals[sell_signal] = -1
        return signals


class AtrChannelStrategy(CtaStrategy):
    class_name = "AtrChannelStrategy"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        atr_window = setting.get("atr_window", 14)
        atr_mult = setting.get("atr_mult", 2.0)
        ma_window = setting.get("ma_window", 20)
        price_ma = sma(df["close"], ma_window)
        atr_val = atr(df["high"], df["low"], df["close"], atr_window)
        upper = price_ma + atr_mult * atr_val
        lower = price_ma - atr_mult * atr_val
        # 状态转换：价格从通道外回到通道内时产生信号
        above_upper = df["close"] > upper
        below_lower = df["close"] < lower
        # 买入：前一天在下轨外，今天回到通道内
        buy_signal = below_lower.shift(1).fillna(False) & ~below_lower
        # 卖出：前一天在上轨外，今天回到通道内
        sell_signal = above_upper.shift(1).fillna(False) & ~above_upper
        signals[buy_signal] = 1
        signals[sell_signal] = -1
        return signals


class DualThrustStrategy(CtaStrategy):
    class_name = "DualThrustStrategy"
    signal_period = "5m"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
        signals = pd.Series(0, index=df.index)
        n_window = setting.get("n_window", 4)
        k_up = setting.get("k_up", 0.5)
        k_down = setting.get("k_down", 0.5)
        hh = df["high"].rolling(window=n_window, min_periods=n_window).max()
        hc = df["close"].rolling(window=n_window, min_periods=n_window).max()
        lc = df["close"].rolling(window=n_window, min_periods=n_window).min()
        ll = df["low"].rolling(window=n_window, min_periods=n_window).min()
        range_val = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)
        upper_bound = df["close"].shift(1) + k_up * range_val.shift(1)
        lower_bound = df["close"].shift(1) - k_down * range_val.shift(1)
        # 状态转换：价格从带外回到带内时产生信号
        above_upper = df["close"] > upper_bound
        below_lower = df["close"] < lower_bound
        # 买入：前一天在下轨外，今天回到带内
        buy_signal = below_lower.shift(1).fillna(False) & ~below_lower
        # 卖出：前一天在上轨外，今天回到带内
        sell_signal = above_upper.shift(1).fillna(False) & ~above_upper
        signals[buy_signal] = 1
        signals[sell_signal] = -1
        return signals


class GridStrategy(CtaStrategy):
    """网格交易策略：基于网格层状态跟踪的配对交易

    每层网格维护 state[i]（EMPTY/HOLDING）：
    - 买入条件：state[i] == EMPTY 且 price_prev > grid_buy_price[i] 且 price_curr ≤ grid_buy_price[i]
    - 卖出条件：state[i] == HOLDING 且 price_prev < grid_sell_price[i] 且 price_curr ≥ grid_sell_price[i]
    - 跳空时批量处理所有被穿越的网格层
    - 初始持仓映射：将现有持仓分配到当前价格以下的网格层，从最接近当前价的层开始

    generate_signals() 返回 (signals, grid_states) 元组，其他策略只返回 signals。
    """
    class_name = "GridStrategy"
    signal_period = "5m"

    @classmethod
    def generate_signals(cls, df: pd.DataFrame, setting: dict) -> tuple[pd.Series, dict]:
        signals = pd.Series(0, index=df.index)
        grid_size = setting.get("grid_size") or setting.get("grid_step") or 0.02  # 网格间距，默认2%
        grid_qty = setting.get("grid_quantity") or setting.get("trading_volume") or 100  # 每层交易量
        initial_position = setting.get("initial_position", 0)  # 初始持仓数量

        if len(df) < 2:
            return signals, {}

        base_price = float(df.iloc[0]["close"])
        grid_step = base_price * grid_size  # 网格间距（绝对值）

        # 网格层状态跟踪：grid_level → state (0=EMPTY, 1=HOLDING)
        grid_states: dict[int, int] = {}
        for level in range(-20, 21):
            grid_states[level] = 0

        # 持仓映射：将 initial_position 分配到当前价格以下的网格层
        # 从最接近当前价的层（价格最高的买入层）开始，依次向低价层分配
        if initial_position > 0:
            qty_remaining = initial_position
            # 找出所有 grid_buy_price <= base_price 的层，按价格从高到低排序
            # level=0 的 buy_price = base_price，不满足 <=（等于）
            # level=-1 的 buy_price = base_price - grid_step，满足 <=
            # 从 level=-1 开始向下分配
            for level in range(-1, -21, -1):
                buy_price = base_price + level * grid_step
                if buy_price <= base_price and qty_remaining >= grid_qty:
                    grid_states[level] = 1  # EMPTY → HOLDING
                    qty_remaining -= grid_qty
                if qty_remaining < grid_qty:
                    break

        # 首次价格更新：price_prev = base_price，避免启动瞬间误触发
        prev_price = base_price

        for i in range(1, len(df)):
            curr_price = float(df.iloc[i]["close"])

            if curr_price < prev_price:
                # 价格下跌：检查所有 grid_buy_price 在 (curr_price, prev_price] 区间的层
                # 即 curr_price ≤ grid_buy_price[i] < prev_price
                buy_count = 0
                for level in range(-20, 21):
                    buy_price = base_price + level * grid_step
                    if curr_price <= buy_price < prev_price and grid_states.get(level, 0) == 0:
                        grid_states[level] = 1  # EMPTY → HOLDING
                        buy_count += 1
                if buy_count > 0:
                    signals.iloc[i] = buy_count  # 买入信号（值=穿越层数）

            elif curr_price > prev_price:
                # 价格上涨：检查所有 grid_sell_price 在 [prev_price, curr_price) 区间的层
                # 即 prev_price < grid_sell_price[i] ≤ curr_price
                # grid_sell_price[i] = grid_buy_price[i] + grid_step = base_price + (level+1) * grid_step
                sell_count = 0
                for level in range(-20, 21):
                    sell_price = base_price + (level + 1) * grid_step
                    if prev_price < sell_price <= curr_price and grid_states.get(level, 0) == 1:
                        grid_states[level] = 0  # HOLDING → EMPTY
                        sell_count += 1
                if sell_count > 0:
                    signals.iloc[i] = -sell_count  # 卖出信号（值=穿越层数的负数）

            prev_price = curr_price

        return signals, grid_states


# ── 策略映射 ──────────────────────────────────────────────────────────────────

STRATEGY_MAP: dict[str, type[CtaStrategy]] = {
    cls.class_name: cls
    for cls in [
        DoubleMaStrategy,
        MacdStrategy,
        BollingerStrategy,
        RsiStrategy,
        TurtleStrategy,
        KdjStrategy,
        CciStrategy,
        TripleMaStrategy,
        EmaCrossStrategy,
        VolumeMaStrategy,
        MomentumStrategy,
        AtrChannelStrategy,
        DualThrustStrategy,
        GridStrategy,
    ]
}


def get_signal_period(class_name: str) -> str:
    """获取策略的信号周期"""
    strategy_cls = STRATEGY_MAP.get(class_name)
    if strategy_cls:
        return strategy_cls.signal_period
    return "daily"


def generate_signals(class_name: str, df: pd.DataFrame, setting: dict) -> pd.Series:
    """根据策略类名生成交易信号（兼容旧接口）"""
    strategy_cls = STRATEGY_MAP.get(class_name)
    if strategy_cls:
        result = strategy_cls.generate_signals(df, setting)
        # GridStrategy 返回 (signals, grid_states) 元组
        if isinstance(result, tuple):
            return result[0]
        return result

    # 未知策略，使用双均线默认
    logger.warning(f"未知策略类 {class_name}，使用双均线策略")
    return DoubleMaStrategy.generate_signals(df, {"fast_window": 10, "slow_window": 20})
