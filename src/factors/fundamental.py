"""基本面因子 - 纯函数，无类继承，简单直接

每个因子一个纯函数，输入DataFrame，输出Series(code -> value)
"""

import pandas as pd
import numpy as np


def calc_roe(financial_df: pd.DataFrame) -> pd.Series:
    """ROE因子 - 净资产收益率

    Args:
        financial_df: 财务指标DataFrame，需包含 code, end_date, roe 列

    Returns:
        Series, index=code, value=最新ROE
    """
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["roe"]


def calc_pe_percentile(daily_df: pd.DataFrame, lookback: int = 1095) -> pd.Series:
    """PE历史分位因子

    注意：PE = 市值/净利润，这里用价格作为代理（同股本下等价）

    Args:
        daily_df: 日线行情DataFrame
        lookback: 回看天数

    Returns:
        Series, index=code, value=PE分位数(0-100)
    """
    def percentile_rank(group):
        if len(group) < 10:
            return np.nan
        current = group["close"].iloc[-1]
        hist = group["close"].iloc[-lookback:] if len(group) > lookback else group["close"]
        return (hist < current).mean() * 100

    sorted_df = daily_df.sort_values(["code", "date"])
    return sorted_df.groupby("code").apply(percentile_rank)


def calc_revenue_yoy(financial_df: pd.DataFrame) -> pd.Series:
    """营收同比增长率"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["revenue_yoy"]


def calc_profit_yoy(financial_df: pd.DataFrame) -> pd.Series:
    """净利润同比增长率"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["profit_yoy"]


def calc_gross_margin(financial_df: pd.DataFrame) -> pd.Series:
    """毛利率"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["gross_margin"]


def calc_ocf_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """经营现金流/营收比率"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["ocf_ratio"]


def calc_debt_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """资产负债率（direction=lower_better, invert=true）"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["debt_ratio"]


def calc_goodwill_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """商誉占比（direction=lower_better, invert=true）"""
    latest = financial_df.sort_values("end_date").groupby("code").last()
    return latest["goodwill_ratio"]


def calc_peg(daily_df: pd.DataFrame, financial_df: pd.DataFrame) -> pd.Series:
    """PEG因子 - PE/盈利增速

    PE越低、增速越高 → PEG越小 → 越被低估
    取倒数使方向为 higher_better

    Args:
        daily_df: 日线行情（用pe列，如果有的话）
        financial_df: 财务指标

    Returns:
        Series, index=code, value=PEG倒数（越大越好）
    """
    latest_fin = financial_df.sort_values("end_date").groupby("code").last()
    latest_daily = daily_df.sort_values("date").groupby("code").last()

    profit_yoy = latest_fin["profit_yoy"]
    pe = latest_daily.get("pe", latest_daily.get("pe_ttm"))

    if pe is None:
        return pd.Series(np.nan, index=latest_fin.index)

    # PEG = PE / profit_yoy
    # 盈利增速为正且PE为正时有效
    valid = (profit_yoy > 0) & (pe > 0) & (pe < 200)
    peg = pd.Series(np.nan, index=latest_fin.index)
    peg[valid] = profit_yoy[valid] / pe[valid]

    # 超高PEG截尾，避免极端值
    peg = peg.clip(-20, 20)
    return peg


def calc_operating_leverage(financial_df: pd.DataFrame) -> pd.Series:
    """经营杠杆 - 营收增速/利润增速

    >1 说明利润弹性大于收入弹性（正面信号）
    <1 说明利润增速低于收入增速（成本扩张）

    Args:
        financial_df: 财务指标

    Returns:
        Series, index=code, value=经营杠杆
    """
    latest = financial_df.sort_values("end_date").groupby("code").last()
    rev = latest["revenue_yoy"]
    profit = latest["profit_yoy"]

    result = pd.Series(np.nan, index=latest.index)
    valid = (profit != 0) & (profit.notna()) & (rev.notna())
    result[valid] = rev[valid] / profit[valid]
    result = result.clip(-10, 10)
    return result


def calc_inventory_turnover(financial_df: pd.DataFrame) -> pd.Series:
    """存货周转率

    营业成本 / 平均存货
    周转率越高说明运营效率越高

    Args:
        financial_df: 财务指标

    Returns:
        Series, index=code, value=存货周转率
    """
    latest = financial_df.sort_values("end_date").groupby("code").last()
    if "inventory_turnover" in latest.columns:
        return latest["inventory_turnover"]
    # 如果没有直接字段，用 revenue / inventory 近似
    if "total_assets" in latest.columns and "total_assets" != 0:
        inv = latest.get("inventory", pd.Series(np.nan, index=latest.index))
        cost = latest.get("operating_cost", latest.get("cogs", latest.get("revenue")))
        result = pd.Series(np.nan, index=latest.index)
        valid = (inv > 0) & (cost.notna())
        result[valid] = cost[valid] / inv[valid]
        return result.clip(0, 100)
    return pd.Series(np.nan, index=latest.index)


def calc_accrual_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """应计项目比率 - 盈利质量指标

    (净利润 - 经营现金流) / 总资产
    高值 = 利润主要靠应计项目（应收/存货），盈利质量差

    Args:
        financial_df: 财务指标

    Returns:
        Series, index=code, value=应计项目比率（方向：lower_better）
    """
    latest = financial_df.sort_values("end_date").groupby("code").last()
    net_profit = latest.get("net_profit", latest.get("profit_yoy"))
    ocf = latest.get("ocf", pd.Series(np.nan, index=latest.index))
    total_assets = latest.get("total_assets", pd.Series(np.nan, index=latest.index))

    result = pd.Series(np.nan, index=latest.index)
    valid = (net_profit.notna()) & (ocf.notna()) & (total_assets.notna()) & (total_assets > 0)
    result[valid] = (net_profit[valid] - ocf[valid]) / total_assets[valid]
    return result.clip(-1, 1)


