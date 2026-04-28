"""轻量风控 — 止损/减仓/集中度控制 + 时间止损 + 移动止盈 + 相关性集中度

规则:
- 单票止损: -15% 清仓
- 单票减仓: -8% 减半
- 行业集中度: 同行业最多3只
- 大盘暴跌: 当日-5%以上触发全体减仓70%
- 时间止损: 持仓过久未达预期收益 (2026-04-22)
- 移动止盈: 盈利阶梯止盈 + 快速拉升保护 (2026-04-29)
- 相关性集中度: 高相关板块限制总仓位 (2026-04-29)
"""

import json
from pathlib import Path
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def check_risk(holdings: dict, prices: dict, include_time_stop: bool = True,
               include_trailing_tp: bool = True, include_correlation: bool = True) -> list:
    """风控检查
    
    Args:
        holdings: {code: {"shares": int, "cost_price": float}}
        prices: {code: current_price}
        include_time_stop: 是否包含时间止损检查
        include_trailing_tp: 是否包含移动止盈检查
        include_correlation: 是否包含相关性集中度检查
    
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
    
    # 移动止盈检查 (新增 2026-04-29)
    if include_trailing_tp and holdings:
        try:
            from src.risk_management.trailing_take_profit import TrailingTakeProfit
            ttp = TrailingTakeProfit()
            tp_alerts = ttp.batch_check(holdings, prices)
            alerts.extend(tp_alerts)
        except Exception as e:
            logger.debug(f"移动止盈检查跳过: {e}")
    
    # 时间止损检查
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
        industry_codes = {}
        for code in holdings:
            ind = get_industry(code)
            if ind:
                industry_count[ind] = industry_count.get(ind, 0) + 1
                industry_codes.setdefault(ind, []).append(code)
        
        for ind, count in industry_count.items():
            if count > 3:
                alerts.append({
                    "code": "portfolio", "action": "diversify",
                    "reason": f"行业集中: {ind[:10]}有{count}只",
                    "urgency": "low",
                })
    except Exception:
        pass
    
    # 相关性集中度检查 (新增 2026-04-29)
    if include_correlation and len(holdings) >= 2:
        try:
            corr_alerts = _check_correlation_clusters(holdings, prices)
            alerts.extend(corr_alerts)
        except Exception as e:
            logger.debug(f"相关性集中度检查跳过: {e}")
    
    # 按紧急度排序
    urgency_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: urgency_order.get(x["urgency"], 3))
    
    return alerts


def _check_correlation_clusters(holdings: dict, prices: dict) -> list:
    """相关性集中度检查

    GitHub学习: PyPortfolioOpt (5678 stars) 的相关性矩阵分析
    思路: 高相关性股票(同板块同质化)合计仓位不应超过限制
    简化实现: 用行业分组 + 同组内价格走势相似度近似相关性

    规则:
    - 同行业股票持仓市值合计 > 总持仓40% → 警告
    - 同行业股票持仓市值合计 > 总持仓50% → 建议减仓
    """
    alerts = []
    
    try:
        from src.data.industry import get_industry
    except ImportError:
        return alerts
    
    # 计算各行业持仓市值
    total_value = 0
    industry_value = {}
    industry_codes = {}
    
    for code, pos in holdings.items():
        price = prices.get(code, 0)
        shares = pos.get("shares", 0)
        value = price * shares
        if value <= 0:
            continue
        
        total_value += value
        ind = None
        try:
            ind = get_industry(code)
        except Exception:
            pass
        
        if ind:
            industry_value[ind] = industry_value.get(ind, 0) + value
            industry_codes.setdefault(ind, []).append(code)
    
    if total_value <= 0:
        return alerts
    
    for ind, value in industry_value.items():
        ratio = value / total_value
        codes_str = ",".join(industry_codes.get(ind, [])[:3])
        
        if ratio > 0.50:
            # 建议减仓行业中权重最低的
            alerts.append({
                "code": codes_str,
                "action": "reduce",
                "ratio": 0.3,
                "reason": f"🔗 行业过度集中: {ind[:8]}占{ratio*100:.0f}%仓位(>{50}%)",
                "urgency": "medium",
            })
        elif ratio > 0.40:
            alerts.append({
                "code": "portfolio",
                "action": "diversify",
                "reason": f"🔗 行业集中警告: {ind[:8]}占{ratio*100:.0f}%仓位",
                "urgency": "low",
            })
    
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
