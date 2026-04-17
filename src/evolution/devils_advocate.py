"""
Devil's Advocate - challenge buy/sell decisions before execution.
Runs before each trade to catch potential mistakes.
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path


def challenge_buy(code: str, name: str, score: float, signal_score: int,
                  reason: str, holdings: dict, market_regime: str = "neutral") -> dict:
    """
    Challenge a buy decision. Returns dict with:
    - approved: bool
    - concerns: list of concern strings
    - risk_level: low/medium/high
    """
    concerns = []
    risk_level = "low"

    # 1. Already holding too many in same industry?
    # (This is a simplified check - full version would check sector_map)
    if len(holdings) >= 5:
        concerns.append(f"已有{len(holdings)}只持仓，接近上限")
        risk_level = "medium"

    # 2. Signal score too low?
    if signal_score < 40:
        concerns.append(f"技术信号偏低({signal_score})，可能追高")
        risk_level = "medium"
    elif signal_score < 55:
        concerns.append(f"技术信号一般({signal_score})")

    # 3. Bearish market regime
    if market_regime == "bearish" and signal_score < 60:
        concerns.append(f"熊市环境+信号不足({signal_score})，风险偏高")
        risk_level = "high"

    # 4. Check if we recently sold this stock at a loss (revenge trading)
    # This would need trade_log access

    # 5. Is this a low-liquidity stock?
    # Would need volume data

    # Decision
    approved = risk_level != "high" and len(concerns) < 3

    return {
        "approved": approved,
        "concerns": concerns,
        "risk_level": risk_level,
        "verdict": "PASS" if approved else "REJECT",
    }


def challenge_sell(code: str, name: str, pnl_pct: float, reason: str,
                   signal_score: int = None) -> dict:
    """
    Challenge a sell decision. Prevents panic selling and premature exits.
    """
    concerns = []
    risk_level = "low"

    # 1. Selling at a loss with weak reason
    if pnl_pct < -0.05 and reason not in ("stop_loss_full", "stop_loss_half"):
        concerns.append(f"亏损{pnl_pct*100:.1f}%但非止损触发，确认原因: {reason}")
        risk_level = "medium"

    # 2. Selling too early (small profit + strong signal)
    if 0 < pnl_pct < 0.05 and signal_score and signal_score >= 70:
        concerns.append(f"盈利仅{pnl_pct*100:.1f}%但信号仍强({signal_score})，是否卖早了?")
        risk_level = "medium"

    # 3. Panic sell check (-3% to -8% without stop loss trigger)
    if -0.10 < pnl_pct < -0.03 and "stop_loss" not in reason:
        concerns.append(f"跌幅{pnl_pct*100:.1f}%未触止损，确认非恐慌卖出")

    approved = True  # We don't block sells, just flag concerns

    return {
        "approved": approved,
        "concerns": concerns,
        "risk_level": risk_level,
        "verdict": "PASS" if not concerns else "FLAGGED",
    }


def generate_defense_report(buy_challenges: list, sell_challenges: list) -> str:
    """Generate a defense report for all challenged trades."""
    lines = ["🛡️ **魔鬼代言人审查**", ""]

    for c in buy_challenges + sell_challenges:
        if not c.get("concerns"):
            continue
        icon = "✅" if c["verdict"] == "PASS" else "⚠️" if c["verdict"] == "FLAGGED" else "❌"
        lines.append(f"{icon} **{c.get('name', c.get('code',''))}** ({c['verdict']})")
        for concern in c["concerns"]:
            lines.append(f"  • {concern}")
        lines.append("")

    if not any(c.get("concerns") for c in buy_challenges + sell_challenges):
        lines.append("所有交易通过审查 ✅")

    return "\n".join(lines)
