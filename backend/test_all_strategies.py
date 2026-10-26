#!/usr/bin/env python3
"""
全策略回测测试 - 使用002202真实数据

对全部14个策略进行回测，检查：
1. 信号生成是否正常（有无信号、信号数量是否合理）
2. 交易模拟是否正常（有无交易、交易逻辑是否正确）
3. 收益率是否合理（异常值可能暗示bug）
4. 各策略买卖信号数量是否匹配
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('IS_VNPY', '1')

import pandas as pd
import numpy as np
from datetime import datetime
import json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.strategies.base import (
    STRATEGY_MAP, generate_signals, sma, ema, rsi, macd, bollinger,
    atr, donchian, kdj, cci
)


# ── 数据获取 ──────────────────────────────────────────────────────────────────

def fetch_from_stock_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 stock_data HTTPS API 获取真实行情数据"""
    import httpx

    base_url = "http://127.0.0.1:8000"
    if symbol.startswith("6") or symbol.startswith("9"):
        xt_symbol = f"{symbol}.SH"
    else:
        xt_symbol = f"{symbol}.SZ"

    start_fmt = start.replace("-", "")
    end_fmt = end.replace("-", "")

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

        if "amount" in df.columns:
            df = df.rename(columns={"amount": "turnover"})

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        print(f"  stock_data 返回 {len(df)} 根日K线")
        return df[["date", "open", "high", "low", "close", "volume", "turnover"]]

    except Exception as e:
        print(f"  stock_data 请求失败: {e}")
        return pd.DataFrame()


def fetch_from_akshare(symbol: str, start: str, end: str) -> pd.DataFrame:
    """通过 akshare 获取真实行情数据"""
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


def fetch_real_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """获取真实数据，优先stock_data，回退akshare"""
    print(f"  [尝试] stock_data 服务...")
    df = fetch_from_stock_data(symbol, start, end)
    if not df.empty:
        return df

    print(f"  [回退] akshare...")
    try:
        df = fetch_from_akshare(symbol, start, end)
        if not df.empty:
            return df
    except Exception as e:
        print(f"  akshare 失败: {e}")

    return pd.DataFrame()


# ── 回测引擎（简化版，与 backtest_service 逻辑一致） ──────────────────────────

def run_backtest_for_strategy(df: pd.DataFrame, class_name: str, setting: dict,
                               capital: float = 1000000,
                               commission_rate: float = 0.0003,
                               stamp_tax_rate: float = 0.001) -> dict:
    """对单个策略运行回测"""
    signals = generate_signals(class_name, df, setting)

    buy_signals = int((signals == 1).sum())
    sell_signals = int((signals == -1).sum())
    hold_signals = int((signals == 0).sum())

    # 检查信号有效性
    signal_issues = []
    if buy_signals == 0 and sell_signals == 0:
        signal_issues.append("无任何买卖信号")
    if buy_signals > 0 and sell_signals == 0:
        signal_issues.append(f"有买入信号({buy_signals})但无卖出信号")
    if sell_signals > 0 and buy_signals == 0:
        signal_issues.append(f"有卖出信号({sell_signals})但无买入信号")

    # 检查买卖信号严重不匹配
    if buy_signals > 0 and sell_signals > 0:
        ratio = max(buy_signals, sell_signals) / min(buy_signals, sell_signals)
        if ratio > 3:
            signal_issues.append(f"买卖信号严重不匹配: 买={buy_signals}, 卖={sell_signals}, 比值={ratio:.1f}")

    # 模拟交易
    is_grid = (class_name == "GridStrategy")
    position = 0
    avg_cost = 0.0
    cash = capital
    trades = []
    max_equity = capital
    max_drawdown = 0.0
    buy_date = None

    # 网格策略专用
    grid_position = 0
    grid_avg_cost = 0.0
    grid_buy_date = None

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        date_str = row["date"].strftime("%Y-%m-%d")
        signal = int(signals.iloc[i])

        if is_grid:
            grid_qty = setting.get("grid_quantity", 100)

            if signal == 1:
                cost = grid_qty * price
                commission = max(cost * commission_rate, 5)
                if cash >= cost + commission:
                    total_cost = grid_avg_cost * grid_position + price * grid_qty
                    grid_position += grid_qty
                    grid_avg_cost = total_cost / grid_position if grid_position > 0 else 0
                    cash -= (cost + commission)
                    grid_buy_date = date_str
                    trades.append({
                        "date": date_str, "side": "buy",
                        "price": round(price, 2), "quantity": grid_qty,
                        "pnl": 0,
                    })

            elif signal == -1 and grid_position > 0 and grid_buy_date != date_str:
                revenue = grid_qty * price
                commission = max(revenue * commission_rate, 5)
                stamp_tax = revenue * stamp_tax_rate
                pnl = (price - grid_avg_cost) * grid_qty - commission - stamp_tax
                cash += (revenue - commission - stamp_tax)
                grid_position -= grid_qty
                if grid_position <= 0:
                    grid_position = 0
                    grid_avg_cost = 0
                    grid_buy_date = None
                trades.append({
                    "date": date_str, "side": "sell",
                    "price": round(price, 2), "quantity": grid_qty,
                    "pnl": round(pnl, 2),
                })

            market_value = grid_position * price
        else:
            if signal == 1 and position == 0:
                buy_amount = cash * 0.9
                shares_100 = int(buy_amount / (price * 100)) * 100
                if shares_100 > 0:
                    shares = shares_100
                else:
                    shares = int(buy_amount / price)
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
                        "pnl": 0,
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

            market_value = position * price

        total_equity = cash + market_value
        if total_equity > max_equity:
            max_equity = total_equity
        drawdown = (max_equity - total_equity) / max_equity if max_equity > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    final_position = grid_position if is_grid else position
    final_equity = cash + final_position * float(df.iloc[-1]["close"])
    total_return = (final_equity - capital) / capital

    # 统计交易
    buy_trades = [t for t in trades if t["side"] == "buy"]
    sell_trades = [t for t in trades if t["side"] == "sell"]
    win_trades = [t for t in sell_trades if t["pnl"] > 0]
    lose_trades = [t for t in sell_trades if t["pnl"] < 0]
    win_rate = len(win_trades) / max(len(sell_trades), 1)

    # 交易逻辑检查
    trade_issues = []
    if len(buy_trades) == 0:
        trade_issues.append("无买入交易")
    if len(sell_trades) == 0 and len(buy_trades) > 0:
        trade_issues.append(f"有买入({len(buy_trades)})但无卖出交易")
    if len(buy_trades) > 0 and len(sell_trades) > 0:
        # 检查买卖交易数量差异
        trade_ratio = max(len(buy_trades), len(sell_trades)) / min(len(buy_trades), len(sell_trades))
        if trade_ratio > 2:
            trade_issues.append(f"买卖交易数量差异大: 买={len(buy_trades)}, 卖={len(sell_trades)}")

    # 检查是否有未平仓
    if is_grid:
        if grid_position > 0:
            trade_issues.append(f"网格策略有未平仓: {grid_position}股")
    else:
        if position > 0:
            trade_issues.append(f"有未平仓: {position}股, 买入价={avg_cost:.2f}")

    # 检查收益率异常
    return_issues = []
    if total_return > 2.0:
        return_issues.append(f"收益率异常高: {total_return*100:.1f}%")
    if total_return < -0.5:
        return_issues.append(f"收益率异常低: {total_return*100:.1f}%")

    # 检查信号与交易的一致性
    consistency_issues = []
    if not is_grid:
        # 非网格策略：买入信号数应与买入交易数大致对应
        if buy_signals > 0 and len(buy_trades) == 0:
            consistency_issues.append(f"有{buy_signals}个买入信号但无买入交易（可能资金不足）")
        if sell_signals > 0 and len(sell_trades) == 0:
            consistency_issues.append(f"有{sell_signals}个卖出信号但无卖出交易（可能无持仓）")

    return {
        "class_name": class_name,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_signals": hold_signals,
        "signal_issues": signal_issues,
        "buy_trades": len(buy_trades),
        "sell_trades": len(sell_trades),
        "win_trades": len(win_trades),
        "lose_trades": len(lose_trades),
        "win_rate": round(win_rate, 4),
        "trade_issues": trade_issues,
        "total_return": round(total_return, 4),
        "final_equity": round(final_equity, 2),
        "max_drawdown": round(max_drawdown, 4),
        "return_issues": return_issues,
        "consistency_issues": consistency_issues,
        "trades": trades,
    }


# ── 策略默认参数 ──────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "DoubleMaStrategy": {"fast_window": 10, "slow_window": 30},
    "MacdStrategy": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    "BollingerStrategy": {"boll_window": 20, "boll_dev": 2.0},
    "RsiStrategy": {"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30},
    "TurtleStrategy": {"entry_window": 20, "exit_window": 10},
    "KdjStrategy": {"kdj_window": 9, "k_smooth": 3, "d_smooth": 3},
    "CciStrategy": {"cci_window": 14, "cci_overbought": 100, "cci_oversold": -100},
    "TripleMaStrategy": {"fast_window": 5, "mid_window": 20, "slow_window": 60},
    "EmaCrossStrategy": {"fast_window": 12, "slow_window": 26},
    "VolumeMaStrategy": {"ma_window": 20, "vol_window": 20, "vol_ratio": 1.5},
    "MomentumStrategy": {"mom_window": 10, "mom_threshold": 0.03, "ma_window": 20},
    "AtrChannelStrategy": {"atr_window": 14, "atr_mult": 2.0, "ma_window": 20},
    "DualThrustStrategy": {"n_window": 4, "k_up": 0.5, "k_down": 0.5},
    "GridStrategy": {"grid_size": 0.02, "grid_quantity": 100},
}


# ── 详细信号分析 ──────────────────────────────────────────────────────────────

def analyze_signals_detail(df: pd.DataFrame, class_name: str, setting: dict):
    """详细分析策略信号，检查逻辑正确性"""
    signals = generate_signals(class_name, df, setting)

    print(f"\n  --- {class_name} 信号详情 ---")

    # 打印所有非零信号
    signal_dates = []
    for i in range(len(signals)):
        if signals.iloc[i] != 0:
            row = df.iloc[i]
            sig_type = '买入' if signals.iloc[i] == 1 else '卖出'
            signal_dates.append({
                "date": row['date'].strftime('%Y-%m-%d'),
                "type": sig_type,
                "close": row['close'],
                "index": i,
            })

    if not signal_dates:
        print("    [WARNING] 无任何信号!")
        return

    # 检查信号连续性（同一方向连续信号可能有问题）
    consecutive_buys = 0
    consecutive_sells = 0
    max_consecutive_buys = 0
    max_consecutive_sells = 0
    for s in signal_dates:
        if s["type"] == "买入":
            consecutive_buys += 1
            consecutive_sells = 0
            max_consecutive_buys = max(max_consecutive_buys, consecutive_buys)
        else:
            consecutive_sells += 1
            consecutive_buys = 0
            max_consecutive_sells = max(max_consecutive_sells, consecutive_sells)

    if max_consecutive_buys > 2:
        print(f"    [WARNING] 连续买入信号最大={max_consecutive_buys}（可能重复触发）")
    if max_consecutive_sells > 2:
        print(f"    [WARNING] 连续卖出信号最大={max_consecutive_sells}（可能重复触发）")

    # 打印前10个和后5个信号
    show_count = min(10, len(signal_dates))
    print(f"    前{show_count}个信号:")
    for s in signal_dates[:show_count]:
        print(f"      {s['date']}: {s['type']} @ {s['close']:.2f}")
    if len(signal_dates) > show_count:
        print(f"    ... 共{len(signal_dates)}个信号")
        print(f"    最后3个信号:")
        for s in signal_dates[-3:]:
            print(f"      {s['date']}: {s['type']} @ {s['close']:.2f}")


# ── 主程序 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    symbol = "002202"
    start_date = "2024-04-30"
    end_date = "2025-04-30"
    capital = 1000000

    print("=" * 80)
    print(f"全策略回测测试: {symbol}")
    print(f"  日期范围: {start_date} ~ {end_date}")
    print(f"  初始资金: {capital:,.0f}")
    print(f"  策略数量: {len(STRATEGY_MAP)}")
    print("=" * 80)

    # 1. 获取数据
    print("\n[1] 获取真实日K线数据...")
    df = fetch_real_data(symbol, start_date, end_date)
    if df.empty:
        print("ERROR: 无法获取数据，退出")
        sys.exit(1)

    print(f"  获取到 {len(df)} 根日K线")
    print(f"  日期范围: {df.iloc[0]['date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"  价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
    print(f"  数据列: {list(df.columns)}")

    # 检查数据完整性
    print(f"\n  数据质量检查:")
    print(f"    NaN统计: {df.isnull().sum().to_dict()}")
    print(f"    零成交量天数: {(df['volume'] == 0).sum()}")
    print(f"    价格异常(涨跌幅>15%): ", end="")
    pct_change = df['close'].pct_change().abs()
    abnormal = (pct_change > 0.15).sum()
    print(f"{abnormal}天")

    # 2. 对每个策略运行回测
    print("\n[2] 运行全策略回测...")
    results = {}
    all_issues = {}

    for class_name in STRATEGY_MAP:
        setting = DEFAULT_SETTINGS.get(class_name, {})
        print(f"\n  >>> {class_name} (参数: {setting})")

        try:
            result = run_backtest_for_strategy(df, class_name, setting, capital)
            results[class_name] = result

            # 收集问题
            issues = []
            issues.extend(result["signal_issues"])
            issues.extend(result["trade_issues"])
            issues.extend(result["return_issues"])
            issues.extend(result["consistency_issues"])

            if issues:
                all_issues[class_name] = issues
                for issue in issues:
                    print(f"    [ISSUE] {issue}")

            print(f"    信号: 买={result['buy_signals']}, 卖={result['sell_signals']}, 持有={result['hold_signals']}")
            print(f"    交易: 买={result['buy_trades']}, 卖={result['sell_trades']}, 胜率={result['win_rate']*100:.1f}%")
            print(f"    收益: {result['total_return']*100:.2f}%, 最大回撤={result['max_drawdown']*100:.2f}%")

        except Exception as e:
            print(f"    [ERROR] 回测失败: {e}")
            import traceback
            traceback.print_exc()
            results[class_name] = {"error": str(e)}
            all_issues[class_name] = [f"回测异常: {e}"]

    # 3. 详细信号分析（对有问题的策略）
    print("\n\n[3] 详细信号分析...")
    for class_name in all_issues:
        setting = DEFAULT_SETTINGS.get(class_name, {})
        try:
            analyze_signals_detail(df, class_name, setting)
        except Exception as e:
            print(f"    [ERROR] 分析失败: {e}")

    # 4. 汇总报告
    print("\n\n" + "=" * 80)
    print("汇总报告")
    print("=" * 80)

    print(f"\n{'策略':25s} {'买信号':>6s} {'卖信号':>6s} {'买交易':>6s} {'卖交易':>6s} {'胜率':>7s} {'收益率':>8s} {'最大回撤':>8s} {'问题数':>6s}")
    print("-" * 95)

    for class_name in STRATEGY_MAP:
        r = results.get(class_name, {})
        if "error" in r:
            print(f"{class_name:25s} {'ERROR':>6s} {'':>6s} {'':>6s} {'':>6s} {'':>7s} {'':>8s} {'':>8s} {'1':>6s}")
            continue

        issue_count = len(all_issues.get(class_name, []))
        issue_str = str(issue_count) if issue_count > 0 else "0"
        print(f"{class_name:25s} {r['buy_signals']:>6d} {r['sell_signals']:>6d} {r['buy_trades']:>6d} {r['sell_trades']:>6d} {r['win_rate']*100:>6.1f}% {r['total_return']*100:>7.2f}% {r['max_drawdown']*100:>7.2f}% {issue_str:>6s}")

    # 5. 问题汇总
    if all_issues:
        print(f"\n\n{'='*80}")
        print("发现的问题:")
        print("=" * 80)
        for class_name, issues in all_issues.items():
            print(f"\n  {class_name}:")
            for issue in issues:
                print(f"    - {issue}")
    else:
        print(f"\n  所有策略均无问题!")

    # 6. 买入并持有基准
    buy_hold_return = (float(df.iloc[-1]["close"]) - float(df.iloc[0]["close"])) / float(df.iloc[0]["close"])
    print(f"\n\n基准: 买入并持有收益率 = {buy_hold_return*100:.2f}%")
    print(f"  期初价: {df.iloc[0]['close']:.2f}, 期末价: {df.iloc[-1]['close']:.2f}")
