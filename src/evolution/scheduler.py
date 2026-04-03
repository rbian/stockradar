"""自我进化调度器 - 统一调度所有进化模块

将感知（IC追踪、结构检测）→ 思考（假设生成、策略诊断）→ 行动（权重调整、因子注册）→ 记忆（知识沉淀）串联成闭环。

调度频率：
  每日盘后：因子IC追踪 + 市场结构检测
  每周日晚：LLM因子研究
  每月首个周日：策略诊断 + 知识回顾
"""

from datetime import datetime, timedelta
from loguru import logger

from src.evolution.auto_register import AutoRegister
from src.evolution.factor_tracker import FactorTracker
from src.evolution.regime_detector import RegimeDetector
from src.evolution.knowledge import KnowledgeStore


class EvolutionScheduler:
    """自我进化调度器

    用法：
        from src.evolution.scheduler import EvolutionScheduler
        scheduler = EvolutionScheduler(store=store, engine=engine)
        scheduler.daily_run(data, date)   # 每日
        scheduler.weekly_run(data, date)  # 每周
        scheduler.monthly_run(data, date) # 每月
    """

    def __init__(self, store=None, engine=None, llm_client=None):
        self.store = store
        self.engine = engine
        self.llm_client = llm_client

        self.tracker = FactorTracker()
        self.regime_detector = RegimeDetector(store=store)
        self.knowledge = KnowledgeStore()
        self.auto_register = AutoRegister(engine=engine)

        # 启动时恢复动态因子
        self.auto_register.restore_all_to_engine()

    # ========== 每日执行 ==========

    def daily_run(self, data: dict, date: str) -> dict:
        """每日盘后执行：IC追踪 + 结构检测

        这是进化的最频繁动作，必须轻量快速。
        """
        results = {"date": date, "daily": {}}

        # 1. 因子IC追踪 + 权重调整
        daily_quote = data.get("daily_quote")
        adjustments = self.tracker.daily_update(
            data=data,
            date=date,
            factor_engine=self.engine,
            daily_quote=daily_quote,
        )
        results["daily"]["factor_adjustments"] = adjustments

        # 2. 将调整后的权重实时反馈到评分引擎
        if adjustments and self.engine:
            self._apply_weights_to_engine()

        # 3. 市场结构检测
        alerts = self.regime_detector.check_structural_change(data, date)
        results["daily"]["regime_alerts"] = alerts

        # 4. 将重要事件写入知识库
        if alerts:
            for alert in alerts:
                if alert["severity"] in ("high", "medium"):
                    self.knowledge.append(
                        "regime_history.md",
                        f"**{alert['type']}** [{alert['severity']}]\n"
                        f"{alert['message']}\n"
                        f"详情: {alert.get('details', {})}"
                    )

        # 5. 持久化IC历史到DuckDB
        self._persist_ic_history(date)

        logger.info(f"每日进化完成 [{date}]: "
                     f"{len(adjustments)}个因子调整, "
                     f"{len(alerts)}个结构警报")
        return results

    # ========== 每周执行 ==========

    async def weekly_run(self, data: dict, date: str) -> dict:
        """每周日晚执行：LLM因子研究"""
        results = {"date": date, "weekly": {}}

        if self.llm_client is None:
            logger.warning("LLM不可用，跳过周度因子研究")
            return results

        from src.evolution.hypothesis_gen import HypothesisGenerator
        gen = HypothesisGenerator(self.llm_client, self.store)

        # 注入因子追踪状态给LLM参考
        data["factor_tracker_status"] = self.tracker.get_status()

        result = await gen.weekly_run(data, date)
        results["weekly"]["hypothesis"] = result

        # 自动注册有效因子
        registrations = []
        for hyp, val in zip(
            result.get("hypotheses", []),
            result.get("validations", []),
        ):
            reg_result = self.auto_register.register_hypothesis(hyp, val)
            if reg_result:
                registrations.append(reg_result)
        results["weekly"]["registrations"] = registrations

        # Review 已注册的动态因子
        reviews = self.auto_register.review_registered_factors(
            data, date, tracker=self.tracker
        )
        results["weekly"]["factor_reviews"] = reviews

        # 将有效发现写入知识库
        for val in result.get("validations", []):
            if val.get("is_valid"):
                self.knowledge.append(
                    "factor_discoveries.md",
                    f"**{val['name']}** ({val.get('category', '?')})\n"
                    f"IC={val.get('ic', '?'):.4f}\n"
                    f"解读: {val.get('ic_interpretation', '?')}"
                )
            elif val.get("can_calculate") and not val.get("is_valid"):
                self.knowledge.append(
                    "factor_failures.md",
                    f"**{val['name']}** — IC={val.get('ic', 'N/A')}\n"
                    f"解读: {val.get('ic_interpretation', '?')}"
                )

        logger.info(f"周度进化完成 [{date}]: {result.get('report', '')[:100]}")
        return results

    # ========== 每月执行 ==========

    async def monthly_run(self, data: dict, date: str) -> dict:
        """每月执行：策略诊断 + 知识回顾"""
        results = {"date": date, "monthly": {}}

        # 1. 策略诊断
        if self.llm_client:
            from src.evolution.strategy_doctor import StrategyDoctor
            doctor = StrategyDoctor(self.llm_client, self.store)
            diagnosis = await doctor.monthly_checkup(date)
            results["monthly"]["diagnosis"] = diagnosis

            # 将诊断结果写入知识库
            self.knowledge.append(
                "strategy_evolution.md",
                f"**健康度**: {diagnosis.get('health_score', '?')}/100\n"
                f"**诊断**: {diagnosis.get('diagnosis', '?')}\n"
                f"**改进建议**: {diagnosis.get('improvements', [])}"
            )

            # 将失败模式写入知识库
            for fp in diagnosis.get("failure_patterns", []):
                self.knowledge.append(
                    "failure_patterns.md",
                    f"**模式**: {fp.get('pattern', '?')}\n"
                    f"频率: {fp.get('frequency', '?')}\n"
                    f"建议: {fp.get('suggestion', '?')}"
                )
        else:
            logger.warning("LLM不可用，跳过月度诊断")

        # 2. 因子体系月度review
        status_df = self.tracker.get_status()
        suspended = status_df[status_df["is_suspended"]]
        active = status_df[~status_df["is_suspended"]]

        results["monthly"]["factor_review"] = {
            "total": len(status_df),
            "active": len(active),
            "suspended": len(suspended),
            "suspended_factors": suspended["factor"].tolist() if not suspended.empty else [],
        }

        # 3. 知识库清理（去重+压缩）
        self._monthly_knowledge_cleanup()

        logger.info(f"月度进化完成 [{date}]")
        return results

    # ========== 闭环：进化结果反馈到核心引擎 ==========

    def _apply_weights_to_engine(self):
        """将FactorTracker调整后的权重实时应用到FactorEngine（因子级）"""
        if self.engine is None:
            return

        for factor_name, status in self.tracker.factor_statuses.items():
            if status.is_suspended:
                self.engine.suspend_factor(factor_name)
            else:
                # 确保未暂停
                cat_config = self.engine.config["categories"].get(status.category, {})
                factor_config = cat_config.get("factors", {}).get(factor_name, {})
                if factor_config.get("_suspended"):
                    self.engine.resume_factor(factor_name, status.current_weight)
                else:
                    # 使用 multiplier × original 作为因子级权重
                    self.engine.adjust_factor_weight(factor_name, status.current_weight)

        logger.debug("进化权重已同步到评分引擎（因子级）")

    def _persist_ic_history(self, date: str):
        """持久化IC历史到DuckDB，防止重启丢失"""
        if self.store is None:
            return

        import pandas as pd
        records = []
        for name, status in self.tracker.factor_statuses.items():
            records.append({
                "factor": name,
                "category": status.category,
                "date": date,
                "ic": status.ic_today,
                "ic_20d_avg": status.ic_20d_avg,
                "weight": status.current_weight,
                "is_suspended": status.is_suspended,
                "consecutive_low_ic": status.consecutive_low_ic_days,
            })

        if records:
            df = pd.DataFrame(records)
            self.store.upsert_df("factor_ic_history", df, ["factor", "date"])

    def _monthly_knowledge_cleanup(self):
        """每月清理知识库：去重、压缩过长内容"""
        for fname in self.knowledge.FILES:
            content = self.knowledge.read(fname)
            if not content:
                continue

            lines = content.split("\n")
            if len(lines) > 500:
                # 保留标题+前50行+最近200行
                header = lines[:5]
                recent = lines[-200:]
                compressed = header + ["\n...(中间内容已压缩)..."] + recent
                self.knowledge.write(fname, "\n".join(compressed))
                logger.info(f"知识库压缩: {fname} {len(lines)}→{len(compressed)}行")

    def get_evolution_status(self) -> dict:
        """获取进化系统整体状态"""
        status_df = self.tracker.get_status()
        return {
            "factors": {
                "total": len(status_df),
                "active": len(status_df[~status_df["is_suspended"]]),
                "suspended": len(status_df[status_df["is_suspended"]]),
                "avg_ic_20d": status_df["ic_20d_avg"].mean() if not status_df.empty else 0,
            },
            "knowledge_files": len(self.knowledge.FILES),
            "dynamic_factors": self.auto_register.get_status().to_dict("records"),
            "last_daily": "N/A",  # TODO: 从DB读取
        }
