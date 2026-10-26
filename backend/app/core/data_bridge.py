"""
stock_data → vnpy 数据桥接

将行情数据转换为 vnpy BarData 列表，供 vnpy 回测引擎使用。
同时保留 DataFrame 接口供策略 generate_signals() 使用。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

try:
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Exchange, Interval
    VNPY_AVAILABLE = True
except ImportError:
    VNPY_AVAILABLE = False
    BarData = None

    class _StubEnum:
        def __init__(self, *_, **__):
            pass
        def __getattr__(self, name):
            return name
    Exchange = _StubEnum()
    Interval = _StubEnum()

from app.core.data_source import DataSourceProvider
from app.core.data_source_akshare import AkshareDataSource
from app.core.data_source_baostock import BaostockDataSource
from app.core.data_source_xtquant import XtquantDataSource
from app.core.data_source_efinance import EfinanceDataSource
from app.core.data_source_sina import SinaDataSource
from app.core.data_source_tencent import TencentDataSource
from app.core.data_source_mootdx import MootdxDataSource
from app.core.data_source_fallback import FallbackDataSource

logger = logging.getLogger(__name__)


# ── 数据源工厂 ──────────────────────────────────────────────────────────────

_DATA_SOURCES: dict[str, type[DataSourceProvider]] = {
    "mootdx": MootdxDataSource,
    "akshare": AkshareDataSource,
    "efinance": EfinanceDataSource,
    "baostock": BaostockDataSource,
    "sina": SinaDataSource,
    "tencent": TencentDataSource,
    "xtquant": XtquantDataSource,
}

_source_cache: dict[str, DataSourceProvider] = {}


def _create_auto_source() -> FallbackDataSource:
    """创建分级降级复合数据源"""
    from app.core.data_source_mootdx import MootdxDataSource
    from app.core.data_source_tencent import TencentDataSource
    from app.core.data_source_baostock import BaostockDataSource
    from app.core.data_source_sina import SinaDataSource
    from app.core.data_source_akshare import AkshareDataSource
    from app.core.data_source_xtquant import XtquantDataSource
    from app.core.data_source_fallback import FallbackDataSource

    sources = {
        "mootdx": MootdxDataSource(),
        "tencent": TencentDataSource(),
        "baostock": BaostockDataSource(),
        "sina": SinaDataSource(),
        "akshare": AkshareDataSource(),
        "xtquant": XtquantDataSource(),
    }
    return FallbackDataSource(sources)


def get_data_source(name: str | None = None) -> DataSourceProvider:
    """获取数据源实例（带缓存）"""
    if name is None:
        from app.config import settings
        name = settings.DATA_SOURCE

    name = name.lower()

    # auto 数据源使用专用工厂
    if name == "auto":
        if "auto" not in _source_cache:
            _source_cache["auto"] = _create_auto_source()
        return _source_cache["auto"]

    if name not in _DATA_SOURCES:
        logger.warning(f"未知数据源 '{name}'，回退到 akshare")
        name = "akshare"

    if name not in _source_cache:
        _source_cache[name] = _DATA_SOURCES[name]()

    return _source_cache[name]


def get_available_sources() -> list[dict]:
    """返回可用的数据源列表"""
    result = []
    for name, cls in _DATA_SOURCES.items():
        source = get_data_source(name)
        result.append({
            "name": name,
            "available": source.is_available(),
        })
    return result


# ── 工具方法（保持原有接口不变）──────────────────────────────────────────────

class XtquantDataBridge:
    """stock_data → vnpy BarData 数据桥接"""

    # vnpy Interval → stock_data period
    INTERVAL_MAP = {
        Interval.MINUTE: "1m",
        Interval.DAILY: "1d",
        Interval.WEEKLY: "1w",
    } if VNPY_AVAILABLE else {}

    # 自定义周期映射（5m, 15m, 30m, 1h）
    CUSTOM_PERIOD_MAP = {
        "1m": Interval.MINUTE,
        "5m": Interval.MINUTE,
        "15m": Interval.MINUTE,
        "30m": Interval.MINUTE,
        "1h": Interval.MINUTE,
        "daily": Interval.DAILY,
        "weekly": Interval.WEEKLY,
    } if VNPY_AVAILABLE else {}

    @staticmethod
    def to_xt_symbol(symbol: str) -> str:
        """6位代码 → stock_data 格式 (600519.SH / 000001.SZ)

        支持以下输入格式：
        - 纯代码: "600519" → "600519.SH"
        - 带后缀: "000300.SH" → "000300.SH"（保留原后缀）
        - 带点号: "600519.SZ" → "600519.SZ"
        """
        code = symbol.strip().upper()
        for suffix in (".SH", ".SZ", ".BJ"):
            if code.endswith(suffix):
                return code
        for prefix in ("SH", "SZ", "BJ"):
            if code.startswith(prefix):
                code = code[len(prefix):]
                break
        code = code.strip(".")
        if code.startswith("6") or code.startswith("9"):
            return f"{code}.SH"
        return f"{code}.SZ"

    @staticmethod
    def to_exchange(symbol: str) -> Exchange:
        """6位代码 → vnpy Exchange"""
        code = symbol.strip().upper()
        for prefix in ("SH", "SZ", "BJ"):
            if code.startswith(prefix):
                code = code[len(prefix):]
                break
        code = code.strip(".")
        if code.startswith("6") or code.startswith("9"):
            return Exchange.SSE
        if code.startswith("8") or code.startswith("4"):
            return Exchange.BSE
        return Exchange.SZSE

    @staticmethod
    def to_vt_symbol(symbol: str) -> str:
        """6位代码 → vnpy vt_symbol (600519.SSE)"""
        code = symbol.strip().upper()
        for prefix in ("SH", "SZ", "BJ"):
            if code.startswith(prefix):
                code = code[len(prefix):]
                break
        code = code.strip(".")
        exchange = XtquantDataBridge.to_exchange(code)
        return f"{code}.{exchange.value}"

    def load_bars(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime,
        data_source: str | None = None,
    ) -> list[BarData]:
        """从数据源获取 K 线数据，转换为 vnpy BarData 列表"""
        source = get_data_source(data_source)
        xt_symbol = self.to_xt_symbol(symbol)

        period_map = {
            Interval.MINUTE: "1m",
            Interval.DAILY: "1d",
            Interval.WEEKLY: "1w",
        }
        period = period_map.get(interval, "1d")

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        df = source.get_klines(
            symbol=xt_symbol,
            period=period,
            start=start_str,
            end=end_str,
            dividend_type="front",
        )

        if df.empty:
            logger.warning(f"无数据: {xt_symbol} {period} {start_str}-{end_str}")
            return []

        bars = []
        for _, row in df.iterrows():
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=row["date"].to_pydatetime() if isinstance(row["date"], pd.Timestamp) else row["date"],
                interval=interval,
                volume=float(row["volume"]),
                turnover=float(row.get("amount", 0)),
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                gateway_name=source.get_name().upper(),
            )
            bars.append(bar)

        logger.info(f"数据桥接: {xt_symbol} 加载 {len(bars)} 根 {period} K线 (source={source.get_name()})")
        return bars

    def load_bars_df(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        period: str = "daily",
        data_source: str | None = None,
    ) -> pd.DataFrame:
        """保留现有 fetch_bar_data 接口，供策略 generate_signals() 使用"""
        source = get_data_source(data_source)
        xt_symbol = self.to_xt_symbol(symbol)

        period_map = {"daily": "1d", "weekly": "1w", "monthly": "1d",
                      "tick": "1m", "1m": "1m", "5m": "5m"}
        mapped_period = period_map.get(period, period)

        df = source.get_klines(
            symbol=xt_symbol,
            period=mapped_period,
            start=start_date,
            end=end_date,
            dividend_type="front",
        )

        if df.empty:
            return pd.DataFrame()

        result = pd.DataFrame({
            "date": df["date"],
            "open": df["open"].values.astype(float),
            "high": df["high"].values.astype(float),
            "low": df["low"].values.astype(float),
            "close": df["close"].values.astype(float),
            "volume": df["volume"].values.astype(float),
            "turnover": df["amount"].values.astype(float),
        })
        return result.sort_values("date").reset_index(drop=True)[
            ["date", "open", "high", "low", "close", "volume", "turnover"]
        ]


# 全局单例
data_bridge = XtquantDataBridge()