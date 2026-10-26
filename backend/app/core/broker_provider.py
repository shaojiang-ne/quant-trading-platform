"""
券商网关抽象接口

所有券商（国金证券 QMT / 长江证券 XTP / ...）实现此接口，
供 trading API 和 broker_bridge 统一调用。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BrokerAccount:
    total_assets: float = 0.0
    cash: float = 0.0
    available: float = 0.0
    market_value: float = 0.0
    frozen_cash: float = 0.0
    account_id: str = ""


@dataclass
class BrokerPosition:
    symbol: str = ""
    name: str = ""
    volume: int = 0
    available: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    profit_loss: float = 0.0
    profit_rate: float = 0.0
    daily_profit: float = 0.0


@dataclass
class BrokerOrder:
    order_id: str = ""
    symbol: str = ""
    name: str = ""
    direction: str = ""  # buy / sell
    price: float = 0.0
    volume: int = 0
    filled_volume: int = 0
    filled_price: float = 0.0
    status: str = ""
    order_type: str = "limit"
    order_time: str = ""


@dataclass
class BrokerTrade:
    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""
    name: str = ""
    direction: str = ""
    price: float = 0.0
    volume: int = 0
    trade_time: str = ""


@dataclass
class BrokerConnectResult:
    success: bool = False
    message: str = ""
    account_id: str = ""


class BrokerProvider(ABC):
    """券商网关抽象基类"""

    @abstractmethod
    async def connect(self, **kwargs) -> BrokerConnectResult:
        """连接券商网关"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        pass

    @property
    def account_id(self) -> str:
        """当前账户 ID"""
        return ""

    @abstractmethod
    async def get_account(self) -> BrokerAccount:
        """获取账户资金"""
        pass

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """获取持仓"""
        pass

    @abstractmethod
    async def get_orders(self) -> list[BrokerOrder]:
        """获取委托"""
        pass

    @abstractmethod
    async def get_trades(self) -> list[BrokerTrade]:
        """获取成交"""
        pass

    @abstractmethod
    async def place_order(
        self, symbol: str, direction: str, price: float,
        volume: int, order_type: str = "limit",
    ) -> dict:
        """下单，返回 {"order_id": ..., "status": ...}"""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> dict:
        """撤单，返回 {"order_id": ..., "status": ...}"""
        pass

    async def get_quote(self, symbol: str) -> dict:
        """获取实时行情（可选实现）"""
        return {}

    @abstractmethod
    def get_name(self) -> str:
        """券商标识（英文，如 qmt / cjzq）"""
        pass

    @abstractmethod
    def get_display_name(self) -> str:
        """券商显示名称（中文，如 国金证券(QMT)）"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """券商网关是否可用（依赖的 SDK/服务是否就绪）"""
        pass
