"""
券商网关注册表与工厂

仿照 data_bridge 的注册/缓存模式，
为 trading API 提供统一的券商网关获取接口。

支持券商:
  - qmt:     国金证券 (QMT/xtquant，通过 stock_trade 微服务)
  - cjzq:    长江证券 (XTP 极速交易，通过 vnpy)
  - ztzq:    中泰证券 (XTP)
  - dfzq:    东方证券 (XTP)
  - ctzq:    财通证券 (XTP)
  - hxzq:    华鑫证券 (XTP)
  - ht:      华泰证券 (htquant SDK)
  - ths:     同花顺 (iFinD 量化接口)
  - gtja:    国泰君安 (tquant2 SDK)
  - hundsun: 恒生PTrade (通用，适用于中信/招商/广发等)
"""

import logging

from app.core.broker_provider import BrokerProvider
from app.core.broker_qmt import QMTBrokerProvider
from app.core.broker_ht import HTBrokerProvider
from app.core.broker_ths import THSBrokerProvider
from app.core.broker_gtja import GTJABrokerProvider
from app.core.broker_hundsun import HundsunBrokerProvider
from app.core.broker_xtp import XTPBrokerProvider, XTP_BROKERS

logger = logging.getLogger(__name__)

# ── 券商注册表 ─────────────────────────────────────────────────────────────

_BROKER_REGISTRY: dict[str, type[BrokerProvider] | tuple] = {}
_broker_cache: dict[str, BrokerProvider] = {}

_DEFAULT_BROKER = "qmt"


def _register_brokers():
    """自动注册所有内置券商"""
    # 独立 SDK 网关
    for cls in [QMTBrokerProvider, HTBrokerProvider, THSBrokerProvider,
                GTJABrokerProvider, HundsunBrokerProvider]:
        name = cls().get_name()
        _BROKER_REGISTRY[name] = cls

    # XTP 通用网关 — 为每个 XTP 券商注册独立实例
    for broker_code in XTP_BROKERS:
        _BROKER_REGISTRY[f"xtp_{broker_code}"] = ("xtp", broker_code)


_register_brokers()


# ── 公开接口 ────────────────────────────────────────────────────────────────

def get_broker(name: str | None = None) -> BrokerProvider:
    """获取券商网关实例（带缓存）

    Args:
        name: 券商标识，如 "qmt" / "xtp_cjzq" / "ht" 等。None 时使用配置默认值。
    """
    if name is None:
        from app.config import settings
        name = getattr(settings, "BROKER", _DEFAULT_BROKER)

    name = name.lower()

    # 兼容: "cjzq" → "xtp_cjzq"（长江证券走 XTP 通道）
    if name in XTP_BROKERS:
        name = f"xtp_{name}"

    if name not in _BROKER_REGISTRY:
        logger.warning(f"未知券商 '{name}'，回退到 {_DEFAULT_BROKER}")
        name = _DEFAULT_BROKER

    if name not in _broker_cache:
        entry = _BROKER_REGISTRY[name]
        if isinstance(entry, tuple) and entry[0] == "xtp":
            _broker_cache[name] = XTPBrokerProvider(broker_code=entry[1])
        else:
            _broker_cache[name] = entry()

    return _broker_cache[name]


def get_available_brokers() -> list[dict]:
    """返回可用券商列表（按分类排序）"""
    result = []

    # QMT
    qmt = get_broker("qmt")
    result.append({
        "name": "qmt",
        "display_name": qmt.get_display_name(),
        "available": qmt.is_available(),
        "category": "独立SDK",
    })

    # 独立 SDK
    for name, cls in _BROKER_REGISTRY.items():
        if isinstance(cls, tuple):
            continue
        if name == "qmt":
            continue
        broker = get_broker(name)
        result.append({
            "name": name,
            "display_name": broker.get_display_name(),
            "available": broker.is_available(),
            "category": "独立SDK",
        })

    # XTP 系列
    for broker_code, display in XTP_BROKERS.items():
        name = f"xtp_{broker_code}"
        broker = get_broker(name)
        result.append({
            "name": name,
            "display_name": broker.get_display_name(),
            "available": broker.is_available(),
            "category": "XTP极速交易",
        })

    return result