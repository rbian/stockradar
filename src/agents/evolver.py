"""EvolverAgent — 进化系统交互入口

处理因子表现查询、动态因子管理、IC监控等进化相关请求。
"""

from loguru import logger

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult


class EvolverAgent(BaseAgent):
    """进化Agent — 因子进化、IC追踪、动态因子管理"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(
            name="evolver",
            description="因子进化、IC追踪、动态因子管理",
        )
        super().__init__(config, context, message_bus)
        self._scheduler = None

    def _get_scheduler(self):
        """延迟加载 EvolutionScheduler"""
        if self._scheduler is None:
            from src.evolution.scheduler import EvolutionScheduler
            self._scheduler = EvolutionScheduler()
        return self._scheduler

    async def perceive(self, context) -> Observation:
        user_msg = context.read("user_message", "") if context else ""
        return Observation(content={"user_message": user_msg}, source="user")

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")

        if not msg:
            return Plan(actions=[])

        action = {"type": "status"}

        if "动态因子" in msg:
            action = {"type": "dynamic_factors"}
        elif "权重" in msg:
            action = {"type": "weights"}
        elif any(k in msg for k in ("IC", "因子表现", "因子监控", "因子状态")):
            action = {"type": "ic_status"}

        return Plan(actions=[action], reasoning=f"进化查询: {msg[:30]}")

    async def act(self, plan: Plan) -> ActionResult:
        if not plan.actions:
            return ActionResult(success=False, message="无法理解进化查询")

        action = plan.actions[0]
        action_type = action.get("type", "status")

        try:
            scheduler = self._get_scheduler()

            if action_type == "ic_status":
                df = scheduler.tracker.get_status()
                if df.empty:
                    return ActionResult(success=True, message="暂无因子IC数据")

                lines = ["📊 **因子IC追踪状态**\n"]
                for _, row in df.iterrows():
                    status = "⏸" if row["is_suspended"] else "✅"
                    lines.append(
                        f"{status} **{row['factor']}** ({row['category']})\n"
                        f"  权重: {row['current_weight']:.2f} "
                        f"(×{row['weight_multiplier']:.2f})\n"
                        f"  IC今日: {row['ic_today']:.4f} | "
                        f"IC30日均值: {row['ic_20d_avg']:.4f}"
                    )
                return ActionResult(success=True, message="\n".join(lines))

            elif action_type == "dynamic_factors":
                df = scheduler.auto_register.get_status()
                if df.empty:
                    return ActionResult(success=True, message="暂无动态因子，等待首次周度研究")
                lines = ["🧬 **动态因子注册表**\n"]
                for _, row in df.iterrows():
                    status = "✅活跃" if row["is_active"] else "❌已下架"
                    ic_str = f"{row['avg_ic_30d']:.4f}" if row['avg_ic_30d'] is not None else "N/A"
                    lines.append(
                        f"**{row['name']}** ({row['category']}) {status}\n"
                        f"  注册: {row['registered_date']} | "
                        f"验证IC: {row['ic_at_validation']:.4f} | "
                        f"30日IC: {ic_str}"
                    )
                return ActionResult(success=True, message="\n".join(lines))

            elif action_type == "weights":
                df = scheduler.tracker.get_status()
                lines = ["⚖️ **因子权重调整状态**\n"]
                active = df[~df["is_suspended"]]
                for _, row in active.iterrows():
                    mult = row["weight_multiplier"]
                    emoji = "📈" if mult > 1.05 else "📉" if mult < 0.95 else "➡️"
                    lines.append(
                        f"{emoji} {row['factor']}: "
                        f"×{mult:.2f} (权重 {row['current_weight']:.2f})"
                    )
                suspended = df[df["is_suspended"]]
                if not suspended.empty:
                    lines.append(f"\n⏸ 暂停: {', '.join(suspended['factor'].tolist())}")
                return ActionResult(success=True, message="\n".join(lines))

            else:
                status = scheduler.get_evolution_status()
                factors = status.get("factors", {})
                dynamic = status.get("dynamic_factors", [])
                lines = [
                    "🧬 **进化系统状态**\n",
                    f"因子: {factors.get('active', 0)}活跃 / "
                    f"{factors.get('suspended', 0)}暂停 / "
                    f"{factors.get('total', 0)}总计",
                    f"平均IC30日: {factors.get('avg_ic_20d', 0):.4f}",
                    f"动态因子: {len(dynamic)} 个",
                    f"知识库文件: {status.get('knowledge_files', 0)} 个",
                ]
                return ActionResult(success=True, message="\n".join(lines))

        except Exception as e:
            logger.error(f"EvolverAgent 执行失败: {e}")
            return ActionResult(success=False, message=f"进化查询失败: {e}")
