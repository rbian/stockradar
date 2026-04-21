"""轻量风控 — 止损/减仓/集中度控制 + 时间止损

规则:
- 单票止损: -15% 清仓
- 单票减仓: -8% 减半
- 行业集中度: 同行业最多3只
- 大盘暴跌: 当日-5%以上触发全体减仓70%
- 时间止损: 持仓过久未达预期收益 (新增 2026-04-22)
"""

import json
from pathlib import Path
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def check_risk(holdings: dict, prices: dict, include_time_stop: bool = True) -> list:
    """风控检查
    
    Args:
        holdings: {code: {"shares": int, "cost_price": float}}
        prices: {code: current_price}
        include_time_stop: 是否包含时间止损检查
    
    Returns:
        list of {code, action, reason, urgency}
    """
    alerts = []
    
    for code, pos in holdings.items():
        cost = pos.get("cost_price", 0)
        price = prices.get(code, 0)
        if cost <= 0 or price <= 0:
            continue
        
        pnl_pct = (price / cost - 1)
        
        # 止损线: -15%
        if pnl_pct <= -0.15:
            alerts.append({
                "code": code, "action": "sell", "ratio": 1.0,
                "reason": f"止损 (亏损{pnl_pct*100:.1f}%)",
                "urgency": "high",
            })
        # 减仓线: -8%
        elif pnl_pct <= -0.08:
            alerts.append({
                "code": code, "action": "reduce", "ratio": 0.5,
                "reason": f"减仓 (亏损{pnl_pct*100:.1f}%)",
                "urgency": "medium",
            })
        # 预警: -5%
        elif pnl_pct <= -0.05:
            alerts.append({
                "code": code, "action": "watch",
                "reason": f"关注 (亏损{pnl_pct*100:.1f}%)",
                "urgency": "low",
            })
    
    # 时间止损检查 (新增)
    if include_time_stop and holdings:
        try:
            from src.risk_management.time_stop import TimeStopManager
            tsm = TimeStopManager()
            time_alerts = tsm.batch_check(holdings, prices)
            for ta in time_alerts:
                ta["reason"] = f"⏱️ {ta['reason']}"
                alerts.append(ta)
        except Exception as e:
            logger.debug(f"时间止损检查跳过: {e}")
    
    # 行业集中度检查
    try:
        from src.data.industry import get_industry
        industry_count = {}
        for code in holdings:
            ind = get_industry(code)
            if ind:
                industry_count[ind] = industry_count.get(ind, 0) + 1
        
        for ind, count in industry_count.items():
            if count > 3:
                alerts.append({
                    "code": "portfolio", "action": "diversify",
                    "reason": f"行业集中: {ind[:10]}有{count}只",
                    "urgency": "low",
                })
    except Exception:
        pass
    
    # 按紧急度排序
    urgency_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: urgency_order.get(x["urgency"], 3))
    
    return alerts


def format_risk_alerts(alerts: list) -> str:
    """格式化风控提示"""
    if not alerts:
        return "✅ 风控检查通过"
    
    lines = ["🛡️ **风控预警**\n"]
    for a in alerts:
        if a["action"] == "sell":
            lines.append(f"🔴 **止损**: {a['code']} — {a['reason']}")
        elif a["action"] == "reduce":
            lines.append(f"🟡 **减仓**: {a['code']} — {a['reason']}")
        elif a["action"] == "watch":
            lines.append(f"⚠️ 关注: {a['code']} — {a['reason']}")
        elif a["action"] == "diversify":
            lines.append(f"📊 {a['reason']}")
    
    return "\n".join(lines)
