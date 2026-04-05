"""错误模式库 — 从交易复盘中提取并持久化错误模式

结构:
knowledge/error_patterns.json — 所有已识别的错误模式
每个模式包含：名称、触发条件、发生频率、修正建议、验证状态
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PATTERNS_FILE = PROJECT_ROOT / "knowledge" / "error_patterns.json"


def load_patterns() -> list[dict]:
    """Load error patterns from file"""
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PATTERNS_FILE.exists():
        return json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))
    return []


def save_patterns(patterns: list[dict]):
    """Save error patterns to file"""
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATTERNS_FILE.write_text(
        json.dumps(patterns, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def update_patterns_from_review(review_result: dict) -> list[dict]:
    """Update error patterns from a trade review result

    Args:
        review_result: dict with 'reviews' and 'patterns' from trade_reviewer

    Returns:
        Updated patterns list
    """
    patterns = load_patterns()
    existing_names = {p["name"] for p in patterns}
    new_patterns = review_result.get("patterns", [])

    updated = False
    for np in new_patterns:
        if np["pattern"] not in existing_names:
            # New pattern discovered
            patterns.append({
                "name": np["pattern"],
                "first_seen": datetime.now().strftime("%Y-%m-%d"),
                "last_seen": datetime.now().strftime("%Y-%m-%d"),
                "count": np["count"],
                "avg_cost": np["avg_cost"],
                "examples": np["examples"][:5],
                "fix_rule": _generate_fix_rule(np["pattern"], np["examples"]),
                "status": "observing",  # observing → verified → fixed
                "verified_count": 0,
            })
            updated = True
            logger.info(f"新错误模式发现: {np['pattern']} ({np['count']}次)")
        else:
            # Update existing pattern
            for p in patterns:
                if p["name"] == np["pattern"]:
                    p["last_seen"] = datetime.now().strftime("%Y-%m-%d")
                    p["count"] = np["count"]
                    p["examples"] = np["examples"][:5]
                    # Auto-promote after 5 occurrences
                    if p["count"] >= 5 and p["status"] == "observing":
                        p["status"] = "verified"
                        logger.info(f"错误模式验证: {p['name']} ({p['count']}次)")
                    updated = True
                    break

    if updated:
        save_patterns(patterns)
    return patterns


def _generate_fix_rule(pattern_name: str, examples: list[dict]) -> str:
    """Generate a suggested fix rule for an error pattern"""
    rules = {
        "卖飞": "卖出前检查: RSI<70 且 MA多头排列 → 不因评分降低卖出，设持有观察期",
        "过早止损": "放宽止损线: 检查是否因短期波动触发，增加-12%缓冲区再止损",
        "买入失误": "买入前增加确认: 次日低开>2%则取消买入，等企稳再进",
    }
    return rules.get(pattern_name, f"需分析{pattern_name}的共性特征，制定预防规则")


def get_active_rules() -> list[dict]:
    """Get all verified fix rules for integration into trading logic"""
    patterns = load_patterns()
    return [
        {"name": p["name"], "rule": p["fix_rule"], "count": p["count"]}
        for p in patterns
        if p["status"] in ("verified", "fixed")
    ]


def check_before_trade(code: str, action: str, daily_quote=None) -> str | None:
    """Check if a trade would violate any known error pattern

    Returns warning message or None
    """
    rules = get_active_rules()
    if not rules or not daily_quote:
        return None

    warnings = []
    if action == "sell":
        # Check 卖飞 rule
        for r in rules:
            if "卖飞" in r["name"] or "RSI" in r["rule"]:
                stock_data = daily_quote[daily_quote["code"] == code].tail(20)
                if len(stock_data) >= 20:
                    from src.factors.technical_signals import score_stock
                    sig = score_stock(stock_data)
                    if sig["signal_score"] >= 65:
                        warnings.append(
                            f"⚠️ {r['name']}模式: {code}技术信号{sig['signal_score']}分({sig['signal']}), "
                            f"规则建议: {r['rule']}"
                        )

    return "\n".join(warnings) if warnings else None


def format_patterns_report() -> str:
    """Format error patterns into readable report"""
    patterns = load_patterns()
    if not patterns:
        return "暂无已识别的错误模式"

    lines = ["🔍 **错误模式库**\n"]
    for p in sorted(patterns, key=lambda x: x["count"], reverse=True):
        status_emoji = {
            "observing": "👁️", "verified": "✅", "fixed": "🔧"
        }.get(p["status"], "❓")
        lines.append(f"  {status_emoji} **{p['name']}** — {p['count']}次")
        lines.append(f"     首次: {p['first_seen']} | 最近: {p['last_seen']}")
        lines.append(f"     平均损失: ¥{p['avg_cost']:,.0f}")
        lines.append(f"     修正规则: {p['fix_rule']}")
        lines.append("")

    active = len([p for p in patterns if p["status"] != "fixed"])
    lines.append(f"共{len(patterns)}个模式，{active}个待修正")
    return "\n".join(lines)
