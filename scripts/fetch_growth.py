"""成长数据(YOY)批量采集 — BaoStock query_growth_data

字段: YOYEquity(净资产增速) YOYAsset(资产增速) YOYNI(净利增速) YOYEPS(EPS增速) YOYProfit(利润增速)
"""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import time
import baostock as bs
import pandas as pd
from loguru import logger
from src.infra.logger import setup_logger
from src.data.cache import save_growth_cache, load_growth_cache


def fetch_growth_batch(codes: list, year: int, quarter: int, delay: float = 0.3):
    """批量拉取成长数据"""
    # 先检查缓存
    cached = load_growth_cache(year, quarter, max_age_days=90)
    if not cached.empty:
        existing_codes = set(cached["code"].str.replace("sh.", "").str.replace("sz.", ""))
        codes = [c for c in codes if c not in existing_codes]
        if not codes:
            logger.info(f"成长数据{year}Q{quarter}全部缓存")
            return cached
    
    lg = bs.login()
    logger.info(f"成长数据: 缺失{len(codes)}只, {year}Q{quarter}")
    
    rows = []
    for i, code in enumerate(codes):
        prefix = "sh." if code.startswith("6") else "sz."
        bs_code = prefix + code
        rs = bs.query_growth_data(code=bs_code, year=year, quarter=quarter)
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            rows.append({
                "code": code,
                "end_date": row[2],
                "YOYEquity": float(row[3]) if row[3] else None,
                "YOYAsset": float(row[4]) if row[4] else None,
                "YOYNI": float(row[5]) if row[5] else None,
                "YOYEPS": float(row[6]) if row[6] else None,
                "YOYProfit": float(row[7]) if row[7] else None,
            })
        
        if (i + 1) % 50 == 0:
            logger.info(f"进度: {i+1}/{len(codes)}, 已获取: {len(rows)}条")
        time.sleep(delay)
    
    bs.logout()
    
    if rows:
        new_df = pd.DataFrame(rows)
        combined = pd.concat([cached, new_df], ignore_index=True) if not cached.empty else new_df
        save_growth_cache(combined, year, quarter)
        logger.info(f"✅ 成长数据: {year}Q{quarter} = {len(combined)}只")
        return combined
    
    return cached


if __name__ == "__main__":
    setup_logger()
    
    # 拉取沪深300成分股的成长数据
    codes_file = PROJECT_ROOT / "data" / "hs300_codes.txt"
    codes = [l.strip() for l in codes_file.read_text().splitlines() if l.strip()]
    
    for year in [2024, 2023]:
        for quarter in [4, 3, 2, 1]:
            fetch_growth_batch(codes, year, quarter)
