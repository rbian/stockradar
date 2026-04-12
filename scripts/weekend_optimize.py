#!/usr/bin/env python3
"""Weekend auto-optimization script.
Run Saturday morning: pre-compute scores + 50 Optuna trials + save results.
Optionally auto-apply if improvement > threshold.
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from loguru import logger
from src.evolution.optuna_optimizer import run_optuna_optimization, apply_optimized_weights

def main():
    logger.info("=" * 50)
    logger.info("Weekend Auto-Optimization")
    logger.info("=" * 50)

    # Run optimization with 50 trials
    result = run_optuna_optimization(n_trials=50, backtest_days=90)

    if "error" in result:
        logger.error(f"Optimization failed: {result['error']}")
        return

    best_score = result["best_score"]
    logger.info(f"Best score: {best_score:.4f}")
    logger.info(f"Category weights: {result['best_category_weights']}")

    # Load previous results for comparison
    knowledge_dir = PROJECT / "knowledge"
    history_file = knowledge_dir / "optuna_results.json"
    prev_best = 0
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
            if history:
                prev_best = max(r.get("best_score", 0) for r in history[:-1])  # exclude current
        except Exception:
            pass

    improvement = best_score - prev_best if prev_best > 0 else 0
    logger.info(f"Previous best: {prev_best:.4f}, Improvement: {improvement:+.4f}")

    # Auto-apply if significant improvement (score > prev by 10%)
    applied = False
    if prev_best > 0 and improvement > prev_best * 0.10:
        logger.info("Significant improvement detected, auto-applying weights...")
        applied = apply_optimized_weights(result)
        if applied:
            logger.info("✅ New weights applied to factors.yaml")
            # Restart bot to pick up new weights
            subprocess.run(["pkill", "-f", "run_bot.py"], capture_output=True)
            import time
            time.sleep(3)
            subprocess.Popen(
                ["python3", "scripts/run_bot.py"],
                cwd=str(PROJECT),
                stdout=open("logs/bot_stdout.log", "a"),
                stderr=open("logs/bot_stderr.log", "a"),
                start_new_session=True,
                stdin=open("/dev/null"),
            )
            logger.info("Bot restarted with new weights")
        else:
            logger.warning("Failed to apply weights")
    else:
        logger.info(f"No significant improvement (<10%), weights NOT auto-applied")
        logger.info("Run apply_optimized_weights() manually to apply")

    # Push results
    subprocess.run(["git", "add", "-A"], cwd=str(PROJECT), capture_output=True)
    try:
        subprocess.run(["git", "commit", "-m", f"optuna: weekend optimization score={best_score:.4f}"],
                      cwd=str(PROJECT), capture_output=True, timeout=10)
        subprocess.run(["git", "push", "origin", "master"],
                      cwd=str(PROJECT), capture_output=True, timeout=30)
        logger.info("Results pushed to GitHub")
    except Exception:
        pass

    logger.info("Weekend optimization complete")


if __name__ == "__main__":
    main()
