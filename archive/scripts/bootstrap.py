"""系统启动 — 组装多Agent系统

用法:
    from scripts.bootstrap import create_system
    orch = create_system()
    result = await orch.process_user_message("分析宁德时代")
"""

from loguru import logger

from src.core import AgentOrchestrator, SharedContext, ToolRegistry
from src.agents import RouterAgent, AnalystAgent, TraderAgent, ReporterAgent, EvolverAgent


def create_system(store=None, llm_client=None, engine=None) -> AgentOrchestrator:
    """创建完整的多Agent系统

    Args:
        store: DuckDB DataStore实例
        llm_client: LLM客户端实例
        engine: FactorEngine实例

    Returns:
        AgentOrchestrator 编排器
    """
    orch = AgentOrchestrator(store=store, llm_client=llm_client)

    # 注入engine到context
    if engine:
        orch.context.write("factor_engine", engine, writer="system")

    # 注册工具
    if store:
        from src.data.fetcher import fetch_daily_quote, fetch_stock_list, fetch_market_sentiment
        orch.tools.register_function("fetch_daily_quote", fetch_daily_quote,
                                     description="获取单只股票日线行情", category="data")
        orch.tools.register_function("fetch_stock_list", fetch_stock_list,
                                     description="获取全市场股票列表", category="data")
        orch.tools.register_function("fetch_market_sentiment", fetch_market_sentiment,
                                     description="获取市场情绪数据", category="data")
        orch.tools.register_function("get_table", store.get_table,
                                     description="查询DuckDB表", category="data")

    if engine:
        orch.tools.register_function("score_all", engine.score_all,
                                     description="全市场评分", category="factor")
        orch.tools.register_function("adjust_factor_weight", engine.adjust_factor_weight,
                                     description="调整因子权重", category="factor",
                                     requires_approval=True)

    # 创建并注册Agents
    router = RouterAgent(context=orch.context, message_bus=orch.bus)
    analyst = AnalystAgent(context=orch.context, message_bus=orch.bus)
    trader = TraderAgent(context=orch.context, message_bus=orch.bus)
    reporter = ReporterAgent(context=orch.context, message_bus=orch.bus)
    evolver = EvolverAgent(
        context=orch.context, message_bus=orch.bus,
        store=store, engine=engine, llm_client=llm_client,
    )

    # 给Analyst注入工具
    for tool_name in ["fetch_daily_quote", "fetch_stock_list", "fetch_market_sentiment",
                       "score_all", "get_table"]:
        tool = orch.tools.get(tool_name)
        if tool:
            analyst.register_tool(tool_name, tool.func)

    # 给Trader注入工具
    for tool_name in ["score_all", "get_table"]:
        tool = orch.tools.get(tool_name)
        if tool:
            trader.register_tool(tool_name, tool.func)

    orch.register_agent(router)
    orch.register_agent(analyst)
    orch.register_agent(trader)
    orch.register_agent(reporter)
    orch.register_agent(evolver)

    logger.info(f"🚀 系统启动完成: {len(orch.agents)}个Agent, {len(orch.tools._tools)}个工具")
    return orch
