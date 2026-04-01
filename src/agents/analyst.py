"""AnalystAgent — 市场分析师

职责：数据采集、因子计算、个股分析、市场状态判断
"""

import os
import re
from loguru import logger
import pandas as pd

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult
from src.data.stock_names import stock_name


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
            msg += f"  {i+1}. {stock_name(code)} | {row['score_total']:+.2f} {arrow}\n"
        return ActionResult(success=True, message=msg, data={"scores": scores})

    async def _analyze_stock(self, code: str) -> ActionResult:
        """个股分析 — 行情 + 技术面 + 基本面"""
        fetch_fn = self.get_tool("fetch_daily_quote")
        if fetch_fn is None:
            return ActionResult(success=False, message="数据工具不可用")

        try:
            df = fetch_fn(symbol=code)
            if df is None or df.empty:
                return ActionResult(success=False, message=f"未找到 {stock_name(code)}({code})")

            df = df.sort_values("date")
            latest = df.iloc[-1]
            name = stock_name(code)
            lines = [f"📈 **{name}({code})**\n"]

            # 1) 行情
            lines.append(f"📊 **行情** ({latest['date'].strftime('%Y-%m-%d')})")
            lines.append(f"  收盘: ¥{latest.get('close', 0):.2f}")
            if "change_pct" in latest and pd.notna(latest["change_pct"]):
                lines.append(f"  涨跌: {latest['change_pct']:+.2f}%")
            if "turnover" in latest and pd.notna(latest.get("turnover", 0)):
                lines.append(f"  换手: {latest['turnover']:.2f}%")
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
            if len(close) >= 15:
                delta_c = pd.Series(close).diff()
                gain = delta_c.where(delta_c > 0, 0).rolling(14).mean()
                loss = (-delta_c.where(delta_c < 0, 0)).rolling(14).mean()
                rs = gain / loss.replace(0, 1e-10)
                rsi = (100 - 100 / (1 + rs)).iloc[-1]
                tag = "超买⚠️" if rsi > 70 else "超卖⚠️" if rsi < 30 else "中性"
                lines.append(f"  RSI(14): {rsi:.1f} ({tag})")

            # 3) 基本面
            financial = self.context.read("financial_data") if self.context else None
            if financial is not None and not financial.empty:
                fin = financial[financial["code"] == code]
                if not fin.empty:
                    fl = fin.sort_values("end_date").iloc[-1]
                    lines.append(f"\n💰 **基本面** (截至{fl['end_date'][:10]})")
                    metrics = [
                        ("ROE", "roe", 100, "%"), ("毛利率", "gross_margin", 100, "%"),
                        ("净利率", "net_margin", 100, "%"), ("营收增速", "revenue_yoy", 1, "%"),
                        ("利润增速", "profit_yoy", 1, "%"), ("EPS", "eps", 1, "元"),
                        ("负债率", "debt_ratio", 100, "%"),
                    ]
                    for label, col, mult, unit in metrics:
                        val = fl.get(col)
                        if val is not None and not pd.isna(val) and val != 0:
                            lines.append(f"  {label}: {val * mult:.2f}{unit}")

            # 4) 资金面
            lines.append(f"\n💵 **资金面**")
            if "volume" in df.columns and len(df) >= 20:
                vol = df["volume"].values
                vol_ma5 = vol[-5:].mean() if len(vol) >= 5 else vol[-1]
                vol_ma20 = vol[-20:].mean()
                vol_ratio = vol_ma5 / max(vol_ma20, 1)
                lines.append(f"  量比(5/20): {vol_ratio:.2f} ({'放量📈' if vol_ratio > 1.5 else '缩量📉' if vol_ratio < 0.7 else '正常'})")
            if "amount" in df.columns and len(df) >= 5:
                amt_avg = df["amount"].tail(5).mean()
                lines.append(f"  5日均额: ¥{amt_avg/1e8:.1f}亿" if amt_avg > 1e8 else f"  5日均额: ¥{amt_avg/1e4:.1f}万")

            # 5) 历史分位
            if len(df) >= 120:
                price_pct = (close[-1] - close[-120:].min()) / (close[-120:].max() - close[-120:].min() + 1e-10) * 100
                lines.append(f"\n📍 **位置** (近120日)")
                lines.append(f"  价格分位: {price_pct:.0f}% ({'高位⚠️' if price_pct > 80 else '低位✅' if price_pct < 20 else '中性'})")
                high120 = close[-120:].max()
                low120 = close[-120:].min()
                lines.append(f"  区间: ¥{low120:.2f} ~ ¥{high120:.2f}")

            # 6) 综合评分 + 排名
            scores = self.context.get_scores() if self.context else None
            if scores is not None and code in scores.index:
                s = scores.loc[code]
                rank = (scores["score_total"] > s["score_total"]).sum() + 1
                total = len(scores)
                lines.append(f"\n📊 **综合评分: {s['score_total']:+.2f}** (排名 {rank}/{total})")
                # 因子分类得分
                for cat in ["fundamental", "technical", "capital_flow", "market_sentiment"]:
                    col = f"score_{cat}"
                    if col in s.index and pd.notna(s[col]):
                        labels = {"fundamental": "基本面", "technical": "技术面",
                                  "capital_flow": "资金流", "market_sentiment": "情绪"}
                        val = s[col]
                        bar = "█" * int(abs(val) * 10) + "░" * (10 - int(abs(val) * 10))
                        lines.append(f"  {labels.get(cat, cat)}: {bar} {val:+.3f}")

            # 7) 同业对比 (从评分排名中找)
            if scores is not None and code in scores.index:
                rank = (scores["score_total"] > scores.loc[code, "score_total"]).sum() + 1
                # 前3名和后3名
                top3 = scores.head(3)
                lines.append(f"\n🏭 **评分对比** (Top3 vs 本股)")
                for _, row in top3.iterrows():
                    marker = " ◀" if row.name == code else ""
                    lines.append(f"  {stock_name(row.name)} {row['score_total']:+.2f}{marker}")
                if rank > 3:
                    lines.append(f"  ... (排名{rank})")
                    # 前后各1名
                    if rank > 1 and rank <= len(scores):
                        nearby = scores.iloc[max(0,rank-2):min(len(scores),rank+1)]
                        for _, row in nearby.iterrows():
                            marker = " ◀" if row.name == code else ""
                            lines.append(f"  {stock_name(row.name)} {row['score_total']:+.2f}{marker}")

            # 8) LLM估值研判
            lines.append(f"\n🧠 **LLM估值研判**")
            try:
                from src.llm.client import LLMClient
                client = LLMClient()
                cur_price = latest.get("close", 0)
                fin_text = ""
                financial = self.context.read("financial_data") if self.context else None
                if financial is not None and not financial.empty:
                    fin = financial[financial["code"] == code]
                    if not fin.empty:
                        fl = fin.sort_values("end_date").iloc[-1]
                        fin_text = f"ROE={fl.get('roe',0)*100:.1f}% 毛利率={fl.get('gross_margin',0)*100:.1f}% 营收增速={fl.get('revenue_yoy',0):.1f}% 利润增速={fl.get('profit_yoy',0):.1f}% EPS={fl.get('eps',0):.1f}元"
                system_prompt = "你是A股估值分析专家。基于基本面数据给出估值判断。严格按要求格式输出。"
                user_prompt = f"""分析{stock_name(code)}({code})，当前股价¥{cur_price:.2f}。
基本面: {fin_text}
请严格按以下格式输出（每项一行，不要其他内容）：
【估值】: 高估/合理/低估
【目标价】: ¥xxx-xxx
【逻辑】: 2-3句核心支撑
【风险】: 1-2句核心风险"""
                raw = await client._call_api(system_prompt, user_prompt)
                if raw:
                    for line in raw.strip().split("\n"):
                        line = line.strip()
                        if line:
                            if "低估" in line:
                                line = "🟢 " + line
                            elif "高估" in line:
                                line = "🔴 " + line
                            elif "合理" in line:
                                line = "⚪ " + line
                            lines.append(f"  {line}")
                else:
                    lines.append("  (LLM未返回结果)")
            except Exception as e:
                lines.append(f"  (LLM暂不可用: {e})")

            return ActionResult(success=True, message="\n".join(lines))
        except Exception as e:
            return ActionResult(success=False, message=f"分析失败: {e}")

    async def _market_overview(self) -> ActionResult:
        lines = ["📊 **市场概况**\n"]
        qveris_key = os.environ.get("QVERIS_API_KEY", "")
        if qveris_key:
            try:
                from src.data.qveris_adapter import fetch_index_quote_qv
                idx = fetch_index_quote_qv("000300")
                if idx and idx.get("最新(点)", "") not in ("", "---"):
                    chg = idx.get("涨跌幅(%)", "?")
                    lines.append(f"📈 **沪深300:** {idx.get('最新(点)')} ({chg}%)")
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
            for _, row in day.sort_values("change_pct", ascending=False).iterrows():
                name = stock_name(row["code"])
                lines.append(f"  {name}({row['code']}) ¥{row['close']:.2f} ({row['change_pct']:+.2f}%)")
        return ActionResult(success=True, message="\n".join(lines))

    async def _score_ranking(self) -> ActionResult:
        scores = self.context.get_scores() if self.context else None
        if scores is None:
            return await self._full_analysis()

        top10 = scores.head(10)
        msg = "📊 **评分排名Top10:**\n\n"
        
        # 查找当前持仓
        nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state.json"
        holdings = set()
        if nav_file.exists():
            try:
                import json
                from src.simulator.nav_tracker import NAVTracker
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                holdings = set(nav.holdings.keys())
            except Exception:
                pass

        for i, (code, row) in enumerate(top10.iterrows()):
            name = stock_name(code)
            tag = "📦" if code in holdings else "  "
            # 分类标签
            score = row["score_total"]
            signal = "🟢" if score > 0.5 else "🟡" if score > 0.2 else "⚪"
            msg += f"{signal}{tag} {i+1}. {name}({code}) | {score:+.2f}\n"

        if holdings:
            msg += f"\n📦 = 当前持仓"
        return ActionResult(success=True, message=msg)

    def _extract_stock_code(self, text: str) -> str:
        """提取股票代码，支持数字代码和中文简称"""
        # 先尝试6位数字
        match = re.search(r'\d{6}', text)
        if match:
            return match.group()
        # 再尝试中文简称
        from src.data.stock_names import _load
        names = _load()
        for code, name in names.items():
            if name and name in text:
                return code
        return ""
