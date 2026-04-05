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
        score = _quick_backtest(data, cat_weights, factor_weights, backtest_days)

        trial_log.append({
            "trial": trial.number,
            "score": score,
            "cat_weights": cat_weights,
            "factor_weights": {k: round(v, 3) for k, v in factor_weights.items()},
        })

        return score

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


def _quick_backtest(data: dict, cat_weights: dict, factor_weights: dict, days: int) -> float:
    """Simplified backtest using factor scores

    Uses a fast scoring approach:
    1. Score stocks with trial weights
    2. Pick top N
    3. Calculate next-period return
    4. Return risk-adjusted score (Sharpe-like)
    """
    df = data["df"]
    if df.empty or "date" not in df.columns:
        return 0.0

    # Get unique dates
    dates = sorted(df["date"].unique())
    if len(dates) < days + 5:
        return 0.0

    # Use last N rebalance points
    rebalance_dates = dates[-(days // 5 + 1):-1]  # every ~5 days

    returns = []
    for i in range(len(rebalance_dates) - 1):
        d = rebalance_dates[i]
        d_next = rebalance_dates[i + 1]

        # Get stocks on this date
        mask = df["date"] == d
        day_data = df[mask].copy()

        if len(day_data) < 20:
            continue

        # Simple scoring: use available numeric columns
        score_cols = [c for c in day_data.columns if day_data[c].dtype in ["float64", "int64"] and c not in ["date", "open", "high", "low", "close", "volume", "amount", "turn"]]
        if not score_cols:
            continue

        # Calculate score
        scores = pd.Series(0.0, index=day_data.index)
        for col in score_cols[:5]:  # limit to avoid noise
            std = day_data[col].std()
            if std > 0:
                scores += (day_data[col] - day_data[col].mean()) / std

        # Pick top 10
        top_idx = scores.nlargest(10).index
        top_codes = day_data.loc[top_idx, "code"].tolist()

        # Calculate forward return
        mask_next = df["date"] == d_next
        day_next = df[mask_next].copy()

        port_return = 0.0
        matched = 0
        for code in top_codes:
            row = day_next[day_next["code"] == code]
            curr = day_data[day_data["code"] == code]
            if len(row) > 0 and len(curr) > 0:
                curr_close = curr["close"].values[0]
                next_close = row["close"].values[0]
                if curr_close > 0:
                    port_return += (next_close - curr_close) / curr_close
                    matched += 1

        if matched > 0:
            returns.append(port_return / matched)

    if len(returns) < 3:
        return 0.0

    # Risk-adjusted return (Sharpe-like)
    returns = np.array(returns)
    mean_ret = returns.mean()
    std_ret = returns.std()

    if std_ret == 0:
        return 0.0

    sharpe = mean_ret / std_ret * np.sqrt(252)
    return sharpe


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
