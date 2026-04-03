"""EvolverAgent 自动因子注册模块

将 LLM 验证通过的新因子自动注册到 FactorEngine：
  - IC > 0.03 的假设自动注册为动态因子
  - 使用 pandas_expr 计算（安全沙箱执行）
  - 维护注册因子清单 + IC 历史
  - 定期 review，IC 持续差的自动下架

注册流程：
  1. HypothesisGenerator 产出 validated hypotheses
  2. register_hypothesis() 验证 → 注册到 FactorEngine + factors.yaml
  3. review_registered_factors() 定期评估，清理低效因子
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from src.evolution.hypothesis_gen import _safe_execute_pandas
from src.infra.config import CONFIG_DIR, PROJECT_ROOT


# 动态因子注册表路径
REGISTRY_PATH = PROJECT_ROOT / "knowledge" / "dynamic_factors.json"


class DynamicFactor:
    """动态因子记录"""

    def __init__(self, name: str, category: str, pandas_expr: str,
                 intuition: str, ic_at_validation: float,
                 registered_date: str):
        self.name = name
        self.category = category
        self.pandas_expr = pandas_expr
        self.intuition = intuition
        self.ic_at_validation = ic_at_validation
        self.registered_date = registered_date
        self.ic_history: list[dict] = []  # [{date, ic}]
        self.is_active = True
        self.deactivation_date: str | None = None
        self.deactivation_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "pandas_expr": self.pandas_expr,
            "intuition": self.intuition,
            "ic_at_validation": self.ic_at_validation,
            "registered_date": self.registered_date,
            "ic_history": self.ic_history,
            "is_active": self.is_active,
            "deactivation_date": self.deactivation_date,
            "deactivation_reason": self.deactivation_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DynamicFactor":
        f = cls(
            name=d["name"],
            category=d["category"],
            pandas_expr=d["pandas_expr"],
            intuition=d.get("intuition", ""),
            ic_at_validation=d.get("ic_at_validation", 0),
            registered_date=d.get("registered_date", ""),
        )
        f.ic_history = d.get("ic_history", [])
        f.is_active = d.get("is_active", True)
        f.deactivation_date = d.get("deactivation_date")
        f.deactivation_reason = d.get("deactivation_reason")
        return f


class AutoRegister:
    """自动因子注册器

    用法:
        ar = AutoRegister(engine=engine)
        ar.register_hypothesis(hypothesis, validation)
        ar.review_registered_factors(data, date, engine, tracker)
    """

    # 注册门槛
    MIN_IC = 0.03       # IC 绝对值 > 0.03 才注册
    MIN_SAMPLES = 30    # 至少 30 个样本

    # 下架标准
    REVIEW_WINDOW = 30  # review 最近 30 天 IC
    DEACTIVATE_IC = 0.005  # 平均 IC < 0.005 则下架

    def __init__(self, engine=None, registry_path: str | Path = None):
        self.engine = engine
        self.registry_path = Path(registry_path) if registry_path else REGISTRY_PATH
        self.registry: list[DynamicFactor] = []
        self._load_registry()

    def _load_registry(self):
        """从 JSON 文件加载注册表"""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.registry = [DynamicFactor.from_dict(d) for d in data]
                active = sum(1 for f in self.registry if f.is_active)
                logger.info(f"加载动态因子注册表: {len(self.registry)} 个 ({active} 活跃)")
            except Exception as e:
                logger.warning(f"加载注册表失败: {e}")
                self.registry = []

    def _save_registry(self):
        """保存注册表到 JSON"""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump([f.to_dict() for f in self.registry], f,
                      ensure_ascii=False, indent=2)

    def register_hypothesis(self, hypothesis: dict,
                            validation: dict) -> dict | None:
        """注册一个验证通过的因子假设

        Args:
            hypothesis: LLM 生成的因子假设
            validation: 验证结果（含 ic, is_valid 等）

        Returns:
            注册结果 dict，或 None（不符合条件）
        """
        name = hypothesis.get("name", "")
        ic = validation.get("ic")
        is_valid = validation.get("is_valid", False)
        pandas_expr = hypothesis.get("pandas_expr", "")
        category = hypothesis.get("category", "technical")

        # 门槛检查
        if not is_valid:
            logger.debug(f"因子 {name} 未通过验证，跳过注册")
            return None

        if ic is None or abs(ic) < self.MIN_IC:
            logger.debug(f"因子 {name} IC={ic} 低于门槛 {self.MIN_IC}，跳过")
            return None

        if not pandas_expr:
            logger.debug(f"因子 {name} 无 pandas_expr，跳过注册")
            return None

        # 检查重名
        existing = next((f for f in self.registry if f.name == name and f.is_active), None)
        if existing:
            logger.info(f"动态因子 {name} 已存在，跳过重复注册")
            return None

        # 注册
        today = datetime.now().strftime("%Y-%m-%d")
        factor = DynamicFactor(
            name=name,
            category=category,
            pandas_expr=pandas_expr,
            intuition=hypothesis.get("intuition", ""),
            ic_at_validation=ic,
            registered_date=today,
        )
        factor.ic_history.append({"date": today, "ic": ic})

        self.registry.append(factor)

        # 注册到 FactorEngine
        if self.engine:
            self._register_to_engine(factor)

        # 持久化
        self._save_registry()

        result = {
            "name": name,
            "action": "registered",
            "ic": ic,
            "category": category,
        }
        logger.info(f"动态因子已注册: {name} (IC={ic:.4f}, category={category})")
        return result

    def _register_to_engine(self, factor: DynamicFactor):
        """将动态因子注册到 FactorEngine"""
        expr = factor.pandas_expr
        category = factor.category

        # 构建安全的因子计算函数
        def make_factor_func(pandas_expr: str):
            def factor_func(data: dict) -> pd.Series:
                daily_quote = data.get("daily_quote", pd.DataFrame())
                if daily_quote is None or daily_quote.empty:
                    return pd.Series(dtype=float)

                date_ts = daily_quote["date"].max() if "date" in daily_quote.columns else None
                if date_ts is not None:
                    recent = daily_quote[daily_quote["date"] <= date_ts].copy()
                else:
                    recent = daily_quote.copy()

                local_vars = {
                    "recent": recent,
                    "daily_quote": daily_quote,
                    "np": np,
                    "pd": pd,
                }
                # 可选数据
                for key in ("financial", "northbound", "industry_index"):
                    val = data.get(key, pd.DataFrame())
                    if val is not None and not val.empty:
                        if "date" in val.columns and date_ts is not None:
                            local_vars[key] = val[val["date"] <= date_ts].copy()
                        else:
                            local_vars[key] = val
                    else:
                        local_vars[key] = pd.DataFrame()

                result = _safe_execute_pandas(pandas_expr, local_vars)
                if result is not None and isinstance(result, pd.Series):
                    return result.dropna()
                return pd.Series(dtype=float)
            return factor_func

        func = make_factor_func(expr)

        factor_config = {
            "direction": "higher_better",
            "weight": 0.5,  # 新因子保守权重
            "_dynamic": True,
            "_pandas_expr": expr,
        }

        success = self.engine.register_dynamic_factor(
            name=factor.name,
            func=func,
            category=category,
            factor_config=factor_config,
        )
        if success:
            logger.info(f"动态因子 {factor.name} 已注册到 FactorEngine")
        return success

    def restore_all_to_engine(self):
        """启动时恢复所有活跃动态因子到引擎"""
        if not self.engine:
            return

        restored = 0
        for factor in self.registry:
            if factor.is_active:
                if self._register_to_engine(factor):
                    restored += 1
        logger.info(f"恢复 {restored} 个动态因子到引擎")

    def review_registered_factors(self, data: dict, date: str,
                                  tracker=None) -> list[dict]:
        """定期 review 动态因子，下架低效因子

        Args:
            data: 数据字典
            date: 当前日期
            tracker: FactorTracker（可选，同步 IC 历史）

        Returns:
            review 结果列表
        """
        results = []
        for factor in self.registry:
            if not factor.is_active:
                continue

            # 如果有 tracker，从 tracker 获取最新 IC
            if tracker and factor.name in tracker.factor_statuses:
                ic = tracker.factor_statuses[factor.name].ic_today
            else:
                # 自行计算 IC（简化版：用 pandas_expr）
                ic = self._quick_ic_check(factor, data, date)

            factor.ic_history.append({"date": date, "ic": ic or 0})

            # 检查最近窗口 IC
            recent = factor.ic_history[-self.REVIEW_WINDOW:]
            if len(recent) >= 10:
                avg_ic = np.mean([h["ic"] for h in recent])
            else:
                avg_ic = factor.ic_at_validation  # 样本不足，保留

            result = {
                "name": factor.name,
                "ic_latest": ic,
                "ic_avg_30d": avg_ic,
                "total_days": len(factor.ic_history),
            }

            # 下架判断
            if len(recent) >= 10 and abs(avg_ic) < self.DEACTIVATE_IC:
                factor.is_active = False
                factor.deactivation_date = date
                factor.deactivation_reason = f"30日平均IC={avg_ic:.4f} < {self.DEACTIVATE_IC}"
                result["action"] = "deactivated"
                logger.info(f"动态因子下架: {factor.name} (avg IC={avg_ic:.4f})")

                # 从引擎移除（暂停）
                if self.engine:
                    self.engine.suspend_factor(factor.name)
            else:
                result["action"] = "active"

            results.append(result)

        self._save_registry()
        return results

    def _quick_ic_check(self, factor: DynamicFactor,
                        data: dict, date: str) -> float | None:
        """快速检查因子 IC（自包含计算）"""
        try:
            daily_quote = data.get("daily_quote", pd.DataFrame())
            if daily_quote is None or daily_quote.empty:
                return None

            # 计算因子值
            from src.evolution.hypothesis_gen import HypothesisGenerator
            gen = HypothesisGenerator(None)
            factor_values = gen._try_pandas_expr(factor.pandas_expr, data, date)
            if factor_values is None or factor_values.empty:
                return None

            return gen._calc_ic(factor_values, daily_quote, date)
        except Exception as e:
            logger.debug(f"动态因子 {factor.name} IC 快检失败: {e}")
            return None

    def get_status(self) -> pd.DataFrame:
        """获取所有动态因子状态"""
        records = []
        for f in self.registry:
            recent_ic = [h["ic"] for h in f.ic_history[-30:]] if f.ic_history else []
            records.append({
                "name": f.name,
                "category": f.category,
                "is_active": f.is_active,
                "registered_date": f.registered_date,
                "ic_at_validation": f.ic_at_validation,
                "avg_ic_30d": np.mean(recent_ic) if recent_ic else None,
                "total_days": len(f.ic_history),
                "deactivation_reason": f.deactivation_reason,
            })
        return pd.DataFrame(records)
