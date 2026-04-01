"""行业数据工具 — BaoStock行业分类

用途: 个股分析时找同行业股票做对比
缓存: data/cache/industry.parquet
"""

import baostock as bs
import pandas as pd
from pathlib import Path
from loguru import logger

CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "industry.parquet"


def _load_industry() -> pd.DataFrame:
    """加载行业数据（带缓存）"""
    if CACHE_PATH.exists():
        return pd.read_parquet(CACHE_PATH)
    return pd.DataFrame()


def get_industry(code: str) -> str:
    """获取股票行业"""
    df = _load_industry()
    if df.empty:
        return ""
    row = df[df["code"] == code]
    if row.empty:
        return ""
    return row.iloc[0].get("industry", "")


def get_industry_peers(code: str, limit: int = 5) -> list:
    """获取同行业股票"""
    df = _load_industry()
    if df.empty:
        return []
    industry = get_industry(code)
    if not industry:
        return []
    peers = df[df["industry"] == industry]
    peers = peers[peers["code"] != code]
    return peers.head(limit)["code"].tolist()


def build_industry_cache(codes: list):
    """构建行业缓存"""
    if CACHE_PATH.exists():
        existing = pd.read_parquet(CACHE_PATH)
        done = set(existing["code"].tolist())
        codes = [c for c in codes if c not in done]
        if not codes:
            logger.info(f"行业缓存完整: {len(existing)}只")
            return existing
    
    logger.info(f"拉取行业数据: {len(codes)}只")
    bs.login()
    rows = []
    for i, code in enumerate(codes):
        prefix = "sh." if code.startswith("6") else "sz."
        rs = bs.query_stock_industry(code=prefix + code)
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            rows.append({
                "code": code,
                "name": row[2] if len(row) > 2 else "",
                "industry": row[3] if len(row) > 3 else "",
            })
        if (i + 1) % 100 == 0:
            logger.info(f"进度: {i+1}/{len(codes)}")
    
    bs.logout()
    
    new_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    
    if CACHE_PATH.exists():
        existing = pd.read_parquet(CACHE_PATH)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["code"], keep="last")
    else:
        combined = new_df
    
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(CACHE_PATH, index=False)
    logger.info(f"✅ 行业缓存: {len(combined)}只")
    return combined
