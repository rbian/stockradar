"""Expression-based Factor Generator (表达式因子生成器)

GitHub学习来源: Microsoft Qlib / RD-Agent 的自动因子挖掘思路
核心idea: 用基础算子(+, -, *, /, rank, ts_mean, ts_std)自动组合现有数据列，
生成新因子表达式，通过简单IC筛选保留有效的。

这不是完整的auto-ML，而是一个轻量级的因子搜索：
- 从OHLCV数据出发
- 用预定义模板生成候选表达式
- 用IC快速筛选（IC > 0.03 且 |IC| 一致性 > 60%）
- 通过筛选的表达式自动注册为因子

参考: qlib.contrib.data.handler中Alpha158因子的构造方法
"""

import numpy as np
import pandas as pd
from loguru import logger
from typing import List, Tuple, Callable


# 基础算子
def ts_mean(x: pd.Series, window: int = 5) -> pd.Series:
    return x.rolling(window).mean()

def ts_std(x: pd.Series, window: int = 5) -> pd.Series:
    return x.rolling(window).std()

def ts_rank(x: pd.Series, window: int = 5) -> pd.Series:
    return x.rolling(window).rank(pct=True)

def ts_delta(x: pd.Series, window: int = 1) -> pd.Series:
    return x - x.shift(window)

def ts_returns(x: pd.Series, window: int = 1) -> pd.Series:
    return x.pct_change(window)

def rank(x: pd.Series) -> pd.Series:
    return x.rank(pct=True)


# 表达式模板: (template_name, lambda)
TEMPLATES = [
    # 趋势类
    ("ts_delta_rank_close_5", lambda df: rank(ts_delta(df["close"], 5))),
    ("ts_delta_rank_close_10", lambda df: rank(ts_delta(df["close"], 10))),
    ("close_div_ts_mean_5", lambda df: rank(df["close"] / ts_mean(df["close"], 5))),
    ("close_div_ts_mean_10", lambda df: rank(df["close"] / ts_mean(df["close"], 10))),
    
    # 波动率类
    ("vol_ratio_5_20", lambda df: rank(ts_std(df["close"], 5) / ts_std(df["close"], 20).replace(0, np.nan))),
    ("ts_std_returns_5", lambda df: rank(ts_std(ts_returns(df["close"]), 5))),
    
    # 量价类
    ("vol_change_rank", lambda df: rank(ts_delta(df["volume"], 5))),
    ("vol_price_corr_10", lambda df: rank(df["close"].rolling(10).corr(df["volume"]))),
    ("close_div_vwap_5", lambda df: rank(df["close"] / (ts_mean(df["close"] * df["volume"], 5) / ts_mean(df["volume"], 5).replace(0, np.nan)).replace(0, np.nan))),
    
    # 动量反转
    ("momentum_5_20", lambda df: rank(ts_returns(df["close"], 5) - ts_returns(df["close"], 20))),
    ("high_low_ratio_5", lambda df: rank(ts_mean(df["high"] - df["low"], 5) / df["close"].replace(0, np.nan))),
    
    # 新增: RSI-like
    ("up_ratio_10", lambda df: rank((df["close"].diff() > 0).rolling(10).mean())),
    
    # 新增: intraday range
    ("intraday_range", lambda df: rank((df["high"] - df["low"]) / df["open"].replace(0, np.nan))),
    
    # 新增: volume price divergence
    ("vol_price_div_5", lambda df: rank(ts_delta(df["volume"], 5)) * rank(-ts_delta(df["close"], 5))),
]


class ExpressionFactorGenerator:
    """表达式因子生成器"""

    def __init__(self, ic_threshold: float = 0.03, consistency_threshold: float = 0.6):
        self.ic_threshold = ic_threshold
        self.consistency_threshold = consistency_threshold
        self.discovered_factors = {}  # {name: template_func}

    def scan_factors(self, daily_df: pd.DataFrame, 
                     forward_returns: pd.Series = None,
                     min_stocks: int = 50) -> List[Tuple[str, float, float]]:
        """扫描所有模板，返回通过IC筛选的因子

        Args:
            daily_df: 日线数据 (columns: code, date, open, high, low, close, volume)
            forward_returns: 前瞻收益率 (用于IC计算)
            min_stocks: 最少需要的股票数

        Returns:
            [(name, ic_mean, ic_consistency)] 通过筛选的因子列表
        """
        if forward_returns is None:
            logger.warning("[ExprGen] 无前瞻收益率，跳过IC计算")
            return []

        results = []

        for name, template_func in TEMPLATES:
            if name in self.discovered_factors:
                continue  # 已经发现过了

            try:
                # 按日期分组计算
                ic_values = []
                for date, group in daily_df.groupby("date"):
                    if len(group) < min_stocks:
                        continue
                    try:
                        factor_values = template_func(group)
                        if factor_values is None or factor_values.std() == 0:
                            continue
                        
                        # 获取对应日期的前瞻收益
                        fr = forward_returns.get(date)
                        if fr is None:
                            continue
                        
                        # 计算rank IC (Spearman)
                        common_idx = factor_values.dropna().index.intersection(fr.dropna().index)
                        if len(common_idx) < min_stocks:
                            continue
                        
                        ic = factor_values[common_idx].corr(fr[common_idx], method="spearman")
                        if not np.isnan(ic):
                            ic_values.append(ic)
                    except Exception:
                        continue

                if len(ic_values) < 10:
                    continue

                ic_mean = np.mean(ic_values)
                ic_consistency = np.mean(np.array(ic_values) > 0) if ic_mean > 0 else np.mean(np.array(ic_values) < 0)

                if abs(ic_mean) > self.ic_threshold and ic_consistency > self.consistency_threshold:
                    results.append((name, ic_mean, ic_consistency))
                    self.discovered_factors[name] = template_func
                    logger.info(
                        f"[ExprGen] 发现有效因子: {name}, "
                        f"IC={ic_mean:.4f}, 一致性={ic_consistency:.1%}"
                    )

            except Exception as e:
                logger.debug(f"[ExprGen] 模板 {name} 计算失败: {e}")

        return results

    def get_factor_func(self, name: str) -> Callable:
        """获取已发现因子的函数"""
        return self.discovered_factors.get(name)

    def get_all_discovered(self) -> dict:
        """获取所有已发现的因子"""
        return dict(self.discovered_factors)
