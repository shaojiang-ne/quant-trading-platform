"""
国金证券 QMT 券商网关

封装 LiveGateway（HTTP 客户端与 stock_trade 微服务通信），
实现 BrokerProvider 接口。
"""

import logging

from app.core.broker_provider import (
    BrokerProvider, BrokerAccount, BrokerPosition,
    BrokerOrder, BrokerTrade, BrokerConnectResult,
)
from app.core.live_gateway import live_gateway

logger = logging.getLogger(__name__)


class QMTBrokerProvider(BrokerProvider):
    """国金证券 QMT 券商网关 — 通过 stock_trade 微服务"""

    def __init__(self):
        self._gw = live_gateway

    async def connect(self, **kwargs) -> BrokerConnectResult:
        result = await self._gw.auto_connect()
        return BrokerConnectResult(
            success=result.get("success", False),
            message=result.get("message", ""),
            account_id=result.get("account_id", ""),
        )

    async def disconnect(self) -> None:
        await self._gw.disconnect()

    def is_connected(self) -> bool:
        return self._gw.is_connected

    @property
    def account_id(self) -> str:
        return self._gw.account_id

    async def get_account(self) -> BrokerAccount:
        data = await self._gw.get_account()
        return BrokerAccount(
            account_id=data.get("account_id", ""),
            total_assets=float(data.get("total_assets", 0)),
            cash=float(data.get("cash", 0)),
            available=float(data.get("available", 0)),
            market_value=float(data.get("market_value", 0)),
            frozen_cash=float(data.get("frozen", 0)),
        )

    async def get_positions(self) -> list[BrokerPosition]:
        data = await self._gw.get_positions()
        positions = data if isinstance(data, list) else data.get("positions", [])
        result = []
        for p in positions:
            result.append(BrokerPosition(
                symbol=p.get("symbol", ""),
                name=p.get("name", ""),
                volume=int(p.get("quantity", p.get("volume", 0))),
                available=int(p.get("available", p.get("can_use_volume", 0))),
                cost_price=float(p.get("avg_cost", p.get("cost_price", 0))),
                current_price=float(p.get("current_price", p.get("last_price", 0))),
                market_value=float(p.get("market_value", 0)),
                profit_loss=float(p.get("profit", 0)),
                profit_rate=float(p.get("profit_rate", 0)),
                daily_profit=float(p.get("daily_profit", 0)),
            ))
        return result

    async def get_orders(self) -> list[BrokerOrder]:
        data = await self._gw.get_orders()
        orders = data if isinstance(data, list) else data.get("orders", [])
        result = []
        for o in orders:
            result.append(BrokerOrder(
                order_id=str(o.get("order_id", "")),
                symbol=o.get("symbol", ""),
                name=o.get("name", ""),
                direction=o.get("side", ""),
                price=float(o.get("price", 0)),
                volume=int(o.get("quantity", o.get("order_volume", 0))),
                filled_volume=int(o.get("filled_quantity", o.get("traded_volume", 0))),
                filled_price=float(o.get("filled_price", o.get("traded_price", 0))),
                status=o.get("status", ""),
                order_type=o.get("order_type", "limit"),
                order_time=o.get("create_time", o.get("order_time", "")),
            ))
        return result

    async def get_trades(self) -> list[BrokerTrade]:
        data = await self._gw.get_trades()
        trades = data if isinstance(data, list) else data.get("trades", [])
        result = []
        for t in trades:
            result.append(BrokerTrade(
                trade_id=str(t.get("trade_id", t.get("traded_id", ""))),
                order_id=str(t.get("order_id", "")),
                symbol=t.get("symbol", t.get("stock_code", "")),
                name=t.get("name", ""),
                direction=t.get("side", ""),
                price=float(t.get("price", t.get("traded_price", 0))),
                volume=int(t.get("quantity", t.get("traded_volume", 0))),
                trade_time=t.get("time", t.get("traded_time", "")),
            ))
        return result

    async def place_order(
        self, symbol: str, direction: str, price: float,
        volume: int, order_type: str = "limit",
    ) -> dict:
        result = await self._gw.place_order(
            symbol=symbol, side=direction,
            quantity=volume, price=price, order_type=order_type,
        )
        return {
            "order_id": str(result.get("order_id", "")),
            "status": result.get("status", "pending"),
            "message": result.get("message", ""),
        }

    async def cancel_order(self, order_id: str) -> dict:
        result = await self._gw.cancel_order(order_id)
        return {
            "order_id": str(result.get("order_id", order_id)),
            "status": result.get("status", "cancelled"),
            "message": result.get("message", ""),
        }

    async def get_quote(self, symbol: str) -> dict:
        return await self._gw.get_quote(symbol)

    async def check_health(self) -> dict:
        return await self._gw.check_health()

    def get_name(self) -> str:
        return "qmt"

    def get_display_name(self) -> str:
        return "国金证券(QMT)"

    def is_available(self) -> bool:
        return bool(self._gw._base_url)
