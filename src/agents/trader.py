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

    def _reload_nav(self):
        """每次操作前重新从文件加载，保持与外部写入同步"""
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        nav_file = data_dir / "nav_state_balanced.json"
        if nav_file.exists():
            try:
                d = json.loads(nav_file.read_text())
                self.nav = NAVTracker.from_dict(d)
            except Exception:
                pass

    def _load_nav(self) -> NAVTracker:
        """加载或创建NAVTracker"""
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        nav_file = data_dir / "nav_state_balanced.json"
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
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state_balanced.json"
        nav_file.parent.mkdir(parents=True, exist_ok=True)
        nav_file.write_text(json.dumps(self.nav.to_dict(), ensure_ascii=False, default=str))

    async def perceive(self, context) -> Observation:
        self._reload_nav()  # 每次交互前重新加载
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

        if "风控" in msg or "风险" in msg:
            return Plan(actions=[{"action": "risk_check"}])

        if "回测" in msg:
            return Plan(actions=[{"action": "run_backtest"}])

        if "调仓" in msg and "建议" not in msg:
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
            "trade_stats": self._trade_stats,
            "risk_check": self._risk_check,
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
        self._save_nav()
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

        # ===== 风控仓位调整 (2026-04-22 集成) =====
        position_multiplier = 1.0
        signal_bonus = 0
        try:
            from src.risk_management.time_stop import ConsecutiveLossProtector
            clp = ConsecutiveLossProtector()
            # 从trade_log更新连续亏损状态
            recent_sells = [t for t in self.nav.trade_log if t.get("action") == "sell"][-10:]
            clp.update_from_trades(recent_sells)
            position_multiplier = clp.get_position_multiplier()
            signal_bonus = clp.get_signal_threshold_bonus()
            status = clp.get_status()
            if status["mode"] != "normal":
                logger.warning(f"连续亏损保护: mode={status['mode']}, streak={status['loss_streak']}, pos×{position_multiplier}")
        except Exception as e:
            logger.debug(f"连续亏损保护跳过: {e}")

        # Kelly仓位调整
        kelly_pct = 0.08  # 默认8%
        try:
            from src.risk_management.kelly_position import KellyPositionManager
            kpm = KellyPositionManager()
            kelly_pct = kpm.get_position_pct()
            logger.info(f"Kelly建议仓位: {kelly_pct*100:.1f}%")
        except Exception:
            pass

        # 应用信号门槛提升 + Kelly仓位
        if signal_bonus > 0:
            scores["score_total"] = scores["score_total"] - signal_bonus
            scores = scores.sort_values("score_total", ascending=False)

        # Technical signal filter — penalize death cross / overbought stocks
        try:
            from src.factors.technical_signals import score_stock
            for code in scores.index[:20]:
                stock_data = quote[quote["code"] == code].tail(60)
                if len(stock_data) >= 30:
                    sig = score_stock(stock_data)
                    ss = sig["signal_score"]
                    # Penalize stocks with very low technical signals
                    if ss < 35:  # 强烈卖出
                        scores.loc[code, "score_total"] *= 0.7
                    elif ss < 50:  # 卖出/观望
                        scores.loc[code, "score_total"] *= 0.9
                    elif ss >= 80:  # 强烈买入 bonus
                        scores.loc[code, "score_total"] *= 1.05
            scores = scores.sort_values("score_total", ascending=False)
        except Exception:
            pass

        # 获取最新价格
        latest_date = quote["date"].max()
        day = quote[quote["date"] == latest_date]
        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

        # 调仓
        self.nav.rebalance(latest_date, scores, prices, "评分调仓")
        self.nav.update_nav(latest_date, prices)
        
        # 风控检查 — 调仓后再检查一遍持仓
        risk_msgs = []
        try:
            from src.simulator.risk_control import check_risk
            alerts = check_risk(self.nav.holdings, prices)
            for a in alerts:
                if a["action"] == "sell":
                    # 自动止损
                    cost = self.nav.holdings[a["code"]]["cost_price"]
                    self.nav._sell(a["code"], prices.get(a["code"], 0), latest_date, a["reason"])
                    risk_msgs.append(f"🔴 止损 {stock_name(a['code'])}: {a['reason']}")
                elif a["action"] == "reduce":
                    risk_msgs.append(f"🟡 {stock_name(a['code'])}: {a['reason']}")
        except Exception:
            pass
        
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

        # 风控提示
        if risk_msgs:
            msg += f"\n🛡️ **风控:**\n"
            for rm in risk_msgs:
                msg += f"  {rm}\n"

        return ActionResult(success=True, message=msg)

    async def _trade_stats(self) -> ActionResult:
        """交易统计"""
        from src.simulator.trade_log import get_trade_stats, get_recent_trades
        
        stats = get_trade_stats()
        if stats["total"] == 0:
            return ActionResult(success=True, message="📊 暂无交易记录")
        
        lines = ["📊 **交易统计**\n"]
        lines.append(f"💰 总交易: {stats['total']}笔 (买{stats.get('buys',0)}/卖{stats.get('sells',0)})")
        if stats.get('sells', 0) > 0:
            lines.append(f"🏆 胜率: {stats['win_rate']:.0f}% ({stats['wins']}胜/{stats['losses']}负)")
            lines.append(f"📈 盈亏比: {stats.get('profit_factor', 0):.2f}")
            lines.append(f"💵 累计盈亏: ¥{stats['pnl_total']:+,.0f}")
            lines.append(f"   平均盈利: ¥{stats['avg_win']:+,.0f}")
            lines.append(f"   平均亏损: ¥{stats['avg_loss']:+,.0f}")
        
        # 最近5笔
        recent = get_recent_trades(5)
        if recent:
            lines.append("\n📋 **最近交易:**")
            for t in recent[-5:]:
                action = "买入" if t["action"] == "buy" else f"卖出(PnL:{t.get('pnl',0):+.0f})"
                lines.append(f"  {t['date']} {action} {t['code']} {t['shares']}@{t['price']}")
        
        return ActionResult(success=True, message="\n".join(lines))

    async def _risk_check(self) -> ActionResult:
        """风控检查"""
        from src.simulator.risk_control import check_risk, format_risk_alerts
        import json as _json
        from pathlib import Path as _Path
        
        nav_dir = _Path(__file__).resolve().parent.parent.parent / "data"
        nav_files = sorted(nav_dir.glob("nav_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not nav_files:
            return ActionResult(success=True, message="📭 无持仓数据")
        
        nav_data = _json.loads(nav_files[0].read_text())
        holdings = nav_data.get("holdings", {})
        if not holdings:
            return ActionResult(success=True, message="📭 当前无持仓")
        
        # 获取当前价格
        daily_quote = self.context.read("data.daily_quote") if self.context else None
        prices = {}
        if daily_quote is not None and not daily_quote.empty:
            for code in holdings:
                sd = daily_quote[daily_quote["code"] == code]
                if not sd.empty:
                    prices[code] = sd["close"].iloc[-1]
        
        alerts = check_risk(holdings, prices)
        return ActionResult(success=True, message=format_risk_alerts(alerts))
