"""因子引擎 - 评分排序 + 动量计算

支持因子级权重：
  - 每个因子有独立weight字段（默认1.0，即等权）
  - FactorTracker可通过adjust_factor_weight()精确调整单个因子权重
  - 向后兼容：旧配置文件无weight字段时自动等权
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

from src.infra.config import CONFIG_DIR
from src.risk_management.stock_blacklist import StockBlacklist


class FactorEngine:
    """因子评分引擎"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(CONFIG_DIR / "factors.yaml")

        self.blacklist = StockBlacklist()
        self.config_path = config_path
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.factor_funcs = self._register_factors()

    def _register_factors(self) -> dict:
        """注册所有因子计算函数"""
        from src.factors.fundamental import (
            calc_roe, calc_pe_percentile, calc_revenue_yoy, calc_profit_yoy,
            calc_gross_margin, calc_ocf_ratio, calc_debt_ratio, calc_goodwill_ratio,
            calc_peg, calc_operating_leverage, calc_inventory_turnover, calc_accrual_ratio,
        )
        from src.factors.technical import (
            calc_atr, calc_volume_trend,
            calc_price_vs_ma, calc_ma_slope, calc_momentum,
            calc_volatility, calc_max_drawdown,
            calc_rsi, calc_macd_signal, calc_bollinger_width,
            calc_volume_price_divergence, calc_turnover_rate_change, calc_amplitude,
            calc_mean_reversion_score, calc_williams_r, calc_ichimoku_signal,
        )
        from src.factors.capital_flow import (
            calc_northbound_net, calc_northbound_consecutive,
            calc_main_force_net_1d, calc_main_force_net_5d,
            calc_margin_balance_change,
        )
        from src.factors.llm_factors import (
            calc_earnings_sentiment, calc_news_sentiment_7d,
            calc_research_consensus,
        )
        from src.factors.market_sentiment import (
            calc_turnover_anomaly, calc_limit_up_count,
            calc_high_low_position, calc_volume_ratio,
        )

        return {
            # Fundamental (12) — 接收 financial DataFrame
            "roe": lambda d: calc_roe(d.get("financial", pd.DataFrame())),
            "pe_percentile": lambda d: calc_pe_percentile(d.get("daily_quote", pd.DataFrame())),
            "revenue_yoy": lambda d: calc_revenue_yoy(d.get("financial", pd.DataFrame())),
            "profit_yoy": lambda d: calc_profit_yoy(d.get("financial", pd.DataFrame())),
            "gross_margin": lambda d: calc_gross_margin(d.get("financial", pd.DataFrame())),
            "ocf_ratio": lambda d: calc_ocf_ratio(d.get("financial", pd.DataFrame())),
            "debt_ratio": lambda d: calc_debt_ratio(d.get("financial", pd.DataFrame())),
            "goodwill_ratio": lambda d: calc_goodwill_ratio(d.get("financial", pd.DataFrame())),
            "peg": lambda d: calc_peg(d.get("daily_quote", pd.DataFrame()), d.get("financial", pd.DataFrame())),
            "operating_leverage": lambda d: calc_operating_leverage(d.get("financial", pd.DataFrame())),
            "inventory_turnover": lambda d: calc_inventory_turnover(d.get("financial", pd.DataFrame())),
            "accrual_ratio": lambda d: calc_accrual_ratio(d.get("financial", pd.DataFrame())),
            # Technical (12) — 接收 daily_quote DataFrame
            "price_vs_ma20": lambda d: calc_price_vs_ma(d.get("daily_quote", pd.DataFrame()), 20),
            "price_vs_ma60": lambda d: calc_price_vs_ma(d.get("daily_quote", pd.DataFrame()), 60),
            "ma20_slope": lambda d: calc_ma_slope(d.get("daily_quote", pd.DataFrame()), 20),
            "momentum_20d": lambda d: calc_momentum(d.get("daily_quote", pd.DataFrame()), 20),
            "volatility_20d": lambda d: calc_volatility(d.get("daily_quote", pd.DataFrame()), 20),
            "max_drawdown_60d": lambda d: calc_max_drawdown(d.get("daily_quote", pd.DataFrame()), 60),
            "rsi": lambda d: calc_rsi(d.get("daily_quote", pd.DataFrame()), 14),
            "macd_signal": lambda d: calc_macd_signal(d.get("daily_quote", pd.DataFrame())),
            "bollinger_width": lambda d: calc_bollinger_width(d.get("daily_quote", pd.DataFrame()), 20),
            "volume_price_divergence": lambda d: calc_volume_price_divergence(d.get("daily_quote", pd.DataFrame()), 20),
            "turnover_rate_change": lambda d: calc_turnover_rate_change(d.get("daily_quote", pd.DataFrame()), 5),
            "amplitude": lambda d: calc_amplitude(d.get("daily_quote", pd.DataFrame()), 10),
            "atr_14d": lambda d: calc_atr(d.get("daily_quote", pd.DataFrame()), 14),
            "volume_trend": lambda d: calc_volume_trend(d.get("daily_quote", pd.DataFrame())),
            "mean_reversion_score": lambda d: calc_mean_reversion_score(d.get("daily_quote", pd.DataFrame())),
            "williams_r": lambda d: calc_williams_r(d.get("daily_quote", pd.DataFrame())),
            "ichimoku_signal": lambda d: calc_ichimoku_signal(d.get("daily_quote", pd.DataFrame())),
            # Capital flow (5) — 接收 daily_quote + northbound
            "northbound_net_5d": lambda d: calc_northbound_net(d.get("daily_quote", pd.DataFrame()), d.get("northbound", pd.DataFrame())),
            "northbound_consecutive_days": lambda d: calc_northbound_consecutive(d.get("northbound", pd.DataFrame())),
            "main_force_net_1d": lambda d: calc_main_force_net_1d(d.get("daily_quote", pd.DataFrame())),
            "main_force_net_5d": lambda d: calc_main_force_net_5d(d.get("daily_quote", pd.DataFrame())),
            "margin_balance_change": lambda d: calc_margin_balance_change(d.get("daily_quote", pd.DataFrame())),
            # Market sentiment (4) — 接收 daily_quote
            "turnover_anomaly": lambda d: calc_turnover_anomaly(d.get("daily_quote", pd.DataFrame()), 20),
            "limit_up_count": lambda d: calc_limit_up_count(d.get("daily_quote", pd.DataFrame()), 20),
            "high_low_position": lambda d: calc_high_low_position(d.get("daily_quote", pd.DataFrame()), 60),
            "volume_ratio": lambda d: calc_volume_ratio(d.get("daily_quote", pd.DataFrame())),
            # LLM (3) — 接收 full data dict
            "earnings_sentiment": lambda d: calc_earnings_sentiment(d),
            "news_sentiment_7d": lambda d: calc_news_sentiment_7d(d),
            "research_consensus": lambda d: calc_research_consensus(d),
        }

    def score_all(self, data: dict, date: str = None) -> pd.DataFrame:
        """给全市场打分

        总分 = Σ(category_weight × Σ(factor_weight × normalized_factor) / weight_sum)
        """
        all_codes = data.get("codes", [])
        if isinstance(all_codes, pd.Series):
            all_codes = all_codes.tolist()

        results = {}

        for category, cat_config in self.config["categories"].items():
            cat_weight = cat_config["weight"]
            factors_config = cat_config.get("factors", {})
            cat_scores = pd.Series(0.0, index=all_codes)
            weight_sum = 0.0

            for factor_name, factor_config in factors_config.items():
                # 因子独立权重（默认1.0，向后兼容）
                factor_weight = factor_config.get("weight", 1.0)

                # 跳过被暂停的因子
                if factor_config.get("_suspended", False):
                    continue

                try:
                    func = self.factor_funcs.get(factor_name)
                    if func is None:
                        continue

                    raw_values = func(data)
                    if raw_values is None or (isinstance(raw_values, pd.Series) and raw_values.empty):
                        continue

                    # 截尾
                    clip_range = factor_config.get("clip")
                    if clip_range and clip_range[0] is not None:
                        raw_values = raw_values.clip(*clip_range)

                    # 标准化
                    std = raw_values.std()
                    if std == 0 or pd.isna(std):
                        normalized = pd.Series(0.0, index=raw_values.index)
                    else:
                        normalized = (raw_values - raw_values.mean()) / std

                    # 方向调整
                    invert = factor_config.get("invert", False)
                    if invert or factor_config.get("direction") == "lower_better":
                        normalized = -normalized

                    # 按因子权重叠加
                    cat_scores += normalized * factor_weight
                    weight_sum += factor_weight

                except Exception as e:
                    logger.warning(f"因子 {factor_name} 计算失败: {e}")

            # 归一化：除以因子权重之和
            if weight_sum > 0:
                cat_scores = cat_scores / weight_sum

            results[f"score_{category}"] = cat_scores * cat_weight

        # 汇总总分
        score_df = pd.DataFrame(results, index=all_codes)
        score_cols = [c for c in score_df.columns if c.startswith("score_") and c != "score_total"]
        score_df["score_total"] = score_df[score_cols].sum(axis=1)
        
        # Apply blacklist penalty: blacklisted stocks get reduced score
        for code in score_df.index:
            modifier = self.blacklist.get_signal_modifier(str(code))
            if modifier < 1.0:
                score_df.loc[code, "score_total"] *= modifier
                logger.info(f"[Blacklist] {code} 信号惩罚 x{modifier}")
        
        score_df = score_df.sort_values("score_total", ascending=False)
        score_df["rank"] = range(1, len(score_df) + 1)

        logger.info(f"评分完成: {len(score_df)} 只股票, Top3: {score_df.head(3).index.tolist()}")
        return score_df

    def adjust_factor_weight(self, factor_name: str, new_weight: float) -> bool:
        """调整单个因子权重（供FactorTracker调用）"""
        for cat_config in self.config["categories"].values():
            if factor_name in cat_config.get("factors", {}):
                cat_config["factors"][factor_name]["weight"] = new_weight
                logger.debug(f"因子权重调整: {factor_name} → {new_weight:.3f}")
                return True
        return False

    def suspend_factor(self, factor_name: str) -> bool:
        """暂停因子"""
        for cat_config in self.config["categories"].values():
            if factor_name in cat_config.get("factors", {}):
                cat_config["factors"][factor_name]["_suspended"] = True
                return True
        return False

    def resume_factor(self, factor_name: str, initial_weight: float = 0.5) -> bool:
        """恢复暂停的因子"""
        for cat_config in self.config["categories"].values():
            if factor_name in cat_config.get("factors", {}):
                cat_config["factors"][factor_name]["_suspended"] = False
                cat_config["factors"][factor_name]["weight"] = initial_weight
                return True
        return False

    def register_dynamic_factor(self, name: str, func, category: str,
                                factor_config: dict) -> bool:
        """注册动态因子（由EvolverAgent自动注册）

        Args:
            name: 因子名称
            func: 因子计算函数，接受 data dict，返回 pd.Series(index=code)
            category: 所属类别（如 'technical', 'fundamental'）
            factor_config: 因子配置（direction, clip, weight 等）

        Returns:
            是否注册成功
        """
        # 添加计算函数
        self.factor_funcs[name] = func

        # 添加到配置
        if category not in self.config["categories"]:
            logger.warning(f"类别 {category} 不存在，无法注册因子 {name}")
            return False

        self.config["categories"][category]["factors"][name] = factor_config
        logger.info(f"动态因子已注册: {name} → {category}")
        return True

    def calc_delta(self, today_scores: pd.DataFrame,
                   prev_scores: pd.DataFrame,
                   lookback: int = 5) -> pd.DataFrame:
        """计算评分动量 ΔS = S(t) - S(t-lookback)"""
        merged = today_scores.join(
            prev_scores[["score_total"]], rsuffix="_prev", how="left"
        )
        merged["delta_s"] = merged["score_total"] - merged["score_total_prev"].fillna(0)
        return merged

    def calc_acceleration(self, scores: pd.DataFrame,
                          prev_delta: pd.Series = None) -> pd.Series:
        """计算评分加速度 Δ²S"""
        if prev_delta is not None and "delta_s" in scores.columns:
            return scores["delta_s"] - prev_delta
        return pd.Series(0.0, index=scores.index)
