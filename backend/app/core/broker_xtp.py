"""
XTP 通用券商网关

通过 vnpy XTP 网关接入，实现 BrokerProvider 接口。
XTP 是中泰证券开发的极速交易系统，支持多家券商：

- 长江证券
- 中泰证券
- 东方证券
- 财通证券
- 华鑫证券
- 国盛证券
- 粤开证券
- 其他 XTP 合作券商

需要安装: pip install vnpy vnpy_xtp
需开通对应券商的 XTP 极速交易权限。
"""

import asyncio
import logging

from app.core.broker_provider import (
    BrokerProvider, BrokerAccount, BrokerPosition,
    BrokerOrder, BrokerTrade, BrokerConnectResult,
)
try:
    from app.core.vnpy_live_gateway import vnpy_live_gateway
except ImportError:
    vnpy_live_gateway = None

logger = logging.getLogger(__name__)

# XTP 支持的券商列表
XTP_BROKERS = {
    "cjzq": "长江证券",
    "ztzq": "中泰证券",
    "dfzq": "东方证券",
    "ctzq": "财通证券",
    "hxzq": "华鑫证券",
    "gszq": "国盛证券",
    "ykzq": "粤开证券",
}


class XTPBrokerProvider(BrokerProvider):
    """XTP 通用券商网关 — 通过 vnpy MainEngine + XtpGateway"""

    def __init__(self, broker_code: str = "cjzq"):
        self._gw = vnpy_live_gateway
        self._connected = False
        self._account_id = ""
        self._broker_code = broker_code

    async def connect(self, **kwargs) -> BrokerConnectResult:
        td_address = kwargs.get("td_address", "")
        md_address = kwargs.get("md_address", "")
        broker_id = kwargs.get("broker_id", "")
        app_id = kwargs.get("app_id", "")
        userid = kwargs.get("userid", "")
        password = kwargs.get("password", "")
        software_key = kwargs.get("software_key", "")

        if not userid or not password:
            broker_display = XTP_BROKERS.get(self._broker_code, "XTP券商")
            return BrokerConnectResult(
                success=False,
                message=f"缺少 {broker_display} XTP 连接参数 (userid/password)",
            )

        setting = {
            "交易服务器": td_address,
            "行情服务器": md_address,
            "经纪商代码": broker_id,
            "产品名称": app_id,
            "授权编码": software_key,
            "用户名": userid,
            "密码": password,
        }

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._gw.connect("xtp", setting),
            )
            self._connected = True
            self._account_id = userid
            broker_display = XTP_BROKERS.get(self._broker_code, "XTP")
            return BrokerConnectResult(
                success=True,
                message=f"{broker_display} XTP 网关连接成功",
                account_id=userid,
            )
        except Exception as e:
            logger.error(f"XTP 连接失败: {e}")
            return BrokerConnectResult(success=False, message=str(e))

    async def disconnect(self) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._gw.main_engine.close(),
            )
        except Exception as e:
            logger.error(f"XTP 断开连接失败: {e}")
        finally:
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._gw.main_engine is not None

    @property
    def account_id(self) -> str:
        return self._account_id

    async def get_account(self) -> BrokerAccount:
        data = await self._gw.query_asset()
        if not data:
            return BrokerAccount(account_id=self._account_id)
        return BrokerAccount(
            account_id=self._account_id,
            total_assets=float(data.get("balance", 0)),
            cash=float(data.get("available", 0)),
            available=float(data.get("available", 0)),
            market_value=float(data.get("market_value", 0)),
            frozen_cash=float(data.get("frozen", 0)),
        )

    async def get_positions(self) -> list[BrokerPosition]:
        data = await self._gw.query_positions()
        if not data:
            return []
        positions = data if isinstance(data, list) else [data]
        result = []
        for p in positions:
            result.append(BrokerPosition(
                symbol=p.get("symbol", ""),
                name=p.get("symbol_name", ""),
                volume=int(p.get("volume", 0)),
                available=int(p.get("frozen", 0)) if p.get("frozen") else int(p.get("volume", 0)),
                cost_price=float(p.get("avg_price", 0)),
                current_price=float(p.get("last_price", 0)),
                market_value=float(p.get("market_value", 0)),
                profit_loss=float(p.get("position_profit", 0)),
                profit_rate=float(p.get("position_profit_rate", 0)),
            ))
        return result

    async def get_orders(self) -> list[BrokerOrder]:
        data = await self._gw.query_orders()
        if not data:
            return []
        orders = data if isinstance(data, list) else [data]
        result = []
        for o in orders:
            result.append(BrokerOrder(
                order_id=str(o.get("order_id", "")),
                symbol=o.get("symbol", ""),
                name=o.get("symbol_name", ""),
                direction=o.get("direction", ""),
                price=float(o.get("price", 0)),
                volume=int(o.get("volume", 0)),
                filled_volume=int(o.get("traded_volume", 0)),
                filled_price=float(o.get("traded_price", 0)),
                status=o.get("status", ""),
                order_type=o.get("order_type", "limit"),
                order_time=o.get("order_time", ""),
            ))
        return result

    async def get_trades(self) -> list[BrokerTrade]:
        data = await self._gw.query_trades()
        if not data:
            return []
        trades = data if isinstance(data, list) else [data]
        result = []
        for t in trades:
            result.append(BrokerTrade(
                trade_id=str(t.get("trade_id", "")),
                order_id=str(t.get("order_id", "")),
                symbol=t.get("symbol", ""),
                name=t.get("symbol_name", ""),
                direction=t.get("direction", ""),
                price=float(t.get("price", 0)),
                volume=int(t.get("volume", 0)),
                trade_time=t.get("trade_time", ""),
            ))
        return result

    async def place_order(
        self, symbol: str, direction: str, price: float,
        volume: int, order_type: str = "limit",
    ) -> dict:
        try:
            result = await self._gw.place_order(
                symbol=symbol, direction=direction,
                price=price, volume=volume, order_type=order_type,
            )
            return {
                "order_id": str(result.get("order_id", "")) if result else "",
                "status": result.get("status", "pending") if result else "failed",
                "message": result.get("message", "") if result else "下单失败",
            }
        except Exception as e:
            logger.error(f"XTP 下单失败: {e}")
            return {"order_id": "", "status": "failed", "message": str(e)}

    async def cancel_order(self, order_id: str) -> dict:
        try:
            result = await self._gw.cancel_order(order_id)
            return {
                "order_id": order_id,
                "status": "cancelled" if result else "failed",
                "message": "" if result else "撤单失败",
            }
        except Exception as e:
            logger.error(f"XTP 撤单失败: {e}")
            return {"order_id": order_id, "status": "failed", "message": str(e)}

    async def get_quote(self, symbol: str) -> dict:
        if not self.is_connected():
            return {}
        try:
            from app.core.data_bridge import data_bridge
            from app.services.market_service import market_service
            xt_symbol = data_bridge.to_xt_symbol(symbol.split(".")[0] if "." in symbol else symbol)
            if market_service.is_available():
                return market_service.get_full_tick(xt_symbol) or {}
            return {}
        except Exception:
            return {}

    def get_name(self) -> str:
        return f"xtp_{self._broker_code}"

    def get_display_name(self) -> str:
        broker_display = XTP_BROKERS.get(self._broker_code, "XTP券商")
        return f"{broker_display}(XTP)"

    def is_available(self) -> bool:
        try:
            import vnpy  # noqa: F401
            import vnpy_xtp  # noqa: F401
            return True
        except ImportError:
            return False