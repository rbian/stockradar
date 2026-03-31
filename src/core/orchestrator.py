"""Agent编排器 — 用户消息处理入口

流程：用户消息 → Router路由 → 目标Agent执行 → 返回结果
"""

import asyncio
from typing import Optional

from loguru import logger

from src.core.agent_base import BaseAgent, Observation, ActionResult
from src.core.message_bus import MessageBus
from src.core.context import SharedContext
from src.core.tool_registry import ToolRegistry


class AgentOrchestrator:
    """Agent编排器"""

    def __init__(self, store=None, llm_client=None):
        self.store = store
        self.llm_client = llm_client
        self.bus = MessageBus()
        self.context = SharedContext(store=store)
        self.tools = ToolRegistry()
        self.agents: dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent):
        self.agents[agent.name] = agent
        self.bus.create_queue(agent.name)
        logger.info(f"Agent注册: {agent.name}")

    # ──── 工具注册 ────

    def register_tool(self, name: str, func, description: str = "", category: str = ""):
        """注册工具函数到所有Agent可用"""
        from src.core.tool_registry import Tool
        tool = Tool(name=name, func=func, description=description, category=category)
        self.tools.register(tool)
        # 注入到所有已注册的Agent
        for agent in self.agents.values():
            agent.register_tool(name, func)
        logger.info(f"工具注册: {name} → {len(self.agents)}个Agent")

    # ──── 用户消息处理 ────

    async def process_user_message(self, text: str, user_id: str = "") -> str:
        """处理用户消息"""
        router = self.agents.get("router")
        if not router:
            return "系统未就绪"

        # 注入消息到context
        self.context.write("user_message", text, writer="user")
        self.context.write("user_id", user_id, writer="user")

        # Router思考
        obs = Observation(content={"user_message": text, "user_id": user_id}, source="user")
        plan = await router.think(obs)

        if not plan.actions:
            return "无法理解您的请求，输入'帮助'查看功能列表"

        action = plan.actions[0]

        # 直接回复（帮助等）
        if "response" in action:
            return action["response"]

        # 转发给目标Agent
        target_name = action.get("target", "")
        target_agent = self.agents.get(target_name)

        if not target_agent:
            return f"Agent '{target_name}' 不可用"

        # 执行目标Agent
        try:
            result = await asyncio.wait_for(
                target_agent.run(self.context),
                timeout=60
            )
            if result.success:
                return result.message or "执行成功（无输出）"
            else:
                return f"⚠️ {result.message}"
        except asyncio.TimeoutError:
            return "⏰ 处理超时，请稍后再试"
        except Exception as e:
            logger.error(f"Agent执行失败: {e}")
            return f"❌ 处理失败: {e}"

    # ──── 每日流水线 ────

    async def run_daily_pipeline(self, date: str = None):
        """每日盘后流水线"""
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"=== 每日流水线 [{date}] ===")
        self.context.write("pipeline_date", date, writer="system")

        for name in ["analyst", "trader", "reporter"]:
            agent = self.agents.get(name)
            if agent:
                try:
                    result = await asyncio.wait_for(agent.run(self.context), timeout=120)
                    logger.info(f"{name}: {'✅' if result.success else '❌'} {result.message[:80]}")
                except Exception as e:
                    logger.error(f"{name}: ❌ {e}")
