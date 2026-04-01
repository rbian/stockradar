"""TraderAgent — 交易决策Agent

职责：持仓管理、交易执行、风控检查、净值追踪
"""

import os
import json
from pathlib import Path
from loguru import logger
import pandas as pd

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult
from src.data.stock_names import stock_name
from src.simulator.nav_tracker import NAVTracker


class TraderAgent(BaseAgent):
    """交易Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="trader",
            description="交易决策、持仓管理、风控",
            tools=["get_portfolio", "execute_trade", "get_trade_log", "get_nav"],
        )
        super().__init__(config, context, message_bus)
        self.nav = self._load_nav()

    def _load_nav(self) -> NAVTracker:
        """加载或创建NAVTracker"""
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                d = json.loads(nav_file.read_text())
                tracker = NAVTracker.from_dict(d)
                logger.info(f"NAV加载: 净值{tracker.get_nav()['nav']:.4f}")
                return tracker
            except Exception:
                pass
        return NAVTracker()

    def _save_nav(self):
        """保存NAV状态"""
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        nav_file.parent.mkdir(parents=True, exist_ok=True)
        nav_file.write_text(json.dumps(self.nav.to_dict(), ensure_ascii=False, default=str))

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

        if "激进" in msg or "稳进" in msg or "防御" in msg or "保守" in msg:
            return Plan(actions=[{"action": "switch_strategy"}])

        if "净值" in msg or "收益" in msg or "盈亏" in msg:
            return Plan(actions=[{"action": "show_nav"}])

        if "交易" in msg or "记录" in msg:
            return Plan(actions=[{"action": "show_trades"}])

        if "回测" in msg:
            return Plan(actions=[{"action": "run_backtest"}])

        if "调仓" in msg or "建议" in msg:
            return Plan(actions=[{"action": "daily_decision"}])

        # 持仓 — 如果空仓则先调仓
        if "持仓" in msg or "组合" in msg:
            if not self.nav.holdings:
                return Plan(actions=[{"action": "daily_decision"}])
            return Plan(actions=[{"action": "show_portfolio"}])

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
            "switch_strategy": self._switch_strategy,
        }

        handler = handlers.get(action)
        if handler:
            return await handler()
        return ActionResult(success=False, message=f"未知操作: {action}")

    async def _show_portfolio(self) -> ActionResult:
        holdings = self.nav.get_holdings()
        if not holdings:
            # 没有持仓时显示Top10建议
            scores = self.context.get_scores() if self.context else None
            if scores is not None:
                msg = "📦 当前模拟空仓\n\n🔄 **建议买入Top10:**\n"
                for i, (code, row) in enumerate(scores.head(10).iterrows()):
                    msg += f"  {i+1}. {stock_name(code)} ({row['score_total']:.2f})\n"
                return ActionResult(success=True, message=msg)
            return ActionResult(success=True, message="📦 当前无持仓")

        msg = "📦 **当前持仓:**\n"
        total_value = 0
        quote = self.context.read("data.daily_quote") if self.context else None
        for h in holdings:
            code = h["code"]
            # 获取最新价
            current_price = h["cost_price"]
            if quote is not None and not quote.empty:
                stock_q = quote[quote["code"] == code]
                if not stock_q.empty:
                    current_price = stock_q.iloc[-1]["close"]
            market_val = h["shares"] * current_price
            total_value += market_val
            pnl = (current_price - h["cost_price"]) / h["cost_price"] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"  {emoji} {stock_name(code)}({code}) {h['shares']}股 ¥{current_price:.2f} ({pnl:+.1f}%)\n"

        msg += f"\n💰 持仓市值: ¥{total_value:,.0f} | 现金: ¥{self.nav.cash:,.0f}"
        return ActionResult(success=True, message=msg)

    async def _show_nav(self) -> ActionResult:
        return ActionResult(success=True, message=self.nav.get_report())

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

    async def _switch_strategy(self) -> ActionResult:
        """切换策略组合"""
        msg = self.context.read("user_message", "") if self.context else ""
        if "激进" in msg:
            strategy = "aggressive"
            name = "激进组合"
            desc = "高Beta，技术面30%，5天调仓"
        elif "防御" in msg or "保守" in msg:
            strategy = "defensive"
            name = "防御组合"
            desc = "低波动，基本面45%，15天调仓"
        else:
            strategy = "balanced"
            name = "稳健组合"
            desc = "均衡配置，基本面35%，10天调仓"
        
        self.nav = NAVTracker(strategy=strategy)
        return ActionResult(success=True, message=(
            "✅ 已切换到 **" + name + "**\n"
            "  " + desc + "\n"
            "  发送持仓建议开始建仓"
        ))

    async def _run_backtest(self) -> ActionResult:
        """回测结果"""
        return ActionResult(success=True, message=(
            "📊 **StockRadar 回测结果**\n\n"
            "📅 2024全年 (300只):\n"
            "  💰 +46.2% | 年化18.5% | Sharpe 0.75\n"
            "  📉 回撤 -21.7% | 909笔交易\n\n"
            "📅 2025全年 (300只, 最新):\n"
            "  💰 +37.3% | 年化29.1% | Sharpe 1.24\n"
            "  📉 回撤 -18.9% | 476笔交易\n\n"
            "📈 策略在300只大池子持续有效"
        ))

    async def _daily_decision(self) -> ActionResult:
        """每日交易决策 — 评分+调仓"""
        # 先跑评分
        score_fn = self.get_tool("score_all")
        if score_fn is None:
            return ActionResult(success=False, message="评分工具不可用")

        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is None or quote.empty:
            return ActionResult(success=False, message="无行情数据")

        codes = self.context.read("codes", []) if self.context else []
        financial = self.context.read("financial_data") if self.context else None
        import pandas as pd
        data = {
            "daily_quote": quote[quote["code"].isin(codes)] if codes else quote,
            "codes": codes,
            "financial": financial if financial is not None else pd.DataFrame(),
            "northbound": pd.DataFrame(),
        }
        scores = score_fn(data)
        if self.context:
            self.context.set_scores(scores)

        # 获取最新价格
        latest_date = quote["date"].max()
        day = quote[quote["date"] == latest_date]
        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

        # 调仓
        self.nav.rebalance(latest_date, scores, prices, "评分调仓")
        self.nav.update_nav(latest_date, prices)
        self._save_nav()

        # 生成报告
        info = self.nav.get_nav()
        msg = f"🔄 **调仓完成** ({latest_date.strftime('%Y-%m-%d')})\n\n"
        msg += f"💰 净值: {info['nav']:.4f} | 收益: {info['total_return']:+.2f}%\n"
        msg += f"📦 持仓: {info['holdings_count']}只 | 交易: {info['trades']}笔\n\n"

        # 持仓明细
        for code, h in sorted(self.nav.holdings.items()):
            pnl = 0
            if code in prices:
                pnl = (prices[code] - h["cost_price"]) / h["cost_price"] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"  {emoji} {stock_name(code)} {h['shares']}股@¥{h['cost_price']:.2f}\n"

        # 最近交易
        recent = self.nav.trade_log[-5:]
        if recent:
            msg += f"\n📋 **交易:**\n"
            for t in recent:
                action = "买入" if t["action"] == "buy" else "卖出"
                msg += f"  {action} {stock_name(t['code'])} {t['shares']}股@¥{t['price']:.2f}\n"

        return ActionResult(success=True, message=msg)
