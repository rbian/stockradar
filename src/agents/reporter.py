"""ReporterAgent — 报告生成Agent

职责：日报/周报/月报、市场总结、消息格式化
"""

import os
from datetime import datetime
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
        return Plan(actions=[{"action": "daily_report"}])

    async def act(self, plan: Plan) -> ActionResult:
        action = plan.actions[0].get("action", "daily_report") if plan.actions else "daily_report"
        try:
            if action == "weekly_report": return await self._weekly_report()
            elif action == "monthly_report": return await self._monthly_report()
            return await self._daily_report()
        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            return ActionResult(success=False, message=f"报告失败: {e}")

    async def _daily_report(self) -> ActionResult:
        """增强日报 — 指数 + 涨跌排行 + 评分 + 关注池"""
        now = datetime.now()
        lines = [f"📰 **StockRadar 日报** {now.strftime('%Y-%m-%d')}\n"]

        # 1) 市场指数（QVeris实时）
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
            except Exception:
                pass

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
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) ¥{r['close']:.2f} ({r['change_pct']:+.2f}%)")
                if not losses.empty:
                    lines.append("🔴 跌:")
                    for _, r in losses.head(3).iterrows():
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) ¥{r['close']:.2f} ({r['change_pct']:+.2f}%)")

        # 3) 评分Top5
        scores = self.context.get_scores() if self.context else None
        if scores is not None and not scores.empty:
            lines.append("\n📋 **评分Top5:**")
            for i, (code, row) in enumerate(scores.head(5).iterrows()):
                lines.append(f"  {i+1}. {stock_name(code)} | {row['score_total']:+.2f}")

        # 4) 持仓
        portfolio = self.context.get_portfolio() if self.context else {}
        holdings = portfolio.get("holdings", [])
        if holdings:
            lines.append(f"\n📦 **持仓:** {len(holdings)}只")
        else:
            lines.append("\n📦 **持仓:** 模拟模式暂无持仓")

        return ActionResult(success=True, message="\n".join(lines))

    async def _weekly_report(self) -> ActionResult:
        """周报 — 本周评分变化 + 涨跌汇总"""
        lines = ["📰 **StockRadar 周报**\n"]

        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is not None and not quote.empty:
            # 最近5个交易日涨跌
            latest_date = quote["date"].max()
            week_start = latest_date - pd.Timedelta(days=7)
            week = quote[(quote["date"] >= week_start) & (quote["date"] <= latest_date)]
            if not week.empty and "change_pct" in week.columns:
                lines.append("📈 **本周涨跌:**")
                for code in sorted(week["code"].unique())[:10]:
                    stock = week[week["code"] == code]
                    if len(stock) >= 2:
                        chg = (stock.iloc[-1]["close"] / stock.iloc[0]["close"] - 1) * 100
                        lines.append(f"  {stock_name(code)}({code}): {chg:+.1f}%")

        lines.append("\n*周报功能持续完善中*")
        return ActionResult(success=True, message="\n".join(lines))

    async def _monthly_report(self) -> ActionResult:
        """月报"""
        lines = ["📰 **StockRadar 月报**\n"]
        lines.append("*月报需配合净值追踪功能，计划下版本支持*")
        return ActionResult(success=True, message="\n".join(lines))
