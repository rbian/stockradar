"""EvolverAgent — 进化系统交互入口

处理因子表现查询、动态因子管理、IC监控等进化相关请求。
"""

from loguru import logger
import pandas as pd
from pathlib import Path

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

        if any(k in msg for k in ("复盘", "交易复盘", "review")):
            action = {"type": "trade_review"}
        elif any(k in msg for k in ("错误模式", "模式库", "错误", "patterns")):
            action = {"type": "error_patterns"}
        elif any(k in msg for k in ("教训", "lessons")):
            action = {"type": "lessons"}
        elif any(k in msg for k in ("知识库", "knowledge")):
            action = {"type": "knowledge_stats"}
        elif any(k in msg for k in ("参数优化", "最优参数", "param")):
            action = {"type": "param_optimize"}
        elif any(k in msg for k in ("因子生命周期", "因子审计", "factor.*audit")):
            action = {"type": "factor_lifecycle"}
        elif any(k in msg for k in ("github", "外部学习", "扫描", "项目发现")):
            action = {"type": "github_scan"}
        elif any(k in msg for k in ("skill评估", "skill.*评估", "技能评估")):
            action = {"type": "skill_eval"}
        elif any(k in msg for k in ("进化月报", "进化报告", "月报")):
            action = {"type": "evolution_report"}
        elif "动态因子" in msg:
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

            elif action_type == "status":
                status = scheduler.get_evolution_status()
                lines = [
                    "🧬 **进化系统状态**\n",
                    f"因子: {status.get('factors', {}).get('active', 0)}活跃 / "
                    f"{status.get('factors', {}).get('suspended', 0)}暂停",
                    f"动态因子: {len(status.get('dynamic_factors', []))} 个",
                    f"交易复盘: {status.get('trade_reviews', 0)} 份",
                    f"错误模式: {status.get('error_patterns', 0)} 个",
                ]
                return ActionResult(success=True, message="\n".join(lines))

            elif action_type == "trade_review":
                import json, pandas as pd
                from src.evolution.trade_reviewer import review_trades, format_review_report
                dq = self.context.read("data.daily_quote") if self.context else None
                nav_file = Path(__file__).resolve().parent.parent.parent / "data" / "nav_state_balanced.json"
                trade_log = []
                if nav_file.exists():
                    nav_data = json.loads(nav_file.read_text())
                    trade_log = nav_data.get("trade_log", [])
                # Also load persistent trade log
                tl_file = Path(__file__).resolve().parent.parent.parent / "data" / "trade_log.json"
                if tl_file.exists():
                    all_trades = json.loads(tl_file.read_text())
                    trade_log.extend(all_trades)
                if dq is None or not trade_log:
                    return ActionResult(success=True, message="暂无数据可复盘")
                result = review_trades(dq, trade_log)
                report = format_review_report(result["reviews"], result["patterns"])
                # Save to knowledge
                from src.evolution.trade_reviewer import save_review_to_knowledge
                from src.evolution.error_patterns import update_patterns_from_review
                save_review_to_knowledge(result["reviews"], result["patterns"])
                update_patterns_from_review(result)
                return ActionResult(success=True, message=report)

            elif action_type == "error_patterns":
                from src.evolution.error_patterns import format_patterns_report
                return ActionResult(success=True, message=format_patterns_report())

            elif action_type == "lessons":
                from src.evolution.knowledge import KnowledgeStore
                ks = KnowledgeStore()
                content = ks.read("lessons_learned.md")
                if len(content.strip()) < 100:
                    return ActionResult(success=True, message="暂无永久教训记录")
                return ActionResult(success=True, message=f"📝 **永久教训**\n\n{content}")

            elif action_type == "knowledge_stats":
                from src.evolution.knowledge import KnowledgeStore
                ks = KnowledgeStore()
                stats = ks.get_stats()
                lines = ["📚 **知识库统计**\n"]
                for fname, line_count in stats["files"].items():
                    lines.append(f"  {fname}: {line_count} 行")
                lines.append(f"\n  交易复盘: {stats['trade_reviews']} 份")
                lines.append(f"  错误模式: {stats['error_patterns']} 个")
                return ActionResult(success=True, message="\n".join(lines))

            elif action_type == "param_optimize":
                from src.evolution.param_optimizer import optimize_params, format_optimization_report
                dq = self.context.read("data.daily_quote") if self.context else None
                financial = self.context.read("financial_data") if self.context else None
                codes = self.context.read("codes", []) if self.context else []
                if dq is None:
                    return ActionResult(success=False, message="无行情数据")
                # Run optimization (may take a few minutes)
                results = optimize_params(dq, financial, codes)
                report = format_optimization_report(results)
                return ActionResult(success=True, message=report)

            elif action_type == "factor_lifecycle":
                tracker = scheduler.tracker
                status_df = tracker.get_status() if tracker else pd.DataFrame()
                if status_df.empty:
                    return ActionResult(success=True, message="暂无因子IC数据")

                lines = ["🔄 **因子生命周期**\n"]
                # Active
                active = status_df[~status_df["is_suspended"]]
                declining = active[active["weight_multiplier"] < 0.9]
                healthy = active[active["weight_multiplier"] >= 0.9]
                suspended = status_df[status_df["is_suspended"]]

                lines.append(f"\n✅ 健康 ({len(healthy)}个):")
                lines.append(f"⚠️ 衰退 ({len(declining)}个):")
                for _, r in declining.iterrows():
                    lines.append(f"  {r['factor']}: IC={r['ic_20d_avg']:.4f}, 权重×{r['weight_multiplier']:.2f}")
                lines.append(f"\n⏸ 暂停 ({len(suspended)}个):")
                for _, r in suspended.iterrows():
                    lines.append(f"  {r['factor']}: IC={r.get('ic_20d_avg', 0):.4f}")

                return ActionResult(success=True, message="\n".join(lines))

            elif action_type == "github_scan":
                from src.evolution.github_scanner import scan_github, format_scan_report
                results = scan_github()
                return ActionResult(success=True, message=format_scan_report(results))

            elif action_type == "skill_eval":
                from src.evolution.skill_evaluator import format_skill_report
                report = format_skill_report()
                return ActionResult(success=True, message=report)

            elif action_type == "evolution_report":
                from src.evolution.evolution_reporter import generate_monthly_report
                report = generate_monthly_report()
                return ActionResult(success=True, message=report)

        except Exception as e:
            logger.error(f"EvolverAgent 执行失败: {e}")
            return ActionResult(success=False, message=f"进化查询失败: {e}")
