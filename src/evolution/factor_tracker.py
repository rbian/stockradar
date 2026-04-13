"""因子IC追踪 + 权重自动调整（因子级）

每日计算每个因子的IC（rank相关性），通过 multiplier 调整因子权重：
- 每个因子有独立的 original_weight（来自factors.yaml，默认1.0）
- FactorTracker 跟踪一个 weight_multiplier（初始1.0）
- 实际权重 = original_weight × weight_multiplier
- IC持续为正 → multiplier × 1.05（上限×1.5）
- IC持续为负 → multiplier × 0.95（下限×0.3）
- 连续60天低IC → 暂停该因子（multiplier=0）
- 暂停因子连续15天IC > 0.02 → 自动恢复，multiplier=0.5
"""

from dataclasses import dataclass, field

import json

import numpy as np
import pandas as pd
import yaml
from pathlib import Path
from loguru import logger
from scipy import stats

from src.infra.config import CONFIG_DIR


@dataclass
class FactorStatus:
    """因子状态"""
    name: str
    category: str
    original_weight: float  # 因子的原始权重（来自factors.yaml，默认1.0）
    weight_multiplier: float  # 权重乘数（初始1.0，由IC动态调整）
    ic_today: float
    ic_20d_avg: float
    consecutive_low_ic_days: int  # 连续IC<0.01天数
    consecutive_recovery_days: int  # 连续IC>0.02天数（恢复用）
    is_suspended: bool
    weight_history: list = field(default_factory=list)
    ic_history: list = field(default_factory=list)

    @property
    def current_weight(self) -> float:
        """实际权重 = original_weight × multiplier"""
        if self.is_suspended:
            return 0.0
        return self.original_weight * self.weight_multiplier


class FactorTracker:
    """因子IC追踪器（因子级权重）

    用法:
        tracker = FactorTracker()
        # 每日收盘后调用
        tracker.daily_update(data, date, factor_engine)
        # 查看状态
        tracker.get_status()
        # 获取调整后的权重（写入factors.yaml）
        tracker.get_adjusted_config()
    """

    def __init__(self, config_path: str = None, store=None):
        if config_path is None:
            config_path = str(CONFIG_DIR / "factors.yaml")
        self.config_path = config_path
        self.store = store  # DuckDB store，用于持久化
        self._json_backup_path = Path("data/cache/factor_ic_state.json")

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.lookforward_days = 10  # IC计算的前瞻天数（加长，更稳健）
        self.ic_window = 30  # IC均值计算窗口（加长）
        self.suspend_threshold_days = 60  # 连续低IC暂停天数（加倍）
        self.recovery_threshold_days = 15  # 恢复需要连续天数

        # 调整幅度限制（更保守）— 作用于 multiplier
        self.boost_rate = 1.05  # multiplier 加权倍数
        self.decay_rate = 0.95  # multiplier 减权倍数
        self.max_weight_mult = 1.5  # multiplier 最大值
        self.min_weight_mult = 0.3  # multiplier 最小值

        # 因子状态
        self.factor_statuses: dict[str, FactorStatus] = {}
        self._init_statuses()
        self._restore_from_store()

    def _restore_from_store(self):
        """从DuckDB或JSON备份恢复历史IC数据，避免重启后丢失"""
        restored = False

        # 优先从DuckDB恢复
        if self.store is not None:
            try:
                ic_df = self.store.get_table("factor_ic_history")
                if ic_df is not None and not ic_df.empty:
                    for name, status in self.factor_statuses.items():
                        factor_history = ic_df[ic_df["factor"] == name].sort_values("date")
                        if factor_history.empty:
                            continue
                        for _, row in factor_history.iterrows():
                            status.ic_history.append({"date": row["date"], "ic": row.get("ic", 0)})
                        latest = factor_history.iloc[-1]
                        restored_weight = latest.get("weight", status.original_weight)
                        if status.original_weight > 0:
                            status.weight_multiplier = restored_weight / status.original_weight
                        status.is_suspended = latest.get("is_suspended", False)
                        if status.is_suspended:
                            status.weight_multiplier = 0.0
                        status.consecutive_low_ic_days = latest.get("consecutive_low_ic", 0)
                        recent_ics = [h["ic"] for h in status.ic_history[-self.ic_window:]]
                        status.ic_20d_avg = np.mean(recent_ics) if recent_ics else 0
                    logger.info(f"从DB恢复 {len(self.factor_statuses)} 个因子的IC历史")
                    restored = True
            except Exception as e:
                logger.debug(f"DB恢复IC历史失败: {e}")

        # 回退：从JSON备份恢复
        if not restored and self._json_backup_path.exists():
            try:
                with open(self._json_backup_path, "r") as f:
                    backup = json.load(f)
                factors_data = backup.get("factors", {})
                for name, fdata in factors_data.items():
                    if name in self.factor_statuses:
                        status = self.factor_statuses[name]
                        status.ic_history = fdata.get("ic_history", [])[-60:]  # 保留最近60天
                        status.weight_multiplier = fdata.get("weight_multiplier", 1.0)
                        status.is_suspended = fdata.get("is_suspended", False)
                        status.consecutive_low_ic_days = fdata.get("consecutive_low_ic_days", 0)
                        status.consecutive_recovery_days = fdata.get("consecutive_recovery_days", 0)
                        recent_ics = [h["ic"] for h in status.ic_history[-self.ic_window:]]
                        status.ic_20d_avg = np.mean(recent_ics) if recent_ics else 0
                logger.info(f"从JSON备份恢复 {len(factors_data)} 个因子的IC历史")
            except Exception as e:
                logger.debug(f"JSON备份恢复失败: {e}")

    def _save_to_json(self):
        """将IC状态保存到JSON备份文件（每次daily_update后调用）"""
        try:
            self._json_backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup = {"factors": {}}
            for name, status in self.factor_statuses.items():
                backup["factors"][name] = {
                    "weight_multiplier": status.weight_multiplier,
                    "is_suspended": status.is_suspended,
                    "consecutive_low_ic_days": status.consecutive_low_ic_days,
                    "consecutive_recovery_days": status.consecutive_recovery_days,
                    "ic_20d_avg": status.ic_20d_avg,
                    "ic_history": status.ic_history[-60:],
                }
            with open(self._json_backup_path, "w") as f:
                json.dump(backup, f)
        except Exception as e:
            logger.debug(f"JSON备份保存失败: {e}")

    def _init_statuses(self):
        """初始化因子状态 — 读取因子级权重"""
        for category, cat_config in self.config["categories"].items():
            for factor_name, factor_config in cat_config.get("factors", {}).items():
                # 读取因子独立权重（默认1.0，向后兼容无weight字段的配置）
                factor_weight = factor_config.get("weight", 1.0)
                self.factor_statuses[factor_name] = FactorStatus(
                    name=factor_name,
                    category=category,
                    original_weight=factor_weight,
                    weight_multiplier=1.0,
                    ic_today=0.0,
                    ic_20d_avg=0.0,
                    consecutive_low_ic_days=0,
                    consecutive_recovery_days=0,
                    is_suspended=False,
                )

    def daily_update(self, data: dict, date: str,
                     factor_engine=None,
                     daily_quote: pd.DataFrame = None) -> dict:
        """每日更新因子IC并调整权重 multiplier

        调整的是 weight_multiplier，实际权重 = original_weight × multiplier
        """
        adjustments = {}

        for factor_name, status in self.factor_statuses.items():
            # 计算IC
            ic = self._calc_factor_ic(factor_name, data, date, factor_engine, daily_quote)
            status.ic_today = ic
            status.ic_history.append({"date": date, "ic": ic})

            # 计算IC_30日均值
            recent_ics = [h["ic"] for h in status.ic_history[-self.ic_window:]]
            status.ic_20d_avg = np.mean(recent_ics) if len(recent_ics) >= 10 else 0

            # IC一致性：最近10次IC中正的比例
            recent_10 = [h["ic"] for h in status.ic_history[-10:]]
            if len(recent_10) >= 10:
                positive_ratio = sum(1 for x in recent_10 if x > 0) / 10
            else:
                positive_ratio = 0.5

            old_mult = status.weight_multiplier
            old_weight = status.current_weight

            if status.is_suspended:
                if ic > 0.02:
                    status.consecutive_recovery_days += 1
                else:
                    status.consecutive_recovery_days = 0

                if status.consecutive_recovery_days >= self.recovery_threshold_days:
                    status.is_suspended = False
                    status.weight_multiplier = 0.5  # 恢复时 multiplier=0.5
                    status.consecutive_recovery_days = 0
                    status.consecutive_low_ic_days = 0
                    adjustments[factor_name] = {
                        "action": "recovered",
                        "old_weight": 0,
                        "new_weight": status.current_weight,
                        "multiplier": status.weight_multiplier,
                    }
            else:
                # 基于 IC 一致性调整 multiplier
                if positive_ratio > 0.7 and status.ic_20d_avg > 0.02:
                    # IC持续为正且一致 → 小幅加大 multiplier
                    status.weight_multiplier = min(
                        status.weight_multiplier * self.boost_rate,
                        self.max_weight_mult
                    )
                    status.consecutive_low_ic_days = 0
                elif positive_ratio < 0.3:
                    # IC持续为负 → 缩小 multiplier
                    status.weight_multiplier = max(
                        status.weight_multiplier * self.decay_rate,
                        self.min_weight_mult
                    )
                    status.consecutive_low_ic_days += 1
                elif status.ic_20d_avg < 0.01 and positive_ratio < 0.5:
                    status.consecutive_low_ic_days += 1
                else:
                    status.consecutive_low_ic_days = max(0, status.consecutive_low_ic_days - 1)

                # 暂停检查
                if status.consecutive_low_ic_days >= self.suspend_threshold_days:
                    status.is_suspended = True
                    status.weight_multiplier = 0.0
                    adjustments[factor_name] = {
                        "action": "suspended",
                        "old_weight": old_weight,
                        "new_weight": 0,
                        "reason": f"连续{status.consecutive_low_ic_days}天IC<0.01",
                    }
                elif abs(status.weight_multiplier - old_mult) > 0.005:
                    adjustments[factor_name] = {
                        "action": "adjusted",
                        "old_weight": old_weight,
                        "new_weight": status.current_weight,
                        "multiplier": status.weight_multiplier,
                        "ic_20d_avg": status.ic_20d_avg,
                    }

            status.weight_history.append({
                "date": date,
                "weight": status.current_weight,
                "multiplier": status.weight_multiplier,
            })

        if adjustments:
            logger.info(f"因子权重调整 [{date}]: {len(adjustments)} 个因子")
            for name, adj in adjustments.items():
                logger.info(
                    f"  {name}: {adj['action']} "
                    f"({adj.get('old_weight', 0):.3f} → {adj.get('new_weight', 0):.3f}, "
                    f"mult={adj.get('multiplier', '?'):.3f})"
                )

        return adjustments

    def _calc_factor_ic(self, factor_name: str, data: dict, date: str,
                        factor_engine, daily_quote: pd.DataFrame) -> float:
        """计算单个因子的IC（Spearman rank相关性）

        IC = rank_corr(因子值, 未来N日收益)
        """
        if factor_engine is None or daily_quote is None or daily_quote.empty:
            return 0.0

        try:
            # 计算因子值
            func = factor_engine.factor_funcs.get(factor_name)
            if func is None:
                return 0.0

            factor_values = func(data)
            if factor_values is None or (isinstance(factor_values, pd.Series) and factor_values.empty):
                return 0.0

            if not isinstance(factor_values, pd.Series):
                return 0.0

            # 计算未来N日收益
            date_ts = pd.Timestamp(date)
            dq = daily_quote.copy()
            dq["date"] = pd.to_datetime(dq["date"])

            # 当日收盘价
            today_prices = dq[dq["date"] == date_ts].set_index("code")["close"]
            # N日后收盘价
            future_date = date_ts + pd.Timedelta(days=self.lookforward_days * 2)  # 宽松估计
            future_prices = dq[
                (dq["date"] > date_ts) & (dq["date"] <= future_date)
            ].groupby("code")["close"].first()

            if today_prices.empty or future_prices.empty:
                return 0.0

            future_returns = (future_prices - today_prices) / today_prices
            future_returns = future_returns.dropna()

            # 对齐因子值和收益
            common_codes = factor_values.index.intersection(future_returns.index)
            if len(common_codes) < 30:  # 样本太少不计算
                return 0.0

            aligned_factors = factor_values.reindex(common_codes).dropna()
            aligned_returns = future_returns.reindex(common_codes).dropna()

            common = aligned_factors.index.intersection(aligned_returns.index)
            if len(common) < 30:
                return 0.0

            # Spearman rank相关
            corr, _ = stats.spearmanr(
                aligned_factors.reindex(common).values,
                aligned_returns.reindex(common).values,
            )
            return corr if not np.isnan(corr) else 0.0

        except Exception as e:
            logger.debug(f"因子 {factor_name} IC计算失败: {e}")
            return 0.0

    def get_status(self) -> pd.DataFrame:
        """获取所有因子状态"""
        records = []
        for name, s in self.factor_statuses.items():
            records.append({
                "factor": name,
                "category": s.category,
                "original_weight": s.original_weight,
                "weight_multiplier": s.weight_multiplier,
                "current_weight": s.current_weight,
                "ic_today": s.ic_today,
                "ic_20d_avg": s.ic_20d_avg,
                "consecutive_low_ic": s.consecutive_low_ic_days,
                "is_suspended": s.is_suspended,
            })
        return pd.DataFrame(records)

    def get_adjusted_config(self) -> dict:
        """获取调整后的因子配置

        保留 category 原始权重，在每个因子配置中写入调整后的 weight。
        可直接写入factors.yaml。
        """
        adjusted = {"categories": {}}

        # 按 category 分组
        categories = {}
        for name, status in self.factor_statuses.items():
            cat = status.category
            if cat not in categories:
                # 保留 category 原始权重
                cat_weight = self.config["categories"][cat]["weight"]
                categories[cat] = {
                    "weight": cat_weight,
                    "factors": {},
                }

            # 保留原始因子配置
            original_factors = self.config["categories"][cat].get("factors", {})
            if name in original_factors:
                categories[cat]["factors"][name] = dict(original_factors[name])

            # 写入调整后的因子级权重
            categories[cat]["factors"][name]["weight"] = status.current_weight

            # 暂停因子标记
            if status.is_suspended:
                categories[cat]["factors"][name]["_suspended"] = True

        adjusted["categories"] = categories
        return adjusted

    def save_adjusted_config(self, output_path: str = None):
        """保存调整后的权重到配置文件"""
        if output_path is None:
            output_path = self.config_path

        adjusted = self.get_adjusted_config()
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(adjusted, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"因子权重已保存到 {output_path}")
