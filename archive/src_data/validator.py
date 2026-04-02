"""数据质量校验模块"""

import pandas as pd
from loguru import logger


class DataQualityError(Exception):
    """数据质量异常"""
    pass


def validate_quote(df: pd.DataFrame):
    """行情数据校验

    Raises:
        DataQualityError: 数据质量不达标
    """
    if df is None or df.empty:
        raise DataQualityError("行情数据为空")

    checks = [
        ("非负价格", (df["close"] > 0).all()),
        ("OHLC关系", (df["high"] >= df["low"]).all()),
        ("成交量非负", (df["volume"] >= 0).all()),
        ("无未来数据", df["date"].max() <= pd.Timestamp.now()),
        ("无大量缺失", df.isnull().mean().max() < 0.05),
    ]

    for name, passed in checks:
        if not passed:
            logger.error(f"行情数据校验失败: {name}")
            raise DataQualityError(f"行情校验失败: {name}")

    logger.info(f"行情数据校验通过，共 {len(df)} 条记录")


def validate_financial(df: pd.DataFrame):
    """财务数据校验

    Raises:
        DataQualityError: 数据质量不达标
    """
    if df is None or df.empty:
        logger.warning("财务数据为空，跳过校验")
        return

    checks = [
        ("ROE范围", df["roe"].between(-100, 100).all() if "roe" in df.columns else True),
        ("负债率范围", df["debt_ratio"].between(0, 100).all() if "debt_ratio" in df.columns else True),
        ("毛利率范围", df["gross_margin"].between(-100, 100).all() if "gross_margin" in df.columns else True),
        ("无重复记录", not df.duplicated(subset=["code", "end_date"]).any()),
    ]

    for name, passed in checks:
        if not passed:
            logger.error(f"财务数据校验失败: {name}")
            raise DataQualityError(f"财务校验失败: {name}")

    logger.info(f"财务数据校验通过，共 {len(df)} 条记录")


def validate_northbound(df: pd.DataFrame):
    """北向资金数据校验"""
    if df is None or df.empty:
        logger.warning("北向资金数据为空")
        return

    checks = [
        ("非负买入", (df["buy_amount"] >= 0).all() if "buy_amount" in df.columns else True),
        ("非负卖出", (df["sell_amount"] >= 0).all() if "sell_amount" in df.columns else True),
    ]

    for name, passed in checks:
        if not passed:
            logger.error(f"北向资金校验失败: {name}")
            raise DataQualityError(f"北向资金校验失败: {name}")

    logger.info(f"北向资金校验通过，共 {len(df)} 条记录")


def validate_market_sentiment(df: pd.DataFrame):
    """大盘情绪数据校验"""
    if df is None or df.empty:
        logger.warning("大盘情绪数据为空")
        return

    checks = [
        ("涨跌家数非负", (df["up_count"] >= 0).all() and (df["down_count"] >= 0).all()),
        ("AD比率范围", df["ad_ratio"].between(0, 1).all()),
    ]

    for name, passed in checks:
        if not passed:
            logger.error(f"大盘情绪校验失败: {name}")
            raise DataQualityError(f"大盘情绪校验失败: {name}")

    logger.info(f"大盘情绪校验通过")


def validate_incremental(df: pd.DataFrame, table_name: str,
                         existing_dates: pd.Series) -> int:
    """增量数据校验 - 检查新数据与已有数据的连续性

    Args:
        df: 新增数据
        table_name: 表名
        existing_dates: 已有数据的日期范围

    Returns:
        新增记录数
    """
    if df is None or df.empty:
        logger.info(f"{table_name}: 无新数据")
        return 0

    new_count = len(df)
    logger.info(f"{table_name}: 新增 {new_count} 条记录")
    return new_count
