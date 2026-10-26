"""
国泰君安 tquant2 券商网关

通过国泰君安官方 tquant2 SDK 接入，实现 BrokerProvider 接口。
需要安装 tquant2: pip install tquant2
国泰君安用户需在国君君弘开通量化交易权限。
"""

import asyncio
import logging

from app.core.broker_provider import (
    BrokerProvider, BrokerAccount, BrokerPosition,
    BrokerOrder, BrokerTrade, BrokerConnectResult,
)

logger = logging.getLogger(__name__)


class GTJABrokerProvider(BrokerProvider):
    """国泰君安 tquant2 券商网关"""

    def __init__(self):
        self._api = None
        self._connected = False
        self._account_id = ""

    async def connect(self, **kwargs) -> BrokerConnectResult:
        userid = kwargs.get("userid", "")
        password = kwargs.get("password", "")
        td_address = kwargs.get("td_address", "")

        if not userid or not password:
            return BrokerConnectResult(
                success=False,
                message="缺少国泰君安连接参数 (userid/password)",
            )

        try:
            from tquant import TQuantApi

            def _do_connect():
                api = TQuantApi()
                api.login(userid, password, td_address=td_address)
                return api

            self._api = await asyncio.get_event_loop().run_in_executor(
                None, _do_connect,
            )
            self._connected = True
            self._account_id = userid
            return BrokerConnectResult(
                success=True,
                message="国泰君安 tquant2 连接成功",
                account_id=userid,
            )
        except ImportError:
            return BrokerConnectResult(
                success=False,
                message="tquant2 未安装，请运行: pip install tquant2",
            )
        except Exception as e:
            logger.error(f"国泰君安连接失败: {e}")
            return BrokerConnectResult(success=False, message=str(e))

    async def disconnect(self) -> None:
        if self._api:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._api.logout(),
                )
            except Exception as e:
                logger.error(f"国泰君安断开连接失败: {e}")
        self._connected = False
        self._api = None

    def is_connected(self) -> bool:
        return self._connected and self._api is not None

    @property
    def account_id(self) -> str:
        return self._account_id

    async def get_account(self) -> BrokerAccount:
        if not self._api:
            return BrokerAccount(account_id=self._account_id)

        def _query():
            return self._api.get_account()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            return BrokerAccount(
                account_id=self._account_id,
                total_assets=float(data.get("total_asset", 0)),
                cash=float(data.get("cash", 0)),
                available=float(data.get("available", data.get("cash", 0))),
                market_value=float(data.get("market_value", 0)),
                frozen_cash=float(data.get("frozen_cash", 0)),
            )
        except Exception as e:
            logger.error(f"国泰君安获取账户失败: {e}")
            return BrokerAccount(account_id=self._account_id)

    async def get_positions(self) -> list[BrokerPosition]:
        if not self._api:
            return []

        def _query():
            return self._api.get_positions()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            positions = data if isinstance(data, list) else []
            result = []
            for p in positions:
                result.append(BrokerPosition(
                    symbol=p.get("symbol", ""),
                    name=p.get("name", ""),
                    volume=int(p.get("volume", 0)),
                    available=int(p.get("available", 0)),
                    cost_price=float(p.get("cost_price", 0)),
                    current_price=float(p.get("current_price", 0)),
                    market_value=float(p.get("market_value", 0)),
                    profit_loss=float(p.get("profit", 0)),
                    profit_rate=float(p.get("profit_rate", 0)),
                ))
            return result
        except Exception as e:
            logger.error(f"国泰君安获取持仓失败: {e}")
            return []

    async def get_orders(self) -> list[BrokerOrder]:
        if not self._api:
            return []

        def _query():
            return self._api.get_orders()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            orders = data if isinstance(data, list) else []
            result = []
            for o in orders:
                result.append(BrokerOrder(
                    order_id=str(o.get("order_id", "")),
                    symbol=o.get("symbol", ""),
                    name=o.get("name", ""),
                    direction=o.get("direction", ""),
                    price=float(o.get("price", 0)),
                    volume=int(o.get("volume", 0)),
                    filled_volume=int(o.get("filled_volume", 0)),
                    filled_price=float(o.get("filled_price", 0)),
                    status=o.get("status", ""),
                    order_type=o.get("order_type", "limit"),
                    order_time=o.get("order_time", ""),
                ))
            return result
        except Exception as e:
            logger.error(f"国泰君安获取委托失败: {e}")
            return []

    async def get_trades(self) -> list[BrokerTrade]:
        if not self._api:
            return []

        def _query():
            return self._api.get_trades()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            trades = data if isinstance(data, list) else []
            result = []
            for t in trades:
                result.append(BrokerTrade(
                    trade_id=str(t.get("trade_id", "")),
                    order_id=str(t.get("order_id", "")),
                    symbol=t.get("symbol", ""),
                    name=t.get("name", ""),
                    direction=t.get("direction", ""),
                    price=float(t.get("price", 0)),
                    volume=int(t.get("volume", 0)),
                    trade_time=t.get("trade_time", ""),
                ))
            return result
        except Exception as e:
            logger.error(f"国泰君安获取成交失败: {e}")
            return []

    async def place_order(
        self, symbol: str, direction: str, price: float,
        volume: int, order_type: str = "limit",
    ) -> dict:
        if not self._api:
            return {"order_id": "", "status": "failed", "message": "未连接"}

        def _place():
            return self._api.place_order(
                symbol=symbol, direction=direction,
                price=price, volume=volume, order_type=order_type,
            )

        try:
            result = await asyncio.get_event_loop().run_in_executor(None, _place)
            return {
                "order_id": str(result.get("order_id", "")) if result else "",
                "status": result.get("status", "pending") if result else "failed",
                "message": result.get("message", "") if result else "下单失败",
            }
        except Exception as e:
            logger.error(f"国泰君安下单失败: {e}")
            return {"order_id": "", "status": "failed", "message": str(e)}

    async def cancel_order(self, order_id: str) -> dict:
        if not self._api:
            return {"order_id": order_id, "status": "failed", "message": "未连接"}

        def _cancel():
            return self._api.cancel_order(order_id)

        try:
            result = await asyncio.get_event_loop().run_in_executor(None, _cancel)
            return {
                "order_id": order_id,
                "status": "cancelled" if result else "failed",
                "message": "" if result else "撤单失败",
            }
        except Exception as e:
            logger.error(f"国泰君安撤单失败: {e}")
            return {"order_id": order_id, "status": "failed", "message": str(e)}

    def get_name(self) -> str:
        return "gtja"

    def get_display_name(self) -> str:
        return "国泰君安(tquant2)"

    def is_available(self) -> bool:
        try:
            import tquant  # noqa: F401
            return True
        except ImportError:
            return False