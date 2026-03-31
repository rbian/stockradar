"""Agent编排器 — 统一创建和管理所有Agent

负责：
1. 创建Agent实例并注入依赖
2. 注册工具
3. 连接消息总线
4. 提供运行入口
"""

import asyncio
from typing import Optional

from loguru import logger

from src.core.agent_base import BaseAgent, AgentConfig
from src.core.message_bus import MessageBus
from src.core.context import SharedContext
from src.core.tool_registry import ToolRegistry


class AgentOrchestrator:
    """Agent编排器 — 系统入口"""

    def __init__(self, store=None, llm_client=None):
        self.store = store
        self.llm_client = llm_client

        # 核心组件
        self.bus = MessageBus()
        self.context = SharedContext(store=store)
        self.tools = ToolRegistry()
        self.agents: dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent):
        """注册Agent"""
        self.agents[agent.name] = agent
        self.bus.create_queue(agent.name)
        logger.info(f"Agent注册: {agent.name} (tools: {list(agent._tools.keys())})")

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """获取Agent"""
        return self.agents.get(name)

    # ──── 消息路由 ────

    async def send_message(self, sender: str, receiver: str,
                           msg_type: str, content: dict, **kwargs):
        """发送消息"""
        return await self.bus.send(
            sender=sender, receiver=receiver,
            msg_type=msg_type, content=content, **kwargs
        )

    async def process_user_message(self, text: str, user_id: str = "") -> str:
        """处理用户消息 → RouterAgent → 对应Agent → 返回结果"""
        router = self.agents.get("router")
        if router is None:
            return "系统未就绪：RouterAgent未注册"

        # Router决定转发给谁
        from src.core.agent_base import Observation, ActionResult
        obs = Observation(content={"user_message": text, "user_id": user_id}, source="user")
        plan = await router.think(obs)

        if not plan.actions:
            return "抱歉，我无法理解这个请求"

        # 执行第一个action（通常是将任务转发给某个Agent）
        target_name = plan.actions[0].get("target", "")
        target_agent = self.agents.get(target_name)

        if target_agent is None:
            return f"Agent '{target_name}' 不存在"

        # 将用户消息注入context
        self.context.write("user_message", text, writer="router")
        self.context.write("user_id", user_id, writer="router")

        # 运行目标Agent
        result = await target_agent.run(self.context)

        if result.success:
            return result.message or str(result.data)[:2000]
        else:
            return f"处理失败: {result.message}"

    # ──── 定时任务 ────

    async def run_daily_pipeline(self, date: str = None):
        """每日盘后流水线"""
        from datetime import datetime
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"=== 每日流水线开始 [{date}] ===")

        # 1. 数据采集
        analyst = self.agents.get("analyst")
        if analyst:
            result = await analyst.run(self.context)
            logger.info(f"分析师: {'✅' if result.success else '❌'} {result.message}")

        # 2. 交易决策
        trader = self.agents.get("trader")
        if trader:
            result = await trader.run(self.context)
            logger.info(f"交易员: {'✅' if result.success else '❌'} {result.message}")

        # 3. 进化（如果Pro版）
        evolver = self.agents.get("evolver")
        if evolver:
            result = await evolver.run(self.context)
            logger.info(f"进化器: {'✅' if result.success else '❌'} {result.message}")

        # 4. 报告
        reporter = self.agents.get("reporter")
        if reporter:
            result = await reporter.run(self.context)
            logger.info(f"报告员: {'✅' if result.success else '❌'} {result.message}")

        logger.info(f"=== 每日流水线完成 [{date}] ===")

    # ──── 状态 ────

    def get_status(self) -> dict:
        """系统整体状态"""
        return {
            "agents": {name: agent.get_status() for name, agent in self.agents.items()},
            "bus": self.bus.get_stats(),
            "tools": len(self.tools._tools),
            "context_keys": len(self.context._blackboard),
        }
