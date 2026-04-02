"""QVeris每日增量更新 — 只拉最新数据补入parquet"""

import os
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger


def incremental_update():
    """用QVeris拉最新数据补入parquet"""
    # 加载.env
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    qveris_key = os.environ.get("QVERIS_API_KEY", "")
    if not qveris_key:
        logger.warning("无QVERIS_API_KEY，跳过增量更新")
        return

    from src.data.qveris_adapter import fetch_daily_quote_qv, fetch_index_quote_qv

    parquet_path = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
    if not parquet_path.exists():
        logger.warning("无hs300_daily.parquet")
        return

    old = pd.read_parquet(parquet_path)
    latest = str(old["date"].max())[:10]
    logger.info(f"当前最新数据: {latest}")

    # 关键股票（watchlist）
    codes = ["600519", "000333", "601318", "600036", "000858",
             "600276", "601127", "600030", "601166", "600887"]

    try:
        df = fetch_daily_quote_qv(codes, delay=0.5)
        if df.empty:
            logger.info("无新数据")
            return

        combined = pd.concat([old, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
        combined = combined.sort_values(["code", "date"])
        combined.to_parquet(parquet_path, index=False)

        new_rows = len(df)
        new_latest = str(df["date"].max())[:10]
        logger.info(f"✅ 增量更新: +{new_rows}条, 最新{new_latest}")

    except Exception as e:
        logger.error(f"增量更新失败: {e}")


if __name__ == "__main__":
    from src.infra.logger import setup_logger
    setup_logger()
    incremental_update()
