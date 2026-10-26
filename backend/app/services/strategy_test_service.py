"""策略代码测试服务

从 api/ai.py:test_code 抽出的可复用沙箱执行 + 信号校验逻辑。
供 /test-code 端点与 LLM 冒烟测试(层3)共用，保证两条路径行为一致。
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.core.strategy_sandbox import build_strategy_ns
from app.strategies.base import CtaStrategy


def _make_sim_df(n: int = 100):
    """生成模拟OHLCV数据（与原 test_code 完全一致，保证行为不变）"""
    np.random.seed(42)
    start_date = datetime(2024, 1, 2)
    dates = [start_date + timedelta(days=i) for i in range(n)]
    base_price = 50.0
    returns = np.random.randn(n) * 0.02 + 0.0005
    close_prices = base_price * np.cumprod(1 + returns)
    df = pd.DataFrame({
        "date": dates,
        "open": close_prices * (1 + np.random.randn(n) * 0.005),
        "high": close_prices * (1 + abs(np.random.randn(n)) * 0.01),
        "low": close_prices * (1 - abs(np.random.randn(n)) * 0.01),
        "close": close_prices,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
        "turnover": close_prices * np.random.randint(100000, 1000000, n),
    })
    return df, dates, close_prices


def test_strategy_code(code: str, parameters: dict = None, df: pd.DataFrame = None):
    """在模拟数据上测试策略代码

    Args:
        code: 策略Python代码，含 generate_signals 函数或 CtaStrategy 子类
        parameters: 参数dict，可为 {key:{value,type,...}} schema 或 {key:value}
        df: 可选自定义数据；None则用内置模拟数据

    Returns:
        dict: success/summary/signals/_signals(回传Series供测试断言)/error
    """
    parameters = parameters or {}
    if df is None:
        df, dates, close_prices = _make_sim_df()
    else:
        dates = list(df["date"])
        close_prices = list(df["close"])

    exec_ns = build_strategy_ns()

    try:
        exec(code, exec_ns)

        user_strategy_cls = None
        for name, obj in exec_ns.items():
            if isinstance(obj, type) and issubclass(obj, CtaStrategy) and obj is not CtaStrategy:
                user_strategy_cls = obj
                break

        if not user_strategy_cls:
            generate_signals_fn = exec_ns.get("generate_signals")
            if not generate_signals_fn:
                return {"success": False, "error": "代码中未找到 generate_signals 函数或 CtaStrategy 子类"}

            class CustomStrategy(CtaStrategy):
                @classmethod
                def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
                    return generate_signals_fn(df, setting)

            CustomStrategy.class_name = "TestStrategy"
            CustomStrategy.__name__ = "TestStrategy"
            user_strategy_cls = CustomStrategy

        param_values = {}
        for k, v in parameters.items():
            if isinstance(v, dict) and "value" in v:
                param_values[k] = v["value"]
            else:
                param_values[k] = v

        signals = user_strategy_cls.generate_signals(df, param_values)
        if isinstance(signals, tuple):
            signals = signals[0]

        if not isinstance(signals, pd.Series):
            return {"success": False, "error": f"generate_signals 应返回 pd.Series，实际返回 {type(signals).__name__}"}

        coerced_warning = None
        try:
            signals = signals.fillna(0)
            if signals.dtype == bool:
                coerced_warning = "信号类型为 bool，已自动转换为 int。建议直接使用整数 1/-1/0。"
                signals = signals.astype(int)
            else:
                signals = signals.astype(int)
            invalid_mask = ~signals.isin([1, -1, 0])
            if invalid_mask.any():
                unique_vals = signals[invalid_mask].unique()[:5]
                return {
                    "success": False,
                    "error": f"信号值必须为 1(买入)/-1(卖出)/0(持有)，发现非法值: {unique_vals.tolist()}",
                }
        except (ValueError, TypeError) as e:
            return {"success": False, "error": f"信号值类型转换失败: {e}"}

        from app.core.strategy_adapter import create_adapter
        try:
            adapter_cls = create_adapter(user_strategy_cls)
            adapter_instance = adapter_cls.__new__(adapter_cls)
            adapter_instance._wrapped_cls = user_strategy_cls
            adapter_instance._wrapped_setting = param_values
            adapter_instance._grid_mode = False
            bars_data = []
            for _, row in df.iterrows():
                bars_data.append({
                    "date": str(row["date"])[:10],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "turnover": float(row["turnover"]),
                })
            adapter_instance.precompute_signals(bars_data)
        except Exception as e:
            import traceback
            return {"success": False, "error": f"回测引擎兼容性错误: {e}", "traceback": traceback.format_exc()}

        buy_count = int((signals == 1).sum())
        sell_count = int((signals == -1).sum())
        hold_count = int((signals == 0).sum())
        total = len(signals)

        signal_dates = []
        for i in range(len(signals)):
            if signals.iloc[i] in (1, -1):
                signal_dates.append({
                    "date": str(dates[i])[:10],
                    "signal": int(signals.iloc[i]),
                    "close": round(float(close_prices[i]), 2),
                })

        position = 0
        total_return = 0.0
        entry_price = 0.0
        for i in range(len(signals)):
            if signals.iloc[i] == 1 and position == 0:
                position = 1
                entry_price = float(close_prices[i])
            elif signals.iloc[i] == -1 and position == 1:
                position = 0
                total_return += (float(close_prices[i]) - entry_price) / entry_price * 100
                entry_price = 0.0

        result = {
            "success": True,
            "summary": {
                "total_bars": total,
                "buy_signals": buy_count,
                "sell_signals": sell_count,
                "hold_signals": hold_count,
            },
            "simulated_return_pct": round(total_return, 2),
            "signals": signal_dates[:20],
            "sample_data_rows": 5,
            "_signals": signals,  # 供测试断言（HTTP响应前由api层剔除）
        }
        if coerced_warning:
            result["coerced_warning"] = coerced_warning
        return result

    except Exception as e:
        import traceback
        return {"success": False, "error": f"执行错误: {e}", "traceback": traceback.format_exc()}
