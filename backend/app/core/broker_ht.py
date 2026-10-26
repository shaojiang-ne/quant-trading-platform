"""
华泰证券 htquant 券商网关

通过华泰证券官方 htquant SDK 接入，实现 BrokerProvider 接口。
需要安装 htquant: pip install htquant
华泰证券用户需开通量化交易权限。
"""

import asyncio
import logging
from typing import Optional

from app.core.broker_provider import (
    BrokerProvider, BrokerAccount, BrokerPosition,
    BrokerOrder, BrokerTrade, BrokerConnectResult,
)

logger = logging.getLogger(__name__)


class HTBrokerProvider(BrokerProvider):
    """华泰证券 htquant 券商网关"""

    def __init__(self):
        self._trader = None
        self._connected = False
        self._account_id = ""

    async def connect(self, **kwargs) -> BrokerConnectResult:
        userid = kwargs.get("userid", "")
        password = kwargs.get("password", "")

        if not userid or not password:
            return BrokerConnectResult(
                success=False,
                message="缺少华泰证券连接参数 (userid/password)",
            )

        try:
            from htquant.ht_trader import HTTrader

            def _do_connect():
                trader = HTTrader()
                trader.login(userid, password)
                return trader

            self._trader = await asyncio.get_event_loop().run_in_executor(
                None, _do_connect,
            )
            self._connected = True
            self._account_id = userid
            return BrokerConnectResult(
                success=True,
                message="华泰证券 htquant 连接成功",
                account_id=userid,
            )
        except ImportError:
            return BrokerConnectResult(
                success=False,
                message="htquant 未安装，请运行: pip install htquant",
            )
        except Exception as e:
            logger.error(f"华泰证券连接失败: {e}")
            return BrokerConnectResult(success=False, message=str(e))

    async def disconnect(self) -> None:
        if self._trader:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._trader.logout(),
                )
            except Exception as e:
                logger.error(f"华泰证券断开连接失败: {e}")
        self._connected = False
        self._trader = None

    def is_connected(self) -> bool:
        return self._connected and self._trader is not None

    @property
    def account_id(self) -> str:
        return self._account_id

    async def get_account(self) -> BrokerAccount:
        if not self._trader:
            return BrokerAccount(account_id=self._account_id)

        def _query():
            return self._trader.get_account()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            return BrokerAccount(
                account_id=self._account_id,
                total_assets=float(data.get("total_asset", data.get("总资产", 0))),
                cash=float(data.get("cash", data.get("可用资金", 0))),
                available=float(data.get("cash", data.get("可用资金", 0))),
                market_value=float(data.get("market_value", data.get("证券市值", 0))),
                frozen_cash=float(data.get("frozen_cash", data.get("冻结资金", 0))),
            )
        except Exception as e:
            logger.error(f"华泰证券获取账户失败: {e}")
            return BrokerAccount(account_id=self._account_id)

    async def get_positions(self) -> list[BrokerPosition]:
        if not self._trader:
            return []

        def _query():
            return self._trader.get_positions()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            positions = data if isinstance(data, list) else []
            result = []
            for p in positions:
                result.append(BrokerPosition(
                    symbol=p.get("symbol", p.get("证券代码", "")),
                    name=p.get("name", p.get("证券名称", "")),
                    volume=int(p.get("volume", p.get("持仓数量", 0))),
                    available=int(p.get("available", p.get("可用数量", 0))),
                    cost_price=float(p.get("cost_price", p.get("成本价", 0))),
                    current_price=float(p.get("current_price", p.get("最新价", 0))),
                    market_value=float(p.get("market_value", p.get("市值", 0))),
                    profit_loss=float(p.get("profit", p.get("盈亏", 0))),
                    profit_rate=float(p.get("profit_rate", p.get("盈亏比例", 0))),
                ))
            return result
        except Exception as e:
            logger.error(f"华泰证券获取持仓失败: {e}")
            return []

    async def get_orders(self) -> list[BrokerOrder]:
        if not self._trader:
            return []

        def _query():
            return self._trader.get_orders()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            orders = data if isinstance(data, list) else []
            result = []
            for o in orders:
                result.append(BrokerOrder(
                    order_id=str(o.get("order_id", o.get("委托编号", ""))),
                    symbol=o.get("symbol", o.get("证券代码", "")),
                    name=o.get("name", o.get("证券名称", "")),
                    direction=o.get("direction", o.get("买卖方向", "")),
                    price=float(o.get("price", o.get("委托价格", 0))),
                    volume=int(o.get("volume", o.get("委托数量", 0))),
                    filled_volume=int(o.get("filled_volume", o.get("成交数量", 0))),
                    filled_price=float(o.get("filled_price", o.get("成交均价", 0))),
                    status=o.get("status", o.get("委托状态", "")),
                    order_type=o.get("order_type", "limit"),
                    order_time=o.get("order_time", o.get("委托时间", "")),
                ))
            return result
        except Exception as e:
            logger.error(f"华泰证券获取委托失败: {e}")
            return []

    async def get_trades(self) -> list[BrokerTrade]:
        if not self._trader:
            return []

        def _query():
            return self._trader.get_trades()

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _query)
            trades = data if isinstance(data, list) else []
            result = []
            for t in trades:
                result.append(BrokerTrade(
                    trade_id=str(t.get("trade_id", t.get("成交编号", ""))),
                    order_id=str(t.get("order_id", t.get("委托编号", ""))),
                    symbol=t.get("symbol", t.get("证券代码", "")),
                    name=t.get("name", t.get("证券名称", "")),
                    direction=t.get("direction", t.get("买卖方向", "")),
                    price=float(t.get("price", t.get("成交价格", 0))),
                    volume=int(t.get("volume", t.get("成交数量", 0))),
                    trade_time=t.get("trade_time", t.get("成交时间", "")),
                ))
            return result
        except Exception as e:
            logger.error(f"华泰证券获取成交失败: {e}")
            return []

    async def place_order(
        self, symbol: str, direction: str, price: float,
        volume: int, order_type: str = "limit",
    ) -> dict:
        if not self._trader:
            return {"order_id": "", "status": "failed", "message": "未连接"}

        def _place():
            return self._trader.place_order(
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
            logger.error(f"华泰证券下单失败: {e}")
            return {"order_id": "", "status": "failed", "message": str(e)}

    async def cancel_order(self, order_id: str) -> dict:
        if not self._trader:
            return {"order_id": order_id, "status": "failed", "message": "未连接"}

        def _cancel():
            return self._trader.cancel_order(order_id)

        try:
            result = await asyncio.get_event_loop().run_in_executor(None, _cancel)
            return {
                "order_id": order_id,
                "status": "cancelled" if result else "failed",
                "message": "" if result else "撤单失败",
            }
        except Exception as e:
            logger.error(f"华泰证券撤单失败: {e}")
            return {"order_id": order_id, "status": "failed", "message": str(e)}

    def get_name(self) -> str:
        return "ht"

    def get_display_name(self) -> str:
        return "华泰证券(htquant)"

    def is_available(self) -> bool:
        try:
            import htquant  # noqa: F401
            return True
        except ImportError:
            return False