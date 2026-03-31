"""市场结构变化检测模块

更高层的结构性变化检测（区别于 src/strategy/regime.py 的即时状态识别）：
  - 检测因子相关性矩阵的结构性断裂
  - 检测行业轮动速度变化
  - 检测到变化时推送警报
"""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.infra.config import PROJECT_ROOT


class RegimeDetector:
    """市场结构变化检测器

    与 src/strategy/regime.py 的区别：
    - regime.py 是即时状态识别（今天市场是什么状态）
    - RegimeDetector 是结构性变化检测（市场结构是否发生了根本性变化）

    用法:
        detector = RegimeDetector(store)
        alerts = detector.check_structural_change(date)
    """

    def __init__(self, store=None):
        self.store = store
        self._prev_corr_matrix = None
        self._prev_industry_rotation = None

    def check_structural_change(self, data: dict, date: str) -> list[dict]:
        """检测市场结构性变化

        Args:
            data: 数据字典
            date: 当前日期

        Returns:
            警报列表 [{"type", "severity", "message", "details"}]
        """
        alerts = []

        # 1. 因子相关性矩阵结构性断裂检测
        corr_alert = self._detect_factor_correlation_break(data, date)
        if corr_alert:
            alerts.append(corr_alert)

        # 2. 行业轮动速度变化
        rotation_alert = self._detect_industry_rotation_change(data, date)
        if rotation_alert:
            alerts.append(rotation_alert)

        # 3. 波动率分布变化
        vol_alert = self._detect_volatility_regime_change(data, date)
        if vol_alert:
            alerts.append(vol_alert)

        if alerts:
            logger.warning(f"检测到 {len(alerts)} 个市场结构变化信号 [{date}]")
            for a in alerts:
                logger.warning(f"  [{a['severity']}] {a['message']}")
        else:
            logger.info(f"市场结构正常 [{date}]")

        return alerts

    def _detect_factor_correlation_break(self, data: dict,
                                         date: str) -> dict | None:
        """检测因子相关性矩阵的结构性断裂

        方法：比较近期和历史的因子相关性矩阵，计算矩阵差异的Frobenius范数。
        如果范数超过阈值，认为发生结构性变化。
        """
        daily_score = data.get("daily_score")
        if daily_score is None or (isinstance(daily_score, pd.DataFrame) and daily_score.empty):
            return None

        if not isinstance(daily_score, pd.DataFrame):
            return None

        score_cols = [c for c in ["score_fundamental", "score_technical", "score_capital", "score_llm"]
                      if c in daily_score.columns]
        if len(score_cols) < 2:
            return None

        try:
            date_ts = pd.Timestamp(date)

            # 近期相关性矩阵（最近20个交易日）
            recent = daily_score[daily_score["date"] <= date_ts].sort_values("date").tail(20)
            # 历史相关性矩阵（之前40个交易日）
            if len(recent) < 20:
                return None

            cutoff_date = recent["date"].iloc[0]
            historical = daily_score[
                (daily_score["date"] < cutoff_date)
            ].sort_values("date").tail(40)

            if len(historical) < 20:
                return None

            # 计算相关性矩阵
            recent_corr = recent[score_cols].corr()
            hist_corr = historical[score_cols].corr()

            if recent_corr.isnull().any().any() or hist_corr.isnull().any().any():
                return None

            # 计算矩阵差异（Frobenius范数）
            diff = (recent_corr.values - hist_corr.values)
            frobenius_norm = np.sqrt(np.sum(diff ** 2))

            # 保存当前矩阵供下次对比
            self._prev_corr_matrix = recent_corr

            # 阈值判断
            if frobenius_norm > 1.5:
                # 找出变化最大的因子对
                changes = []
                for i, c1 in enumerate(score_cols):
                    for j, c2 in enumerate(score_cols):
                        if i < j:
                            delta = abs(recent_corr.iloc[i, j] - hist_corr.iloc[i, j])
                            if delta > 0.3:
                                changes.append(
                                    f"{c1} vs {c2}: "
                                    f"{hist_corr.iloc[i, j]:.2f} → {recent_corr.iloc[i, j]:.2f}"
                                )

                severity = "high" if frobenius_norm > 2.5 else "medium"
                message = f"因子相关性矩阵发生结构性变化（差异度={frobenius_norm:.2f}）"

                return {
                    "type": "factor_correlation_break",
                    "severity": severity,
                    "message": message,
                    "details": {
                        "frobenius_norm": round(frobenius_norm, 3),
                        "recent_correlation": recent_corr.round(3).to_dict(),
                        "historical_correlation": hist_corr.round(3).to_dict(),
                        "major_changes": changes,
                    },
                    "date": date,
                }

        except Exception as e:
            logger.debug(f"因子相关性检测异常: {e}")
            return None

        return None

    def _detect_industry_rotation_change(self, data: dict,
                                         date: str) -> dict | None:
        """检测行业轮动速度变化

        方法：比较近期和历史的行业排名稳定性。
        如果行业排名频繁变化，说明轮动加速。
        """
        industry_index = data.get("industry_index")
        if industry_index is None or (isinstance(industry_index, pd.DataFrame) and industry_index.empty):
            return None

        if not isinstance(industry_index, pd.DataFrame):
            return None

        try:
            date_ts = pd.Timestamp(date)
            df = industry_index.copy()
            df["date"] = pd.to_datetime(df["date"])

            # 近期行业收益排名
            recent_data = df[df["date"] <= date_ts].sort_values("date").tail(20)
            hist_data = df[
                (df["date"] <= date_ts - pd.Timedelta(days=20))
            ].sort_values("date").tail(40)

            if recent_data.empty or hist_data.empty:
                return None

            # 计算各行业近期收益率
            recent_returns = recent_data.groupby("industry_code").apply(
                lambda g: (g["close"].iloc[-1] / g["close"].iloc[0] - 1) * 100
                if len(g) >= 2 else np.nan
            ).dropna().sort_values(ascending=False)

            hist_returns = hist_data.groupby("industry_code").apply(
                lambda g: (g["close"].iloc[-1] / g["close"].iloc[0] - 1) * 100
                if len(g) >= 2 else np.nan
            ).dropna().sort_values(ascending=False)

            if len(recent_returns) < 5 or len(hist_returns) < 5:
                return None

            # 计算排名变化
            recent_ranks = recent_returns.rank(ascending=False)
            hist_ranks = hist_returns.reindex(recent_returns.index).rank(ascending=False)

            rank_changes = (recent_ranks - hist_ranks).dropna()
            avg_rank_change = rank_changes.abs().mean()

            # 领涨行业变化
            recent_top3 = set(recent_returns.head(3).index)
            hist_top3 = set(hist_returns.head(3).index)
            top3_overlap = len(recent_top3 & hist_top3)

            # 保存
            self._prev_industry_rotation = avg_rank_change

            # 阈值：平均排名变化 > 5 表示轮动加速
            if avg_rank_change > 5:
                severity = "high" if avg_rank_change > 8 else "medium"
                return {
                    "type": "industry_rotation_acceleration",
                    "severity": severity,
                    "message": (
                        f"行业轮动加速（平均排名变化={avg_rank_change:.1f}），"
                        f"领涨行业重叠度={top3_overlap}/3"
                    ),
                    "details": {
                        "avg_rank_change": round(avg_rank_change, 2),
                        "top3_overlap": top3_overlap,
                        "recent_leaders": list(recent_returns.head(5).index),
                        "historical_leaders": list(hist_returns.head(5).index),
                    },
                    "date": date,
                }

        except Exception as e:
            logger.debug(f"行业轮动检测异常: {e}")
            return None

        return None

    def _detect_volatility_regime_change(self, data: dict,
                                         date: str) -> dict | None:
        """检测波动率分布变化

        方法：比较近期和历史波动率的分布特征（均值和偏度）。
        """
        daily_quote = data.get("daily_quote")
        if daily_quote is None or (isinstance(daily_quote, pd.DataFrame) and daily_quote.empty):
            return None

        if not isinstance(daily_quote, pd.DataFrame):
            return None

        try:
            date_ts = pd.Timestamp(date)
            df = daily_quote.copy()
            df["date"] = pd.to_datetime(df["date"])

            # 计算每日截面波动率（个股收益率的截面标准差）
            daily_data = df[df["date"] <= date_ts].sort_values("date")

            if len(daily_data) < 60:
                return None

            # 每日截面收益率标准差
            daily_vol = daily_data.groupby("date").apply(
                lambda g: g["change_pct"].std() if len(g) > 10 else np.nan
            ).dropna()

            if len(daily_vol) < 40:
                return None

            recent_vol = daily_vol.tail(20)
            hist_vol = daily_vol.iloc[-40:-20]

            recent_mean = recent_vol.mean()
            hist_mean = hist_vol.mean()
            recent_std = recent_vol.std()

            if hist_mean == 0:
                return None

            # 波动率变化比率
            vol_ratio = recent_mean / hist_mean

            # 阈值判断
            if vol_ratio > 1.8:
                return {
                    "type": "volatility_spike",
                    "severity": "high" if vol_ratio > 2.5 else "medium",
                    "message": (
                        f"市场波动率显著上升（近期{recent_mean:.2f}% vs 历史{hist_mean:.2f}%，"
                        f"倍率{vol_ratio:.1f}x）"
                    ),
                    "details": {
                        "recent_vol_mean": round(recent_mean, 3),
                        "historical_vol_mean": round(hist_mean, 3),
                        "vol_ratio": round(vol_ratio, 2),
                    },
                    "date": date,
                }
            elif vol_ratio < 0.5:
                return {
                    "type": "volatility_compression",
                    "severity": "low",
                    "message": (
                        f"市场波动率异常收缩（近期{recent_mean:.2f}% vs 历史{hist_mean:.2f}%，"
                        f"倍率{vol_ratio:.1f}x），可能酝酿大波动"
                    ),
                    "details": {
                        "recent_vol_mean": round(recent_mean, 3),
                        "historical_vol_mean": round(hist_mean, 3),
                        "vol_ratio": round(vol_ratio, 2),
                    },
                    "date": date,
                }

        except Exception as e:
            logger.debug(f"波动率变化检测异常: {e}")
            return None

        return None

    def format_alerts(self, alerts: list[dict]) -> str:
        """格式化警报为可读文本"""
        if not alerts:
            return "市场结构正常，未检测到异常变化。"

        lines = [
            f"## 市场结构变化警报 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "",
        ]

        severity_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}

        for alert in alerts:
            icon = severity_icons.get(alert["severity"], "⚪")
            lines.append(f"{icon} **[{alert['severity'].upper()}] {alert['message']}**")
            if alert.get("details"):
                for k, v in alert["details"].items():
                    if isinstance(v, (list, dict)):
                        v = str(v)[:100]
                    lines.append(f"  - {k}: {v}")
            lines.append("")

        return "\n".join(lines)
