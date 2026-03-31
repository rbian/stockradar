"""AnalystAgent — 市场分析师

职责：数据采集、因子计算、个股分析、市场状态判断
"""

import os
import re
from loguru import logger
import pandas as pd

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult


class AnalystAgent(BaseAgent):
    """分析师Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="analyst",
            description="市场分析、因子计算、个股研究",
            tools=["fetch_daily_quote", "fetch_stock_list", "fetch_market_index",
                   "fetch_market_sentiment", "score_all", "calc_delta", "get_table"],
        )
        super().__init__(config, context, message_bus)

    async def perceive(self, context) -> Observation:
        user_msg = context.read("user_message", "") if context else ""
        return Observation(
            content={"user_message": user_msg},
            source="user" if user_msg else "scheduler",
        )

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")
        if not msg:
            return Plan(actions=[{"action": "full_analysis"}])

        code = self._extract_stock_code(msg)
        if code:
            return Plan(actions=[{"action": "analyze_stock", "code": code}])

        if any(kw in msg for kw in ["市场", "大盘", "行情", "指数"]):
            return Plan(actions=[{"action": "market_overview"}])

        return Plan(actions=[{"action": "score_ranking"}])

    async def act(self, plan: Plan) -> ActionResult:
        if not plan.actions:
            return ActionResult(success=False, message="无分析任务")
        action = plan.actions[0]
        action_type = action.get("action", "")
        try:
            if action_type == "full_analysis":
                return await self._full_analysis()
            elif action_type == "analyze_stock":
                return await self._analyze_stock(action.get("code", ""))
            elif action_type == "market_overview":
                return await self._market_overview()
            elif action_type == "score_ranking":
                return await self._score_ranking()
            return ActionResult(success=False, message=f"未知类型: {action_type}")
        except Exception as e:
            logger.error(f"分析失败: {e}")
            return ActionResult(success=False, message=f"分析失败: {e}")

    async def _full_analysis(self) -> ActionResult:
        """全市场分析"""
        score_fn = self.get_tool("score_all")
        if score_fn is None:
            return ActionResult(success=False, message="评分工具不可用")

        daily = self.context.read("data.daily_quote") if self.context else None
        if daily is None:
            return ActionResult(success=False, message="无行情数据")

        codes = self.context.read("codes", daily["code"].unique().tolist())
        daily = daily[daily["code"].isin(codes)]
        financial = self.context.read("financial_data") if self.context else None

        data = {
            "daily_quote": daily,
            "codes": codes,
            "financial": financial if financial is not None else pd.DataFrame(),
            "northbound": pd.DataFrame(),
        }
        scores = score_fn(data)

        if self.context:
            self.context.set_scores(scores)

        top10 = scores.head(10)
        msg = "📊 **今日评分Top10:**\n"
        for i, (code, row) in enumerate(top10.iterrows()):
            msg += f"  {i+1}. {code} | 总分={row['score_total']:.2f}\n"
        return ActionResult(success=True, message=msg, data={"scores": scores})

    async def _analyze_stock(self, code: str) -> ActionResult:
        """个股分析"""
        fetch_fn = self.get_tool("fetch_daily_quote")
        if fetch_fn is None:
            return ActionResult(success=False, message="数据工具不可用")
        try:
            df = fetch_fn(symbol=code)
            if df is None or df.empty:
                return ActionResult(success=False, message=f"未找到 {code} 的数据")
            latest = df.iloc[-1]
            msg = (
                f"📈 **{code} 个股分析**\n"
                f"  最新价: {latest.get('close', 'N/A')}\n"
                f"  涨跌幅: {latest.get('change_pct', 'N/A')}%\n"
                f"  成交量: {latest.get('volume', 'N/A')}\n"
            )
            return ActionResult(success=True, message=msg)
        except Exception as e:
            return ActionResult(success=False, message=f"获取 {code} 数据失败: {e}")

    async def _market_overview(self) -> ActionResult:
        """市场概况 — QVeris实时 + Watchlist涨跌"""
        lines = ["📊 **市场概况**\n"]

        # QVeris实时指数
        qveris_key = os.environ.get("QVERIS_API_KEY", "")
        if qveris_key:
            try:
                from src.data.qveris_adapter import fetch_index_quote_qv
                idx = fetch_index_quote_qv("000300")
                if idx and idx.get("最新(点)", "") not in ("", "---"):
                    lines.append(f"📈 **沪深300:** {idx.get('最新(点)')} ({idx.get('涨跌幅(%)', '?')}%)")
                    lines.append(f"   高: {idx.get('最高(点)')} | 低: {idx.get('最低(点)')}")
                    lines.append(f"   成交额: {idx.get('成交额', '?')}")
            except Exception:
                pass

        # Watchlist涨跌
        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is not None and not quote.empty:
            codes = self.context.read("codes", []) if self.context else []
            if not codes:
                codes = quote["code"].unique().tolist()[:10]
            q = quote[quote["code"].isin(codes)]
            latest_date = q["date"].max()
            day = q[q["date"] == latest_date]
            lines.append(f"\n📋 **关注池 ({latest_date.strftime('%m-%d')})**:")
            for _, row in day.sort_values("change_pct", ascending=False).head(5).iterrows():
                lines.append(f"  {row['code']} {row['close']:.2f} ({row['change_pct']:+.2f}%)")

        return ActionResult(success=True, message="\n".join(lines))

    async def _score_ranking(self) -> ActionResult:
        """评分排名"""
        scores = self.context.get_scores() if self.context else None
        if scores is None:
            return await self._full_analysis()
        top10 = scores.head(10)
        msg = "📊 **评分排名Top10:**\n"
        for i, (code, row) in enumerate(top10.iterrows()):
            msg += f"  {i+1}. {code} | {row['score_total']:.2f}\n"
        return ActionResult(success=True, message=msg)

    def _extract_stock_code(self, text: str) -> str:
        match = re.search(r'\d{6}', text)
        return match.group() if match else ""
