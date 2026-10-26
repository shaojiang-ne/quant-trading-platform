#!/usr/bin/env python3
"""
真实数据回测测试

优先从 stock_data 服务 (http://127.0.0.1:8000) 获取真实行情数据，
服务不可用时回退到 akshare。
分别用 backtest_service 逻辑和 vnpy_backtest_service 逻辑进行回测，
对比信号数量和交易结果。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('IS_VNPY', '1')

import pandas as pd
import numpy as np
from datetime import datetime
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── 1. 从 stock_data 服务获取数据 ──────────────────────────────────────────

def fetch_from_stock_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 stock_data HTTPS API 获取真实行情数据

    API文档: GET /api/v1/klines?symbol=002202.SZ&period=1d&start_time=20240430&dividend_type=front
    """
    import httpx

    base_url = "http://127.0.0.1:8000"
    # 代码格式: 002202 → 002202.SZ
    if symbol.startswith("6") or symbol.startswith("9"):
        xt_symbol = f"{symbol}.SH"
    else:
        xt_symbol = f"{symbol}.SZ"

    start_fmt = start.replace("-", "")
    end_fmt = end.replace("-", "")

    print(f"  请求: {base_url}/api/v1/klines?symbol={xt_symbol}&period=1d&start_time={start_fmt}&end_time={end_fmt}&dividend_type=front")

    try:
        client = httpx.Client(base_url=base_url, timeout=10.0, verify=False)
        resp = client.get("/api/v1/klines", params={
            "symbol": xt_symbol,
            "period": "1d",
            "start_time": start_fmt,
            "end_time": end_fmt,
            "dividend_type": "front",
        })

        if resp.status_code != 200:
            print(f"  stock_data 返回 HTTP {resp.status_code}")
            return pd.DataFrame()

        data = resp.json()
        klines = data.get("klines", [])
        if not klines:
            print(f"  stock_data 返回空数据")
            return pd.DataFrame()

        df = pd.DataFrame(klines)
        df = df.rename(columns={"datetime": "date"})
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 统一列名
        if "amount" in df.columns:
            df = df.rename(columns={"amount": "turnover"})

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        print(f"  stock_data 返回 {len(df)} 根日K线")
        return df[["date", "open", "high", "low", "close", "volume", "turnover"]]

    except Exception as e:
        print(f"  stock_data 请求失败: {e}")
        return pd.DataFrame()


def fetch_from_stock_data_1m(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 stock_data HTTPS API 获取1分钟K线数据"""
    import httpx

    base_url = "http://127.0.0.1:8000"
    if symbol.startswith("6") or symbol.startswith("9"):
        xt_symbol = f"{symbol}.SH"
    else:
        xt_symbol = f"{symbol}.SZ"

    start_fmt = start.replace("-", "")
    end_fmt = end.replace("-", "")

    print(f"  请求1分钟数据: symbol={xt_symbol}&period=1m&start_time={start_fmt}&end_time={end_fmt}")

    try:
        client = httpx.Client(base_url=base_url, timeout=30.0, verify=False)
        resp = client.get("/api/v1/klines", params={
            "symbol": xt_symbol,
            "period": "1m",
            "start_time": start_fmt,
            "end_time": end_fmt,
            "dividend_type": "front",
        })

        if resp.status_code != 200:
            print(f"  stock_data 1m 返回 HTTP {resp.status_code}")
            return pd.DataFrame()

        data = resp.json()
        klines = data.get("klines", [])
        if not klines:
            print(f"  stock_data 1m 返回空数据")
            return pd.DataFrame()

        df = pd.DataFrame(klines)
        df = df.rename(columns={"datetime": "date"})
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "amount" in df.columns:
            df = df.rename(columns={"amount": "turnover"})

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        print(f"  stock_data 返回 {len(df)} 根1分钟K线")
        return df[["date", "open", "high", "low", "close", "volume", "turnover"]]

    except Exception as e:
        print(f"  stock_data 1m 请求失败: {e}")
        return pd.DataFrame()


def fetch_from_akshare(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 akshare 获取真实行情数据（回退方案1）"""
    import akshare as ak

    start_fmt = start.replace("-", "")
    end_fmt = end.replace("-", "")

    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_fmt,
        end_date=end_fmt,
        adjust="qfq",
    )

    if df.empty:
        print(f"  akshare 返回空数据")
        return pd.DataFrame()

    result = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]),
        "open": df["开盘"].astype(float),
        "high": df["最高"].astype(float),
        "low": df["最低"].astype(float),
        "close": df["收盘"].astype(float),
        "volume": df["成交量"].astype(float),
        "turnover": df["成交额"].astype(float),
    })
    result = result.sort_values("date").reset_index(drop=True)
    print(f"  akshare 返回 {len(result)} 根日K线")
    return result


def fetch_from_baostock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 baostock 获取真实行情数据（回退方案2）"""
    import baostock as bs

    lg = bs.login()
    if lg.error_code != '0':
        print(f"  baostock 登录失败: {lg.error_msg}")
        return pd.DataFrame()
    print(f"  baostock 登录成功")

    bs_code = f"sz.{symbol}"
    start_fmt = start if "-" in start else f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    end_fmt = end if "-" in end else f"{end[:4]}-{end[4:6]}-{end[6:8]}"
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,turn,pctChg",
        start_date=start_fmt,
        end_date=end_fmt,
        frequency="d",
        adjustflag="2",  # 前复权
    )

    if rs is None or rs.error_code != '0':
        err_msg = rs.error_msg if rs else "query returned None"
        print(f"  baostock 查询失败: {err_msg}")
        bs.logout()
        return pd.DataFrame()

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    bs.logout()

    if not rows:
        print(f"  baostock 返回空数据")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=rs.fields)
    print(f"  baostock 返回 {len(df)} 行")

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "amount" in df.columns:
        df = df.rename(columns={"amount": "turnover"})

    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume", "turnover"]]


def fetch_from_sina(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过新浪财经API获取真实行情数据（回退方案3）"""
    import httpx

    # 新浪代码格式: sz002202, sh600519
    if symbol.startswith("6") or symbol.startswith("9"):
        sina_code = f"sh{symbol}"
    else:
        sina_code = f"sz{symbol}"

    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina_code,
        "scale": "240",  # 日线
        "ma": "no",
        "datalen": "1000",
    }

    try:
        resp = httpx.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"  新浪API返回 HTTP {resp.status_code}")
            return pd.DataFrame()

        import json
        data = json.loads(resp.text)
        if not data:
            print(f"  新浪API返回空数据")
            return pd.DataFrame()

        rows = []
        for item in data:
            day = item.get("day", "")
            # 过滤日期范围
            if day < start or day > end:
                continue
            rows.append({
                "date": pd.Timestamp(day),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": float(item.get("volume", 0)),
                "turnover": 0.0,
            })

        if not rows:
            print(f"  新浪API日期范围内无数据")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values("date").reset_index(drop=True)
        print(f"  新浪API返回 {len(df)} 根日K线")
        return df[["date", "open", "high", "low", "close", "volume", "turnover"]]

    except Exception as e:
        print(f"  新浪API请求失败: {e}")
        return pd.DataFrame()


def fetch_real_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """优先从 stock_data 服务获取数据，不可用时依次回退"""
    print(f"\n  [尝试] stock_data 服务 (http://127.0.0.1:8000)...")
    df = fetch_from_stock_data(symbol, start, end)
    if not df.empty:
        return df

    print(f"\n  [回退1] akshare...")
    try:
        df = fetch_from_akshare(symbol, start, end)
        if not df.empty:
            return df
    except Exception as e:
        print(f"  akshare 失败: {e}")

    print(f"\n  [回退2] baostock...")
    try:
        df = fetch_from_baostock(symbol, start, end)
        if not df.empty:
            return df
    except Exception as e:
        print(f"  baostock 失败: {e}")

    print(f"\n  [回退3] 新浪财经API...")
    try:
        df = fetch_from_sina(symbol, start, end)
        if not df.empty:
            return df
    except Exception as e:
        print(f"  新浪API 失败: {e}")

    return pd.DataFrame()


# ── 2. 信号生成与交易模拟（backtest_service 逻辑） ───────────────────────────

def run_backtest_simple(df: pd.DataFrame, setting: dict, capital: float = 1000000):
    """使用 backtest_service 的逻辑进行回测"""
    from app.strategies.base import DoubleMaStrategy

    signals = DoubleMaStrategy.generate_signals(df, setting)

    buy_signals = (signals == 1).sum()
    sell_signals = (signals == -1).sum()
    print(f"\n  信号统计: 买入信号={buy_signals}, 卖出信号={sell_signals}")

    # 打印每个信号的日期
    for i in range(len(signals)):
        if signals.iloc[i] != 0:
            row = df.iloc[i]
            sig_type = '金叉(买入)' if signals.iloc[i] == 1 else '死叉(卖出)'
            print(f"    {row['date'].strftime('%Y-%m-%d')}: {sig_type}, close={row['close']:.2f}")

    # 模拟交易
    position = 0
    avg_cost = 0.0
    cash = capital
    trades = []
    buy_date = None
    commission_rate = 0.0003
    stamp_tax_rate = 0.001

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        date_str = row["date"].strftime("%Y-%m-%d")
        signal = int(signals.iloc[i])

        if signal == 1 and position == 0:
            buy_amount = cash * 0.9
            shares_100 = int(buy_amount / (price * 100)) * 100
            shares = shares_100 if shares_100 > 0 else int(buy_amount / price)
            if shares > 0:
                cost = shares * price
                commission = max(cost * commission_rate, 5)
                cash -= (cost + commission)
                avg_cost = price
                position = shares
                buy_date = date_str
                trades.append({
                    "date": date_str, "side": "buy",
                    "price": round(price, 2), "quantity": shares,
                })

        elif signal == -1 and position > 0 and buy_date != date_str:
            revenue = position * price
            commission = max(revenue * commission_rate, 5)
            stamp_tax = revenue * stamp_tax_rate
            pnl = (price - avg_cost) * position - commission - stamp_tax
            cash += (revenue - commission - stamp_tax)
            trades.append({
                "date": date_str, "side": "sell",
                "price": round(price, 2), "quantity": position,
                "pnl": round(pnl, 2),
            })
            position = 0
            avg_cost = 0
            buy_date = None

    final_equity = cash + position * float(df.iloc[-1]["close"])
    total_return = (final_equity - capital) / capital

    return {
        "total_return": total_return,
        "final_equity": final_equity,
        "total_trades": len(trades),
        "trades": trades,
        "buy_signals": int(buy_signals),
        "sell_signals": int(sell_signals),
    }


# ── 3. vnpy 回测引擎测试 ────────────────────────────────────────────────────

def run_vnpy_backtest_real(df: pd.DataFrame, setting: dict, capital: float = 1000000):
    """使用 vnpy 回测引擎进行回测（绕过 data_bridge，直接注入数据）"""
    from vnpy.trader.constant import Exchange, Interval, Direction
    from vnpy.trader.object import BarData
    from app.services.vnpy_backtest_service import CtaBacktestingEngine
    from app.core.strategy_adapter import VNPY_STRATEGY_MAP

    symbol = "002202"
    exchange = Exchange.SZSE
    vt_symbol = f"{symbol}.{exchange.value}"

    # 构建 BarData 列表
    bars = []
    for _, row in df.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["date"].to_pydatetime(),
            interval=Interval.DAILY,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            turnover=float(row.get("turnover", 0)),
            gateway_name="TEST",
        )
        bars.append(bar)

    # 初始化引擎
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=Interval.DAILY,
        start=df.iloc[0]["date"].to_pydatetime(),
        end=df.iloc[-1]["date"].to_pydatetime(),
        rate=0.0003,
        stamp_tax_rate=0.001,
        size=1,
        pricetick=0.01,
        capital=capital,
    )

    # 注入数据（绕过 data_bridge）
    strategy_cls = VNPY_STRATEGY_MAP["DoubleMaStrategy"]
    engine.add_strategy(strategy_cls, setting)

    # 手动注入历史数据
    engine.history_data.clear()
    engine.dts.clear()
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, vt_symbol)] = bar

    print(f"\n  vnpy引擎: 注入 {len(bars)} 根日K线")

    # 运行回测
    engine.run_backtesting()
    result = engine.calculate_result()

    if not result:
        print("  vnpy回测无结果")
        return None

    # 打印交易记录
    print(f"\n  vnpy交易记录 ({len(engine.trades)} 笔):")
    for trade in sorted(engine.trades.values(), key=lambda t: t.tradeid):
        side = "买入" if trade.direction == Direction.LONG else "卖出"
        print(f"    {trade.datetime.strftime('%Y-%m-%d')}: {side} "
              f"价格={trade.price:.2f} 数量={int(trade.volume)}")

    return {
        "total_return": result["total_return"],
        "total_trades": result["total_trades"],
        "win_rate": result["win_rate"],
        "max_drawdown": result["max_drawdown"],
        "sharpe_ratio": result["sharpe_ratio"],
    }


# ── 4. vnpy 1分钟回测测试 ──────────────────────────────────────────────────

def run_vnpy_backtest_1m(df_daily: pd.DataFrame, df_1m: pd.DataFrame, setting: dict, capital: float = 1000000):
    """使用 vnpy 回测引擎进行1分钟回测（信号基于日K线，交易在1分钟线上执行）"""
    from vnpy.trader.constant import Exchange, Interval, Direction
    from vnpy.trader.object import BarData
    from app.services.vnpy_backtest_service import CtaBacktestingEngine
    from app.core.strategy_adapter import VNPY_STRATEGY_MAP

    symbol = "002202"
    exchange = Exchange.SZSE
    vt_symbol = f"{symbol}.{exchange.value}"

    # 构建1分钟 BarData 列表
    bars_1m = []
    for _, row in df_1m.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["date"].to_pydatetime(),
            interval=Interval.MINUTE,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            turnover=float(row.get("turnover", 0)),
            gateway_name="TEST",
        )
        bars_1m.append(bar)

    # 初始化引擎
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=Interval.MINUTE,
        start=df_1m.iloc[0]["date"].to_pydatetime(),
        end=df_1m.iloc[-1]["date"].to_pydatetime(),
        rate=0.0003,
        stamp_tax_rate=0.001,
        size=1,
        pricetick=0.01,
        capital=capital,
    )

    strategy_cls = VNPY_STRATEGY_MAP["DoubleMaStrategy"]
    engine.add_strategy(strategy_cls, setting)

    # 注入1分钟历史数据
    engine.history_data.clear()
    engine.dts.clear()
    for bar in bars_1m:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, vt_symbol)] = bar

    # 同时注入日K线数据（供 _precompute_with_daily_signals 使用）
    # 需要临时替换 data_bridge.load_bars
    import app.core.data_bridge as db_module
    original_load_bars = db_module.data_bridge.load_bars

    daily_bars = []
    for _, row in df_daily.iterrows():
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=row["date"].to_pydatetime(),
            interval=Interval.DAILY,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            turnover=float(row.get("turnover", 0)),
            gateway_name="TEST",
        )
        daily_bars.append(bar)

    def mock_load_bars(symbol, exchange, interval, start, end):
        if interval == Interval.DAILY:
            return daily_bars
        return bars_1m

    db_module.data_bridge.load_bars = mock_load_bars

    print(f"\n  vnpy引擎: 注入 {len(bars_1m)} 根1分钟K线 + {len(daily_bars)} 根日K线")

    try:
        # 运行回测
        engine.run_backtesting()
        result = engine.calculate_result()

        if not result:
            print("  vnpy 1分钟回测无结果")
            return None

        # 打印交易记录
        print(f"\n  vnpy 1分钟交易记录 ({len(engine.trades)} 笔):")
        for trade in sorted(engine.trades.values(), key=lambda t: t.tradeid):
            side = "买入" if trade.direction == Direction.LONG else "卖出"
            dt_str = trade.datetime.strftime('%Y-%m-%d %H:%M') if hasattr(trade.datetime, 'hour') and trade.datetime.hour > 0 else trade.datetime.strftime('%Y-%m-%d')
            print(f"    {dt_str}: {side} 价格={trade.price:.2f} 数量={int(trade.volume)}")

        return {
            "total_return": result["total_return"],
            "total_trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "max_drawdown": result["max_drawdown"],
            "sharpe_ratio": result["sharpe_ratio"],
        }
    finally:
        # 恢复原始方法
        db_module.data_bridge.load_bars = original_load_bars


# ── 5. MA 可视化 ────────────────────────────────────────────────────────────

def show_ma_crossovers(df: pd.DataFrame, setting: dict):
    """显示 MA 交叉情况"""
    from app.strategies.base import sma

    fast_window = setting.get("fast_window", 5)
    slow_window = setting.get("slow_window", 20)

    fast_ma = sma(df["close"], fast_window)
    slow_ma = sma(df["close"], slow_window)

    # 找出交叉点
    cross_over = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    cross_below = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    print(f"\n  MA{fast_window}/MA{slow_window} 交叉统计:")
    print(f"    金叉(买入)次数: {cross_over.sum()}")
    print(f"    死叉(卖出)次数: {cross_below.sum()}")

    print(f"\n  金叉日期:")
    for i in range(len(cross_over)):
        if cross_over.iloc[i]:
            row = df.iloc[i]
            print(f"    {row['date'].strftime('%Y-%m-%d')}: close={row['close']:.2f}, "
                  f"MA{fast_window}={fast_ma.iloc[i]:.2f}, MA{slow_window}={slow_ma.iloc[i]:.2f}")

    print(f"\n  死叉日期:")
    for i in range(len(cross_below)):
        if cross_below.iloc[i]:
            row = df.iloc[i]
            print(f"    {row['date'].strftime('%Y-%m-%d')}: close={row['close']:.2f}, "
                  f"MA{fast_window}={fast_ma.iloc[i]:.2f}, MA{slow_window}={slow_ma.iloc[i]:.2f}")


# ── 主程序 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    symbol = "002202"
    start_date = "2024-04-30"
    end_date = "2025-04-30"
    capital = 1000000
    setting = {"fast_window": 5, "slow_window": 20}

    print("=" * 70)
    print(f"真实数据回测测试: {symbol}")
    print(f"  日期范围: {start_date} ~ {end_date}")
    print(f"  策略: 双均线 (fast={setting['fast_window']}, slow={setting['slow_window']})")
    print(f"  初始资金: {capital:,.0f}")
    print("=" * 70)

    # 1. 获取日K线数据
    print("\n[1] 获取真实日K线数据...")
    df = fetch_real_data(symbol, start_date, end_date)
    if df.empty:
        print("ERROR: 无法获取数据，退出")
        sys.exit(1)

    print(f"  获取到 {len(df)} 根日K线")
    print(f"  日期范围: {df.iloc[0]['date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"  价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")

    # 2. MA 交叉分析
    print("\n[2] MA 交叉分析...")
    show_ma_crossovers(df, setting)

    # 3. backtest_service 逻辑回测
    print("\n[3] backtest_service 逻辑回测...")
    result_simple = run_backtest_simple(df, setting, capital)
    print(f"\n  === backtest_service 结果 ===")
    print(f"  总收益率: {result_simple['total_return']*100:.2f}%")
    print(f"  总交易次数: {result_simple['total_trades']}")
    print(f"  买入信号: {result_simple['buy_signals']}, 卖出信号: {result_simple['sell_signals']}")
    print(f"\n  交易明细:")
    for t in result_simple['trades']:
        pnl_str = f", pnl={t['pnl']}" if 'pnl' in t else ""
        print(f"    {t['date']}: {t['side']} 价格={t['price']} 数量={t['quantity']}{pnl_str}")

    # 4. vnpy 回测引擎测试（日K线）
    print("\n[4] vnpy 回测引擎测试（日K线）...")
    result_vnpy = run_vnpy_backtest_real(df, setting, capital)
    if result_vnpy:
        print(f"\n  === vnpy_backtest_service 结果（日K线）===")
        print(f"  总收益率: {result_vnpy['total_return']*100:.2f}%")
        print(f"  总交易次数: {result_vnpy['total_trades']}")
        print(f"  胜率: {result_vnpy['win_rate']*100:.1f}%")
        print(f"  最大回撤: {result_vnpy['max_drawdown']*100:.2f}%")
        print(f"  夏普比率: {result_vnpy['sharpe_ratio']:.4f}")

    # 5. 尝试获取1分钟数据并测试
    print("\n[5] 尝试获取1分钟K线数据...")
    df_1m = fetch_from_stock_data_1m(symbol, start_date, end_date)
    if not df_1m.empty:
        print(f"  获取到 {len(df_1m)} 根1分钟K线")
        print(f"  日期范围: {df_1m.iloc[0]['date'].strftime('%Y-%m-%d %H:%M')} ~ {df_1m.iloc[-1]['date'].strftime('%Y-%m-%d %H:%M')}")

        print("\n[6] vnpy 回测引擎测试（1分钟K线，信号基于日K线）...")
        result_1m = run_vnpy_backtest_1m(df, df_1m, setting, capital)
        if result_1m:
            print(f"\n  === vnpy_backtest_service 结果（1分钟K线）===")
            print(f"  总收益率: {result_1m['total_return']*100:.2f}%")
            print(f"  总交易次数: {result_1m['total_trades']}")
            print(f"  胜率: {result_1m['win_rate']*100:.1f}%")
            print(f"  最大回撤: {result_1m['max_drawdown']*100:.2f}%")
            print(f"  夏普比率: {result_1m['sharpe_ratio']:.4f}")
    else:
        print("  1分钟数据不可用，跳过1分钟回测测试")

    # 7. 对比
    print("\n" + "=" * 70)
    print("对比结果:")
    print(f"  {'':20s} {'backtest_service':>15s} {'vnpy(日线)':>15s}", end="")
    if not df_1m.empty:
        print(f" {'vnpy(1分钟)':>15s}")
    else:
        print()
    print(f"  {'总收益率':20s} {result_simple['total_return']*100:>14.2f}%", end="")
    if result_vnpy:
        print(f" {result_vnpy['total_return']*100:>14.2f}%", end="")
    else:
        print(f" {'N/A':>15s}", end="")
    if not df_1m.empty and result_1m:
        print(f" {result_1m['total_return']*100:>14.2f}%")
    else:
        print()
    print(f"  {'交易次数':20s} {result_simple['total_trades']:>15d}", end="")
    if result_vnpy:
        print(f" {result_vnpy['total_trades']:>15d}", end="")
    else:
        print(f" {'N/A':>15s}", end="")
    if not df_1m.empty and result_1m:
        print(f" {result_1m['total_trades']:>15d}")
    else:
        print()
    print("=" * 70)
