"""市场情绪因子 - 纯函数

换手率异常、涨停统计、高低点位置、量比等情绪类指标。
"""

import pandas as pd
import numpy as np


def calc_turnover_anomaly(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """换手率异常度

    当日换手率 / 20日均值换手率
    >2 = 异常放量，可能有重大事件

    Args:
        daily_df: 日线行情DataFrame，需含 turnover 列
        period: 基准周期

    Returns:
        Series, index=code, value=异常度倍数
    """
    def anomaly(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        recent = group["turnover"].iloc[-1]
        base = group["turnover"].iloc[-period:].mean()
        if base == 0:
            return np.nan
        return recent / base

    return daily_df.groupby("code").apply(anomaly)


def calc_limit_up_count(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """近N日涨停次数

    涨幅 >= 9.8% 记为涨停（考虑误差）

    Args:
        daily_df: 日线行情DataFrame，需含 change_pct 列
        period: 回看天数

    Returns:
        Series, index=code, value=涨停次数
    """
    def limit_up(group):
        if len(group) < period:
            group = group.sort_values("date")
        else:
            group = group.sort_values("date").tail(period)
        return (group["change_pct"] >= 9.8).sum()

    return daily_df.groupby("code").apply(limit_up)


def calc_high_low_position(daily_df: pd.DataFrame, period: int = 60) -> pd.Series:
    """距N日高低点位置

    (当前价 - N日最低) / (N日最高 - N日最低) * 100
    0 = 在底部，100 = 在顶部

    Args:
        daily_df: 日线行情DataFrame
        period: 回看天数

    Returns:
        Series, index=code, value=位置(0-100)
    """
    def position(group):
        if len(group) < period:
            group = group.sort_values("date")
        else:
            group = group.sort_values("date").tail(period)
        high = group["high"].max()
        low = group["low"].min()
        current = group["close"].iloc[-1]
        if high == low:
            return 50.0
        return (current - low) / (high - low) * 100

    return daily_df.groupby("code").apply(position)


def calc_volume_ratio(daily_df: pd.DataFrame, short_period: int = 5, long_period: int = 20) -> pd.Series:
    """量比 - 短期均量/长期均量

    >1.5 = 放量，<0.8 = 缩量

    Args:
        daily_df: 日线行情DataFrame，需含 volume 列
        short_period: 短期周期
        long_period: 长期周期

    Returns:
        Series, index=code, value=量比
    """
    def vratio(group):
        if len(group) < long_period:
            return np.nan
        group = group.sort_values("date")
        short_avg = group["volume"].tail(short_period).mean()
        long_avg = group["volume"].tail(long_period).mean()
        if long_avg == 0:
            return np.nan
        return short_avg / long_avg

    return daily_df.groupby("code").apply(vratio)
