"""首次历史数据下载脚本

初始化全量历史数据，默认下载最近10年：
1. 股票列表（基础信息）
2. 全市场日线行情
3. 大盘指数（沪深300、上证指数）
4. 行业指数
5. 北向资金（汇总+个股）
6. 大盘情绪
7. 财务指标（需Tushare Pro Token）

用法:
    python -m scripts.init_data                        # 默认下载10年
    python -m scripts.init_data --lookback-years 5     # 下载5年数据
    python -m scripts.init_data --symbols-only         # 仅下载股票列表
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger

from src.infra.config import get_settings, PROJECT_ROOT as _ROOT
from src.infra.logger import setup_logger
from src.data.fetcher import (
    fetch_stock_list,
    fetch_daily_quote_batch,
    fetch_market_index,
    fetch_industry_index,
    fetch_northbound_daily,
    fetch_northbound_stock,
    fetch_market_sentiment,
    fetch_suspension,
    fetch_financial_indicator,
    DataFetchError,
)
from src.data.store import DataStore
from src.data.validator import (
    validate_quote,
    validate_financial,
    validate_northbound,
    validate_market_sentiment,
)


def parse_args():
    parser = argparse.ArgumentParser(description="A股智能盯盘Agent - 首次数据初始化")
    parser.add_argument(
        "--lookback-years", type=int, default=10,
        help="下载最近N年数据（默认10）",
    )
    parser.add_argument(
        "--symbols-only", action="store_true",
        help="仅下载股票列表",
    )
    parser.add_argument(
        "--skip-quote", action="store_true",
        help="跳过日线行情下载（耗时最长）",
    )
    parser.add_argument(
        "--batch-size", type=int, default=50,
        help="每批下载股票数（默认50）",
    )
    return parser.parse_args()


def download_stock_list(store: DataStore) -> list:
    """下载股票列表并保存"""
    logger.info("====== 下载股票列表 ======")
    df = fetch_stock_list()
    if df.empty:
        logger.error("股票列表下载失败")
        return []

    # 构建基础 stock_info（后续可补充行业分类等）
    stock_info = df.copy()
    stock_info["sw_l1"] = ""
    stock_info["sw_l2"] = ""
    stock_info["sw_l3"] = ""
    stock_info["sector"] = ""
    stock_info["list_date"] = pd.NaT
    stock_info["is_st"] = stock_info["name"].str.contains("ST", na=False)

    store.upsert_df("stock_info", stock_info, pk_cols=["code"])
    codes = df["code"].tolist()
    logger.info(f"股票列表: {len(codes)} 只")
    return codes


def download_daily_quotes(store: DataStore, codes: list,
                          start_date: str, end_date: str,
                          batch_size: int = 50):
    """分批下载全市场日线行情"""
    logger.info(f"====== 下载日线行情 ({len(codes)} 只) ======")
    total = len(codes)
    success_count = 0
    fail_count = 0

    for i in range(0, total, batch_size):
        batch = codes[i:i + batch_size]
        logger.info(f"行情进度: {i+1}-{min(i+batch_size, total)}/{total}")

        try:
            df = fetch_daily_quote_batch(batch, start_date, end_date)
            if not df.empty:
                validate_quote(df)
                # 按年拆分保存
                for year, group in df.groupby(df["date"].dt.year):
                    store.upsert_df("daily_quote", group, pk_cols=["code", "date"])
                success_count += len(batch)
            else:
                fail_count += len(batch)
        except Exception as e:
            logger.error(f"行情批次 {i//batch_size+1} 失败: {e}")
            fail_count += len(batch)

        # 控制请求频率
        time.sleep(2)

    logger.info(f"行情下载完成: 成功{success_count}只, 失败{fail_count}只")


def download_market_indices(store: DataStore, start_date: str, end_date: str):
    """下载大盘指数"""
    logger.info("====== 下载大盘指数 ======")
    indices = {
        "000300": "沪深300",
        "000001": "上证指数",
        "399006": "创业板指",
    }

    for symbol, name in indices.items():
        try:
            df = fetch_market_index(symbol, start_date, end_date)
            if not df.empty:
                store.upsert_df("market_index_daily", df, pk_cols=["index_code", "date"])
                logger.info(f"{name}({symbol}): {len(df)} 条")
        except Exception as e:
            logger.warning(f"{name}({symbol}) 下载失败: {e}")
        time.sleep(1)


def download_industry_indices(store: DataStore, start_date: str, end_date: str):
    """下载申万行业指数"""
    logger.info("====== 下载行业指数 ======")
    # 申万一级行业指数代码（部分常用）
    industry_codes = [
        "801010", "801020", "801030", "801040", "801050",  # 农林牧渔, 采掘, 化工, 钢铁, 有色
        "801080", "801110", "801120", "801130", "801140",  # 电子, 家用电器, 食品饮料, 纺织服装, 轻工制造
        "801150", "801160", "801170", "801180", "801200",  # 医药生物, 公用事业, 交通运输, 房地产, 商业贸易
        "801210", "801230", "801710", "801720", "801730",  # 综合, 综合, 建筑材料, 建筑装饰, 电气设备
        "801740", "801750", "801760", "801770", "801780",  # 国防军工, 计算机, 传媒, 通信, 银行
        "801790", "801880", "801890",                      # 非银金融, 汽车, 机械设备
    ]

    success = 0
    for symbol in industry_codes:
        try:
            df = fetch_industry_index(symbol, start_date, end_date)
            if not df.empty:
                store.upsert_df("industry_index_daily", df, pk_cols=["industry_code", "date"])
                success += 1
        except Exception:
            pass
        time.sleep(0.5)

    logger.info(f"行业指数下载完成: {success}/{len(industry_codes)}")


def download_northbound(store: DataStore, start_date: str, end_date: str):
    """下载北向资金数据"""
    logger.info("====== 下载北向资金汇总 ======")
    try:
        df = fetch_northbound_daily(start_date, end_date)
        if not df.empty:
            validate_northbound(df)
            store.upsert_df("northbound_daily", df, pk_cols=["date"])
            logger.info(f"北向资金汇总: {len(df)} 条")
    except Exception as e:
        logger.warning(f"北向资金汇总下载失败: {e}")

    # 北向个股数据（最新一天）
    logger.info("====== 下载北向资金个股 ======")
    try:
        df = fetch_northbound_stock()
        if not df.empty:
            store.upsert_df("northbound_stock", df, pk_cols=["code", "date"])
            logger.info(f"北向个股: {len(df)} 条")
    except Exception as e:
        logger.warning(f"北向个股下载失败: {e}")


def download_market_sentiment(store: DataStore, date: str = None):
    """下载大盘情绪"""
    logger.info("====== 下载大盘情绪 ======")
    try:
        df = fetch_market_sentiment(date)
        if not df.empty:
            validate_market_sentiment(df)
            store.upsert_df("market_sentiment", df, pk_cols=["date"])
            logger.info(f"大盘情绪: {len(df)} 条")
    except Exception as e:
        logger.warning(f"大盘情绪下载失败: {e}")


def download_financials(store: DataStore, tushare_token: str = None):
    """下载财务指标（需要Tushare Pro Token）"""
    logger.info("====== 下载财务指标 ======")
    if not tushare_token:
        logger.warning("未配置 TUSHARE_TOKEN，跳过财务数据下载")
        return

    try:
        # 按季度下载最近几年的财务数据
        now = datetime.now()
        for year_offset in range(4):  # 最近4年
            year = now.year - year_offset
            for quarter_end in [f"{year}0331", f"{year}0630", f"{year}0930", f"{year}1231"]:
                try:
                    start = f"{year}0101"
                    end = quarter_end
                    df = fetch_financial_indicator(
                        start_date=start, end_date=end,
                        tushare_token=tushare_token,
                    )
                    if not df.empty:
                        validate_financial(df)
                        store.upsert_df("financial_indicator", df, pk_cols=["code", "end_date"])
                        logger.info(f"财务数据 {quarter_end}: {len(df)} 条")
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"财务数据 {quarter_end} 失败: {e}")
    except Exception as e:
        logger.error(f"财务数据下载失败: {e}")


def main():
    args = parse_args()
    setup_logger()

    logger.info("=" * 60)
    logger.info("A股智能盯盘Agent - 首次数据初始化")
    logger.info(f"回溯年数: {args.lookback_years}")
    logger.info("=" * 60)

    # 计算日期范围
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=args.lookback_years * 365)).strftime("%Y%m%d")

    settings = get_settings()
    tushare_token = settings.get("tushare", {}).get("token", "")

    # 初始化存储
    store = DataStore()

    try:
        # 1. 股票列表
        codes = download_stock_list(store)
        if not codes:
            logger.error("股票列表下载失败，无法继续")
            sys.exit(1)

        if args.symbols_only:
            logger.info("--symbols-only 模式，仅下载股票列表")
            store.close()
            return

        # 2. 日线行情
        if not args.skip_quote:
            download_daily_quotes(store, codes, start_date, end_date, args.batch_size)
        else:
            logger.info("--skip-quote 跳过日线行情下载")

        # 3. 大盘指数
        download_market_indices(store, start_date, end_date)

        # 4. 行业指数
        download_industry_indices(store, start_date, end_date)

        # 5. 北向资金
        download_northbound(store, start_date, end_date)

        # 6. 大盘情绪
        download_market_sentiment(store)

        # 7. 财务指标
        download_financials(store, tushare_token)

        # 8. 归档历史数据到 Parquet
        logger.info("====== 归档历史数据到Parquet ======")
        current_year = datetime.now().year
        for year in range(current_year - args.lookback_years, current_year):
            try:
                store.archive_to_parquet("daily_quote", year)
            except Exception as e:
                logger.warning(f"归档 {year} 年行情数据失败: {e}")

        logger.info("=" * 60)
        logger.info("数据初始化完成！")
        logger.info(f"DuckDB: {store.db_path}")
        logger.info(f"Parquet: {store.parquet_dir}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.warning("用户中断")
    except Exception as e:
        logger.error(f"初始化失败: {e}")
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
