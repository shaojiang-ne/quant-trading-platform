"""策略代码动态执行的公共沙箱命名空间

消除三处exec注入不一致：
- app/api/ai.py:test_code (经 strategy_test_service)
- app/core/strategy_adapter.py:resolve_strategy_class
- app/services/vnpy_backtest_service.py:run_vnpy_backtest (间接经resolve)

三处必须注入完全相同的依赖，否则会出现'测试过但实盘崩'。
"""
import logging as logging_module
import math as math_module

import numpy as np
import pandas as pd

from app.strategies.base import (
    sma, ema, rsi, macd, bollinger, atr, donchian, kdj, cci, CtaStrategy,
)


def build_strategy_ns(logger=None):
    """构建策略代码 exec 命名空间

    Args:
        logger: 策略日志器；None则新建 strategy logger（与历史行为一致）

    Returns:
        dict: exec 命名空间，含 pd/np/math/logging/logger/sma.../cci/CtaStrategy
    """
    if logger is None:
        logger = logging_module.getLogger("strategy")
        if not logger.handlers:
            handler = logging_module.StreamHandler()
            handler.setFormatter(logging_module.Formatter("[%(name)s] %(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging_module.INFO)

    return {
        "__name__": "strategy",
        "pd": pd,
        "np": np,
        "math": math_module,
        "logging": logging_module,
        "logger": logger,
        "sma": sma,
        "ema": ema,
        "rsi": rsi,
        "macd": macd,
        "bollinger": bollinger,
        "atr": atr,
        "donchian": donchian,
        "kdj": kdj,
        "cci": cci,
        "CtaStrategy": CtaStrategy,
    }
