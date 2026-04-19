"""周度复盘自动分析器

自动分析交易记录，识别亏损模式，生成参数调整建议。
周一自动执行。

分析维度:
1. 胜率/盈亏比趋势
2. 亏损集中度（哪类股票亏最多）
3. 过早止损 vs 过晚止损
4. 行业/板块集中度
5. 持仓时间vs收益关系
"""

import json
import numpy as np
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta


class WeeklyReviewer:
    """周度复盘分析器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            self.data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        else:
            self.data_dir = Path(data_dir)

    def analyze(self) -> dict:
        """执行完整周度分析

        Returns:
            分析结果字典，含调整建议
        """
        trade_log = self._load_trades()
        if not trade_log:
            return {"status": "no_data", "message": "无交易记录"}

        sells = [t for t in trade_log if t.get("action") == "sell" and "pnl" in t]
        buys = [t for t in trade_log if t.get("action") == "buy"]

        if len(sells) < 5:
            return {"status": "insufficient", "message": f"仅{len(sells)}笔卖出，不足5笔"}

        result = {
            "status": "ok",
            "total_trades": len(trade_log),
            "total_sells": len(sells),
            "total_buys": len(buys),
        }

        # 1. 基础统计
        result["basic_stats"] = self._basic_stats(sells)

        # 2. 亏损模式分析
        result["loss_patterns"] = self._loss_patterns(sells)

        # 3. 时间分析
        result["timing_analysis"] = self._timing_analysis(trade_log)

        # 4. 参数调整建议
        result["adjustments"] = self._generate_adjustments(result)

        # 保存报告
        self._save_report(result)

        return result

    def _load_trades(self) -> list:
        """加载交易记录"""
        trade_file = self.data_dir / "trade_log.json"
        if not trade_file.exists():
            return []
        try:
            return json.loads(trade_file.read_text())
        except Exception:
            return []

    def _basic_stats(self, sells: list) -> dict:
        """基础统计"""
        pnls = [t["pnl"] for t in sells]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        # 近10笔 vs 之前
        recent = pnls[-10:] if len(pnls) >= 10 else pnls
        earlier = pnls[:-10] if len(pnls) > 10 else []

        recent_win_rate = len([p for p in recent if p > 0]) / len(recent) if recent else 0
        earlier_win_rate = len([p for p in earlier if p > 0]) / len(earlier) if earlier else 0

        return {
            "win_rate": len(wins) / len(pnls) if pnls else 0,
            "total_pnl": sum(pnls),
            "avg_win": np.mean(wins) if wins else 0,
            "avg_loss": np.mean(losses) if losses else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0,
            "max_win": max(pnls) if pnls else 0,
            "max_loss": min(pnls) if pnls else 0,
            "recent_win_rate": recent_win_rate,
            "earlier_win_rate": earlier_win_rate,
            "trend": "improving" if recent_win_rate > earlier_win_rate else "declining",
        }

    def _loss_patterns(self, sells: list) -> dict:
        """亏损模式分析"""
        losses = [t for t in sells if t["pnl"] < -100]  # 亏损>100元
        if not losses:
            return {"message": "无显著亏损", "top_losses": []}

        # 按亏损金额排序
        sorted_losses = sorted(losses, key=lambda x: x["pnl"])
        top_losses = sorted_losses[:5]

        # 计算亏损集中度
        total_loss = sum(t["pnl"] for t in losses)
        top5_loss = sum(t["pnl"] for t in top_losses)
        concentration = abs(top5_loss / total_loss) if total_loss != 0 else 0

        return {
            "total_loss_trades": len(losses),
            "total_loss_amount": total_loss,
            "top5_concentration": concentration,
            "top_losses": [
                {
                    "code": t.get("code", "?"),
                    "date": t.get("date", "?"),
                    "pnl": t["pnl"],
                    "shares": t.get("shares", 0),
                    "price": t.get("price", 0),
                }
                for t in top_losses
            ],
        }

    def _timing_analysis(self, trades: list) -> dict:
        """交易时间分析"""
        if not trades:
            return {}

        # 按日期统计
        date_pnl = {}
        for t in trades:
            if t.get("action") == "sell" and "pnl" in t:
                d = str(t.get("date", ""))[:10]
                date_pnl.setdefault(d, []).append(t["pnl"])

        if not date_pnl:
            return {}

        daily_totals = {d: sum(pnls) for d, pnls in date_pnl.items()}
        worst_day = min(daily_totals, key=daily_totals.get)
        best_day = max(daily_totals, key=daily_totals.get)

        return {
            "trading_days": len(daily_totals),
            "best_day": {"date": best_day, "pnl": daily_totals[best_day]},
            "worst_day": {"date": worst_day, "pnl": daily_totals[worst_day]},
        }

    def _generate_adjustments(self, result: dict) -> list:
        """生成参数调整建议"""
        adjustments = []
        stats = result.get("basic_stats", {})
        patterns = result.get("loss_patterns", {})

        win_rate = stats.get("win_rate", 0)
        profit_factor = stats.get("profit_factor", 0)
        avg_loss = abs(stats.get("avg_loss", 0))
        avg_win = stats.get("avg_win", 0)

        # 胜率太低 → 收紧买入条件
        if win_rate < 0.35:
            adjustments.append({
                "param": "buy_signal_threshold",
                "action": "raise",
                "current": "75",
                "suggested": "80",
                "reason": f"胜率仅{win_rate:.0%}，提高信号门槛减少低质量交易",
            })

        # 盈亏比太差 → 调整止损
        if profit_factor < 0.5 and avg_loss > 0:
            ratio = avg_win / avg_loss if avg_loss > 0 else 0
            tighter_stop = max(5, 10 - (1 - ratio) * 5)
            adjustments.append({
                "param": "stop_loss_pct",
                "action": "tighten",
                "current": "10%",
                "suggested": f"{tighter_stop:.0f}%",
                "reason": f"盈亏比仅{ratio:.2f}，收紧止损控制单笔亏损",
            })

        # 亏损集中度高 → 需要分散
        concentration = patterns.get("top5_concentration", 0)
        if concentration > 0.6:
            adjustments.append({
                "param": "max_single_position",
                "action": "reduce",
                "current": "15%",
                "suggested": "10%",
                "reason": f"Top5亏损占{concentration:.0%}，降低单只上限",
            })

        # 近期趋势恶化
        if stats.get("trend") == "declining":
            adjustments.append({
                "param": "overall_risk",
                "action": "reduce",
                "current": "normal",
                "suggested": "defensive",
                "reason": "近期胜率下降趋势，切换到防御模式",
            })

        if not adjustments:
            adjustments.append({
                "param": "none",
                "action": "maintain",
                "reason": "当前参数表现尚可，无需调整",
            })

        return adjustments

    def _save_report(self, result: dict):
        """保存周度报告"""
        report_dir = self.data_dir / "weekly_reviews"
        report_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = report_dir / f"{date_str}.json"

        # JSON序列化处理numpy类型
        def default_serializer(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        report_file.write_text(
            json.dumps(result, ensure_ascii=False, default=default_serializer, indent=2)
        )
        logger.info(f"周度复盘报告已保存: {report_file}")

    def format_report(self, result: dict) -> str:
        """格式化为可读报告"""
        if result.get("status") != "ok":
            return f"⚠️ 复盘跳过: {result.get('message', '未知')}"

        stats = result["basic_stats"]
        patterns = result.get("loss_patterns", {})
        adj = result.get("adjustments", [])

        lines = [
            "📊 **周度复盘报告**",
            f"  交易: {result['total_sells']}卖/{result['total_buys']}买",
            f"  胜率: {stats['win_rate']:.0%} | 盈亏比: {stats['profit_factor']:.2f}",
            f"  平均盈利: ¥{stats['avg_win']:+,.0f} | 平均亏损: ¥{stats['avg_loss']:,.0f}",
            f"  累计盈亏: ¥{stats['total_pnl']:+,.0f}",
            f"  趋势: {'📈 改善' if stats['trend'] == 'improving' else '📉 恶化'}",
        ]

        if patterns.get("top_losses"):
            lines.append("\n🔴 **最大亏损:**")
            for t in patterns["top_losses"][:3]:
                lines.append(f"  {t['code']} {t['date']} ¥{t['pnl']:+,.0f}")

        if adj:
            lines.append("\n🔧 **调整建议:**")
            for a in adj:
                if a["action"] != "maintain":
                    lines.append(f"  • {a['param']}: {a.get('current','')}→{a.get('suggested','')} ({a['reason']})")
                else:
                    lines.append(f"  ✅ {a['reason']}")

        return "\n".join(lines)
