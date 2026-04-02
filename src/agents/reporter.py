"""ReporterAgent — 报告生成Agent

职责：日报/周报/月报、市场总结、新闻情绪
"""

import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger
import pandas as pd

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult
from src.data.stock_names import stock_name


class ReporterAgent(BaseAgent):
    """报告Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(name="reporter", description="报告生成、市场总结")
        super().__init__(config, context, message_bus)

    async def perceive(self, context) -> Observation:
        msg = context.read("user_message", "") if context else ""
        return Observation(content={"user_message": msg})

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")
        if "周报" in msg:
            return Plan(actions=[{"action": "weekly_report"}])
        elif "月报" in msg:
            return Plan(actions=[{"action": "monthly_report"}])
        elif "新闻" in msg or "情绪" in msg or "舆情" in msg:
            return Plan(actions=[{"action": "news_sentiment"}])
        return Plan(actions=[{"action": "daily_report"}])

    async def act(self, plan: Plan) -> ActionResult:
        action = plan.actions[0].get("action", "daily_report") if plan.actions else "daily_report"
        try:
            if action == "weekly_report":
                return await self._weekly_report()
            elif action == "monthly_report":
                return await self._monthly_report()
            elif action == "news_sentiment":
                return await self._news_sentiment()
            return await self._daily_report()
        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            return ActionResult(success=False, message=f"报告失败: {e}")

    async def _daily_report(self) -> ActionResult:
        """增强日报 — 指数 + 涨跌排行 + 评分 + 持仓"""
        now = datetime.now()
        lines = [f"📰 **StockRadar 日报** {now.strftime('%Y-%m-%d')}\n"]

        # 1) 市场指数
        qveris_key = os.environ.get("QVERIS_API_KEY", "")
        if qveris_key:
            try:
                from src.data.qveris_adapter import fetch_index_quote_qv
                idx = fetch_index_quote_qv("000300")
                if idx and idx.get("最新(点)", "") not in ("", "---"):
                    chg = idx.get("涨跌幅(%)", "0")
                    try:
                        chg_f = float(chg)
                        mood = "🔴" if chg_f < -1 else "🟡" if chg_f < 0 else "🟢"
                    except ValueError:
                        mood = ""
                    lines.append(f"{mood} **沪深300:** {idx.get('最新(点)')} ({chg}%)")
                    lines.append(f"   成交额: {idx.get('成交额', '?')}")
            except Exception as e:
                lines.append("   (实时行情暂不可用)")
                logger.warning(f"QVeris失败: {e}")

        # 2) 关注池涨跌
        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is not None and not quote.empty:
            latest_date = quote["date"].max()
            day = quote[quote["date"] == latest_date]
            if not day.empty and "change_pct" in day.columns:
                gains = day[day["change_pct"] > 0].sort_values("change_pct", ascending=False)
                losses = day[day["change_pct"] < 0].sort_values("change_pct")
                lines.append(f"\n📊 **涨跌榜** ({latest_date.strftime('%m-%d')})")
                if not gains.empty:
                    lines.append("🟢 涨:")
                    for _, r in gains.head(3).iterrows():
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) {r['change_pct']:+.2f}%")
                if not losses.empty:
                    lines.append("🔴 跌:")
                    for _, r in losses.head(3).iterrows():
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) {r['change_pct']:+.2f}%")

        # 3) 评分Top5
        scores = self.context.get_scores() if self.context else None
        if scores is not None and not scores.empty:
            lines.append("\n📋 **评分Top5:**")
            for i, (code, row) in enumerate(scores.head(5).iterrows()):
                lines.append(f"  {i+1}. {stock_name(code)} | {row['score_total']:+.2f}")

        # 4) 持仓+净值
        lines.append("\n📦 **模拟持仓:**")
        from src.simulator.nav_tracker import NAVTracker
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                info = nav.get_nav()
                lines.append(f"  净值: {info['nav']:.4f} | 收益: {info['total_return']:+.2f}%")
                lines.append(f"  持仓: {info['holdings_count']}只 | 交易: {info['trades']}笔")
            except Exception:
                lines.append("  模拟模式")
        else:
            lines.append("  尚未建仓，发送'持仓建议'开始")

        # 5) 新闻情绪
        try:
            from src.data.news_sentiment import get_market_sentiment_report
            report = get_market_sentiment_report()
            # 提取情绪指标（只取前5行）
            for line in report.split("\n")[1:5]:
                if line.strip():
                    lines.append(line)
        except Exception:
            pass

        # 6) 持仓诊断
        try:
            from src.evolution.strategy_doctor import diagnose_holdings
            import json as _json
            nav_f = Path(__file__).resolve().parent.parent.parent / "data"
            for f in sorted(nav_f.glob("nav_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:1]:
                nav_data = _json.loads(f.read_text())
                if nav_data.get("holdings"):
                    diag = diagnose_holdings(nav_data)
                    lines.append("\n" + diag)
        except Exception:
            pass

        return ActionResult(success=True, message="\n".join(lines))

    async def _weekly_report(self) -> ActionResult:
        """周报"""
        lines = ["📰 **StockRadar 周报**\n"]
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                from src.simulator.nav_tracker import NAVTracker
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                if len(nav.nav_history) >= 5:
                    nav_df = pd.DataFrame(nav.nav_history)
                    nav_df["date"] = pd.to_datetime(nav_df["date"])
                    latest = nav_df["date"].max()
                    week_ago = latest - pd.Timedelta(days=7)
                    week = nav_df[nav_df["date"] >= week_ago]
                    if len(week) >= 2:
                        week_return = (week["nav"].iloc[-1] / week["nav"].iloc[0] - 1) * 100
                        lines.append(f"📊 **本周收益:** {week_return:+.2f}%")
            except Exception:
                pass
        if len(lines) <= 2:
            lines.append("本周暂无数据，发送'持仓建议'开始模拟交易")
        return ActionResult(success=True, message="\n".join(lines))

    async def _monthly_report(self) -> ActionResult:
        """月报"""
        lines = ["📰 **StockRadar 月报**\n"]
        lines.append("月报功能完善中，请使用'周报'或'日报'")
        return ActionResult(success=True, message="\n".join(lines))

    async def _news_sentiment(self) -> ActionResult:
        """新闻情绪报告"""
        try:
            from src.data.news_sentiment import get_market_sentiment_report
            report = get_market_sentiment_report()
            return ActionResult(success=True, message=report)
        except Exception as e:
            return ActionResult(success=False, message="新闻情绪暂不可用: " + str(e))
