#!/usr/bin/env python3
"""Weekly portfolio report generator.
Runs every Friday 15:45 after market close.
Sends structured weekly report to Telegram.
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from loguru import logger


def generate_weekly_report() -> str:
    """Generate weekly report markdown."""
    nav_file = PROJECT / "data" / "nav_state_balanced.json"
    if not nav_file.exists():
        return "⚠️ NAV数据文件不存在"

    nav_data = json.loads(nav_file.read_text())
    nav = nav_data.get("nav", 0)
    cash = nav_data.get("cash", 0)
    holdings = nav_data.get("holdings", {})
    trade_log = nav_data.get("trades", [])

    # Calculate total value
    total_value = cash
    holdings_info = []

    for code, h in holdings.items():
        shares = h.get("shares", 0)
        cost = h.get("cost_price", 0)
        # Use last known price from trade_log or cost
        mv = shares * cost  # conservative estimate
        total_value += mv
        pnl = (cost - cost) * shares  # 0 without real-time price
        holdings_info.append({
            "code": code,
            "shares": shares,
            "cost": cost,
            "mv": mv,
            "weight": f"{mv/total_value*100:.1f}%" if total_value > 0 else "0%",
        })

    # Filter trades this week
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    week_trades = [
        t for t in trade_log
        if isinstance(t.get("date"), str) and t["date"] >= week_ago.strftime("%Y-%m-%d")
    ]

    buys = [t for t in week_trades if t.get("action") == "buy"]
    sells = [t for t in week_trades if t.get("action") == "sell"]

    # Build report
    report = f"""📊 **StockRadar 周报** ({week_ago.strftime('%m/%d')} - {today.strftime('%m/%d')})

💰 **组合概况**
• NAV: {nav:.4f}
• 现金: ¥{cash:,.0f}
• 持仓: {len(holdings)}只

📈 **本周交易**
• 买入: {len(buys)}笔
• 卖出: {len(sells)}笔

📋 **当前持仓**"""
    for h in sorted(holdings_info, key=lambda x: x["mv"], reverse=True):
        report += f"\n• {h['code']} {h['shares']}股 @{h['cost']:.2f} 权重{h['weight']}"

    # Optuna optimization status
    optuna_file = PROJECT / "knowledge" / "optuna_results.json"
    if optuna_file.exists():
        try:
            results = json.loads(optuna_file.read_text())
            if results:
                latest = results[-1]
                report += f"\n\n🔧 **优化状态**"
                report += f"\n• 最近优化: {latest.get('date', 'N/A')}"
                report += f"\n• 最佳分数: {latest.get('best_score', 'N/A')}"
        except Exception:
            pass

    # Next week outlook
    report += f"\n\n🔮 **下周关注**"
    report += f"\n• 周六Optuna自动优化 (50 trials)"
    report += f"\n• 大盘择时系统监控中"

    return report


if __name__ == "__main__":
    report = generate_weekly_report()
    print(report)
