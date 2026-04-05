"""交易复盘系统 — 每日收盘后自动分析每笔交易的效果

对每笔交易：
  买入 → 追踪后续5/10/20日涨跌幅 → 判断因子是否识别正确
  卖出 → 追踪后续涨跌 → 判断是否卖飞/正确止损

输出到 knowledge/trade_reviews/YYYY-MM-DD.md
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def review_trades(daily_quote: pd.DataFrame, trade_log: list[dict],
                  review_date=None) -> dict:
    """Review all trades, tracking subsequent performance

    Args:
        daily_quote: DataFrame with code, date, close columns
        trade_log: list of trade dicts with date, code, action, price, shares, reason, pnl
        review_date: date to review up to (defaults to latest in data)

    Returns:
        Dict with review results
    """
    if not trade_log or daily_quote is None or daily_quote.empty:
        return {"reviews": [], "patterns": []}

    if review_date is None:
        review_date = daily_quote["date"].max()

    reviews = []
    # Group trades by (code, action, date) to avoid duplicates from test runs
    seen = set()
    for trade in trade_log:
        key = (trade["code"], trade["action"], trade.get("date", "")[:10])
        if key in seen:
            continue
        seen.add(key)

        review = _review_single_trade(trade, daily_quote, review_date)
        if review:
            reviews.append(review)

    # Extract error patterns
    patterns = _extract_patterns(reviews)

    return {"reviews": reviews, "patterns": patterns}


def _review_single_trade(trade: dict, dq: pd.DataFrame, review_date) -> dict | None:
    """Review a single trade's subsequent performance"""
    code = trade["code"]
    action = trade["action"]
    trade_date_str = str(trade.get("date", ""))[:10]
    trade_price = trade["price"]

    if not trade_date_str:
        return None

    try:
        trade_date = pd.Timestamp(trade_date_str)
    except Exception:
        return None

    # Get price data for this stock
    stock_data = dq[dq["code"] == code].sort_values("date")
    if stock_data.empty:
        return None

    # Find price on trade date
    mask = stock_data["date"].dt.date == trade_date.date()
    if not mask.any():
        # Try closest date after
        after = stock_data[stock_data["date"] >= trade_date]
        if after.empty:
            return None
        trade_row = after.iloc[0]
    else:
        trade_row = stock_data[mask].iloc[0]

    actual_price = trade_row["close"]
    # Get prices at N days after
    future = stock_data[stock_data["date"] > trade_row["date"]].head(25)

    if future.empty:
        return None

    # Calculate returns at 1/5/10/20 days
    returns = {}
    for n, label in [(1, "1d"), (5, "5d"), (10, "10d"), (20, "20d")]:
        if len(future) >= n:
            ret = (future.iloc[n - 1]["close"] - actual_price) / actual_price * 100
            returns[label] = round(ret, 2)

    # Judge outcome
    if action == "sell":
        outcome = _judge_sell(trade, returns)
    else:
        outcome = _judge_buy(trade, returns)

    # Get stock name
    try:
        from src.data.stock_names import stock_name
        name = stock_name(code)
    except Exception:
        name = code

    return {
        "code": code,
        "name": name,
        "action": action,
        "date": trade_date_str,
        "price": trade_price,
        "reason": trade.get("reason", ""),
        "pnl": trade.get("pnl", 0),
        "subsequent_returns": returns,
        "outcome": outcome["verdict"],
        "analysis": outcome["analysis"],
    }


def _judge_sell(trade: dict, returns: dict) -> dict:
    """Judge if a sell was correct"""
    pnl = trade.get("pnl", 0)
    r5d = returns.get("5d", 0)
    r10d = returns.get("10d", 0)
    reason = trade.get("reason", "")

    if r5d is None:
        return {"verdict": "insufficient_data", "analysis": "数据不足，无法评估"}

    if pnl > 0 and r5d < -2:
        return {
            "verdict": "excellent",
            "analysis": f"卖出后5日跌{r5d:+.1f}%，成功止盈"
        }
    elif pnl > 0 and r5d < 2:
        return {
            "verdict": "good",
            "analysis": f"卖出后5日{r5d:+.1f}%，卖出时机合理"
        }
    elif pnl > 0 and r5d >= 2:
        return {
            "verdict": "early_sell",
            "analysis": f"卖出后5日涨{r5d:+.1f}%，可能卖早了",
            "pattern": "卖飞",
        }
    elif pnl < 0 and r5d >= 0:
        return {
            "verdict": "bad_stop",
            "analysis": f"止损后5日反弹{r5d:+.1f}%，止损可能过早",
            "pattern": "过早止损",
        }
    elif pnl <= 0 and r5d < -2:
        return {
            "verdict": "correct_stop",
            "analysis": f"卖出后5日继续跌{r5d:+.1f}%，止损正确"
        }
    elif "止损" in reason:
        return {
            "verdict": "stop_loss",
            "analysis": f"止损{pnl:+.0f}元，后续{r5d:+.1f}%",
        }
    else:
        return {
            "verdict": "neutral",
            "analysis": f"卖出后5日{r5d:+.1f}%",
        }


def _judge_buy(trade: dict, returns: dict) -> dict:
    """Judge if a buy was correct"""
    r5d = returns.get("5d", 0)
    r10d = returns.get("10d", 0)

    if r5d is None:
        return {"verdict": "insufficient_data", "analysis": "数据不足"}

    if r5d >= 3:
        return {
            "verdict": "excellent",
            "analysis": f"买入后5日涨{r5d:+.1f}%，选股正确",
        }
    elif r5d >= 0:
        return {
            "verdict": "good",
            "analysis": f"买入后5日{r5d:+.1f}%，表现尚可",
        }
    elif r5d >= -3:
        return {
            "verdict": "mediocre",
            "analysis": f"买入后5日跌{r5d:+.1f}%，需观察",
        }
    else:
        return {
            "verdict": "bad",
            "analysis": f"买入后5日跌{r5d:+.1f}%，选股失误",
            "pattern": "买入失误",
        }


def _extract_patterns(reviews: list[dict]) -> list[dict]:
    """Extract recurring error patterns"""
    from collections import Counter

    # Count pattern types
    patterns = []
    verdict_counts = Counter(r["outcome"] for r in reviews)
    pattern_counts = Counter(r.get("pattern") for r in reviews if "pattern" in r)

    for pattern, count in pattern_counts.most_common(5):
        examples = [r for r in reviews if r.get("pattern") == pattern][:3]
        avg_cost = 0
        for r in examples:
            pnl = r.get("pnl", 0) or r.get("subsequent_returns", {}).get("5d", 0)
            avg_cost += abs(pnl) if pnl else 0
        avg_cost /= len(examples) if examples else 1

        patterns.append({
            "pattern": pattern,
            "count": count,
            "avg_cost": round(avg_cost, 0),
            "examples": [
                {"code": e["code"], "name": e["name"], "date": e["date"],
                 "analysis": e["analysis"]}
                for e in examples
            ],
        })

    return patterns


def format_review_report(reviews: list[dict], patterns: list[dict]) -> str:
    """Format reviews into readable markdown report"""
    if not reviews:
        return "暂无交易可复盘"

    lines = ["📊 **交易复盘报告**\n"]

    # Summary
    from collections import Counter
    verdicts = Counter(r["outcome"] for r in reviews)
    total = len(reviews)
    good = sum(verdicts.get(v, 0) for v in ["excellent", "good", "correct_stop"])
    bad = sum(verdicts.get(v, 0) for v in ["bad", "bad_stop", "early_sell"])

    lines.append(f"总交易: {total}笔 | ✅ 正确: {good}笔 | ❌ 需改进: {bad}笔\n")

    # Individual reviews
    lines.append("## 交易明细\n")
    for r in reviews[-10:]:  # Last 10
        emoji = {"excellent": "🌟", "good": "✅", "correct_stop": "✅",
                 "early_sell": "⚠️", "bad_stop": "⚠️", "bad": "❌",
                 "mediocre": "😐", "neutral": "➖", "stop_loss": "🛑",
                 "insufficient_data": "❓"}.get(r["outcome"], "❓")

        action = "买入" if r["action"] == "buy" else "卖出"
        r5 = r["subsequent_returns"].get("5d", "N/A")
        r10 = r["subsequent_returns"].get("10d", "N/A")

        lines.append(f"  {emoji} {r['date']} {action} **{r['name']}**({r['code']}) @{r['price']}")

        rets_str = f" → 5日:{r5}%"
        if r10 != "N/A":
            rets_str += f" 10日:{r10}%"
        if r.get("pnl") and r["pnl"] != 0:
            rets_str += f" 盈亏:¥{r['pnl']:+.0f}"

        lines.append(f"    {rets_str}")
        lines.append(f"    💡 {r['analysis']}")

    # Patterns
    if patterns:
        lines.append(f"\n## 错误模式 (Top {len(patterns)})\n")
        for p in patterns:
            lines.append(f"  🔴 **{p['pattern']}** — {p['count']}次, 平均损失¥{p['avg_cost']:,.0f}")
            for ex in p["examples"]:
                lines.append(f"    · {ex['name']}({ex['date']}): {ex['analysis']}")

    return "\n".join(lines)


def save_review_to_knowledge(reviews: list[dict], patterns: list[dict]):
    """Save review to knowledge/trade_reviews/"""
    review_dir = PROJECT_ROOT / "knowledge" / "trade_reviews"
    review_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    filepath = review_dir / f"{today}.md"

    report = format_review_report(reviews, patterns)
    filepath.write_text(report, encoding="utf-8")

    # Also save structured data
    data_path = review_dir / f"{today}.json"
    json.dump({
        "date": today,
        "total_reviews": len(reviews),
        "patterns": patterns,
        "reviews": reviews,
    }, open(data_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)

    logger.info(f"交易复盘已保存: {len(reviews)}条, {len(patterns)}个模式")
    return report
