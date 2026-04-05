"""参数自动调优 — 每周回测不同参数组合，选Sharpe最优

测试维度：
- 调仓频率：5/7/10/15/20天
- 持仓数量：5/8/10/15只
- 止损线：-5%/-8%/-10%/-15%
- 止盈线：+10%/+15%/+20%

输出最佳参数到 knowledge/params_history.json
"""

import json
import itertools
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def backtest_with_params(daily_quote: pd.DataFrame, scores_history: dict,
                         params: dict) -> dict:
    """Run a single backtest with given parameters

    Args:
        daily_quote: full daily data
        scores_history: {date_str: scores_df} — pre-computed scores per rebalance date
        params: {rebalance_days, top_n, stop_loss, stop_profit}

    Returns:
        {sharpe, total_return, max_drawdown, trades, final_nav}
    """
    rebalance_days = params["rebalance_days"]
    top_n = params["top_n"]
    stop_loss = params["stop_loss"]
    stop_profit = params.get("stop_profit", 0.20)

    initial_capital = 1_000_000
    cash = initial_capital
    holdings = {}  # code -> {shares, cost_price, buy_date}
    nav_history = []
    trade_count = 0

    dates = sorted(daily_quote["date"].unique())
    if len(dates) < 20:
        return {"sharpe": 0, "total_return": 0, "max_drawdown": 0,
                "trades": 0, "final_nav": 1.0}
    start_date = pd.Timestamp(dates[0]) + timedelta(days=max(rebalance_days, 20))
    start_idx = 0
    for idx, d in enumerate(dates):
        if pd.Timestamp(d) >= start_date:
            start_idx = idx
            break

    last_rebalance = None

    for i in range(start_idx, len(dates)):
        date = dates[i]
        # Get prices for this date
        day = daily_quote[daily_quote["date"] == date]
        prices = dict(zip(day["code"].astype(str), day["close"]))
        date_str = str(date)[:10]

        # Check stop loss / stop profit for holdings
        for code in list(holdings.keys()):
            h = holdings[code]
            if code in prices and prices[code] > 0:
                pnl = (prices[code] - h["cost_price"]) / h["cost_price"]
                if pnl <= stop_loss:
                    # Stop loss
                    proceeds = h["shares"] * prices[code] * 0.999
                    cash += proceeds
                    trade_count += 1
                    del holdings[code]
                elif pnl >= stop_profit:
                    # Take profit
                    proceeds = h["shares"] * prices[code] * 0.999
                    cash += proceeds
                    trade_count += 1
                    del holdings[code]

        # Rebalance
        if last_rebalance is None or (date - last_rebalance).days >= rebalance_days:
            last_rebalance = date
            # Find nearest score date
            score_key = None
            for sk in sorted(scores_history.keys(), reverse=True):
                if sk <= date_str:
                    score_key = sk
                    break
            if score_key and scores_history[score_key] is not None:
                scores = scores_history[score_key]
                target_codes = set(scores.head(top_n).index.tolist())
                # Sell non-target
                for code in list(holdings.keys()):
                    if code not in target_codes and code in prices:
                        proceeds = holdings[code]["shares"] * prices[code] * 0.999
                        cash += proceeds
                        trade_count += 1
                        del holdings[code]
                # Buy new targets
                new_codes = target_codes - set(holdings.keys())
                n_buy = min(len(new_codes), top_n - len(holdings))
                if n_buy > 0 and cash > 0:
                    per_stock = cash / n_buy
                    for code in list(new_codes)[:n_buy]:
                        if code in prices and prices[code] > 0:
                            shares = int(per_stock / prices[code] / 100) * 100
                            if shares >= 100:
                                cost = shares * prices[code] * 1.001
                                if cost <= cash:
                                    cash -= cost
                                    holdings[code] = {
                                        "shares": shares,
                                        "cost_price": prices[code],
                                        "buy_date": date_str,
                                    }
                                    trade_count += 1

        # Record NAV
        mv = sum(h["shares"] * prices.get(code, h["cost_price"])
                 for code, h in holdings.items())
        nav = (cash + mv) / initial_capital
        nav_history.append({"date": date_str, "nav": nav})

    if not nav_history:
        return {"sharpe": 0, "total_return": 0, "max_drawdown": 0,
                "trades": 0, "final_nav": 1.0}

    # Calculate metrics
    navs = pd.Series([h["nav"] for h in nav_history])
    navs.index = pd.to_datetime([h["date"] for h in nav_history])
    daily_returns = navs.pct_change().dropna()

    total_return = (navs.iloc[-1] - 1) * 100
    peak = navs.cummax()
    drawdown = ((navs - peak) / peak).min() * 100

    # Sharpe (annualized)
    if len(daily_returns) > 5:
        sharpe = daily_returns.mean() / daily_returns.std() * (252 ** 0.5) if daily_returns.std() > 0 else 0
    else:
        sharpe = 0

    return {
        "sharpe": round(sharpe, 3),
        "total_return": round(total_return, 2),
        "max_drawdown": round(drawdown, 2),
        "trades": trade_count,
        "final_nav": round(navs.iloc[-1], 4),
    }


def optimize_params(daily_quote: pd.DataFrame, financial: pd.DataFrame = None,
                    codes: list = None) -> list[dict]:
    """Run parameter grid search

    Returns top 5 parameter combinations sorted by Sharpe
    """
    from src.factors.engine import FactorEngine
    engine = FactorEngine()

    if codes is None:
        codes = daily_quote["code"].unique().tolist()

    # Pre-compute scores for each potential rebalance date
    # Use a sample of dates to keep it fast
    dates = sorted(daily_quote["date"].unique())
    # Score every 5 days (covers all rebalance frequencies)
    score_dates = []
    for i, d in enumerate(dates):
        if i % 5 == 0 or i == len(dates) - 1:
            score_dates.append(d)

    logger.info(f"Pre-computing scores for {len(score_dates)} dates...")
    scores_history = {}
    for date in score_dates:
        date_str = str(date)[:10]
        dq_up_to = daily_quote[daily_quote["date"] <= date]
        data = {
            "daily_quote": dq_up_to[dq_up_to["code"].isin(codes)],
            "codes": codes,
            "financial": financial if financial is not None else pd.DataFrame(),
            "northbound": pd.DataFrame(),
        }
        try:
            scores = engine.score_all(data)
            scores_history[date_str] = scores
        except Exception as e:
            logger.warning(f"Score failed for {date_str}: {e}")
            scores_history[date_str] = None

    # Parameter grid
    grid = list(itertools.product(
        [5, 7, 10, 15, 20],     # rebalance_days
        [5, 8, 10, 15],          # top_n
        [-0.05, -0.08, -0.10, -0.15],  # stop_loss
        [0.10, 0.15, 0.20, 0.25],      # stop_profit
    ))

    # Limit combinations for speed — sample 40
    if len(grid) > 40:
        np.random.seed(42)
        grid = list(np.random.choice(len(grid), 40, replace=False))
        grid = [list(itertools.product([5,7,10,15,20],[5,8,10,15],[-0.05,-0.08,-0.10,-0.15],[0.10,0.15,0.20,0.25]))[i] for i in grid]

    logger.info(f"Testing {len(grid)} parameter combinations...")
    results = []

    for rb_days, top_n, stop_loss, stop_profit in grid:
        params = {
            "rebalance_days": rb_days,
            "top_n": top_n,
            "stop_loss": stop_loss,
            "stop_profit": stop_profit,
        }
        try:
            result = backtest_with_params(daily_quote, scores_history, params)
            result["params"] = params
            results.append(result)
        except Exception as e:
            logger.warning(f"Backtest failed: {params}")

    # Sort by Sharpe
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    logger.info(f"Optimization complete. Top Sharpe: {results[0]['sharpe']}")

    # Save results
    _save_best_params(results[:10])

    return results[:10]


def _save_best_params(results: list[dict]):
    """Save best params to knowledge/params_history.json"""
    params_dir = PROJECT_ROOT / "knowledge"
    params_dir.mkdir(parents=True, exist_ok=True)
    filepath = params_dir / "params_history.json"

    history = []
    if filepath.exists():
        try:
            history = json.loads(filepath.read_text())
        except Exception:
            history = []

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_period": "last 6 months",
        "results": results[:10],
    }
    history.append(entry)
    # Keep last 10 runs
    history = history[-10:]

    filepath.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    logger.info(f"参数优化结果已保存: {len(results)}条")

    # Record best as lesson
    best = results[0]
    p = best["params"]
    from src.evolution.knowledge import KnowledgeStore
    ks = KnowledgeStore()
    ks.record_external_learning(
        "参数优化",
        f"最优参数: 调仓{p['rebalance_days']}天, 持仓{p['top_n']}只, "
        f"止损{p['stop_loss']*100:.0f}%, 止盈{p['stop_profit']*100:.0f}% "
        f"(Sharpe={best['sharpe']}, 收益={best['total_return']}%)",
        "自动应用到下次调仓参数"
    )


def get_best_params() -> dict | None:
    """Get the best parameters from last optimization"""
    filepath = PROJECT_ROOT / "knowledge" / "params_history.json"
    if not filepath.exists():
        return None
    history = json.loads(filepath.read_text())
    if not history:
        return None
    best = history[-1]["results"][0]
    return best["params"]


def format_optimization_report(results: list[dict]) -> str:
    """Format optimization results"""
    if not results:
        return "暂无参数优化结果"

    lines = ["⚙️ **参数优化 Top 5**\n"]
    lines.append("| 排名 | 调仓天 | 持仓数 | 止损 | 止盈 | Sharpe | 收益% | 回撤% |")
    lines.append("|------|--------|--------|------|------|--------|-------|-------|")

    for i, r in enumerate(results[:5]):
        p = r["params"]
        lines.append(
            f"| {i+1} | {p['rebalance_days']}天 | {p['top_n']}只 | "
            f"{p['stop_loss']*100:.0f}% | {p['stop_profit']*100:.0f}% | "
            f"{r['sharpe']:.2f} | {r['total_return']:+.1f}% | {r['max_drawdown']:.1f}% |"
        )

    best = results[0]
    bp = best["params"]
    lines.append(f"\n🏆 **推荐**: 调仓{bp['rebalance_days']}天, {bp['top_n']}只持仓")
    return "\n".join(lines)
