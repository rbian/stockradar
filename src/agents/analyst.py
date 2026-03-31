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
        t = action.get("action", "")
        try:
            if t == "full_analysis": return await self._full_analysis()
            elif t == "analyze_stock": return await self._analyze_stock(action.get("code", ""))
            elif t == "market_overview": return await self._market_overview()
            elif t == "score_ranking": return await self._score_ranking()
            return ActionResult(success=False, message=f"未知类型: {t}")
        except Exception as e:
            logger.error(f"分析失败: {e}")
            return ActionResult(success=False, message=f"分析失败: {e}")

    # ── 核心方法 ──────────────────────────────────────────

    async def _full_analysis(self) -> ActionResult:
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
            "daily_quote": daily, "codes": codes,
            "financial": financial if financial is not None else pd.DataFrame(),
            "northbound": pd.DataFrame(),
        }
        scores = score_fn(data)
        if self.context:
            self.context.set_scores(scores)
        top10 = scores.head(10)
        msg = "📊 **今日评分Top10:**\n"
        for i, (code, row) in enumerate(top10.iterrows()):
            delta = row.get("delta", 0)
            arrow = "🔺" if delta > 0.01 else "🔻" if delta < -0.01 else "➖"
            msg += f"  {i+1}. {code} | {row['score_total']:+.2f} {arrow}\n"
        return ActionResult(success=True, message=msg, data={"scores": scores})

    async def _analyze_stock(self, code: str) -> ActionResult:
        """个股分析 — 行情 + 技术面 + 基本面"""
        fetch_fn = self.get_tool("fetch_daily_quote")
        if fetch_fn is None:
            return ActionResult(success=False, message="数据工具不可用")

        try:
            df = fetch_fn(symbol=code)
            if df is None or df.empty:
                return ActionResult(success=False, message=f"未找到 {code}")

            df = df.sort_values("date")
            latest = df.iloc[-1]
            lines = [f"📈 **{code} 个股分析**\n"]

            # 1) 行情摘要
            lines.append(f"📊 **行情** (最近: {latest['date'].strftime('%m-%d')})")
            lines.append(f"  收盘: ¥{latest.get('close', 0):.2f}")
            if "change_pct" in latest:
                chg = latest["change_pct"]
                lines.append(f"  涨跌: {chg:+.2f}%")
            if "turnover" in latest and latest["turnover"] > 0:
                lines.append(f"  换手: {latest['turnover']:.2f}%")

            # 5日/20日涨跌
            if len(df) >= 5:
                chg5 = (df.iloc[-1]["close"] / df.iloc[-5]["close"] - 1) * 100
                lines.append(f"  5日: {chg5:+.1f}%")
            if len(df) >= 20:
                chg20 = (df.iloc[-1]["close"] / df.iloc[-20]["close"] - 1) * 100
                lines.append(f"  20日: {chg20:+.1f}%")

            # 2) 技术面
            lines.append(f"\n🔧 **技术面**")
            close = df["close"].values
            if len(close) >= 5:
                ma5 = close[-5:].mean()
                lines.append(f"  MA5: ¥{ma5:.2f} ({'上方' if close[-1] > ma5 else '下方'})")
            if len(close) >= 20:
                ma20 = close[-20:].mean()
                lines.append(f"  MA20: ¥{ma20:.2f} ({'上方' if close[-1] > ma20 else '下方'})")
            # 简易RSI
            if len(close) >= 15:
                delta_c = pd.Series(close).diff()
                gain = delta_c.where(delta_c > 0, 0).rolling(14).mean()
                loss = (-delta_c.where(delta_c < 0, 0)).rolling(14).mean()
                rs = gain / loss.replace(0, 1e-10)
                rsi = (100 - 100 / (1 + rs)).iloc[-1]
                tag = "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性"
                lines.append(f"  RSI(14): {rsi:.1f} ({tag})")

            # 3) 基本面
            financial = self.context.read("financial_data") if self.context else None
            if financial is not None and not financial.empty:
                fin = financial[financial["code"] == code]
                if not fin.empty:
                    fin_latest = fin.sort_values("end_date").iloc[-1]
                    lines.append(f"\n💰 **基本面** (截至{fin_latest['end_date'][:10]})")
                    for label, col, mult in [("ROE", "roe", 100), ("毛利率", "gross_margin", 100),
                                               ("净利率", "net_margin", 100), ("营收增速", "revenue_yoy", 1),
                                               ("利润增速", "profit_yoy", 1), ("EPS", "eps", 1)]:
                        val = fin_latest.get(col)
                        if val is not None and val != 0:
                            val_display = val * mult
                            suffix = "%" if col != "eps" else ""
                            fmt = f"{val_display:.2f}{suffix}"
                            lines.append(f"  {label}: {fmt}")

            # 4) 综合评分
            scores = self.context.get_scores() if self.context else None
            if scores is not None and code in scores.index:
                s = scores.loc[code]
                lines.append(f"\n📊 **综合评分: {s['score_total']:.2f}**")
                # 显示各维度
                dims = {}
                for col in s.index:
                    if col.startswith("cat_"):
                        cat = col.replace("cat_", "").replace("score_", "")
                        if "total" not in cat:
                            dims[cat] = s[col]
                if dims:
                    lines.append("  维度:")
                    for dim, val in sorted(dims.items(), key=lambda x: -x[1]):
                        bar = "█" * max(1, int(val * 10)) if val > 0 else ""
                        lines.append(f"    {dim}: {val:+.2f} {bar}")

            return ActionResult(success=True, message="\n".join(lines))
        except Exception as e:
            return ActionResult(success=False, message=f"分析 {code} 失败: {e}")

    async def _market_overview(self) -> ActionResult:
        lines = ["📊 **市场概况**\n"]
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
                lines.append(f"  {row['code']} ¥{row['close']:.2f} ({row['change_pct']:+.2f}%)")
        return ActionResult(success=True, message="\n".join(lines))

    async def _score_ranking(self) -> ActionResult:
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
