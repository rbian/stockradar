"""Agent基类 — 所有Agent的公共接口和生命周期

生命周期: perceive → think → act → reflect
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import asyncio

from loguru import logger


class AgentState(Enum):
    IDLE = "idle"
    PERCEIVING = "perceiving"
    THINKING = "thinking"
    ACTING = "acting"
    REFLECTING = "reflecting"
    ERROR = "error"


@dataclass
class Observation:
    """感知结果"""
    content: dict = field(default_factory=dict)
    urgency: int = 3  # 1=critical, 5=low
    source: str = ""


@dataclass
class Plan:
    """思考后的行动计划"""
    actions: list[dict] = field(default_factory=list)
    reasoning: str = ""
    needs_approval: bool = False
    estimated_cost: float = 0.0  # LLM调用成本估算(元)


@dataclass
class ActionResult:
    """行动结果"""
    success: bool = True
    data: dict = field(default_factory=dict)
    message: str = ""
    cost: float = 0.0  # 实际LLM成本


@dataclass
class Lesson:
    """反思总结"""
    insight: str = ""
    should_remember: bool = False
    correction: str = ""


@dataclass
class AgentConfig:
    """Agent配置"""
    name: str
    description: str = ""
    llm_model: str = ""  # 留空=不用LLM
    max_retries: int = 3
    timeout_seconds: int = 60
    tools: list[str] = field(default_factory=list)  # 允许使用的工具名


class BaseAgent(ABC):
    """Agent基类

    子类必须实现: perceive, think, act
    可选实现: reflect
    """

    def __init__(self, config: AgentConfig, context=None, message_bus=None):
        self.config = config
        self.context = context
        self.bus = message_bus
        self.state = AgentState.IDLE
        self._tools: dict = {}
        self._cost_today = 0.0
        self._tasks_today = 0

    @property
    def name(self) -> str:
        return self.config.name

    def register_tool(self, name: str, func):
        """注册工具函数"""
        self._tools[name] = func

    def get_tool(self, name: str):
        """获取工具"""
        return self._tools.get(name)

    # ──── 生命周期 ────

    @abstractmethod
    async def perceive(self, context) -> Observation:
        """感知：从上下文中提取相关信息"""
        ...

    @abstractmethod
    async def think(self, observation: Observation) -> Plan:
        """思考：基于感知结果制定计划"""
        ...

    @abstractmethod
    async def act(self, plan: Plan) -> ActionResult:
        """行动：执行计划"""
        ...

    async def reflect(self, result: ActionResult) -> Lesson:
        """反思：评估结果，提取教训（可选）"""
        return Lesson()

    async def run(self, context=None) -> ActionResult:
        """完整执行一次Agent循环"""
        ctx = context or self.context
        try:
            # 感知
            self.state = AgentState.PERCEIVING
            observation = await self.perceive(ctx)

            # 思考
            self.state = AgentState.THINKING
            plan = await self.think(observation)

            # 需要审批时暂停
            if plan.needs_approval and self.bus:
                await self.bus.send(
                    sender=self.name,
                    receiver="router",
                    msg_type="approval_request",
                    priority=2,
                    content={"plan": plan.actions, "reasoning": plan.reasoning},
                )
                return ActionResult(success=False, message="等待用户审批")

            # 行动
            self.state = AgentState.ACTING
            result = await self.act(plan)
            self._cost_today += result.cost
            self._tasks_today += 1

            # 反思
            self.state = AgentState.REFLECTING
            lesson = await self.reflect(result)

            # 有价值的教训 → 写入知识库
            if lesson.should_remember and lesson.insight:
                self._save_lesson(lesson)

            self.state = AgentState.IDLE
            return result

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Agent {self.name} 执行失败: {e}")
            return ActionResult(success=False, message=str(e))

    def _save_lesson(self, lesson: Lesson):
        """保存教训到知识库"""
        if self.context and hasattr(self.context, 'knowledge'):
            self.context.knowledge.append(
                "failure_patterns.md",
                f"**Agent:{self.name}** {lesson.insight}\n"
                f"纠正: {lesson.correction}"
            )

    def get_status(self) -> dict:
        """获取Agent状态"""
        return {
            "name": self.name,
            "state": self.state.value,
            "cost_today": self._cost_today,
            "tasks_today": self._tasks_today,
            "tools": list(self._tools.keys()),
        }

    def reset_daily(self):
        """每日重置"""
        self._cost_today = 0.0
        self._tasks_today = 0
