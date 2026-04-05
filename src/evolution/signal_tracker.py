"""Signal Evolution Tracker — 投资信号演化追踪

Based on alphaear-signal-tracker from Awesome-finance-skills.
Lightweight version without agno dependency.

Track how new information affects investment signals:
- Strengthened: new info supports the thesis
- Weakened: new info partially contradicts
- Falsified: new info completely contradicts
- Unchanged: no relevant new info
"""

from datetime import datetime
from loguru import logger

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SIGNALS_FILE = PROJECT_ROOT / "knowledge" / "tracked_signals.json"


def _load_signals() -> list[dict]:
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SIGNALS_FILE.exists():
        import json
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    return []


def _save_signals(signals: list[dict]):
    SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    SIGNALS_FILE.write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")


def create_signal(thesis: str, code: str = None, direction: str = "bullish",
                  confidence: float = 0.5) -> dict:
    """Create a new investment signal to track

    Args:
        thesis: investment thesis (e.g., "新能源政策利好锂电池板块")
        code: related stock code (optional)
        direction: bullish/bearish
        confidence: 0.0 to 1.0

    Returns:
        signal dict
    """
    signals = _load_signals()
    signal = {
        "id": len(signals) + 1,
        "thesis": thesis,
        "code": code,
        "direction": direction,
        "confidence": confidence,
        "status": "active",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "updates": [],
    }
    signals.append(signal)
    _save_signals(signals)
    logger.info(f"Signal created: #{signal['id']} {thesis[:30]}")
    return signal


def track_signal(signal_id: int, new_info: str) -> dict:
    """Update a signal with new information

    Uses LLM to assess impact (or simple keyword matching as fallback)

    Returns:
        updated signal with evolution assessment
    """
    signals = _load_signals()
    signal = None
    for s in signals:
        if s["id"] == signal_id:
            signal = s
            break

    if signal is None:
        return {"error": f"Signal #{signal_id} not found"}

    # Simple keyword-based assessment (production should use LLM)
    impact = _assess_impact(signal, new_info)

    signal["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    signal["updates"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "info": new_info[:200],
        "impact": impact["verdict"],
        "reason": impact["reason"],
    })

    # Update confidence
    if impact["verdict"] == "strengthened":
        signal["confidence"] = min(1.0, signal["confidence"] + 0.1)
    elif impact["verdict"] == "weakened":
        signal["confidence"] = max(0.0, signal["confidence"] - 0.1)
    elif impact["verdict"] == "falsified":
        signal["status"] = "falsified"
        signal["confidence"] = 0.0

    _save_signals(signals)
    return signal


def _assess_impact(signal: dict, new_info: str) -> dict:
    """Simple keyword-based impact assessment"""
    info_lower = new_info.lower()
    thesis_lower = signal["thesis"].lower()

    # Positive signals for bullish thesis
    bullish_keywords = ["增长", "利好", "超预期", "上涨", "突破", "政策支持",
                       "订单", "营收", "利润", "positive", "beat", "surge", "rally"]
    bearish_keywords = ["下跌", "亏损", "减持", "处罚", "放缓", "下跌",
                       "风险", "负", "negative", "miss", "drop", "fall", "risk"]

    if signal["direction"] == "bullish":
        # Check if new info contradicts or supports
        bull_hits = sum(1 for k in bullish_keywords if k in info_lower)
        bear_hits = sum(1 for k in bearish_keywords if k in info_lower)
    else:
        # Reverse for bearish thesis
        bull_hits = sum(1 for k in bearish_keywords if k in info_lower)
        bear_hits = sum(1 for k in bearish_keywords if k in info_lower)
        bull_hits, bear_hits = bear_hits, bull_hits

    if bull_hits > bear_hits + 1:
        return {"verdict": "strengthened", "reason": f"正面信号({bull_hits}个正面 vs {bear_hits}个负面)"}
    elif bear_hits > bull_hits + 1:
        return {"verdict": "weakened", "reason": f"负面信号({bear_hits}个负面 vs {bull_hits}个正面)"}
    elif bear_hits >= 3:
        return {"verdict": "falsified", "reason": f"强烈负面({bear_hits}个负面信号)"}
    else:
        return {"verdict": "unchanged", "reason": "无明确影响"}


def get_active_signals() -> list[dict]:
    """Get all active signals"""
    signals = _load_signals()
    return [s for s in signals if s["status"] == "active"]


def format_signal_report() -> str:
    """Format tracked signals into readable report"""
    signals = _load_signals()
    if not signals:
        return "暂无追踪中的投资信号"

    active = [s for s in signals if s["status"] == "active"]
    falsified = [s for s in signals if s["status"] == "falsified"]

    lines = [f"📡 **投资信号追踪** (共{len(signals)}个, 活跃{len(active)}个)\n"]

    for s in active:
        emoji = "📈" if s["direction"] == "bullish" else "📉"
        conf_bar = "█" * int(s["confidence"] * 10) + "░" * (10 - int(s["confidence"] * 10))
        lines.append(f"{emoji} #{s['id']} {s['thesis'][:40]}")
        lines.append(f"   信心: [{conf_bar}] {s['confidence']:.0%} | 方向: {s['direction']}")
        if s["code"]:
            lines.append(f"   相关股票: {s['code']}")
        if s["updates"]:
            last = s["updates"][-1]
            lines.append(f"   最新: {last['impact']} — {last['reason']}")

    if falsified:
        lines.append(f"\n❌ 已证伪 ({len(falsified)}个):")
        for s in falsified:
            lines.append(f"   #{s['id']} {s['thesis'][:40]}")

    return "\n".join(lines)
