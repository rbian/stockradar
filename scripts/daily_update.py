#!/usr/bin/env python3
"""每日增量更新脚本

每日盘后15:30自动执行：
1. 拉取当日日线行情
2. 拉取当日北向资金
3. 更新大盘情绪
4. 更新停复牌信息
5. 检查新财报
6. 执行全市场评分
7. 运行连续评分策略

Usage:
    python scripts/daily_update.py
    python scripts/daily_update.py --date 2026-03-28
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.infra.config import get_settings
from src.infra.logger import setup_logger
from src.data import fetcher
from src.data.validator import validate_quote, validate_financial
from src.data.store import DataStore
from src.factors.engine import FactorEngine
from src.factors.filter import hard_filter
from src.strategy.continuous_score import ContinuousScoreStrategy

setup_logger()


def main():
    parser = argparse.ArgumentParser(description="每日增量更新")
    parser.add_argument("--date", type=str, default=None, help="指定日期 YYYY-MM-DD")
    parser.add_argument("--skip-scoring", action="store_true", help="跳过评分")
    parser.add_argument("--skip-strategy", action="store_true", help="跳过策略")
    args = parser.parse_args()

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    logger.info(f"========== 每日更新开始: {target_date} ==========")

    settings = get_settings()
    store = DataStore()
    validator = DataValidator()
    engine = FactorEngine()

    try:
        # 1. 拉取股票列表（如有更新）
        stock_list = fetcher.fetch_stock_list()
        if stock_list is not None and not stock_list.empty:
            store.upsert_df("stock_info", stock_list, ["code"])
            logger.info(f"股票列表更新: {len(stock_list)} 只")

        # 2. 行业分类
        industry = fetcher.fetch_industry_classification()
        if industry is not None and not industry.empty:
            store.upsert_df("sw_industry", industry, ["code"])
            logger.info(f"行业分类更新: {len(industry)} 只")

        # 3. 当日全市场行情
        quotes = fetcher.fetch_daily_quote_batch(
            symbols=None,  # 全市场
            start_date=target_date.replace("-", ""),
            end_date=target_date.replace("-", ""),
        )
        if quotes is not None and not quotes.empty:
            validate_quote(quotes)
            store.upsert_df("daily_quote", quotes, ["code", "date"])
            logger.info(f"行情更新: {len(quotes)} 条")

        # 4. 北向资金
        nb_stock = fetcher.fetch_northbound_stock(target_date.replace("-", ""))
        if nb_stock is not None and not nb_stock.empty:
            store.upsert_df("northbound_stock", nb_stock, ["code", "date"])
            logger.info(f"北向个股: {len(nb_stock)} 条")

        nb_daily = fetcher.fetch_northbound_daily(
            start_date=target_date.replace("-", ""),
            end_date=target_date.replace("-", ""),
        )
        if nb_daily is not None and not nb_daily.empty:
            store.upsert_df("northbound_daily", nb_daily, ["date"])
            logger.info(f"北向汇总: {len(nb_daily)} 条")

        # 5. 大盘指数
        for idx_code in ["000300", "000905", "000852"]:
            idx_data = fetcher.fetch_market_index(
                idx_code,
                start_date=target_date.replace("-", ""),
                end_date=target_date.replace("-", ""),
            )
            if idx_data is not None and not idx_data.empty:
                store.upsert_df("market_index_daily", idx_data, ["index_code", "date"])

        # 6. 财务数据（月初或季报期才拉）
        day = int(target_date.split("-")[2])
        month = int(target_date.split("-")[1])
        if day <= 5 or month in [1, 4, 7, 10]:
            fin = fetcher.fetch_financial_indicator()
            if fin is not None and not fin.empty:
                store.upsert_df("financial_indicator", fin, ["code", "end_date"])
                logger.info(f"财务数据更新: {len(fin)} 条")

        # 7. 全市场评分
        if not args.skip_scoring:
            logger.info("开始全市场评分...")
            # 获取评分所需数据
            stock_info = store.get_table("stock_info")
            daily_quote = store.get_table("daily_quote")
            financial = store.get_table("financial_indicator")
            northbound = store.get_table("northbound_stock")

            if stock_info is not None and not stock_info.empty:
                # 硬筛选
                valid_codes = hard_filter(stock_info, daily_quote, financial, target_date)
                logger.info(f"硬筛选后有效股票: {len(valid_codes)} 只")

                data = {
                    "daily_quote": daily_quote,
                    "financial": financial,
                    "stock_info": stock_info,
                    "northbound": northbound,
                    "codes": sorted(valid_codes),
                }

                scores = engine.score_all(data, target_date)

                # 计算动量
                prev_scores = store.get_table(
                    "daily_score",
                    where=f"date < '{target_date}' ORDER BY date DESC LIMIT 1",
                )
                if prev_scores is not None and not prev_scores.empty:
                    scores = engine.calc_delta(scores, prev_scores)

                # 保存评分
                scores["date"] = target_date
                store.upsert_df("daily_score", scores.reset_index(), ["code", "date"])
                logger.info(f"评分完成, Top5: {scores.head(5).index.tolist()}")

                # 8. 策略评估
                if not args.skip_strategy:
                    strategy = ContinuousScoreStrategy(engine=engine)
                    portfolio_codes = store.get_table("portfolio")
                    current = (
                        portfolio_codes["code"].tolist()
                        if portfolio_codes is not None and not portfolio_codes.empty
                        else []
                    )

                    result = strategy.daily_evaluate(
                        data=data,
                        date=target_date,
                        current_portfolio=current,
                    )

                    actions = result.get("actions", [])
                    if actions:
                        logger.info(f"生成 {len(actions)} 条操作建议")
                        for a in actions:
                            logger.info(f"  {a['action'].upper()} {a['code']}: {a.get('reason', '')}")

        logger.info(f"========== 每日更新完成: {target_date} ==========")

    except Exception as e:
        logger.error(f"每日更新失败: {e}", exc_info=True)
        sys.exit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
