"""
StockRadar 交易跟踪闭环系统
每笔平仓自动记录盈亏 → 因子归因 → 策略评估 → 驱动daily-improve

数据流:
  alert_check卖出 → record_close() → update_tracker() → generate_report()
  daily-improve读取 → 基于数据调参数
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tracking"
TRADE_LOG = DATA_DIR / "closed_trades.json"
DAILY_STATS = DATA_DIR / "daily_stats.json"
STRATEGY_REPORT = DATA_DIR / "strategy_report.json"


def _load(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default if default is not None else {}
    return default if default is not None else {}


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ============================================================
# 1. 记录已平仓交易
# ============================================================

def record_trade(code: str, name: str, action: str, buy_price: float, sell_price: float,
                 shares: int, buy_date: str, sell_date: str, reason: str,
                 factors: dict = None, signals: dict = None) -> dict:
    """
    记录一笔完整的交易（买入到卖出）。
    
    Args:
        code: 股票代码
        name: 股票名称
        action: "sell" (平仓)
        buy_price: 买入均价
        sell_price: 卖出均价
        shares: 股数
        buy_date: 买入日期 "2026-05-12"
        sell_date: 卖出日期 "2026-05-15"
        reason: 卖出原因
        factors: 买入时的因子评分 {"momentum": 0.8, "value": 0.6, ...}
        signals: 买入时的信号 {"technical": 72, "fundamental": 85, ...}
    """
    gross_pnl = (sell_price - buy_price) * shares
    commission = (buy_price * shares + sell_price * shares) * 0.001  # 双边0.1%
    net_pnl = gross_pnl - commission
    return_pct = (sell_price / buy_price - 1) * 100
    hold_days = (datetime.strptime(sell_date, '%Y-%m-%d') - 
                 datetime.strptime(buy_date, '%Y-%m-%d')).days
    
    trade = {
        "code": code,
        "name": name,
        "buy_price": round(buy_price, 2),
        "sell_price": round(sell_price, 2),
        "shares": shares,
        "buy_date": buy_date,
        "sell_date": sell_date,
        "hold_days": hold_days,
        "reason": reason,
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "return_pct": round(return_pct, 2),
        "is_win": net_pnl > 0,
        "factors": factors or {},
        "signals": signals or {},
        "recorded_at": datetime.now().isoformat(),
    }
    
    log = _load(TRADE_LOG, {"trades": [], "metadata": {}})
    log["trades"].append(trade)
    
    # 只保留最近500笔
    log["trades"] = log["trades"][-500:]
    
    # 更新元数据
    all_trades = log["trades"]
    wins = [t for t in all_trades if t["is_win"]]
    log["metadata"] = {
        "total_trades": len(all_trades),
        "total_wins": len(wins),
        "win_rate": round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "avg_return": round(sum(t["return_pct"] for t in all_trades) / len(all_trades), 2) if all_trades else 0,
        "avg_hold_days": round(sum(t["hold_days"] for t in all_trades) / len(all_trades), 1) if all_trades else 0,
        "total_pnl": round(sum(t["net_pnl"] for t in all_trades), 2),
        "best_trade": max((t["return_pct"] for t in all_trades), default=0),
        "worst_trade": min((t["return_pct"] for t in all_trades), default=0),
        "updated": datetime.now().isoformat(),
    }
    
    _save(TRADE_LOG, log)
    return trade


# ============================================================
# 2. 每日统计更新
# ============================================================

def update_daily_stats(nav_data: dict = None, holdings: dict = None):
    """每日收盘后更新统计"""
    today = datetime.now().strftime('%Y-%m-%d')
    stats = _load(DAILY_STATS, {"days": []})
    
    day_entry = {
        "date": today,
        "nav": nav_data.get("nav", 0) if nav_data else 0,
        "cash": nav_data.get("cash", 0) if nav_data else 0,
        "market_value": nav_data.get("market_value", 0) if nav_data else 0,
        "holdings_count": len(holdings) if holdings else 0,
        "holdings": list(holdings.keys()) if holdings else [],
    }
    
    # 如果今天已有记录，更新；否则新增
    existing = [i for i, d in enumerate(stats["days"]) if d["date"] == today]
    if existing:
        stats["days"][existing[0]] = day_entry
    else:
        stats["days"].append(day_entry)
    
    # 保留最近90天
    cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    stats["days"] = [d for d in stats["days"] if d["date"] >= cutoff]
    
    # 计算累计指标
    if len(stats["days"]) >= 2:
        first_nav = stats["days"][0]["nav"]
        last_nav = stats["days"][-1]["nav"]
        if first_nav > 0:
            stats["cumulative_return"] = round((last_nav / first_nav - 1) * 100, 2)
        
        # 计算最大回撤
        peak = 0
        max_dd = 0
        for d in stats["days"]:
            if d["nav"] > peak:
                peak = d["nav"]
            dd = (peak - d["nav"]) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        stats["max_drawdown"] = round(max_dd, 2)
    
    _save(DAILY_STATS, stats)


# ============================================================
# 3. 策略报告（daily-improve读取）
# ============================================================

def generate_strategy_report() -> dict:
    """生成策略评估报告"""
    trade_log = _load(TRADE_LOG, {"trades": [], "metadata": {}})
    daily = _load(DAILY_STATS, {"days": []})
    
    trades = trade_log["trades"]
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_trades": len(trades),
            "win_rate": 0,
            "avg_return": 0,
            "total_pnl": 0,
            "avg_hold_days": 0,
            "profit_factor": 0,  # 总盈利/总亏损
        },
        "by_reason": {},       # 按卖出原因统计
        "by_factor": {},       # 按因子强度统计
        "by_signal": {},       # 按信号类型统计
        "recent_trades": [],   # 最近10笔
        "nav_performance": {}, # NAV表现
        "suggestions": [],     # 改进建议
        "data_status": "insufficient",  # insufficient / accumulating / sufficient
    }
    
    if len(trades) < 10:
        report["data_status"] = "insufficient"
        report["data_status_msg"] = f"仅{len(trades)}笔已平仓交易，需要至少20笔才有统计意义。当前只做bug修复。"
        _save(STRATEGY_REPORT, report)
        return report
    
    report["data_status"] = "accumulating" if len(trades) < 30 else "sufficient"
    
    # 基本统计
    wins = [t for t in trades if t["is_win"]]
    losses = [t for t in trades if not t["is_win"]]
    
    report["summary"] = {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_return": round(sum(t["return_pct"] for t in trades) / len(trades), 2),
        "total_pnl": round(sum(t["net_pnl"] for t in trades), 2),
        "avg_hold_days": round(sum(t["hold_days"] for t in trades) / len(trades), 1),
        "profit_factor": round(
            sum(t["net_pnl"] for t in wins) / abs(sum(t["net_pnl"] for t in losses)) if losses else 999,
            2
        ),
    }
    
    # 按卖出原因统计
    for t in trades:
        reason = t.get("reason", "unknown")
        if reason not in report["by_reason"]:
            report["by_reason"][reason] = {"count": 0, "wins": 0, "avg_return": [], "pnl": 0}
        report["by_reason"][reason]["count"] += 1
        if t["is_win"]:
            report["by_reason"][reason]["wins"] += 1
        report["by_reason"][reason]["avg_return"].append(t["return_pct"])
        report["by_reason"][reason]["pnl"] += t["net_pnl"]
    
    for reason, stats in report["by_reason"].items():
        if stats["avg_return"]:
            stats["avg_return"] = round(sum(stats["avg_return"]) / len(stats["avg_return"]), 2)
            stats["win_rate"] = round(stats["wins"] / stats["count"] * 100, 1)
    
    # 按因子统计（因子值高的交易表现是否更好？）
    factor_trades = [t for t in trades if t.get("factors")]
    if factor_trades:
        for factor_name in set(f for t in factor_trades for f in t["factors"]):
            high_factor = [t for t in factor_trades if t["factors"].get(factor_name, 0) > 0.6]
            low_factor = [t for t in factor_trades if t["factors"].get(factor_name, 0) <= 0.6]
            if high_factor and low_factor:
                high_wr = sum(1 for t in high_factor if t["is_win"]) / len(high_factor) * 100
                low_wr = sum(1 for t in low_factor if t["is_win"]) / len(low_factor) * 100
                report["by_factor"][factor_name] = {
                    "high_score_trades": len(high_factor),
                    "high_score_winrate": round(high_wr, 1),
                    "low_score_trades": len(low_factor),
                    "low_score_winrate": round(low_wr, 1),
                    "is_effective": high_wr > low_wr + 10,  # 高分胜率明显更高才有效
                }
    
    # 按信号统计
    signal_trades = [t for t in trades if t.get("signals")]
    if signal_trades:
        for sig_name in set(f for t in signal_trades for f in t["signals"]):
            sig_trades = [t for t in signal_trades if sig_name in t.get("signals", {})]
            if sig_trades:
                wr = sum(1 for t in sig_trades if t["is_win"]) / len(sig_trades) * 100
                report["by_signal"][sig_name] = {
                    "count": len(sig_trades),
                    "win_rate": round(wr, 1),
                    "avg_return": round(sum(t["return_pct"] for t in sig_trades) / len(sig_trades), 2),
                }
    
    # 最近10笔
    report["recent_trades"] = trades[-10:]
    
    # NAV表现
    if len(daily.get("days", [])) >= 2:
        first = daily["days"][0]
        last = daily["days"][-1]
        report["nav_performance"] = {
            "start_date": first["date"],
            "end_date": last["date"],
            "start_nav": first["nav"],
            "end_nav": last["nav"],
            "total_return": round((last["nav"] / first["nav"] - 1) * 100, 2) if first["nav"] > 0 else 0,
            "max_drawdown": daily.get("max_drawdown", 0),
            "trading_days": len(daily["days"]),
        }
    
    # 生成建议
    suggestions = []
    
    # 1. 胜率过低
    wr = report["summary"]["win_rate"]
    if wr < 45 and len(trades) >= 15:
        suggestions.append({
            "type": "提高门槛",
            "suggestion": f"胜率仅{wr}%，建议提高买入信号门槛（当前值→+10）",
        })
    
    # 2. 持仓时间过短
    avg_hold = report["summary"]["avg_hold_days"]
    if avg_hold < 3 and len(trades) >= 10:
        suggestions.append({
            "type": "减少交易频率",
            "suggestion": f"平均持仓{avg_hold}天，过于频繁。建议提高止损容忍度或增加确认机制",
        })
    
    # 3. 亏损原因集中
    for reason, stats in report["by_reason"].items():
        if stats["count"] >= 5 and stats.get("win_rate", 100) < 30:
            suggestions.append({
                "type": "修复卖出逻辑",
                "suggestion": f"{reason}类卖出胜率仅{stats.get('win_rate', 0)}%（{stats['count']}笔），检查是否过度触发",
            })
    
    # 4. 因子无效
    for factor, stats in report["by_factor"].items():
        if not stats.get("is_effective") and stats.get("high_score_trades", 0) >= 5:
            suggestions.append({
                "type": "降权因子",
                "suggestion": f"{factor}高分胜率({stats['high_score_winrate']}%)反而不比低分({stats['low_score_winrate']}%)好，考虑降权或移除",
            })
    
    report["suggestions"] = suggestions
    
    _save(STRATEGY_REPORT, report)
    return report


# ============================================================
# 4. 状态摘要（daily-improve读取）
# ============================================================

def get_status() -> str:
    """返回人类可读的策略状态"""
    trade_log = _load(TRADE_LOG, {"trades": [], "metadata": {}})
    daily = _load(DAILY_STATS, {"days": []})
    report = _load(STRATEGY_REPORT, {})
    
    lines = ["📊 StockRadar 策略状态"]
    
    # 基本数据
    trades = trade_log.get("trades", [])
    meta = trade_log.get("metadata", {})
    lines.append(f"已平仓: {len(trades)}笔 | 胜率: {meta.get('win_rate', '?')}% | "
                 f"均收益: {meta.get('avg_return', '?')}% | 总盈亏: ¥{meta.get('total_pnl', '?')}")
    lines.append(f"平均持仓: {meta.get('avg_hold_days', '?')}天 | "
                 f"最佳: {meta.get('best_trade', '?')}% | 最差: {meta.get('worst_trade', '?')}%")
    
    # 数据状态
    status = report.get("data_status", "insufficient")
    if status == "insufficient":
        lines.append(f"\n⏳ 数据积累中: {len(trades)}/20笔，暂不调参数")
    elif status == "accumulating":
        lines.append(f"\n📈 数据积累中: {len(trades)}/30笔，可谨慎调参")
    else:
        lines.append(f"\n✅ 数据充足: {len(trades)}笔，可正常优化")
    
    # NAV表现
    nav_perf = report.get("nav_performance", {})
    if nav_perf:
        lines.append(f"\nNAV: {nav_perf.get('start_nav', '?')} → {nav_perf.get('end_nav', '?')} "
                     f"({nav_perf.get('total_return', '?')}%) | "
                     f"最大回撤: {nav_perf.get('max_drawdown', '?')}%")
    
    # 卖出原因统计
    by_reason = report.get("by_reason", {})
    if by_reason:
        lines.append("\n卖出原因:")
        for reason, stats in sorted(by_reason.items(), key=lambda x: x[1]["count"], reverse=True):
            lines.append(f"  {reason}: {stats['count']}笔 胜率{stats.get('win_rate', '?')}% "
                        f"均收益{stats.get('avg_return', '?')}%")
    
    # 建议
    suggestions = report.get("suggestions", [])
    if suggestions:
        lines.append(f"\n⚠️ 建议({len(suggestions)}条):")
        for s in suggestions[:5]:
            lines.append(f"  • [{s['type']}] {s['suggestion']}")
    
    # 最近交易
    if trades:
        lines.append(f"\n最近交易:")
        for t in trades[-5:]:
            emoji = "✅" if t["is_win"] else "❌"
            lines.append(f"  {emoji} {t['code']} {t.get('name','')} "
                        f"{t['return_pct']}% ({t['hold_days']}天) {t['reason']}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(get_status())
    else:
        report = generate_strategy_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("\n" + get_status())
