"""Optuna Factor Weight Optimizer — 因子权重自动优化

Inspired by AShare-AI-Stock-Picker's Optuna usage.
Uses historical data to find optimal factor weights that maximize backtest returns.

Strategy: optimize category weights + top-N factor weights within each category.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

import optuna
from optuna.samplers import TPESampler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def run_optuna_optimization(n_trials: int = 50, backtest_days: int = 60) -> dict:
    """Run Optuna optimization on factor weights

    Args:
        n_trials: number of optimization trials
        backtest_days: days of historical data for backtesting

    Returns:
        {best_params, best_score, trial_results}
    """
    logger.info(f"Starting Optuna optimization: {n_trials} trials, {backtest_days}d backtest")

    # Load historical data
    data = _load_historical_data()
    if data is None:
        return {"error": "No historical data available"}

    # Load current factor config
    config_path = CONFIG_DIR / "factors.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        factor_config = yaml.safe_load(f)

    # Define parameter space
    categories = list(factor_config["categories"].keys())
    cat_names = list(factor_config["categories"].keys())

    # Track trial results
    trial_log = []

    def objective(trial):
        """Objective: maximize risk-adjusted return"""
        # Sample category weights
        cat_weights = {}
        for cat in categories:
            cat_weights[cat] = trial.suggest_float(f"cat_{cat}", 0.1, 3.0)

        # Normalize category weights
        total = sum(cat_weights.values())
        cat_weights = {k: v / total for k, v in cat_weights.items()}

        # Sample top factor weights per category (top 3 most impactful)
        factor_weights = {}
        for cat in categories:
            factors = factor_config["categories"][cat].get("factors", {})
            for fname in list(factors.keys())[:3]:  # top 3 per category
                fw = trial.suggest_float(f"fw_{cat}_{fname}", 0.2, 2.0)
                factor_weights[f"{cat}.{fname}"] = fw

        # Run simplified backtest
        score = _quick_backtest(data, cat_weights, factor_weights, backtest_days,
                                score_cache=score_cache)

        trial_log.append({
            "trial": trial.number,
            "score": score,
            "cat_weights": cat_weights,
            "factor_weights": {k: round(v, 3) for k, v in factor_weights.items()},
        })

        return score

    # Pre-compute scores once for all trials
    score_cache = _precompute_scores(data)
    if not score_cache:
        logger.warning("Score cache empty, using fallback")
        score_cache = None
    # Run optimization
    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=42),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    best_score = study.best_value

    # Format results
    result = {
        "best_score": round(best_score, 4),
        "best_category_weights": {k.replace("cat_", ""): round(v, 3) for k, v in best.items() if k.startswith("cat_")},
        "best_factor_weights": {k.replace("fw_", ""): round(v, 3) for k, v in best.items() if k.startswith("fw_")},
        "n_trials": n_trials,
        "improvement": f"+{(best_score - trial_log[0]['score']) * 100:.1f}%" if len(trial_log) > 1 else "N/A",
    }

    # Save results
    _save_optimization(result)

    logger.info(f"Optimization done: best score={best_score:.4f}")
    logger.info(f"  Category weights: {result['best_category_weights']}")

    return result


def _load_historical_data() -> dict | None:
    """Load historical stock data for backtesting"""
    # Try multiple possible data paths
    for p in ["data/parquet/hs300_daily.parquet", "data/stock_data.parquet"]:
        path = PROJECT_ROOT / p
        if path.exists():
            parquet_path = path
            break
    else:
        logger.warning("No historical data found in known paths")
        return None

    data_dir = PROJECT_ROOT / "data"
    parquet_path = PROJECT_ROOT / "data/parquet/hs300_daily.parquet"

    if not parquet_path.exists():
        logger.warning("No parquet data found")
        return None

    try:
        df = pd.read_parquet(parquet_path)
        if df.empty:
            return None

        # Get latest date for each stock
        latest = df.groupby("code").last().reset_index()
        codes = latest["code"].tolist()

        return {
            "df": df,
            "codes": codes,
            "latest": latest,
            "date_range": f"{df['date'].min()} ~ {df['date'].max()}",
        }
    except Exception as e:
        logger.warning(f"Data load failed: {e}")
        return None



def _precompute_scores(data: dict) -> dict:
    """Pre-compute factor scores for all rebalance dates using FactorEngine."""
    from src.factors.engine import FactorEngine

    df = data["df"]
    dates = sorted(df["date"].unique())
    # Use last 20 rebalance points (~100 trading days) for speed
    n_rebalance = 20
    rebalance_dates = dates[-(n_rebalance + 1):-1] if len(dates) > n_rebalance + 1 else dates[-(len(dates)//5+1):-1]

    logger.info(f"Pre-computing scores for {len(rebalance_dates)} dates...")
    engine = FactorEngine()
    score_cache = {}

    for i, d in enumerate(rebalance_dates):
        d_str = str(d)[:10]
        hist_data = df[df["date"] <= d].copy()
        day_data = df[df["date"] == d].copy()
        if len(day_data) < 20:
            continue
        codes = day_data["code"].astype(str).str[:6].tolist()
        try:
            scores_df = engine.score_all({"daily_quote": hist_data, "codes": codes})
            if not scores_df.empty:
                score_cache[d_str] = scores_df[["score_fundamental", "score_technical", "score_capital_flow", "score_llm", "score_market_sentiment", "score_total"]].to_dict("index")
        except Exception:
            pass
        if (i + 1) % 5 == 0:
            logger.info(f"  Scored {i+1}/{len(rebalance_dates)} dates")

    logger.info(f"Score cache ready: {len(score_cache)} dates")
    return score_cache


def _quick_backtest(data: dict, cat_weights: dict, factor_weights: dict, days: int,
                    score_cache: dict = None) -> float:
    """Backtest using pre-computed scores or price momentum fallback."""
    df = data["df"]
    if df.empty or "date" not in df.columns:
        return 0.0

    # Build price lookup
    price_map = {}
    for _, row in df.iterrows():
        key = (str(row["code"])[:6], str(row["date"])[:10])
        price_map[key] = row["close"]

    if score_cache:
        rebalance_dates = sorted(score_cache.keys())
    else:
        dates = sorted(df["date"].unique())
        rebalance_dates = dates[-(days // 5 + 1):-1]

    returns = []
    # A-share trading costs: commission 0.025% each way + stamp tax 0.05% (sell only)
    BUY_COST = 0.00025
    SELL_COST = 0.00075  # 0.025% commission + 0.05% stamp tax
    for i in range(len(rebalance_dates) - 1):
        d_str, d_next_str = rebalance_dates[i], rebalance_dates[i + 1]

        if score_cache and d_str in score_cache:
            stock_scores = score_cache[d_str]
            # Apply trial category weights to compute weighted score
            weighted = {}
            for code, info in stock_scores.items():
                if isinstance(info, dict):
                    s = 0.0
                    for cat, w in cat_weights.items():
                        col = f"score_{cat}"
                        if col in info:
                            s += info[col] * w
                    weighted[code] = s
            top_codes = sorted(weighted, key=weighted.get, reverse=True)[:10]
        else:
            # Fallback: pick top by price momentum
            day_data = df[df["date"] == d_str].copy() if d_str in price_map.values() else pd.DataFrame()
            if day_data.empty or len(day_data) < 20:
                continue
            top_codes = day_data.nlargest(10, "change_pct")["code"].astype(str).str[:6].tolist()

        port_return, matched = 0.0, 0
        for code in top_codes:
            curr_p = price_map.get((str(code)[:6], d_str))
            next_p = price_map.get((str(code)[:6], d_next_str))
            if curr_p and next_p and curr_p > 0:
                gross_ret = (next_p - curr_p) / curr_p
                net_ret = gross_ret - BUY_COST - SELL_COST  # each rebalance = sell old + buy new
                port_return += net_ret
                matched += 1

        if matched > 0:
            returns.append(port_return / matched)

    if len(returns) < 3:
        return 0.0

    returns = np.array(returns)
    mean_ret, std_ret = returns.mean(), returns.std()
    if std_ret == 0:
        return 0.0

    sharpe = mean_ret / std_ret * np.sqrt(252)
    total = (1 + returns).prod() - 1
    return sharpe * (1 if mean_ret >= 0 else -1) * (1 + abs(total))

def apply_optimized_weights(result: dict) -> bool:
    """Apply optimized weights to factor config (human approval needed)"""
    if "error" in result:
        return False

    config_path = CONFIG_DIR / "factors.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Apply category weights
    for cat, weight in result.get("best_category_weights", {}).items():
        if cat in config["categories"]:
            config["categories"][cat]["weight"] = weight
            logger.info(f"  {cat}: weight → {weight:.3f}")

    # Apply factor weights
    for key, weight in result.get("best_factor_weights", {}).items():
        parts = key.split(".", 1)
        if len(parts) == 2:
            cat, fname = parts
            if cat in config["categories"] and fname in config["categories"][cat].get("factors", {}):
                config["categories"][cat]["factors"][fname]["weight"] = weight

    # Backup original
    backup_path = CONFIG_DIR / "factors.yaml.bak"
    with open(config_path, "r", encoding="utf-8") as f:
        backup_path.write_text(f.read())

    # Write new config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    logger.info("Factor weights updated (backup saved to factors.yaml.bak)")
    return True


def _save_optimization(result: dict):
    """Save optimization results"""
    knowledge_dir = PROJECT_ROOT / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    filepath = knowledge_dir / "optuna_results.json"
    history = []
    if filepath.exists():
        try:
            history = json.loads(filepath.read_text())
        except Exception:
            history = []

    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        **result,
    })
    filepath.write_text(json.dumps(history[-10:], ensure_ascii=False, indent=2))


def format_optimization_report(result: dict) -> str:
    """Format optimization results into readable report"""
    if "error" in result:
        return f"❌ 优化失败: {result['error']}"

    lines = [
        f"🎯 **Optuna因子权重优化**",
        f"   评分: {result['best_score']:.4f} | 试验次数: {result['n_trials']}",
        f"",
        f"📊 **最佳类别权重:**",
    ]
    for cat, w in sorted(result.get("best_category_weights", {}).items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(w * 10) + "░" * (10 - int(w * 10))
        lines.append(f"   {cat}: [{bar}] {w:.3f}")

    if result.get("best_factor_weights"):
        lines.append(f"\n🔧 **关键因子权重:**")
        for fw, w in sorted(result["best_factor_weights"].items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"   {fw}: {w:.3f}")

    lines.append(f"\n💡 改进: {result.get('improvement', 'N/A')}")
    lines.append(f"   输入 /apply_weights 确认应用到因子配置")

    return "\n".join(lines)
