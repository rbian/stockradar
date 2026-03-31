"""AnalystAgent — 市场分析师

职责：数据采集、因子计算、个股分析、市场状态判断
"""

from loguru import logger

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
        """感知：获取用户请求或定时触发"""
        user_msg = context.read("user_message", "") if context else ""
        date = context.read("data.date", "") if context else ""

        return Observation(
            content={
                "user_message": user_msg,
                "date": date,
                "has_data": context.read("data.daily_quote") is not None if context else False,
            },
            source="user" if user_msg else "scheduler",
        )

    async def think(self, observation: Observation) -> Plan:
        """思考：决定分析什么"""
        msg = observation.content.get("user_message", "")

        if not msg:
            # 定时触发 → 全市场分析
            return Plan(actions=[{
                "action": "full_analysis",
            }], reasoning="每日定时分析")

        # 个股分析
        code = self._extract_stock_code(msg)
        if code:
            return Plan(actions=[{
                "action": "analyze_stock",
                "code": code,
            }], reasoning=f"个股分析: {code}")

        # 市场概况
        if any(kw in msg for kw in ["市场", "大盘", "行情", "指数"]):
            return Plan(actions=[{
                "action": "market_overview",
            }], reasoning="市场概况")

        # 默认：评分排名
        return Plan(actions=[{
            "action": "score_ranking",
        }], reasoning="评分排名")

    async def act(self, plan: Plan) -> ActionResult:
        """执行分析"""
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
            else:
                return ActionResult(success=False, message=f"未知分析类型: {action_type}")
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
            return ActionResult(success=False, message="无行情数据，请先拉取数据")

        # 评分
        data = {"daily_quote": daily, "codes": daily.index.unique().tolist()}
        scores = score_fn(data)

        # 写入context供其他Agent使用
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

        # 获取行情
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
        """市场概况"""
        sentiment_fn = self.get_tool("fetch_market_sentiment")
        if sentiment_fn:
            try:
                sentiment = sentiment_fn()
                msg = f"📊 **市场情绪:** {sentiment}"
                return ActionResult(success=True, message=msg)
            except Exception:
                pass

        return ActionResult(success=True, message="市场数据暂不可用")

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
        """从文本中提取股票代码"""
        import re
        match = re.search(r'\d{6}', text)
        return match.group() if match else ""
