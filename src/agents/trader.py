"""TraderAgent — 交易决策Agent

职责：持仓管理、交易执行、风控检查、净值追踪
"""

from loguru import logger

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult


class TraderAgent(BaseAgent):
    """交易Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="trader",
            description="交易决策、持仓管理、风控",
            tools=["get_portfolio", "execute_trade", "get_trade_log", "get_nav"],
        )
        super().__init__(config, context, message_bus)

    async def perceive(self, context) -> Observation:
        msg = context.read("user_message", "") if context else ""
        scores = context.get_scores() if context else None
        portfolio = context.get_portfolio() if context else {}

        return Observation(
            content={
                "user_message": msg,
                "has_scores": scores is not None,
                "portfolio_size": len(portfolio.get("holdings", [])),
            },
            source="user" if msg else "scheduler",
        )

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")

        if "持仓" in msg or "组合" in msg:
            return Plan(actions=[{"action": "show_portfolio"}])

        if "净值" in msg or "收益" in msg or "盈亏" in msg:
            return Plan(actions=[{"action": "show_nav"}])

        if "交易" in msg or "记录" in msg:
            return Plan(actions=[{"action": "show_trades"}])

        if "回测" in msg:
            return Plan(actions=[{"action": "run_backtest"}])

        # 默认：每日决策
        if observation.content.get("has_scores"):
            return Plan(actions=[{"action": "daily_decision"}])

        return Plan(actions=[{"action": "show_portfolio"}])

    async def act(self, plan: Plan) -> ActionResult:
        if not plan.actions:
            return ActionResult(success=False, message="无交易任务")

        action = plan.actions[0].get("action", "")

        handlers = {
            "show_portfolio": self._show_portfolio,
            "show_nav": self._show_nav,
            "show_trades": self._show_trades,
            "run_backtest": self._run_backtest,
            "daily_decision": self._daily_decision,
        }

        handler = handlers.get(action)
        if handler:
            return await handler()
        return ActionResult(success=False, message=f"未知操作: {action}")

    async def _show_portfolio(self) -> ActionResult:
        fn = self.get_tool("get_portfolio")
        if fn is None:
            portfolio = self.context.get_portfolio() if self.context else {}
        else:
            portfolio = fn()

        holdings = portfolio.get("holdings", [])
        if not holdings:
            return ActionResult(success=True, message="📦 当前无持仓")

        msg = "📦 **当前持仓:**\n"
        for h in holdings:
            msg += f"  • {h.get('code', '?')} {h.get('shares', 0)}股\n"
        return ActionResult(success=True, message=msg, data=portfolio)

    async def _show_nav(self) -> ActionResult:
        fn = self.get_tool("get_nav")
        if fn:
            try:
                nav = fn()
                msg = f"💰 **净值:** {nav}"
                return ActionResult(success=True, message=msg)
            except Exception as e:
                return ActionResult(success=False, message=f"获取净值失败: {e}")
        return ActionResult(success=True, message="净值追踪暂未启动")

    async def _show_trades(self) -> ActionResult:
        fn = self.get_tool("get_trade_log")
        if fn:
            try:
                trades = fn()
                msg = f"📋 **交易记录:** {len(trades)}笔\n"
                for t in (trades[-5:] if isinstance(trades, list) else []):
                    msg += f"  • {t}\n"
                return ActionResult(success=True, message=msg)
            except Exception:
                pass
        return ActionResult(success=True, message="暂无交易记录")

    async def _run_backtest(self) -> ActionResult:
        fn = self.get_tool("run_backtest")
        if fn is None:
            return ActionResult(success=False, message="回测引擎不可用")
        return ActionResult(success=True, message="回测功能请使用 scripts/run_backtest.py")

    async def _daily_decision(self) -> ActionResult:
        """每日交易决策"""
        scores = self.context.get_scores() if self.context else None
        if scores is None:
            return ActionResult(success=False, message="无评分数据，请先运行分析")

        # 简单版：Top10持仓建议
        top10 = scores.head(10)
        msg = "🔄 **今日持仓建议:**\n"
        msg += "建议持有:\n"
        for i, (code, row) in enumerate(top10.iterrows()):
            msg += f"  {i+1}. {code} (评分={row['score_total']:.2f})\n"

        return ActionResult(success=True, message=msg)
