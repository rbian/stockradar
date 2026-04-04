"""基本面因子 - 纯函数，无类继承，简单直接

每个因子一个纯函数，输入DataFrame，输出Series(code -> value)
"""

import pandas as pd
import numpy as np


def _latest_financial(financial_df: pd.DataFrame) -> pd.DataFrame:
    """Get latest financial data per stock, with empty guard"""
    if financial_df is None or financial_df.empty or "end_date" not in financial_df.columns:
        return pd.DataFrame()
    return financial_df.sort_values("end_date").groupby("code").last()


def calc_roe(financial_df: pd.DataFrame) -> pd.Series:
    """ROE因子 - 净资产收益率"""
    latest = _latest_financial(financial_df)
    if latest.empty or "roe" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["roe"]


def calc_pe_percentile(daily_df: pd.DataFrame, lookback: int = 1095) -> pd.Series:
    """PE历史分位因子 — 用价格作为代理"""
    if daily_df is None or daily_df.empty:
        return pd.Series(dtype=float)

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
    latest = _latest_financial(financial_df)
    if latest.empty or "revenue_yoy" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["revenue_yoy"]


def calc_profit_yoy(financial_df: pd.DataFrame) -> pd.Series:
    """净利润同比增长率"""
    latest = _latest_financial(financial_df)
    if latest.empty or "profit_yoy" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["profit_yoy"]


def calc_gross_margin(financial_df: pd.DataFrame) -> pd.Series:
    """毛利率"""
    latest = _latest_financial(financial_df)
    if latest.empty or "gross_margin" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["gross_margin"]


def calc_ocf_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """经营现金流/营收比率"""
    latest = _latest_financial(financial_df)
    if latest.empty or "ocf_ratio" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["ocf_ratio"]


def calc_debt_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """资产负债率"""
    latest = _latest_financial(financial_df)
    if latest.empty or "debt_ratio" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["debt_ratio"]


def calc_goodwill_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """商誉占比"""
    latest = _latest_financial(financial_df)
    if latest.empty or "goodwill_ratio" not in latest.columns:
        return pd.Series(dtype=float)
    return latest["goodwill_ratio"]


def calc_peg(daily_df: pd.DataFrame, financial_df: pd.DataFrame) -> pd.Series:
    """PEG因子 - PE/盈利增速，取倒数使方向为 higher_better"""
    latest_fin = _latest_financial(financial_df)
    if latest_fin.empty:
        return pd.Series(dtype=float)
    if daily_df is None or daily_df.empty:
        return pd.Series(dtype=float)

    latest_daily = daily_df.sort_values("date").groupby("code").last()
    profit_yoy = latest_fin["profit_yoy"]
    pe = latest_daily.get("pe", latest_daily.get("pe_ttm"))

    if pe is None:
        return pd.Series(np.nan, index=latest_fin.index)

    valid = (profit_yoy > 0) & (pe > 0) & (pe < 200)
    peg = pd.Series(np.nan, index=latest_fin.index)
    peg[valid] = profit_yoy[valid] / pe[valid]
    return peg.clip(-20, 20)


def calc_operating_leverage(financial_df: pd.DataFrame) -> pd.Series:
    """经营杠杆 - 营收增速/利润增速"""
    latest = _latest_financial(financial_df)
    if latest.empty:
        return pd.Series(dtype=float)
    rev = latest.get("revenue_yoy", pd.Series(np.nan, index=latest.index))
    profit = latest.get("profit_yoy", pd.Series(np.nan, index=latest.index))
    valid = (profit != 0) & profit.notna() & rev.notna()
    result = pd.Series(np.nan, index=latest.index)
    result[valid] = rev[valid] / profit[valid]
    return result.clip(-10, 10)


def calc_inventory_turnover(financial_df: pd.DataFrame) -> pd.Series:
    """存货周转率"""
    latest = _latest_financial(financial_df)
    if latest.empty:
        return pd.Series(dtype=float)
    if "inventory_turnover" in latest.columns:
        return latest["inventory_turnover"]
    return pd.Series(np.nan, index=latest.index)


def calc_accrual_ratio(financial_df: pd.DataFrame) -> pd.Series:
    """应计项目比率 - 盈利质量指标"""
    latest = _latest_financial(financial_df)
    if latest.empty:
        return pd.Series(dtype=float)
    net_profit = latest.get("net_profit", pd.Series(np.nan, index=latest.index))
    ocf = latest.get("ocf", pd.Series(np.nan, index=latest.index))
    total_assets = latest.get("total_assets", pd.Series(np.nan, index=latest.index))
    valid = net_profit.notna() & ocf.notna() & total_assets.notna() & (total_assets > 0)
    result = pd.Series(np.nan, index=latest.index)
    result[valid] = (net_profit[valid] - ocf[valid]) / total_assets[valid]
    return result.clip(-1, 1)
