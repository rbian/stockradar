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

        # 4) 持仓+净值
        lines.append("\n📦 **模拟持仓:**")
        # 从TraderAgent获取NAV
        from src.simulator.nav_tracker import NAVTracker
        import json
        from pathlib import Path
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                info = nav.get_nav()
                lines.append(f"  净值: {info['nav']:.4f} | 收益: {info['total_return']:+.2f}%")
                lines.append(f"  持仓: {info['holdings_count']}只 | 交易: {info['trades']}笔")
                for code, h in sorted(nav.holdings.items()):
                    name = stock_name(code)
                    lines.append(f"  {name}({code}) {h['shares']}股@¥{h['cost_price']:.2f}")
            except Exception:
                lines.append("  模拟模式")
        else:
            lines.append("  尚未建仓，发送'持仓建议'开始")

        return ActionResult(success=True, message="\n".join(lines))

    async def _weekly_report(self) -> ActionResult:
        """周报 — 净值+持仓+交易统计"""
        lines = ["📰 **StockRadar 周报**\n"]

        # 净值统计
        import json
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                from src.simulator.nav_tracker import NAVTracker
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                if len(nav.nav_history) >= 5:
                    nav_df = pd.DataFrame(nav.nav_history)
                    nav_df["date"] = pd.to_datetime(nav_df["date"])
                    # 本周数据
                    latest = nav_df["date"].max()
                    week_ago = latest - pd.Timedelta(days=7)
                    week = nav_df[nav_df["date"] >= week_ago]
                    if len(week) >= 2:
                        week_return = (week["nav"].iloc[-1] / week["nav"].iloc[0] - 1) * 100
                        lines.append(f"📊 **本周收益:** {week_return:+.2f}%")
                        lines.append(f"  净值: {week['nav'].iloc[0]:.4f} → {week['nav'].iloc[-1]:.4f}")
            except Exception:
                pass

        # 本周交易
        if nav_file.exists():
            try:
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                recent_trades = [t for t in nav.trade_log 
                                if pd.Timestamp(t["date"]) >= pd.Timestamp.now() - pd.Timedelta(days=7)]
                if recent_trades:
                    lines.append(f"\n📋 **本周交易:** {len(recent_trades)}笔")
                    buys = sum(1 for t in recent_trades if t["action"] == "buy")
                    sells = sum(1 for t in recent_trades if t["action"] == "sell")
                    lines.append(f"  买入{buys}笔 卖出{sells}笔")
                    for t in recent_trades[-5:]:
                        action = "买入" if t["action"] == "buy" else "卖出"
                        lines.append(f"  {t['date'][:10]} {action} {stock_name(t['code'])} {t['shares']}股@¥{t['price']:.2f}")
            except Exception:
                pass

        # 当前持仓
        if nav_file.exists():
            try:
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                if nav.holdings:
                    lines.append(f"\n📦 **当前持仓:** {len(nav.holdings)}只")
                    for code, h in sorted(nav.holdings.items()):
                        lines.append(f"  {stock_name(code)} {h['shares']}股@¥{h['cost_price']:.2f}")
            except Exception:
                pass

        if len(lines) <= 2:
            lines.append("本周暂无数据，发送'持仓建议'开始模拟交易")
        
        return ActionResult(success=True, message="\n".join(lines))

    async def _monthly_report(self) -> ActionResult:
        """月报"""
        lines = ["📰 **StockRadar 月报**\n"]
        
        import json
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        if nav_file.exists():
            try:
                from src.simulator.nav_tracker import NAVTracker
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                info = nav.get_nav()
                lines.append(f"💰 **净值:** {info['nav']:.4f}")
                lines.append(f"📈 **总收益:** {info['total_return']:+.2f}%")
                lines.append(f"📉 **回撤:** {info['drawdown']:+.2f}%")
                lines.append(f"📋 **交易:** {info['trades']}笔")
                
                # 月度收益分布
                if len(nav.nav_history) >= 20:
                    nav_df = pd.DataFrame(nav.nav_history)
                    nav_df["date"] = pd.to_datetime(nav_df["date"])
                    nav_df["month"] = nav_df["date"].dt.to_period("M")
                    monthly = nav_df.groupby("month")["nav"].last()
                    monthly_ret = monthly.pct_change().dropna() * 100
                    lines.append(f"\n📅 **月度收益:**")
                    for m, r in monthly_ret.tail(6).items():
                        emoji = "🟢" if r > 0 else "🔴"
                        lines.append(f"  {m} {emoji} {r:+.1f}%")
            except Exception:
                pass
        
        return ActionResult(success=True, message="\n".join(lines))
