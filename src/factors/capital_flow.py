"""资金面因子 - 纯函数"""

import pandas as pd
import numpy as np


def calc_northbound_net(daily_quote_df: pd.DataFrame,
                        northbound_df: pd.DataFrame,
                        period: int = 5) -> pd.Series:
    """北向资金N日净买入

    Args:
        daily_quote_df: 日线行情（用于获取全部股票代码）
        northbound_df: 北向资金个股数据
        period: 回看天数

    Returns:
        Series, index=code, value=净买入金额
    """
    if northbound_df is None or northbound_df.empty:
        codes = daily_quote_df["code"].unique()
        return pd.Series(0.0, index=codes)

    def net_sum(group):
        recent = group.sort_values("date").tail(period)
        return recent["net_amount"].sum()

    result = northbound_df.groupby("code").apply(net_sum)
    # 填充没有北向数据的股票为0
    all_codes = daily_quote_df["code"].unique()
    result = result.reindex(all_codes, fill_value=0.0)
    return result


def calc_northbound_consecutive(northbound_df: pd.DataFrame) -> pd.Series:
    """北向连续买入天数（负数=连续卖出）

    从最近一天往前数连续同符号天数

    Args:
        northbound_df: 北向资金个股数据

    Returns:
        Series, index=code, value=连续天数（正=连续买入，负=连续卖出）
    """
    if northbound_df is None or northbound_df.empty:
        return pd.Series(dtype=float)

    def consecutive(group):
        recent = group.sort_values("date").tail(20)
        if len(recent) < 2:
            return 0

        signs = np.sign(recent["net_amount"].values)
        last_sign = signs[-1]
        count = 0
        for s in reversed(signs):
            if s == last_sign:
                count += 1
            else:
                break
        return count * int(last_sign)

    return northbound_df.groupby("code").apply(consecutive)


def calc_main_force_net_1d(daily_quote_df: pd.DataFrame,
                           period: int = 1) -> pd.Series:
    """主力资金单日净流入（代理指标：大单净额）

    由于AKShare大单数据获取较慢，这里用成交额*涨跌幅作为代理：
    正向涨跌+放量 ≈ 主力买入

    Args:
        daily_quote_df: 日线行情

    Returns:
        Series, index=code, value=代理主力净流入
    """
    if daily_quote_df is None or daily_quote_df.empty:
        return pd.Series(dtype=float)

    def main_force(group):
        recent = group.sort_values("date").tail(period)
        if recent.empty:
            return 0.0
        # 简化代理：amount * change_pct / 100
        return (recent["amount"] * recent["change_pct"] / 100).sum()

    return daily_quote_df.groupby("code").apply(main_force)


def calc_main_force_net_5d(daily_quote_df: pd.DataFrame,
                           period: int = 5) -> pd.Series:
    """主力资金5日累计净流入（代理指标）"""
    return calc_main_force_net_1d(daily_quote_df, period=period)


def calc_margin_balance_change(daily_quote_df: pd.DataFrame,
                               period: int = 5) -> pd.Series:
    """融资余额变化（代理指标）

    使用成交量变化趋势作为融资余额变化的代理

    Args:
        daily_quote_df: 日线行情

    Returns:
        Series, index=code, value=代理融资余额变化
    """
    if daily_quote_df is None or daily_quote_df.empty:
        return pd.Series(dtype=float)

    def margin_change(group):
        if len(group) < period + 5:
            return 0.0
        recent = group.sort_values("date")
        vol_current = recent["volume"].tail(period).mean()
        vol_prev = recent["volume"].iloc[-(period + 5):-period].mean()
        if vol_prev == 0:
            return 0.0
        return (vol_current / vol_prev - 1) * 100

    return daily_quote_df.groupby("code").apply(margin_change)
