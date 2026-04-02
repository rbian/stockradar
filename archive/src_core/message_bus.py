"""消息总线 — Agent间异步通信

支持点对点和广播消息，带优先级队列。
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from loguru import logger


@dataclass
class Message:
    """Agent间消息"""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    sender: str = ""
    receiver: str = ""      # 具体Agent名 / "all"(广播)
    msg_type: str = ""      # analysis, signal, decision, alert, approval_request
    priority: int = 3       # 1=critical, 2=high, 3=normal, 4=low
    content: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: str = ""  # 关联ID，追踪任务流
    reply_to: str = ""       # 回复的消息ID


class MessageBus:
    """异步消息总线

    用法:
        bus = MessageBus()
        bus.subscribe("trader", handler)
        await bus.send(sender="analyst", receiver="trader", ...)
        msg = await bus.receive("trader")
    """

    def __init__(self):
        # 每个Agent一个优先级队列
        self._queues: dict[str, asyncio.PriorityQueue] = {}
        # 主题订阅
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        # 消息历史（最近1000条）
        self._history: list[Message] = []
        self._max_history = 1000
        self._lock = asyncio.Lock()

    def create_queue(self, agent_name: str):
        """为Agent创建消息队列"""
        if agent_name not in self._queues:
            self._queues[agent_name] = asyncio.PriorityQueue()

    def subscribe(self, msg_type: str, handler: Callable):
        """订阅特定类型的消息"""
        self._subscribers[msg_type].append(handler)

    async def send(self, sender: str, receiver: str, msg_type: str,
                   priority: int = 3, content: dict = None,
                   correlation_id: str = "", reply_to: str = "") -> Message:
        """发送消息"""
        msg = Message(
            sender=sender,
            receiver=receiver,
            msg_type=msg_type,
            priority=priority,
            content=content or {},
            correlation_id=correlation_id,
            reply_to=reply_to,
        )

        # 广播
        if receiver == "all":
            for name, queue in self._queues.items():
                if name != sender:
                    await queue.put((priority, msg))
        # 点对点
        elif receiver in self._queues:
            await self._queues[receiver].put((priority, msg))
        else:
            logger.warning(f"消息目标不存在: {receiver}")
            return msg

        # 记录历史
        async with self._lock:
            self._history.append(msg)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # 触发订阅者
        for handler in self._subscribers.get(msg_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg)
                else:
                    handler(msg)
            except Exception as e:
                logger.error(f"消息订阅者处理失败: {e}")

        logger.debug(f"消息: {sender}→{receiver} [{msg_type}] priority={priority}")
        return msg

    async def receive(self, agent_name: str, timeout: float = 0.1) -> Optional[Message]:
        """接收消息（非阻塞，带超时）"""
        queue = self._queues.get(agent_name)
        if queue is None:
            return None

        try:
            _, msg = await asyncio.wait_for(queue.get(), timeout=timeout)
            return msg
        except asyncio.TimeoutError:
            return None

    async def receive_all(self, agent_name: str) -> list[Message]:
        """接收所有待处理消息"""
        messages = []
        queue = self._queues.get(agent_name)
        if queue is None:
            return messages

        while not queue.empty():
            try:
                _, msg = queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break

        # 按优先级排序
        messages.sort(key=lambda m: m.priority)
        return messages

    def get_history(self, agent_name: str = None, limit: int = 50) -> list[Message]:
        """获取消息历史"""
        if agent_name:
            msgs = [m for m in self._history
                    if m.sender == agent_name or m.receiver == agent_name]
        else:
            msgs = self._history
        return msgs[-limit:]

    def get_stats(self) -> dict:
        """获取总线统计"""
        return {
            "agents": list(self._queues.keys()),
            "pending": {name: q.qsize() for name, q in self._queues.items()},
            "total_sent": len(self._history),
        }
