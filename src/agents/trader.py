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
        """快速回测 — 使用当前数据"""
        from src.backtest.engine import BacktestEngine
        from src.backtest.a_share_constraints import AShareConstraints
        import pandas as pd
        from datetime import datetime

        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is None or quote.empty:
            return ActionResult(success=False, message="无行情数据")

        scores_fn = self.get_tool("score_all")
        if scores_fn is None:
            return ActionResult(success=False, message="评分工具不可用")

        codes = self.context.read("codes", quote["code"].unique().tolist())
        financial = self.context.read("financial_data", pd.DataFrame()) if self.context else pd.DataFrame()

        # 跑简化回测
        capital = 1_000_000
        holdings = {}
        nav_list = []
        dates = sorted(quote["date"].dt.date.unique())

        for i, dt in enumerate(dates[::10]):  # 每10天调仓
            ds = dt.strftime("%Y-%m-%d")
            day = quote[quote["date"].dt.date == dt]
            if day.empty: continue
            prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

            # 评分
            hist = quote[quote["date"].dt.date <= dt]
            data = {"daily_quote": hist, "codes": codes, "financial": financial, "northbound": pd.DataFrame()}
            try:
                scores = scores_fn(data, ds)
            except: continue

            target = scores.head(10).index.tolist()

            # 卖出
            for c in list(holdings):
                if c not in target and c in prices and prices[c]>0:
                    capital += holdings.pop(c)["sh"] * prices[c] * 0.999

            # 买入
            need = [c for c in target if c not in holdings and c in prices and prices[c]>0]
            if need and capital > 0:
                per = capital / len(need)
                for c in need:
                    sh = int(per/prices[c]/100)*100
                    if sh > 0 and capital >= sh*prices[c]*1.001:
                        capital -= sh*prices[c]*1.001
                        holdings[c] = {"sh": sh, "bp": prices[c]}

            pv = capital + sum(h["sh"]*prices.get(c,h["bp"]) for c,h in holdings.items() if c in prices)
            nav_list.append({"date": ds, "nav": pv})

        if len(nav_list) < 2:
            return ActionResult(success=False, message="数据不足，无法回测")

        nav_df = pd.DataFrame(nav_list)
        total_ret = (nav_df["nav"].iloc[-1]/capital*10 - 1)*100  # 相对初始
        ret = (nav_df["nav"].iloc[-1]/1_000_000 - 1)*100

        lines = [
            f"📊 **快速回测结果**",
            f"区间: {nav_df['date'].iloc[0]} ~ {nav_df['date'].iloc[-1]}",
            f"总收益: {ret:+.1f}%",
            f"调仓次数: {len(nav_list)}",
        ]
        return ActionResult(success=True, message="\n".join(lines))

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
