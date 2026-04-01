"""数据缓存层 — Parquet本地缓存，避免重复拉取

策略:
- 行情数据按月缓存到 data/cache/quotes/{code}_{YYYYMM}.parquet
- 财务数据按年缓存到 data/cache/financial/{year}Q{quarter}.parquet
- 股票列表缓存到 data/cache/stock_list.parquet
- 指数数据缓存到 data/cache/index/
- 缓存有效期：行情7天，财务90天，列表7天
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger


CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _cache_path(prefix: str, name: str) -> Path:
    p = CACHE_DIR / prefix / f"{name}.parquet"
    _ensure_dir(p.parent)
    return p


def _is_expired(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime) > timedelta(days=max_age_days)


# ── 行情缓存 ──

def save_quote_cache(code: str, df: pd.DataFrame, start: str, end: str):
    """按月拆分保存行情缓存"""
    if df.empty:
        return
    df["date"] = pd.to_datetime(df["date"])
    for month, group in df.groupby(df["date"].dt.to_period("M")):
        path = _cache_path("quotes", f"{code}_{month}")
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if existing.empty:
            group.to_parquet(path, index=False)
        else:
            combined = pd.concat([existing, group]).drop_duplicates(subset=["date", "code"])
            combined.to_parquet(path, index=False)


def load_quote_cache(code: str, start: str, end: str) -> pd.DataFrame:
    """从缓存加载行情，返回在[start,end]范围内的数据"""
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    dfs = []
    for path in (CACHE_DIR / "quotes").glob(f"{code}_*.parquet"):
        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"])
            mask = (df["date"] >= start_dt) & (df["date"] <= end_dt)
            if mask.any():
                dfs.append(df[mask])
        except Exception:
            pass
    if dfs:
        return pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["date", "code"]).sort_values("date")
    return pd.DataFrame()


# ── 财务缓存 ──

def save_financial_cache(codes: list, df: pd.DataFrame, year: int, quarter: int):
    path = _cache_path("financial", f"{year}Q{quarter}")
    df.to_parquet(path, index=False)
    logger.debug(f"财务缓存: {path}")


def load_financial_cache(year: int, quarter: int, max_age_days: int = 90) -> pd.DataFrame:
    path = _cache_path("financial", f"{year}Q{quarter}")
    if path.exists() and not _is_expired(path, max_age_days):
        df = pd.read_parquet(path)
        logger.info(f"财务缓存命中: {len(df)}条")
        return df
    return pd.DataFrame()


# ── 股票列表缓存 ──

def save_stock_list_cache(df: pd.DataFrame):
    path = _cache_path("stock_list", "hs300")
    df.to_parquet(path, index=False)


def load_stock_list_cache(max_age_days: int = 7) -> pd.DataFrame:
    path = _cache_path("stock_list", "hs300")
    if path.exists() and not _is_expired(path, max_age_days):
        return pd.read_parquet(path)
    return pd.DataFrame()


# ── 指数缓存 ──

def save_index_cache(df: pd.DataFrame, index_code: str):
    path = _cache_path("index", index_code)
    df.to_parquet(path, index=False)


def load_index_cache(index_code: str, max_age_days: int = 7) -> pd.DataFrame:
    path = _cache_path("index", index_code)
    if path.exists() and not _is_expired(path, max_age_days):
        return pd.read_parquet(path)
    return pd.DataFrame()


# ── 清理 ──

def clean_old_cache(max_age_days: int = 90):
    """清理过期缓存"""
    removed = 0
    for path in CACHE_DIR.rglob("*.parquet"):
        if _is_expired(path, max_age_days):
            path.unlink()
            removed += 1
    if removed:
        logger.info(f"清理过期缓存: {removed}个文件")


# ── 成长数据缓存 ──

def save_growth_cache(df: pd.DataFrame, year: int, quarter: int):
    path = _cache_path("growth", f"{year}Q{quarter}")
    df.to_parquet(path, index=False)
    logger.debug(f"成长数据缓存: {path}")


def load_growth_cache(year: int, quarter: int, max_age_days: int = 90) -> pd.DataFrame:
    path = _cache_path("growth", f"{year}Q{quarter}")
    if path.exists() and not _is_expired(path, max_age_days):
        df = pd.read_parquet(path)
        logger.info(f"成长数据缓存命中: {len(df)}条")
        return df
    return pd.DataFrame()
