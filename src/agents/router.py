"""RouterAgent — 意图识别+任务分发

用户消息 → 理解意图 → 转发给合适的Agent
"""

import re
from loguru import logger

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult


class RouterAgent(BaseAgent):
    """路由Agent — 系统入口，理解用户意图并分发"""

    # 意图 → Agent映射规则
    ROUTES = {
        # 分析类 → AnalystAgent
        r"(分析|研究|看看|怎么样|基本面|技术面|财报).*(\d{6}|[\u4e00-\u9fa5]{2,4})": "analyst",
        r"(市场|大盘|指数|行情|走势)": "analyst",
        r"(北向|资金|主力|融资)": "analyst",
        r"(评分|排名|Top|选股|推荐|IC|因子)": "analyst",

        # 交易类 → TraderAgent
        r"(持仓|组合|买入|卖出|换仓|止[损盈])": "trader",
        r"(净值|收益|盈亏|绩效|回撤)": "trader",
        r"(激进|稳健|防御|保守|策略)": "trader",

        # 回测类 → TraderAgent（backtest子功能）
        r"(回测|测试|验证|策略效果)": "trader",

        # 进化类 → EvolverAgent
        r"(因子.*表现|IC|进化|优化|权重)": "evolver",
        r"(诊断|体检|复盘|失败)": "evolver",

        # 报告类 → ReporterAgent
        r"(报告|日报|周报|月报|总结|新闻|情绪|舆情)": "reporter",
        r"(涨停|跌停|热点|板块|概念)": "reporter",

        # 帮助
        r"(帮助|help|怎么用|功能|能做什么)": "help",
    }

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="router",
            description="意图识别和任务分发",
        )
        super().__init__(config, context, message_bus)

    async def perceive(self, context) -> Observation:
        user_msg = context.read("user_message", "") if context else ""
        return Observation(
            content={"user_message": user_msg},
            source="user",
        )

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")

        if not msg:
            return Plan(actions=[])

        # 规则匹配
        target = self._match_intent(msg)

        if target == "help":
            return Plan(actions=[{
                "target": "none",
                "response": self._help_text(),
            }], reasoning="帮助信息")

        if target is None:
            # 无法匹配 → 用LLM（如果可用）或默认给analyst
            target = "analyst"

        return Plan(actions=[{
            "target": target,
            "user_message": msg,
        }], reasoning=f"意图匹配: {msg[:30]}... → {target}")

    async def act(self, plan: Plan) -> ActionResult:
        if not plan.actions:
            return ActionResult(success=False, message="无法理解请求")

        action = plan.actions[0]

        # 直接回复（help等）
        if "response" in action or action.get("target") == "none":
            return ActionResult(success=True, message=action.get("response", "未知"))

        # 转发给目标Agent
        target = action.get("target", "")
        user_msg = action.get("user_message", "")

        if self.bus:
            await self.bus.send(
                sender="router",
                receiver=target,
                msg_type="user_request",
                priority=2,
                content={"user_message": user_msg},
            )

        return ActionResult(
            success=True,
            data={"forwarded_to": target},
            message=f"已转发给{target}",
        )

    def _match_intent(self, text: str) -> str | None:
        """规则匹配意图"""
        for pattern, target in self.ROUTES.items():
            if re.search(pattern, text):
                return target
        return None

    def _help_text(self) -> str:
        return (
            "📊 **A股智能盯盘Agent**\n\n"
            "你可以问我：\n"
            "• 分析宁德时代 / 看看300750\n"
            "• 今天持仓怎么样\n"
            "• 市场行情如何\n"
            "• 当前评分排名\n"
            "• 净值和收益情况\n"
            "• 跑一下回测\n"
            "• 因子表现如何\n"
            "• 生成日报/周报\n"
        )
