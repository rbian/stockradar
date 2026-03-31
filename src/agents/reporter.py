"""ReporterAgent — 报告生成Agent

职责：日报/周报/月报、市场总结、消息格式化
"""

from datetime import datetime

from loguru import logger

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult


class ReporterAgent(BaseAgent):
    """报告Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="reporter",
            description="报告生成、市场总结",
        )
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
        else:
            return Plan(actions=[{"action": "daily_report"}])

    async def act(self, plan: Plan) -> ActionResult:
        action = plan.actions[0].get("action", "daily_report") if plan.actions else "daily_report"

        if action == "weekly_report":
            return await self._weekly_report()
        elif action == "monthly_report":
            return await self._monthly_report()
        else:
            return await self._daily_report()

    async def _daily_report(self) -> ActionResult:
        """生成日报"""
        now = datetime.now()
        header = f"📰 **A股智能盯盘日报** {now.strftime('%Y-%m-%d')}\n\n"

        # 从context获取数据
        scores = self.context.get_scores() if self.context else None
        portfolio = self.context.get_portfolio() if self.context else {}
        regime, confidence = self.context.get_market_regime() if self.context else ("unknown", 0)

        sections = [header]

        # 市场状态
        sections.append(f"🌡️ **市场状态:** {regime} (置信度{confidence:.0%})\n")

        # 持仓概况
        holdings = portfolio.get("holdings", [])
        if holdings:
            sections.append(f"📦 **持仓:** {len(holdings)}只")
        else:
            sections.append("📦 **持仓:** 空")

        # 评分Top5
        if scores is not None and not scores.empty:
            sections.append("\n📊 **评分Top5:**")
            for i, (code, row) in enumerate(scores.head(5).iterrows()):
                sections.append(f"  {i+1}. {code} | {row['score_total']:.2f}")

        msg = "\n".join(sections)
        return ActionResult(success=True, message=msg)

    async def _weekly_report(self) -> ActionResult:
        """周报"""
        msg = "📰 **周报功能需配合净值数据使用**\n请确保系统已运行满一周。"
        return ActionResult(success=True, message=msg)

    async def _monthly_report(self) -> ActionResult:
        """月报"""
        msg = "📰 **月报功能需配合净值和交易数据使用**\n请确保系统已运行满一个月。"
        return ActionResult(success=True, message=msg)
