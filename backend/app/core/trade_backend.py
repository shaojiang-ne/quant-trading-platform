"""
交易数据后端抽象 + 实现

TradeBackend 定义交易网关统一接口，
StockTradeBackend 是原有 stock_trade 微服务实现，
SimTradeBackend 是模拟成交实现（复用 _sim_accounts）。
"""

import abc
import asyncio
import logging
import uuid
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# A 股模拟交易费用常量（与 vnpy_strategy_runner 同步）
SIM_COMMISSION_RATE = 0.0003      # 佣金费率万三
SIM_MIN_COMMISSION = 5.0          # 最低佣金 5 元
SIM_STAMP_TAX_RATE = 0.001        # 印花税千一（仅卖出）


class TradeBackend(abc.ABC):
    """交易后端抽象基类（异步接口）"""

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool: ...

    @abc.abstractmethod
    async def auto_connect(self) -> dict: ...

    @abc.abstractmethod
    async def auto_connect_background(self) -> None: ...

    @abc.abstractmethod
    async def check_health(self) -> dict: ...

    @abc.abstractmethod
    async def get_account(self) -> dict: ...

    @abc.abstractmethod
    async def get_positions(self) -> list: ...

    @abc.abstractmethod
    async def get_orders(self) -> list: ...

    @abc.abstractmethod
    async def get_trades(self) -> list: ...

    @abc.abstractmethod
    async def place_order(self, symbol, side, quantity, price=0, order_type="limit") -> dict: ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> dict: ...

    @abc.abstractmethod
    async def get_quote(self, symbol: str) -> dict: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...


class StockTradeBackend(TradeBackend):
    """与 stock_trade 微服务通信的网关"""

    def __init__(self):
        self._connected: bool = False
        self._client: Optional[httpx.AsyncClient] = None       # 常规请求 30s
        self._order_client: Optional[httpx.AsyncClient] = None  # 下单请求 10s
        self._base_url: str = settings.STOCK_TRADE_URL
        self._account_id: str = ""
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_interval = 30  # 重连间隔秒数
        self._on_disconnect_callback = None  # 断连通知回调

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if settings.STOCK_TRADE_API_KEY:
                headers["X-API-Key"] = settings.STOCK_TRADE_API_KEY
            self._client = httpx.AsyncClient(
                timeout=30.0, headers=headers, verify=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )
        return self._client

    async def _get_order_client(self) -> httpx.AsyncClient:
        """下单专用 client，超时更短（独立实例，不与常规 client 互相覆盖）"""
        if self._order_client is None or self._order_client.is_closed:
            headers = {}
            if settings.STOCK_TRADE_API_KEY:
                headers["X-API-Key"] = settings.STOCK_TRADE_API_KEY
            self._order_client = httpx.AsyncClient(
                timeout=10.0, headers=headers, verify=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )
        return self._order_client

    async def auto_connect(self) -> dict:
        """自动连接 stock_trade 服务（使用配置的 STOCK_TRADE_URL）

        启动时重试3次（间隔5秒），避免 stock_trade 启动顺序晚于本项目导致连接失败。
        """
        if not self._base_url:
            return {"success": False, "message": "未配置 STOCK_TRADE_URL"}

        last_error = ""
        for attempt in range(3):
            try:
                health = await self.check_health()
                if health.get("status") not in ("online",):
                    last_error = f"stock_trade 服务状态异常: {health.get('error', health.get('status', '未知错误'))}"
                    logger.warning(f"交易网关自动连接失败 (attempt {attempt+1}/3): {last_error}")
                    if attempt < 2:
                        await asyncio.sleep(5)
                    continue

                self._connected = True
                self._account_id = health.get("account_id", "")
                qmt_connected = health.get("connected", False)
                self._start_reconnect_guard()
                logger.info(f"交易网关已自动连接: {self._base_url}, account_id={self._account_id}, qmt_connected={qmt_connected}")
                return {
                    "success": True,
                    "message": "连接成功" + ("" if qmt_connected else "（QMT未连接）"),
                    "account_id": self._account_id,
                    "qmt_connected": qmt_connected,
                }
            except Exception as e:
                last_error = str(e)
                logger.warning(f"交易网关自动连接异常 (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(5)

        self._connected = False
        logger.error(f"交易网关自动连接3次均失败: {last_error}")
        return {"success": False, "message": f"连接失败: {last_error}"}

    async def auto_connect_background(self) -> None:
        """后台自动连接 — 不阻塞 lifespan"""
        result = await self.auto_connect()
        if result.get("success"):
            logger.info(f"后台连接交易网关成功: {result}")
        else:
            logger.warning(f"后台连接交易网关失败: {result.get('message', '未知错误')}")
            # 启动后台重连守护
            self._start_reconnect_guard()

    def _start_reconnect_guard(self) -> None:
        """启动自动重连守护任务"""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """定期检测连接状态，断开时自动重连"""
        while self._connected:
            await asyncio.sleep(self._reconnect_interval)
            try:
                health = await self.check_health()
                if health.get("status") not in ("online",):
                    logger.warning(f"交易网关健康检查失败，尝试重连: {health}")
                    self._connected = False
                    self._account_id = ""
                    # 尝试重连
                    for attempt in range(3):
                        await asyncio.sleep(5)
                        try:
                            health = await self.check_health()
                            if health.get("status") == "online":
                                self._connected = True
                                self._account_id = health.get("account_id", "")
                                logger.info(f"交易网关重连成功: attempt={attempt + 1}")
                                break
                        except Exception:
                            logger.warning(f"交易网关重连失败: attempt={attempt + 1}")
                    if not self._connected:
                        logger.error("交易网关重连3次均失败，停止守护")
                        if self._on_disconnect_callback:
                            await self._on_disconnect_callback("交易网关连接断开，自动重连失败")
                        return
            except Exception as e:
                logger.warning(f"交易网关健康检查异常: {e}")
                self._connected = False
                self._account_id = ""
                # 尝试重连
                for attempt in range(3):
                    await asyncio.sleep(5)
                    try:
                        health = await self.check_health()
                        if health.get("status") in ("online", "ok"):
                            self._connected = True
                            self._account_id = health.get("account_id", "")
                            logger.info(f"交易网关重连成功: attempt={attempt + 1}")
                            break
                    except Exception:
                        logger.warning(f"交易网关重连失败: attempt={attempt + 1}")
                if not self._connected:
                    logger.error("交易网关重连3次均失败，停止守护")
                    if self._on_disconnect_callback:
                        await self._on_disconnect_callback("交易网关连接断开，自动重连失败")
                    return

    async def disconnect(self):
        """断开连接"""
        self._connected = False
        self._account_id = ""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        if self._order_client and not self._order_client.is_closed:
            await self._order_client.aclose()
            self._order_client = None
        logger.info("交易网关已断开")

    # ─── stock_trade API ───

    async def check_health(self) -> dict:
        """GET /api/v1/health"""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/health", timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] GET /api/v1/health -> {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] GET /api/v1/health 请求失败: {e}")
            raise

    async def get_account(self) -> dict:
        """GET /api/v1/asset"""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/asset")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] GET /api/v1/asset -> {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] GET /api/v1/asset 请求失败: {e}")
            raise

    async def get_positions(self) -> list:
        """GET /api/v1/positions — 返回持仓列表"""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/positions")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("positions", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] GET /api/v1/positions -> {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] GET /api/v1/positions 请求失败: {e}")
            raise

    async def get_orders(self) -> list:
        """GET /api/v1/orders — 返回委托列表"""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/orders")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("orders", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] GET /api/v1/orders -> {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] GET /api/v1/orders 请求失败: {e}")
            raise

    async def get_trades(self) -> list:
        """GET /api/v1/trades — 返回成交列表"""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/trades")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("trades", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] GET /api/v1/trades -> {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] GET /api/v1/trades 请求失败: {e}")
            raise

    async def place_order(self, symbol: str, side: str, quantity: int,
                          price: float = 0, order_type: str = "limit") -> dict:
        """POST /api/v1/orders — 下单使用更短超时"""
        try:
            client = await self._get_order_client()
            payload = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
            }
            resp = await client.post(f"{self._base_url}/api/v1/orders", json=payload, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] POST /api/v1/orders -> {e.response.status_code}: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] POST /api/v1/orders 请求失败: {e}")
            raise

    async def cancel_order(self, order_id: str) -> dict:
        """DELETE /api/v1/orders/{order_id} — 撤单使用更短超时"""
        try:
            client = await self._get_order_client()
            resp = await client.delete(f"{self._base_url}/api/v1/orders/{order_id}", timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_trade] DELETE /api/v1/orders/{order_id} -> {e.response.status_code}: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"[stock_trade] DELETE /api/v1/orders/{order_id} 请求失败: {e}")
            raise

    async def get_quote(self, symbol: str) -> dict:
        """获取实时行情 — 走 stock_data /api/v1/tick/{symbol}"""
        from app.services.market_service import market_service
        return market_service.get_full_tick(symbol) or {}


class SimTradeBackend(TradeBackend):
    """模拟成交后端：复用 vnpy_strategy_runner._sim_accounts

    account_id 默认 "sim-live"（API 层手动下单用）；
    也可在实例化时指定（如某个 live 实例的 sim-{instance_id}）。
    """

    def __init__(self, account_id: str = "sim-live"):
        self._account_id = account_id
        self._connected: bool = False
        # 与 StockTradeBackend 对称：模拟后端不会断连，回调不会被触发，
        # 但 LiveGateway._set_disconnect_callback 会写入此属性，预先声明避免动态属性。
        self._on_disconnect_callback = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def auto_connect(self) -> dict:
        """模拟后端永远连上，不连任何服务"""
        self._connected = True
        logger.info(f"SimTradeBackend 已就绪 (account_id={self._account_id})")
        return {"success": True, "message": "模拟成交后端已就绪",
                "account_id": self._account_id, "qmt_connected": False}

    async def auto_connect_background(self) -> None:
        await self.auto_connect()

    async def check_health(self) -> dict:
        return {"status": "online" if self._connected else "offline",
                "account_id": self._account_id, "connected": self._connected}

    async def get_account(self) -> dict:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        acct = runner._sim_accounts.get(self._account_id)
        if not acct:
            return {"cash": 0, "available_cash": 0, "total_assets": 0, "market_value": 0}
        positions = runner._sim_positions.get(self._account_id, {})
        market_value = sum(p.get("market_value", 0) for p in positions.values())
        return {
            "cash": acct["balance"],
            "available_cash": acct["available"],
            "total_assets": acct["balance"] + market_value,
            "market_value": market_value,
        }

    async def get_positions(self) -> list:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        positions = runner._sim_positions.get(self._account_id, {})
        result = []
        for symbol, p in positions.items():
            if p.get("quantity", 0) > 0:
                result.append({
                    "symbol": symbol, "name": "",
                    "volume": p["quantity"], "quantity": p["quantity"],
                    "cost_price": p["avg_cost"], "avg_cost": p["avg_cost"],
                    "current_price": p.get("current_price", p["avg_cost"]),
                    "market_value": p.get("market_value", 0),
                    "pnl": (p.get("current_price", p["avg_cost"]) - p["avg_cost"]) * p["quantity"],
                })
        return result

    async def get_orders(self) -> list:
        return []  # 模拟后端不维护委托列表，走 DB Order 表查询

    async def get_trades(self) -> list:
        return []

    async def place_order(self, symbol, side, quantity, price=0,
                          order_type="limit") -> dict:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        account = runner._sim_accounts.get(self._account_id)
        if not account:
            return {"success": False, "error": "模拟账户不存在",
                    "order_id": ""}

        side = side.lower()
        if price <= 0:
            return {"success": False, "error": "模拟下单需指定价格",
                    "order_id": ""}

        # T+1 和涨跌停校验
        passed, reason = runner._check_t1_and_limit(self._account_id, symbol, side, price)
        if not passed:
            return {"success": False, "error": reason, "order_id": ""}

        if side == "buy":
            cost = quantity * price
            commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
            if account["available"] < cost + commission:
                return {"success": False,
                        "error": f"资金不足：可用 {account['available']:.2f}，需要 {cost + commission:.2f}",
                        "order_id": ""}
            runner._update_sim_account_buy(self._account_id, symbol, quantity, price)
            order_id = str(uuid.uuid4())
            await self._record_order(symbol, side, quantity, price, order_id)
            return {"success": True, "order_id": order_id,
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "price": price}

        elif side == "sell":
            positions = runner._sim_positions.get(self._account_id, {})
            pos = positions.get(symbol)
            if not pos or pos["quantity"] < quantity:
                avail = pos["quantity"] if pos else 0
                return {"success": False,
                        "error": f"持仓不足：可用 {avail}，需要 {quantity}",
                        "order_id": ""}
            runner._update_sim_account_sell(self._account_id, symbol, quantity,
                                            price, pos["avg_cost"])
            order_id = str(uuid.uuid4())
            await self._record_order(symbol, side, quantity, price, order_id)
            return {"success": True, "order_id": order_id,
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "price": price}

        return {"success": False, "error": f"不支持的方向: {side}", "order_id": ""}

    async def cancel_order(self, order_id: str) -> dict:
        # 模拟成交立即成交，无撤单概念
        return {"success": False, "error": "模拟成交不支持撤单"}

    async def get_quote(self, symbol: str) -> dict:
        from app.services.market_service import market_service
        return market_service.get_full_tick(symbol) or {}

    async def disconnect(self) -> None:
        self._connected = False

    async def _record_order(self, symbol, side, quantity, price, order_id) -> None:
        """落 Order 表"""
        try:
            from app.database import SessionLocal
            from app.models.models import Order, TradingInstance
            db = SessionLocal()
            try:
                # 从 account_id 反查 user_id
                user_id = ""
                inst = db.query(TradingInstance).filter(
                    TradingInstance.account_id == self._account_id
                ).first()
                if inst:
                    user_id = inst.user_id
                db.add(Order(
                    id=order_id, user_id=user_id, account_id=self._account_id,
                    symbol=symbol, side=side, type="market",
                    quantity=quantity, price=price, status="filled",
                    filled_quantity=quantity, filled_price=price,
                    source="sim_live", gateway_order_id=order_id,
                ))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"模拟成交落 Order 表失败: {e}")
