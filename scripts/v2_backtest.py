#!/usr/bin/env python3
"""StockRadar V2回测 — 暂停有害因子后的效果

基于IC分析结果：
- 暂停7个有害因子（IC10 < -0.02）
- 暂停基本面全类（IC=0，数据可能缺失）
- 暂停LLM全类（IC=0，数据可能缺失）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from loguru import logger
from src.factors.engine import FactorEngine

# 需要暂停的有害因子
SUSPEND_FACTORS = [
    # IC10 < -0.02 的有害因子
    "high_low_position",      # IC10=-0.0906
    "williams_r",             # IC10=-0.0708
    "limit_up_count",         # IC10=-0.0656
    "volume_price_divergence",# IC10=-0.0589
    "pe_percentile",          # IC10=-0.0566
    "amplitude",              # IC10=-0.0457
    "volatility_20d",         # IC10=-0.0250
]

# 需要暂停的整类（IC=0，数据缺失）
SUSPEND_CATEGORIES = [
    # "fundamental",  # 暂不暂停，部分因子可能有效
    "llm",           # IC全部为0，数据缺失
]

# V2类别权重（基于IC分析结果）
V2_WEIGHTS = {
    "capital_flow": 0.10,
    "fundamental": 0.15,     # 大幅降低（大部分IC=0）
    "llm": 0.00,             # 暂停
    "market_sentiment": 0.15, # 降低（2个有害因子）
    "technical": 0.60,        # 大幅提升（大部分有效！）
}

# V3类别权重（更激进）
V3_WEIGHTS = {
    "capital_flow": 0.08,
    "fundamental": 0.10,
    "llm": 0.00,
    "market_sentiment": 0.12,
    "technical": 0.70,
}

# 旧配置
OLD_WEIGHTS = {
    "capital_flow": 0.20,
    "fundamental": 0.35,
    "llm": 0.10,
    "market_sentiment": 0.15,
    "technical": 0.20,
}


def create_engine_v2(weights: dict, suspend_factors: list, suspend_categories: list) -> FactorEngine:
    """创建V2因子引擎"""
    engine = FactorEngine()
    
    # 暂停有害因子
    for factor_name in suspend_factors:
        engine.adjust_factor_weight(factor_name, 0)
        # 标记为暂停
        for cat_name, cat_config in engine.config["categories"].items():
            if factor_name in cat_config.get("factors", {}):
                cat_config["factors"][factor_name]["_suspended"] = True
                break
    
    # 暂停整类
    for cat_name in suspend_categories:
        if cat_name in engine.config["categories"]:
            engine.config["categories"][cat_name]["weight"] = 0
    
    # 调整类别权重
    for cat_name, cat_weight in weights.items():
        if cat_name in engine.config["categories"]:
            engine.config["categories"][cat_name]["weight"] = cat_weight
    
    return engine


def run_backtest(daily_quote: pd.DataFrame, engine: FactorEngine,
                 top_n: int = 10, rebalance_days: int = 10,
                 stop_loss: float = -0.15, start_date: str = None,
                 end_date: str = None, initial_capital: float = 1_000_000) -> dict:
    """回测"""
    label = getattr(engine, '_label', 'unknown')
    
    if start_date:
        daily_quote = daily_quote[daily_quote["date"] >= pd.Timestamp(start_date)]
    if end_date:
        daily_quote = daily_quote[daily_quote["date"] <= pd.Timestamp(end_date)]

    trading_dates = sorted(daily_quote["date"].unique())
    if not trading_dates:
        return {"nav_series": pd.Series(dtype=float), "trades": []}

    cash = initial_capital
    positions = {}
    nav_list = []
    trades = []
    prev_portfolio = []

    price_map = {}
    for _, row in daily_quote.iterrows():
        d = row["date"]
        if d not in price_map:
            price_map[d] = {}
        price_map[d][row["code"]] = float(row["close"])

    for i, date in enumerate(trading_dates):
        date_str = str(date.date()) if hasattr(date, "date") else str(date)
        prices_today = price_map.get(date, {})

        if i % rebalance_days == 0:
            hist_data = daily_quote[daily_quote["date"] <= date]
            codes = sorted(hist_data["code"].unique())
            data = {"daily_quote": hist_data, "codes": codes}

            try:
                scores = engine.score_all(data, date_str)
                if not scores.empty:
                    scores = scores.sort_values("score_total", ascending=False)
                    target_portfolio = scores.head(top_n).index.tolist()
                else:
                    target_portfolio = []
            except Exception as e:
                target_portfolio = prev_portfolio if prev_portfolio else []

            prev_portfolio = target_portfolio

        # 止损
        to_sell = []
        for code, pos in list(positions.items()):
            cp = prices_today.get(code)
            if cp and (cp - pos["cost_price"]) / pos["cost_price"] <= stop_loss:
                to_sell.append(code)

        if i % rebalance_days == 0:
            for code in list(positions.keys()):
                if code not in target_portfolio and code not in to_sell:
                    to_sell.append(code)

        # 卖出
        for code in to_sell:
            pos = positions.get(code)
            if not pos:
                continue
            cp = prices_today.get(code)
            if not cp:
                continue
            shares = pos["shares"]
            amount = shares * cp
            cash += amount - max(amount * 0.00025, 5) - amount * 0.001 - amount * 0.002
            trades.append({"date": date_str, "code": code, "action": "sell", "shares": shares, "price": cp})
            del positions[code]

        # 买入
        if i % rebalance_days == 0 and target_portfolio:
            buy_codes = [c for c in target_portfolio if c not in positions and prices_today.get(c)]
            if buy_codes and cash > 0:
                per_stock = cash / max(len(buy_codes) + len(positions), 1)
                for code in buy_codes:
                    cp = prices_today.get(code)
                    if not cp or cp <= 0:
                        continue
                    buy_cash = min(per_stock, cash * 0.95)
                    shares = int(buy_cash / (cp * 1.002)) // 100 * 100
                    if shares < 100:
                        continue
                    amount = shares * cp
                    cost = amount + max(amount * 0.00025, 5) + amount * 0.002
                    if cost > cash:
                        continue
                    cash -= cost
                    positions[code] = {"shares": shares, "cost_price": cp + amount * 0.002 / shares}
                    trades.append({"date": date_str, "code": code, "action": "buy", "shares": shares, "price": cp})

        mv = sum(p["shares"] * prices_today.get(c, p["cost_price"]) for c, p in positions.items())
        nav_list.append({"date": date_str, "nav": (cash + mv) / initial_capital})

    return {"nav_series": pd.DataFrame(nav_list).set_index("date")["nav"], "trades": trades}


def analyze(result: dict) -> dict:
    nav = result["nav_series"]
    if nav.empty:
        return {"error": True}
    trades = result["trades"]
    total_return = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    days = max((pd.Timestamp(nav.index[-1]) - pd.Timestamp(nav.index[0])).days, 1)
    daily_ret = nav.pct_change().dropna()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    cummax = nav.cummax()
    max_dd = ((nav - cummax) / cummax).min() * 100
    sells = [t for t in trades if t["action"] == "sell"]
    wins = sum(1 for t in sells if prices_ok(t) and t.get("pnl_pct", 0) > 0) if False else 0
    return {
        "total_return": total_return,
        "annual_return": total_return * 365 / days,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trades": len(trades),
        "final_nav": nav.iloc[-1],
    }


def main():
    print("=" * 70)
    print("StockRadar V2/V3 回测 — 暂停有害因子")
    print("=" * 70)

    parquet_path = Path(__file__).parent.parent / "data" / "parquet" / "hs300_daily.parquet"
    daily_quote = pd.read_parquet(parquet_path)
    daily_quote["date"] = pd.to_datetime(daily_quote["date"])

    configs = [
        ("旧配置", OLD_WEIGHTS, [], [], -0.15),
        ("V2(暂停7因子+LLM)", V2_WEIGHTS, SUSPEND_FACTORS, SUSPEND_CATEGORIES, -0.15),
        ("V3(技术70%)", V3_WEIGHTS, SUSPEND_FACTORS, SUSPEND_CATEGORIES, -0.12),
    ]

    periods = [
        ("2025-10-01", "2026-03-31", "最近6个月"),
        ("2024-01-02", "2026-03-31", "全周期"),
    ]

    for start, end, desc in periods:
        print(f"\n{'='*70}")
        print(f"📊 {desc}: {start} ~ {end}")
        print(f"{'='*70}")

        results = []
        for label, weights, suspend_f, suspend_c, sl in configs:
            engine = create_engine_v2(weights, suspend_f, suspend_c)
            engine._label = label
            result = run_backtest(daily_quote, engine, stop_loss=sl, start_date=start, end_date=end)
            stats = analyze(result)
            stats["label"] = label
            results.append(stats)
            print(f"\n  {label}: 收益{stats['total_return']:+.2f}%, 夏普{stats['sharpe']:.2f}, 回撤{stats['max_drawdown']:.2f}%, 交易{stats['trades']}笔")

        # 对比
        if len(results) >= 2:
            base = results[0]
            print(f"\n  {'指标':<14} {'旧配置':>10} {'V2':>10} {'V3':>10}")
            print(f"  {'-'*50}")
            for key, fmt in [("total_return", ".2f"), ("sharpe", ".2f"), ("max_drawdown", ".2f"), ("trades", "d")]:
                vals = []
                for r in results:
                    v = r.get(key, 0)
                    vals.append(f"{v:{fmt}}" if isinstance(v, float) else str(v))
                print(f"  {key:<14} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")


if __name__ == "__main__":
    main()
