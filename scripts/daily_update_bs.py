"""BaoStock每日数据更新 — 免费，无credits限制

每天收盘后拉取沪深300最新行情，补入parquet
"""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import baostock as bs
from loguru import logger
from src.infra.logger import setup_logger


def daily_update_bs():
    """用BaoStock拉取最新数据"""
    parquet_path = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
    if not parquet_path.exists():
        logger.warning("无hs300_daily.parquet")
        return
    
    old = pd.read_parquet(parquet_path)
    latest = str(old["date"].max())[:10]
    logger.info(f"当前最新: {latest}")
    
    # 读取hs300成分股
    codes_file = PROJECT_ROOT / "data" / "hs300_codes.txt"
    codes = [l.strip() for l in codes_file.read_text().splitlines() if l.strip()]
    
    # 从最新日期+1开始拉
    bs.login()
    
    rows = []
    for i, code in enumerate(codes):
        prefix = "sh." if code.startswith("6") else "sz."
        rs = bs.query_history_k_data_plus(
            prefix + code,
            "date,code,open,high,low,close,volume,amount,turn,pctChg",
            start_date=latest,
            frequency="d",
        )
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            if row[0] > latest:  # 只取新数据
                rows.append({
                    "date": row[0], "code": code,
                    "open": float(row[2]) if row[2] else None,
                    "high": float(row[3]) if row[3] else None,
                    "low": float(row[4]) if row[4] else None,
                    "close": float(row[5]) if row[5] else None,
                    "volume": float(row[6]) if row[6] else None,
                    "amount": float(row[7]) if row[7] else None,
                    "turn": float(row[8]) if row[8] else None,
                    "pctChg": float(row[9]) if row[9] else None,
                })
        
        if (i + 1) % 50 == 0:
            logger.info(f"进度: {i+1}/{len(codes)}, 新数据: {len(rows)}条")
    
    bs.logout()
    
    if rows:
        new_df = pd.DataFrame(rows)
        new_df["date"] = pd.to_datetime(new_df["date"])
        combined = pd.concat([old, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
        combined = combined.sort_values(["code", "date"])
        combined.to_parquet(parquet_path, index=False)
        logger.info(f"✅ 更新: +{len(rows)}条, 最新{new_df['date'].max()}")
    else:
        logger.info("无新数据（可能非交易日）")


if __name__ == "__main__":
    setup_logger()
    daily_update_bs()
