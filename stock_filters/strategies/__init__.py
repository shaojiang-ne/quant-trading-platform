import importlib
import pkgutil
from strategies.base import BaseStrategy


def discover_strategies() -> dict[str, type[BaseStrategy]]:
    """扫描 strategies/ 目录，发现所有 BaseStrategy 子类"""
    strategies = {}
    package = importlib.import_module("strategies")
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"strategies.{name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and hasattr(attr, "name")):
                strategies[attr.name] = attr
    return strategies


def load_strategies(config: dict) -> list[BaseStrategy]:
    """根据配置加载启用的策略实例"""
    all_strategies = discover_strategies()
    loaded = []
    strategy_configs = config.get("strategies", {})
    for name, cls in all_strategies.items():
        cfg = strategy_configs.get(name, {})
        if cfg.get("enabled", False):
            params = cfg.get("params", {})
            loaded.append(cls(params=params))
    return loaded
