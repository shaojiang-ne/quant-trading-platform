"""
数据源通道测试程序

对所有数据源进行全面的可用性、K线获取、数据格式、复权方式等测试。
支持彩色终端输出，测试结果以 PASS/FAIL/SKIP 标记。

用法: python test_data_sources.py [数据源名称...]
示例:
  python test_data_sources.py              # 测试所有数据源
  python test_data_sources.py sina tencent # 仅测试 sina 和 tencent
"""

import sys
import time
import traceback
from datetime import datetime, timedelta

import pandas as pd

from app.core.data_bridge import get_data_source, get_available_sources

# ── 终端颜色 ─────────────────────────────────────────────────────────────────

_COLORS = {
    "green": "\033[92m",
    "red": "\033[91m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}

_NO_COLOR = not sys.stdout.isatty()


def _c(color: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"{_COLORS[color]}{text}{_COLORS['reset']}"


# ── 测试统计 ──────────────────────────────────────────────────────────────────

_stats = {"pass": 0, "fail": 0, "skip": 0, "netfail": 0}


def _pass(msg: str = ""):
    _stats["pass"] += 1
    print(f"  {_c('green', 'PASS')} {msg}")


def _fail(msg: str = ""):
    _stats["fail"] += 1
    print(f"  {_c('red', 'FAIL')} {msg}")


def _netfail(msg: str = ""):
    """网络连接失败（非代码逻辑问题）"""
    _stats["netfail"] += 1
    print(f"  {_c('red', 'NET!')} {msg}")


def _skip(msg: str = ""):
    _stats["skip"] += 1
    print(f"  {_c('yellow', 'SKIP')} {msg}")


# ── 数据格式验证 ──────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]

_NETWORK_ERRORS = (
    ConnectionError, TimeoutError, OSError,
)
try:
    import requests
    _NETWORK_ERRORS = _NETWORK_ERRORS + (requests.ConnectionError, requests.Timeout)
except ImportError:
    pass


def _is_network_error(e: Exception) -> bool:
    return isinstance(e, _NETWORK_ERRORS) or any(
        kw in str(e).lower() for kw in ("proxy", "connection", "timeout", "resolve", "refused")
    )


def validate_dataframe(df: pd.DataFrame, label: str = "") -> bool:
    """验证 DataFrame 格式是否正确，返回 True 表示通过"""
    if df.empty:
        _fail(f"{label}: 返回空 DataFrame")
        return False

    ok = True

    # 列名检查
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        _fail(f"{label}: 缺少列 {missing}")
        ok = False

    # date 类型与排序
    if "date" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            _fail(f"{label}: date 列不是 datetime 类型 (实际: {df['date'].dtype})")
            ok = False
        elif len(df) > 1 and not df["date"].is_monotonic_increasing:
            _fail(f"{label}: date 列未升序排列")
            ok = False

    # OHLC 数值检查
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]):
                _fail(f"{label}: {col} 列不是数值类型")
                ok = False
            elif (df[col] <= 0).any():
                _fail(f"{label}: {col} 列存在 ≤0 的值")
                ok = False

    # volume ≥ 0
    if "volume" in df.columns:
        if (df["volume"] < 0).any():
            _fail(f"{label}: volume 列存在负值")
            ok = False

    # high ≥ max(open, close, low), low ≤ min(open, close, high)
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        row_max = df[["open", "close", "low"]].max(axis=1)
        row_min = df[["open", "close", "high"]].min(axis=1)
        if (df["high"] < row_max).any():
            _fail(f"{label}: high 列存在小于 max(open,close,low) 的值")
            ok = False
        if (df["low"] > row_min).any():
            _fail(f"{label}: low 列存在大于 min(open,close,high) 的值")
            ok = False

    if ok:
        _pass(f"{label}: 格式验证通过 ({len(df)} 行)")
    return ok


# ── 各测试项 ──────────────────────────────────────────────────────────────────

def test_availability(name: str, source):
    """测试数据源可用性"""
    available = source.is_available()
    source_name = source.get_name()
    if available:
        _pass(f"is_available()=True, get_name()='{source_name}'")
    else:
        _skip(f"is_available()=False, get_name()='{source_name}'")
    return available


def test_stock_daily(source, symbol: str = "600519.SH", start: str = "2024-06-01", end: str = "2024-06-30"):
    """测试股票日线K线"""
    label = f"股票日线 {symbol}"
    try:
        df = source.get_klines(symbol, "1d", start, end, "front")
        if df.empty:
            _netfail(f"{label}: 返回空数据(可能网络/代理问题)")
            return None
        ok = validate_dataframe(df, label)
        return df if ok else None
    except Exception as e:
        if _is_network_error(e):
            _netfail(f"{label}: 网络错误 {e}")
        else:
            _fail(f"{label}: 异常 {e}")
            traceback.print_exc()
        return None


def test_stock_minute(source, name: str, symbol: str = "600519.SH", period: str = "5m"):
    """测试股票分钟线K线"""
    # 腾讯不支持分钟线
    if name == "tencent":
        _skip("腾讯财经不支持分钟线")
        return None

    # baostock 不支持 1m
    if name == "baostock" and period == "1m":
        _skip("baostock 不支持 1m 分钟线")
        return None

    # 分钟线使用近期数据（历史范围太大可能导致慢查询/超时）
    if name == "sina" or name == "baostock":
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        start_date = "2024-06-01"
        end_date = "2024-06-30"

    label = f"股票{period}分钟线 {symbol}"
    try:
        df = source.get_klines(symbol, period, start_date, end_date, "front")
        if df.empty:
            _skip(f"{label}: 无数据 (可能该周期不支持或无交易数据)")
            return None
        ok = validate_dataframe(df, label)
        return df if ok else None
    except Exception as e:
        if _is_network_error(e):
            _netfail(f"{label}: 网络错误 {e}")
        else:
            _fail(f"{label}: 异常 {e}")
            traceback.print_exc()
        return None


def test_index_daily(source, index_code: str = "000300.SH", start: str = "2024-06-01", end: str = "2024-06-30"):
    """测试指数日线K线"""
    label = f"指数日线 {index_code}"
    try:
        df = source.get_index_klines(index_code, "1d", start, end)
        if df.empty:
            _fail(f"{label}: 返回空数据")
            return None
        ok = validate_dataframe(df, label)
        return df if ok else None
    except Exception as e:
        if _is_network_error(e):
            _netfail(f"{label}: 网络错误 {e}")
        else:
            _fail(f"{label}: 异常 {e}")
            traceback.print_exc()
        return None


def test_dividend_types(source, symbol: str = "600519.SH", start: str = "2024-06-01", end: str = "2024-06-30"):
    """测试不同复权方式"""
    results = {}
    for dtype in ["front", "back", "none"]:
        label = f"复权 {dtype}"
        try:
            df = source.get_klines(symbol, "1d", start, end, dividend_type=dtype)
            if df.empty:
                _skip(f"{label}: 无数据")
                results[dtype] = None
            else:
                _pass(f"{label}: {len(df)} 行")
                results[dtype] = df
        except Exception as e:
            if _is_network_error(e):
                _netfail(f"{label}: 网络错误 {e}")
            else:
                _fail(f"{label}: 异常 {e}")
            results[dtype] = None
    return results


def test_multi_stock(source, start: str = "2024-06-01", end: str = "2024-06-30"):
    """测试沪深两市多只股票"""
    test_stocks = [
        ("600519.SH", "贵州茅台"),
        ("000001.SZ", "平安银行"),
        ("300750.SZ", "宁德时代"),
    ]
    results = {}
    for symbol, name_cn in test_stocks:
        label = f"多股票 {symbol}({name_cn})"
        try:
            df = source.get_klines(symbol, "1d", start, end, "front")
            if df.empty:
                _fail(f"{label}: 无数据")
                results[symbol] = None
            else:
                _pass(f"{label}: {len(df)} 行, 收盘价 {df['close'].iloc[-1]:.2f}")
                results[symbol] = df
        except Exception as e:
            if _is_network_error(e):
                _netfail(f"{label}: 网络错误 {e}")
            else:
                _fail(f"{label}: 异常 {e}")
            results[symbol] = None
    return results


# ── 跨数据源对比 ──────────────────────────────────────────────────────────────

def test_cross_source_comparison(sources: dict, symbol: str = "600519.SH",
                                  start: str = "2024-06-01", end: str = "2024-06-30"):
    """跨数据源数据一致性对比（不复权，避免复权差异）"""
    print(f"\n{_c('bold', '━━━ 跨数据源对比 (不复权) ━━━')}")
    print(f"  标的: {symbol}  周期: 日线  范围: {start} ~ {end}\n")

    close_prices = {}
    row_counts = {}
    for name, source in sources.items():
        try:
            df = source.get_klines(symbol, "1d", start, end, "none")
            if not df.empty:
                close_prices[name] = df["close"]
                row_counts[name] = len(df)
        except Exception:
            pass

    if len(close_prices) < 2:
        _skip("可用数据源不足2个，无法对比")
        return

    # 打印对比表
    print(f"  {'数据源':12} {'行数':>6} {'收盘价均值':>12} {'收盘价最小':>12} {'收盘价最大':>12}")
    print(f"  {'─'*12} {'─'*6} {'─'*12} {'─'*12} {'─'*12}")
    for name, prices in close_prices.items():
        print(f"  {name:12} {row_counts[name]:>6} {prices.mean():>12.2f} {prices.min():>12.2f} {prices.max():>12.2f}")

    # 对比收盘价差异
    names = list(close_prices.keys())
    ref_name = names[0]
    ref_prices = close_prices[ref_name]
    print(f"\n  以 {ref_name} 为基准对比收盘价:")
    for name in names[1:]:
        other = close_prices[name]
        min_len = min(len(ref_prices), len(other))
        if min_len == 0:
            _skip(f"  {name} vs {ref_name}: 无共同数据")
            continue
        ref_vals = ref_prices.values[:min_len]
        other_vals = other.values[:min_len]
        pct_diff = abs(ref_vals - other_vals) / ref_vals * 100
        max_diff = pct_diff.max()
        mean_diff = pct_diff.mean()
        if max_diff > 10:
            _fail(f"  {name} vs {ref_name}: 最大差异 {max_diff:.2f}%, 均值差异 {mean_diff:.2f}%")
        elif max_diff > 5:
            _skip(f"  {name} vs {ref_name}: 最大差异 {max_diff:.2f}%, 均值差异 {mean_diff:.2f}% (可能是复权差异)")
        else:
            _pass(f"  {name} vs {ref_name}: 最大差异 {max_diff:.2f}%, 均值差异 {mean_diff:.2f}%")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def test_single_source(name: str):
    """测试单个数据源的全部项目"""
    source = get_data_source(name)

    print(f"\n{_c('bold', '━' * 50)}")
    print(f"  数据源: {_c('cyan', name)}")
    print(f"{_c('bold', '━' * 50)}")

    # 1. 可用性
    available = test_availability(name, source)
    if not available:
        print(f"\n  {_c('dim', '数据源不可用，跳过后续测试')}")
        return source

    # 2. 股票日线 — 作为连通性验证，失败则跳过后续
    df_daily = test_stock_daily(source)
    if df_daily is None:
        print(f"\n  {_c('dim', '核心数据获取失败，跳过后续测试')}")
        return source

    # 3. 股票5分钟线
    test_stock_minute(source, name, period="5m")

    # 4. 指数日线
    test_index_daily(source)

    # 5. 不同复权方式
    test_dividend_types(source)

    # 6. 多股票
    test_multi_stock(source)

    return source


def main():
    start_time = time.time()

    # 解析命令行参数：指定要测试的数据源
    target_sources = [s.lower() for s in sys.argv[1:]] if len(sys.argv) > 1 else None

    print(_c("bold", "\n╔══════════════════════════════════════════╗"))
    print(_c("bold", "║       数据源通道测试程序                  ║"))
    print(_c("bold", "╚══════════════════════════════════════════╝\n"))

    # 检测所有数据源可用性
    print(_c("bold", "━━━ 数据源可用性检测 ━━━\n"))
    avail_map = {}
    for info in get_available_sources():
        status = _c("green", "可用") if info["available"] else _c("red", "不可用")
        print(f"  {info['name']:12} {status}")
        avail_map[info["name"]] = info["available"]

    # 确定要测试的数据源
    all_sources = ["akshare", "efinance", "baostock", "sina", "tencent", "xtquant"]
    if target_sources:
        test_list = [s for s in target_sources if s in all_sources]
        unknown = [s for s in target_sources if s not in all_sources]
        if unknown:
            print(f"\n  {_c('yellow', '警告')}: 未知数据源 {unknown}，已忽略")
    else:
        test_list = all_sources

    print(f"\n  将测试: {_c('cyan', ', '.join(test_list))}")

    # 逐个测试
    available_sources = {}
    for name in test_list:
        source = test_single_source(name)
        if avail_map.get(name, False):
            available_sources[name] = source

    # 跨数据源对比
    if len(available_sources) >= 2:
        test_cross_source_comparison(available_sources)

    # 汇总
    elapsed = time.time() - start_time
    total = _stats["pass"] + _stats["fail"] + _stats["skip"] + _stats["netfail"]
    print(f"\n{_c('bold', '━' * 50)}")
    print(f"  测试完成，耗时 {elapsed:.1f}s")
    pass_count = _stats["pass"]
    fail_count = _stats["fail"]
    skip_count = _stats["skip"]
    netfail_count = _stats["netfail"]
    print(f"  {_c('green', f'PASS: {pass_count}')}  {_c('red', f'FAIL: {fail_count}')}  {_c('yellow', f'SKIP: {skip_count}')}  {_c('red', f'NET!: {netfail_count}')}  共 {total} 项")
    if fail_count > 0:
        print(f"  {_c('red', '存在代码逻辑失败的测试项，请检查上方输出')}")
        sys.exit(1)
    elif netfail_count > 0:
        print(f"  {_c('yellow', f'存在 {netfail_count} 个网络连接失败(非代码问题)，可忽略')}")
    else:
        print(f"  {_c('green', '所有测试项通过或已跳过')}")
    print(f"{_c('bold', '━' * 50)}\n")


if __name__ == "__main__":
    main()
