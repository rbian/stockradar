"""工具注册中心 — Agent可调用的工具统一管理

每个工具是一个命名函数，Agent通过名字调用。
支持权限控制（哪些Agent能用哪些工具）。
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger


@dataclass
class Tool:
    """工具定义"""
    name: str
    func: Callable
    description: str = ""
    category: str = ""       # data / factor / backtest / portfolio / notify
    cost: float = 0.0        # 每次调用预估成本(元)
    allowed_agents: list[str] = field(default_factory=list)  # 空=所有Agent可用
    requires_approval: bool = False


class ToolRegistry:
    """工具注册中心

    用法:
        registry = ToolRegistry()

        # 注册工具
        registry.register(Tool(
            name="fetch_daily_quote",
            func=data_fetcher.fetch_daily_quote,
            category="data",
        ))

        # Agent调用
        result = await registry.call("analyst", "fetch_daily_quote", symbol="300750")
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.debug(f"工具注册: {tool.name} ({tool.category})")

    def register_function(self, name: str, func: Callable, **kwargs):
        """快捷注册：直接传函数"""
        self.register(Tool(name=name, func=func, **kwargs))

    def unregister(self, name: str):
        """注销工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self, category: str = None, agent_name: str = None) -> list[Tool]:
        """列出可用工具"""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        if agent_name:
            tools = [t for t in tools
                     if not t.allowed_agents or agent_name in t.allowed_agents]
        return tools

    async def call(self, agent_name: str, tool_name: str,
                   args: tuple = (), kwargs: dict = None) -> Any:
        """调用工具（带权限检查）"""
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"工具不存在: {tool_name}")

        # 权限检查
        if tool.allowed_agents and agent_name not in tool.allowed_agents:
            raise PermissionError(
                f"Agent '{agent_name}' 无权使用工具 '{tool_name}'"
            )

        # 执行
        kwargs = kwargs or {}
        try:
            import asyncio
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(*args, **kwargs)
            else:
                result = tool.func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"工具调用失败 {tool_name}: {e}")
            raise

    def get_tools_description(self, agent_name: str = None) -> str:
        """生成工具列表描述（给LLM看的）"""
        tools = self.list_tools(agent_name=agent_name)
        lines = []
        for t in tools:
            approval = " [需审批]" if t.requires_approval else ""
            lines.append(f"- {t.name}: {t.description}{approval}")
        return "\n".join(lines)

    # ──── 批量注册现有模块 ────

    def register_data_tools(self, fetcher, store):
        """注册数据层工具"""
        self.register(Tool(name="fetch_daily_quote", func=fetcher.fetch_daily_quote,
                           description="获取单只股票日线行情", category="data"))
        self.register(Tool(name="fetch_daily_quote_batch", func=fetcher.fetch_daily_quote_batch,
                           description="批量获取日线行情", category="data"))
        self.register(Tool(name="fetch_stock_list", func=fetcher.fetch_stock_list,
                           description="获取全市场股票列表", category="data"))
        self.register(Tool(name="fetch_market_index", func=fetcher.fetch_market_index,
                           description="获取市场指数数据", category="data"))
        self.register(Tool(name="fetch_market_sentiment", func=fetcher.fetch_market_sentiment,
                           description="获取市场情绪数据(涨跌家数等)", category="data"))
        self.register(Tool(name="get_table", func=store.get_table,
                           description="从DuckDB查询表数据", category="data"))

    def register_factor_tools(self, engine):
        """注册因子层工具"""
        self.register(Tool(name="score_all", func=engine.score_all,
                           description="全市场因子评分排序", category="factor"))
        self.register(Tool(name="calc_delta", func=engine.calc_delta,
                           description="计算评分动量ΔS", category="factor"))
        self.register(Tool(name="adjust_factor_weight", func=engine.adjust_factor_weight,
                           description="调整因子权重", category="factor",
                           requires_approval=True))

    def register_backtest_tools(self, backtest_engine):
        """注册回测工具"""
        self.register(Tool(name="run_backtest", func=backtest_engine.run,
                           description="运行回测", category="backtest"))
        self.register(Tool(name="run_walk_forward", func=backtest_engine.run_walk_forward,
                           description="运行滚动回测", category="backtest"))

    def register_portfolio_tools(self, portfolio_mgr, trade_logger, nav_tracker):
        """注册持仓管理工具"""
        self.register(Tool(name="get_portfolio", func=portfolio_mgr.get_portfolio,
                           description="获取当前持仓", category="portfolio"))
        self.register(Tool(name="execute_trade", func=portfolio_mgr.execute_trade,
                           description="执行交易", category="portfolio",
                           requires_approval=True))
        self.register(Tool(name="get_trade_log", func=trade_logger.get_trades,
                           description="获取交易记录", category="portfolio"))
        self.register(Tool(name="get_nav", func=nav_tracker.get_latest_nav,
                           description="获取最新净值", category="portfolio"))

    def register_all(self, fetcher=None, store=None, engine=None,
                     backtest=None, portfolio=None, trade_logger=None,
                     nav_tracker=None):
        """一次性注册所有工具"""
        if fetcher and store:
            self.register_data_tools(fetcher, store)
        if engine:
            self.register_factor_tools(engine)
        if backtest:
            self.register_backtest_tools(backtest)
        if portfolio and trade_logger and nav_tracker:
            self.register_portfolio_tools(portfolio, trade_logger, nav_tracker)
        logger.info(f"工具注册完成: {len(self._tools)} 个工具")
