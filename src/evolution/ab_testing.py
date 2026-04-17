"""
Strategy A/B Testing Framework.
Compare current strategy vs variant on recent data.
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ABTestFramework:
    """Compare strategy variants via backtesting."""

    def __init__(self):
        self.results_dir = PROJECT_ROOT / "knowledge" / "ab_tests"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run_comparison(self, strategy_a: dict, strategy_b: dict,
                       backtest_days: int = 60) -> dict:
        """
        Compare two strategy configurations.

        strategy_a/b: dict with keys like:
          - stop_loss_1: float (e.g., -0.10)
          - stop_loss_2: float (e.g., -0.15)
          - signal_threshold: int (e.g., 50)
          - max_holdings: int (e.g., 5)
          - position_pct: float (e.g., 0.20)
        """
        # Load historical data
        nav_file = PROJECT_ROOT / "data" / "nav_state_balanced.json"
        if not nav_file.exists():
            return {"error": "No NAV data available"}

        # For now, compare based on recent trade performance
        # Full backtest would need daily_quote data
        trade_log = json.loads(nav_file.read_text()).get("trade_log", [])

        # Evaluate recent trades under both strategies
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "strategy_a": strategy_a,
            "strategy_b": strategy_b,
            "comparison": self._compare_on_trades(trade_log, strategy_a, strategy_b),
        }

        # Save result
        path = self.results_dir / f"ab_{datetime.now().strftime('%Y%m%d')}.json"
        with open(path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        return result

    def _compare_on_trades(self, trade_log: list,
                           strategy_a: dict, strategy_b: dict) -> dict:
        """Compare strategies on historical trades."""
        if not trade_log:
            return {"note": "No trades to compare"}

        # Count trades that would pass each strategy's filters
        a_trades = 0
        b_trades = 0

        for t in trade_log:
            action = t.get("action", "")
            reason = t.get("reason", "")

            # Simple heuristic: count by reason type
            if "stop_loss" in reason:
                # Both strategies would have stop loss
                a_trades += 1
                b_trades += 1
            elif "signal" in reason:
                sig = int(reason.split("_")[-1]) if reason.split("_")[-1].isdigit() else 50
                threshold_a = strategy_a.get("signal_threshold", 35)
                threshold_b = strategy_b.get("signal_threshold", 35)
                if sig >= threshold_a:
                    a_trades += 1
                if sig >= threshold_b:
                    b_trades += 1

        return {
            "strategy_a_trades": a_trades,
            "strategy_b_trades": b_trades,
            "note": "Simplified comparison based on trade log"
        }

    def get_latest_results(self) -> dict:
        """Get latest A/B test results."""
        results = sorted(self.results_dir.glob("ab_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not results:
            return {"note": "No A/B test results yet"}
        with open(results[0]) as f:
            return json.load(f)
