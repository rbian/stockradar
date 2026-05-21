#!/usr/bin/env python3
"""StockRadar 对比回测 - 旧配置 vs 新配置

从parquet读取数据，分别用旧/新权重运行因子引擎，模拟交易。
"""

import sys
from pathlib import Path
import copy

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

from src.factors.engine import FactorEngine

# 旧配置类别权重
OLD_WEIGHTS = {
    "capital_flow": 0.20,
    "fundamental": 0.35,
    "llm": 0.10,
    "market_sentiment": 0.15,
    "technical": 0.20,
}

# 新配置类别权重 (2026-05-20重构)
NEW_WEIGHTS = {
    "capital_flow": 0.15,
    "fundamental": 0.50,
    "llm": 0.10,
    "market_sentiment": 0.15,
    "technical": 0.10,
}


def load_data():
    """从parquet加载数据"""
    parquet_path = Path(__file__).parent.parent / "data" / "parquet" / "hs300_daily.parquet"
    df = pd.read_parquet(parquet_path)
    df["date"] = pd.to_datetime(df["date"])
    logger.info(f"加载 {len(df)} 行, {df['code'].nunique()} 只股票, {df['date'].min()} ~ {df['date'].max()}")
    return df


def create_engine_with_weights(weights: dict) -> FactorEngine:
    """创建指定权重的因子引擎"""
    engine = FactorEngine()
    for cat_name, cat_weight in weights.items():
        if cat_name in engine.config["categories"]:
            engine.config["categories"][cat_name]["weight"] = cat_weight
    return engine


def run_backtest(daily_quote: pd.DataFrame, weights: dict,
                 top_n: int = 10, rebalance_days: int = 10,
                 stop_loss: float = -0.15, start_date: str = None,
                 end_date: str = None, initial_capital: float = 1_000_000) -> dict:
    """简化回测引擎

    每N天重新评分选股，模拟买入卖出。
    """
    logger.info(f"回测开始: weights={weights}, stop_loss={stop_loss}")

    # 日期范围
    if start_date:
        daily_quote = daily_quote[daily_quote["date"] >= pd.Timestamp(start_date)]
    if end_date:
        daily_quote = daily_quote[daily_quote["date"] <= pd.Timestamp(end_date)]

    trading_dates = sorted(daily_quote["date"].unique())
    if len(trading_dates) == 0:
        logger.error("无交易日")
        return {"nav_series": pd.Series(dtype=float), "trades": []}

    # 创建因子引擎
    engine = create_engine_with_weights(weights)

    # 状态
    cash = initial_capital
    positions = {}  # code -> {"shares": int, "cost_price": float}
    nav_list = []
    trades = []
    prev_portfolio = []

    # 找到所有日期的收盘价映射
    price_map = {}
    for _, row in daily_quote.iterrows():
        d = row["date"]
        if d not in price_map:
            price_map[d] = {}
        price_map[d][row["code"]] = float(row["close"])

    for i, date in enumerate(trading_dates):
        date_str = str(date.date()) if hasattr(date, "date") else str(date)
        prices_today = price_map.get(date, {})

        # 每 rebalance_days 天重新选股
        if i % rebalance_days == 0:
            # 截取截止当日的数据
            hist_data = daily_quote[daily_quote["date"] <= date]
            codes = sorted(hist_data["code"].unique())

            data = {
                "daily_quote": hist_data,
                "codes": codes,
            }

            # 评分
            try:
                scores = engine.score_all(data, date_str)
                if not scores.empty:
                    scores = scores.sort_values("score_total", ascending=False)
                    target_portfolio = scores.head(top_n).index.tolist()
                else:
                    target_portfolio = []
            except Exception as e:
                logger.warning(f"评分失败 {date_str}: {e}")
                target_portfolio = prev_portfolio if prev_portfolio else []

            prev_portfolio = target_portfolio

        # 止损检查
        to_sell = []
        for code, pos in list(positions.items()):
            current_price = prices_today.get(code)
            if current_price is None:
                continue

            pnl_pct = (current_price - pos["cost_price"]) / pos["cost_price"]
            if pnl_pct <= stop_loss:
                to_sell.append(code)

        # 重新选股导致的卖出
        if i % rebalance_days == 0:
            for code in list(positions.keys()):
                if code not in target_portfolio and code not in to_sell:
                    to_sell.append(code)

        # 执行卖出
        for code in to_sell:
            pos = positions.get(code)
            if not pos:
                continue
            current_price = prices_today.get(code)
            if current_price is None:
                continue

            shares = pos["shares"]
            amount = shares * current_price
            commission = max(amount * 0.00025, 5)
            stamp_tax = amount * 0.001
            slippage = amount * 0.002

            sell_amount = amount - commission - stamp_tax - slippage
            cash += sell_amount

            pnl = (current_price - pos["cost_price"]) / pos["cost_price"] * 100
            trades.append({
                "date": date_str,
                "code": code,
                "action": "sell",
                "shares": shares,
                "price": current_price,
                "pnl_pct": pnl,
                "reason": "stop_loss" if pnl <= stop_loss else "rebalance",
            })

            del positions[code]

        # 买入
        if i % rebalance_days == 0 and target_portfolio:
            buy_codes = [c for c in target_portfolio if c not in positions and prices_today.get(c)]
            if buy_codes and cash > 0:
                per_stock = cash / min(len(buy_codes) + len(positions), top_n)
                per_stock = min(per_stock, cash / max(len(buy_codes), 1))

                for code in buy_codes:
                    current_price = prices_today.get(code)
                    if current_price is None or current_price <= 0:
                        continue

                    buy_cash = min(per_stock, cash * 0.95)
                    shares = int(buy_cash / (current_price * 1.002)) // 100 * 100
                    if shares < 100:
                        continue

                    amount = shares * current_price
                    commission = max(amount * 0.00025, 5)
                    slippage = amount * 0.002
                    total_cost = amount + commission + slippage

                    if total_cost > cash:
                        continue

                    cash -= total_cost
                    positions[code] = {
                        "shares": shares,
                        "cost_price": current_price + slippage / shares,
                    }

                    trades.append({
                        "date": date_str,
                        "code": code,
                        "action": "buy",
                        "shares": shares,
                        "price": current_price,
                    })

        # 计算净值
        market_value = sum(
            pos["shares"] * prices_today.get(code, pos["cost_price"])
            for code, pos in positions.items()
        )
        total_assets = cash + market_value
        nav = total_assets / initial_capital
        nav_list.append({"date": date_str, "nav": nav})

        if (i + 1) % 100 == 0 or i == len(trading_dates) - 1:
            logger.info(f"  进度 {i+1}/{len(trading_dates)}: {date_str} nav={nav:.4f}")

    nav_series = pd.DataFrame(nav_list).set_index("date")["nav"]
    return {"nav_series": nav_series, "trades": trades}


def analyze_result(result: dict, label: str) -> dict:
    """分析回测结果"""
    nav = result["nav_series"]
    trades = result["trades"]

    if nav.empty:
        return {"label": label, "error": "empty"}

    total_return = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    days = (nav.index[-1] - nav.index[0]).days if hasattr(nav.index[-1], 'days') else 1
    annual_return = total_return * 365 / days

    daily_ret = nav.pct_change().dropna()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    max_drawdown = drawdown.min() * 100

    # 交易统计
    sell_trades = [t for t in trades if t["action"] == "sell"]
    wins = sum(1 for t in sell_trades if t.get("pnl_pct", 0) > 0)
    total_sells = len(sell_trades)
    win_rate = wins / total_sells * 100 if total_sells > 0 else 0

    return {
        "label": label,
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_trades": len(trades),
        "sell_trades": total_sells,
        "win_rate": win_rate,
        "final_nav": nav.iloc[-1],
        "start_date": str(nav.index[0])[:10],
        "end_date": str(nav.index[-1])[:10],
    }


def main():
    print("=" * 60)
    print("StockRadar 对比回测")
    print("=" * 60)

    daily_quote = load_data()

    # 测试区间
    periods = [
        ("2025-10-01", "2026-03-31", "最近6个月(重点)"),
        ("2024-01-02", "2026-03-31", "全周期"),
    ]

    all_results = []

    for start, end, desc in periods:
        print(f"\n{'='*60}")
        print(f"📊 {desc}: {start} ~ {end}")
        print(f"{'='*60}")

        # 旧配置回测
        print(f"\n🔄 旧配置 (基本面35% 技术20% 止损-15%)...")
        old_result = run_backtest(
            daily_quote, OLD_WEIGHTS,
            stop_loss=-0.15,
            start_date=start, end_date=end,
        )
        old_stats = analyze_result(old_result, "旧配置")
        all_results.append(old_stats)

        # 新配置回测
        print(f"\n🔄 新配置 (基本面50% 技术10% 止损-12%)...")
        new_result = run_backtest(
            daily_quote, NEW_WEIGHTS,
            stop_loss=-0.12,
            start_date=start, end_date=end,
        )
        new_stats = analyze_result(new_result, "新配置")
        all_results.append(new_stats)

        # 对比输出
        print(f"\n{'='*60}")
        print(f"📋 对比结果 ({desc})")
        print(f"{'='*60}")
        print(f"{'指标':<20} {'旧配置':>12} {'新配置':>12} {'变化':>12}")
        print("-" * 60)

        metrics = [
            ("总收益%", "total_return"),
            ("年化收益%", "annual_return"),
            ("夏普比率", "sharpe"),
            ("最大回撤%", "max_drawdown"),
            ("总交易数", "total_trades"),
            ("卖出次数", "sell_trades"),
            ("胜率%", "win_rate"),
        ]

        for label, key in metrics:
            old_val = old_stats.get(key, 0)
            new_val = new_stats.get(key, 0)
            diff = new_val - old_val
            sign = "+" if diff > 0 else ""
            if key in ("max_drawdown",):
                # 回撤越小越好，反向标记
                better = "✅" if diff > 0 else "❌"
            elif key in ("sharpe", "win_rate", "total_return", "annual_return"):
                better = "✅" if diff > 0 else "❌"
            else:
                better = ""

            if isinstance(old_val, float):
                print(f"{label:<18} {old_val:>12.2f} {new_val:>12.2f} {sign}{diff:>10.2f} {better}")
            else:
                print(f"{label:<18} {old_val:>12} {new_val:>12} {sign}{diff:>10.0f} {better}")

    # 最终结论
    print(f"\n{'='*60}")
    print(f"🎯 总结")
    print(f"{'='*60}")

    for r in all_results:
        label = r["label"]
        ret = r["total_return"]
        dd = r["max_drawdown"]
        sharpe = r["sharpe"]
        wr = r["win_rate"]
        print(f"  {label}: 收益{ret:+.2f}%, 回撤{dd:.2f}%, 夏普{sharpe:.2f}, 胜率{wr:.1f}%")


if __name__ == "__main__":
    main()
