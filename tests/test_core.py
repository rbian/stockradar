"""核心模块单元测试"""

import asyncio
import pytest

# ──── Test MessageBus ────

def test_message_bus_create():
    from src.core.message_bus import MessageBus
    bus = MessageBus()
    bus.create_queue("agent_a")
    bus.create_queue("agent_b")
    stats = bus.get_stats()
    assert "agent_a" in stats["agents"]
    assert "agent_b" in stats["agents"]


@pytest.mark.asyncio
async def test_message_bus_send_receive():
    from src.core.message_bus import MessageBus
    bus = MessageBus()
    bus.create_queue("agent_a")

    msg = await bus.send(
        sender="test", receiver="agent_a",
        msg_type="test", priority=2, content={"key": "value"}
    )
    assert msg.sender == "test"

    received = await bus.receive("agent_a", timeout=1.0)
    assert received is not None
    assert received.content["key"] == "value"


@pytest.mark.asyncio
async def test_message_bus_broadcast():
    from src.core.message_bus import MessageBus
    bus = MessageBus()
    bus.create_queue("agent_a")
    bus.create_queue("agent_b")

    await bus.send(sender="test", receiver="all",
                   msg_type="broadcast", content={"msg": "hello"})

    msg_a = await bus.receive("agent_a", timeout=1.0)
    msg_b = await bus.receive("agent_b", timeout=1.0)
    assert msg_a is not None
    assert msg_b is not None
    assert msg_a.content["msg"] == "hello"


# ──── Test SharedContext ────

def test_context_read_write():
    from src.core.context import SharedContext
    ctx = SharedContext()
    ctx.write("market.regime", "bullish", writer="analyst")
    assert ctx.read("market.regime") == "bullish"
    assert ctx.read("nonexistent", "default") == "default"


def test_context_namespace():
    from src.core.context import SharedContext
    ctx = SharedContext()
    ctx.write("market.regime", "bullish", writer="analyst")
    ctx.write("market.sentiment", 0.8, writer="analyst")
    ctx.write("portfolio.cash", 100000, writer="trader")

    market = ctx.read_namespace("market.")
    assert len(market) == 2
    assert "market.regime" in market
    assert "portfolio.cash" not in market


def test_context_scores():
    import pandas as pd
    from src.core.context import SharedContext
    ctx = SharedContext()
    scores = pd.DataFrame({"score_total": [1.0, 0.8]}, index=["A", "B"])
    ctx.set_scores(scores)
    assert ctx.get_scores() is not None
    assert len(ctx.get_scores()) == 2


def test_context_snapshot():
    from src.core.context import SharedContext
    ctx = SharedContext()
    ctx.write("key1", "value1", writer="test")
    snapshot = ctx.snapshot()
    assert "data" in snapshot
    assert "key1" in snapshot["data"]


# ──── Test ToolRegistry ────

def test_tool_register():
    from src.core.tool_registry import ToolRegistry, Tool
    reg = ToolRegistry()

    def my_tool(x): return x * 2
    reg.register(Tool(name="double", func=my_tool, description="乘2", category="math"))

    assert reg.get("double") is not None
    assert len(reg.list_tools(category="math")) == 1


@pytest.mark.asyncio
async def test_tool_call():
    from src.core.tool_registry import ToolRegistry, Tool
    reg = ToolRegistry()

    def add(a, b): return a + b
    reg.register(Tool(name="add", func=add, category="math"))

    result = await reg.call("test_agent", "add", args=(1, 2))
    assert result == 3


@pytest.mark.asyncio
async def test_tool_permission():
    from src.core.tool_registry import ToolRegistry, Tool
    reg = ToolRegistry()

    def secret(): return "secret"
    reg.register(Tool(name="secret", func=secret, allowed_agents=["admin"]))

    with pytest.raises(PermissionError):
        await reg.call("hacker", "secret")


def test_tool_description():
    from src.core.tool_registry import ToolRegistry, Tool
    reg = ToolRegistry()
    reg.register(Tool(name="tool1", func=lambda: None, description="Tool 1"))
    reg.register(Tool(name="tool2", func=lambda: None, description="Tool 2"))

    desc = reg.get_tools_description()
    assert "tool1" in desc
    assert "tool2" in desc


# ──── Test RouterAgent ────

def test_router_intent_matching():
    from src.agents.router import RouterAgent
    router = RouterAgent()

    tests = {
        "分析宁德时代": "analyst",
        "今天持仓怎么样": "trader",
        "生成日报": "reporter",
        "因子表现如何": "evolver",
        "净值和收益": "trader",
        "市场行情": "analyst",
        "跑一下回测": "trader",
    }

    for text, expected in tests.items():
        result = router._match_intent(text)
        assert result == expected, f"'{text}' 应该匹配 {expected}，实际 {result}"


@pytest.mark.asyncio
async def test_router_help():
    from src.agents.router import RouterAgent
    from src.core.context import SharedContext

    router = RouterAgent(context=SharedContext())
    result = await router.run(SharedContext())
    # 默认无消息时应该能处理
    assert result is not None


# ──── Test AgentOrchestrator ────

@pytest.mark.asyncio
async def test_orchestrator_setup():
    from src.core.orchestrator import AgentOrchestrator
    from src.agents.router import RouterAgent
    from src.agents.analyst import AnalystAgent

    orch = AgentOrchestrator()
    orch.register_agent(RouterAgent(context=orch.context, message_bus=orch.bus))
    orch.register_agent(AnalystAgent(context=orch.context, message_bus=orch.bus))

    status = orch.get_status()
    assert len(status["agents"]) == 2


@pytest.mark.asyncio
async def test_orchestrator_process_message():
    from src.core.orchestrator import AgentOrchestrator
    from src.agents import RouterAgent, AnalystAgent, TraderAgent, ReporterAgent, EvolverAgent

    orch = AgentOrchestrator()
    orch.register_agent(RouterAgent(context=orch.context, message_bus=orch.bus))
    orch.register_agent(AnalystAgent(context=orch.context, message_bus=orch.bus))
    orch.register_agent(TraderAgent(context=orch.context, message_bus=orch.bus))
    orch.register_agent(ReporterAgent(context=orch.context, message_bus=orch.bus))
    orch.register_agent(EvolverAgent(context=orch.context, message_bus=orch.bus))

    # 测试交易相关消息
    result = await orch.process_user_message("今天持仓怎么样", "test_user")
    assert "持仓" in result

    # 测试报告
    result = await orch.process_user_message("生成日报", "test_user")
    assert "日报" in result
