"""每日数据更新 — 混合策略

1. BaoStock: 免费，拉历史数据（全量）
2. QVeris: 补充今天最新数据（只拉10只关键股）

每天credits消耗: 30 (指数10 + 3只×10 = 40)
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger
from src.infra.logger import setup_logger

# 加载.env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_hs300_codes() -> list:
    """获取沪深300成分股"""
    codes_file = PROJECT_ROOT / "data" / "hs300_codes.txt"
    if codes_file.exists():
        return codes_file.read_text().strip().split("\n")
    
    import baostock as bs
    bs.login()
    rs = bs.query_hs300_stocks()
    codes = []
    while rs.error_code == "0" and rs.next():
        row = rs.get_row_data()
        codes.append(row[1].replace("sh.", "").replace("sz.", ""))
    bs.logout()
    codes_file.parent.mkdir(parents=True, exist_ok=True)
    codes_file.write_text("\n".join(codes))
    return codes


def update_bs_cache(codes: list, start_date: str = "20200101"):
    """BaoStock拉历史行情（免费）"""
    from src.data.baostock_adapter import fetch_daily_quote_batch_bs
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    
    logger.info(f"BaoStock拉取{len(codes)}只历史行情...")
    quote = fetch_daily_quote_batch_bs(codes, start_date, today, delay=0.05)
    
    if not quote.empty:
        out_dir = PROJECT_ROOT / "data" / "parquet"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "hs300_daily.parquet"
        
        # 合并已有
        if out_file.exists():
            old = pd.read_parquet(out_file)
            combined = pd.concat([old, quote], ignore_index=True)
            combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
        else:
            combined = quote
        
        combined = combined.sort_values(["code", "date"])
        combined.to_parquet(out_file, index=False)
        logger.info(f"BaoStock: {len(codes)}只, {len(combined)}条 → {out_file}")
        return combined
    return pd.DataFrame()


def qveris_topup(codes: list = None):
    """QVeris补最新数据（关键股）"""
    if codes is None:
        codes = ["600519", "000333", "601318", "600036", "000858"]
    
    from src.data.qveris_adapter import fetch_daily_quote_qv, fetch_index_quote_qv
    
    # 指数
    logger.info("QVeris补指数...")
    idx = fetch_index_quote_qv("000300")
    if idx and idx.get("最新(点)", "") not in ("", "---"):
        logger.info(f"沪深300: {idx.get('最新(点)')} ({idx.get('涨跌幅(%)')}%)")
    
    # 关键股
    logger.info(f"QVeris补{len(codes)}只行情...")
    df = fetch_daily_quote_qv(codes, delay=0.8)
    if not df.empty:
        logger.info(f"QVeris: {len(df)}条, {df['code'].nunique()}只")
        
        # 合并到parquet
        out_file = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
        if out_file.exists():
            old = pd.read_parquet(out_file)
            combined = pd.concat([old, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
            combined.to_parquet(out_file, index=False)
            logger.info(f"合并后: {len(combined)}条")
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=0, help="只拉前N只")
    parser.add_argument("--qveris-only", action="store_true", help="只用QVeris")
    parser.add_argument("--start", default="20200101", help="起始日期")
    args = parser.parse_args()
    
    setup_logger()
    
    codes = get_hs300_codes()
    if args.top:
        codes = codes[:args.top]
    logger.info(f"沪深300: {len(codes)}只")
    
    if not args.qveris_only:
        update_bs_cache(codes, args.start)
    
    # QVeris补最新
    qveris_codes = ["600519", "000333", "601318", "600036", "000858",
                    "600276", "601127", "600030", "601166", "600887"]
    qveris_topup(qveris_codes)
    
    logger.info("✅ 数据更新完成")


if __name__ == "__main__":
    main()
