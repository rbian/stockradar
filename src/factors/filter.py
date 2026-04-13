"""硬筛选 - 评分前过滤不合格股票"""

import pandas as pd
from loguru import logger


def hard_filter(stock_info_df: pd.DataFrame,
                daily_df: pd.DataFrame,
                financial_df: pd.DataFrame,
                date,
                min_avg_amount: float = 5e7,
                max_debt_ratio: float = 80.0,
                max_goodwill_ratio: float = 30.0,
                min_list_days: int = 365) -> set:
    """在评分之前排除不合格股票，返回有效代码集合

    Args:
        stock_info_df: 股票基础信息
        daily_df: 日线行情
        financial_df: 财务指标
        date: 当前日期
        min_avg_amount: 最低20日均成交额（默认5000万）
        max_debt_ratio: 最大资产负债率
        max_goodwill_ratio: 最大商誉占比
        min_list_days: 最少上市天数

    Returns:
        有效股票代码集合
    """
    if stock_info_df is None or stock_info_df.empty:
        logger.warning("股票信息为空，无法执行硬筛选")
        return set()

    codes = set(stock_info_df["code"])
    date_ts = pd.Timestamp(date)
    initial_count = len(codes)
    filter_log = []

    # 确保 daily_df 的 date 列为 datetime 类型
    if daily_df is not None and not daily_df.empty and "date" in daily_df.columns:
        daily_df = daily_df.copy()
        daily_df["date"] = pd.to_datetime(daily_df["date"])

    # 1. 排除ST
    if "is_st" in stock_info_df.columns:
        st_codes = set(stock_info_df[stock_info_df["is_st"] == True]["code"])
        codes -= st_codes
        filter_log.append(f"排除ST: {len(st_codes)} 只")

    # 2. 排除上市不满1年
    if "list_date" in stock_info_df.columns:
        one_year_ago = date_ts - pd.Timedelta(days=min_list_days)
        new_codes = set(stock_info_df[
            pd.to_datetime(stock_info_df["list_date"]) > one_year_ago
        ]["code"])
        codes -= new_codes
        filter_log.append(f"排除次新股(<1年): {len(new_codes)} 只")

    # 3. 排除当日停牌（当日无行情数据的股票）
    if daily_df is not None and not daily_df.empty:
        trading_codes = set(daily_df[daily_df["date"] == date_ts]["code"])
        suspended = codes - trading_codes
        codes &= trading_codes
        filter_log.append(f"排除停牌/无数据: {len(suspended)} 只")

    # 4. 排除流动性差（20日均成交额 < 5000万）
    if daily_df is not None and not daily_df.empty:
        cutoff = date_ts - pd.Timedelta(days=30)
        recent = daily_df[daily_df["date"] >= cutoff]
        if not recent.empty and "amount" in recent.columns:
            avg_amount = recent.groupby("code")["amount"].mean()
            liquid_codes = set(avg_amount[avg_amount >= min_avg_amount].index)
            illiquid_count = len(codes - liquid_codes)
            codes &= liquid_codes
            filter_log.append(f"排除流动性差: {illiquid_count} 只")

    # 5. 排除亏损股（最近一期净利润为负）
    if financial_df is not None and not financial_df.empty:
        latest_fin = financial_df.sort_values("end_date").groupby("code").last()
        if "net_profit" in latest_fin.columns:
            loss_codes = set(latest_fin[latest_fin["net_profit"] <= 0].index)
            codes -= loss_codes
            filter_log.append(f"排除亏损股: {len(loss_codes & (codes | loss_codes))} 只")

        # 6. 排除高资产负债率
        if "debt_ratio" in latest_fin.columns:
            high_debt = set(latest_fin[latest_fin["debt_ratio"] > max_debt_ratio].index)
            codes -= high_debt
            filter_log.append(f"排除高负债(>{max_debt_ratio}%): {len(high_debt)} 只")

        # 7. 排除高商誉
        if "goodwill_ratio" in latest_fin.columns:
            high_gw = set(latest_fin[latest_fin["goodwill_ratio"] > max_goodwill_ratio].index)
            codes -= high_gw
            filter_log.append(f"排除高商誉(>{max_goodwill_ratio}%): {len(high_gw)} 只")

    # 8. 排除连续涨停追高风险（近5日涨停≥2次）
    if daily_df is not None and not daily_df.empty:
        recent_cutoff = date_ts - pd.Timedelta(days=7)
        recent = daily_df[(daily_df["date"] >= recent_cutoff) & (daily_df["code"].isin(codes))]
        if not recent.empty and "change_pct" in recent.columns:
            limit_up_counts = recent[recent["change_pct"] >= 9.8].groupby("code").size()
            chase_codes = set(limit_up_counts[limit_up_counts >= 2].index)
            codes -= chase_codes
            if chase_codes:
                filter_log.append(f"排除连续涨停追高: {len(chase_codes)} 只")

    logger.info(
        f"硬筛选: {initial_count} → {len(codes)} 只 "
        f"(排除 {initial_count - len(codes)} 只)"
    )
    for log_msg in filter_log:
        logger.debug(f"  {log_msg}")

    return codes
