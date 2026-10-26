"""
行情数据服务

按 MARKET_BACKEND 配置委托给对应后端：
- akshare: 公开 HTTP 轮询（默认）
- stock_data: stock_data 微服务（fallback）
"""

import logging
from typing import Optional

import pandas as pd

from app.config import settings
from app.core.market_backend import (
    MarketBackend, AkshareMarketBackend, StockDataMarketBackend,
)

logger = logging.getLogger(__name__)


def _create_market_backend() -> MarketBackend:
    """根据配置创建行情后端，未知值 fallback 到 akshare"""
    name = settings.MARKET_BACKEND.lower()
    if name == "stock_data":
        return StockDataMarketBackend()
    if name != "akshare":
        logger.warning(f"未知 MARKET_BACKEND '{name}'，回退到 akshare")
    return AkshareMarketBackend()


class MarketService:
    """行情数据服务（委托给 MarketBackend）"""

    def __init__(self):
        self._backend: MarketBackend = _create_market_backend()

    def is_available(self) -> bool:
        return self._backend.is_available()

    def check_health(self) -> dict:
        return self._backend.check_health()

    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame:
        return self._backend.get_klines(symbol, period, start_time, end_time,
                                        count, dividend_type)

    def get_full_tick(self, symbol: str) -> Optional[dict]:
        return self._backend.get_full_tick(symbol)

    def get_stock_list(self, sector: str = '沪深A股') -> list[str]:
        return self._backend.get_stock_list(sector)

    def get_stock_list_full(self, sector: str = '沪深A股') -> list[dict]:
        return self._backend.get_stock_list_full(sector)

    def get_instrument_detail(self, symbol: str) -> Optional[dict]:
        return self._backend.get_instrument_detail(symbol)

    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]:
        return self._backend.get_instruments_batch(symbols)

    def subscribe_quote(self, symbol, period='tick', callback=None) -> Optional[int]:
        return self._backend.subscribe_quote(symbol, period, callback)

    def unsubscribe_quote(self, seq: int) -> bool:
        return self._backend.unsubscribe_quote(seq)

    def close(self) -> None:
        self._backend.close()


# 全局单例
market_service = MarketService()
