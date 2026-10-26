"""
实盘交易网关

按 TRADE_BACKEND 配置委托给对应后端：
- sim: 模拟成交（默认）
- stock_trade: stock_trade 微服务（fallback）
"""

import logging
from typing import Optional

from app.config import settings
from app.core.trade_backend import (
    TradeBackend, SimTradeBackend, StockTradeBackend,
)

logger = logging.getLogger(__name__)


def _create_trade_backend() -> TradeBackend:
    name = settings.TRADE_BACKEND.lower()
    if name == "stock_trade":
        return StockTradeBackend()
    if name != "sim":
        logger.warning(f"未知 TRADE_BACKEND '{name}'，回退到 sim")
    return SimTradeBackend()


class LiveGateway:
    """交易网关（委托给 TradeBackend）"""

    def __init__(self):
        self._backend: TradeBackend = _create_trade_backend()

    @property
    def is_connected(self) -> bool:
        return self._backend.is_connected

    @property
    def account_id(self) -> str:
        return getattr(self._backend, "_account_id", "")

    @property
    def base_url(self) -> str:
        return settings.STOCK_TRADE_URL

    def _set_disconnect_callback(self, callback) -> None:
        self._backend._on_disconnect_callback = callback

    async def auto_connect(self) -> dict:
        return await self._backend.auto_connect()

    async def auto_connect_background(self) -> None:
        await self._backend.auto_connect_background()

    async def check_health(self) -> dict:
        return await self._backend.check_health()

    async def get_account(self) -> dict:
        return await self._backend.get_account()

    async def get_positions(self) -> list:
        return await self._backend.get_positions()

    async def get_orders(self) -> list:
        return await self._backend.get_orders()

    async def get_trades(self) -> list:
        return await self._backend.get_trades()

    async def place_order(self, symbol, side, quantity, price=0,
                          order_type="limit") -> dict:
        return await self._backend.place_order(symbol, side, quantity, price, order_type)

    async def cancel_order(self, order_id: str) -> dict:
        return await self._backend.cancel_order(order_id)

    async def get_quote(self, symbol: str) -> dict:
        return await self._backend.get_quote(symbol)

    async def disconnect(self) -> None:
        await self._backend.disconnect()


# 全局单例
live_gateway = LiveGateway()
