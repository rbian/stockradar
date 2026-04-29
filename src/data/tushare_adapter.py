"""Tushare data adapter for StockRadar

Provides data not available from BaoStock/mootdx:
- Northbound capital flow (hsgt_top10)
- Sector/industry strength (sw_daily)
- Macro indicators (CPI, PMI, etc.)
- Dragon & Tiger list (top_list)

Features:
- Exponential backoff retry (3 attempts)
- Parquet cache for northbound/sector/dragon data
- Graceful degradation on API failures
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger

from src.data.cache import _cache_path, _is_expired

# ── Retry with exponential backoff ──

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


def _retry_api_call(fn, *args, **kwargs):
    """Call Tushare API with exponential backoff retry.
    
    Returns the API result or None on failure.
    """
    fn_name = getattr(fn, '__name__', str(fn))
    if fn_name in _DENIED_APIS:
        logger.debug(f"Tushare API跳过(无权限缓存): {fn_name}")
        return None
    for attempt in range(MAX_RETRIES):
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(f"Tushare API retry {attempt + 1}/{MAX_RETRIES} after {delay}s: {e}")
                time.sleep(delay)
            else:
                logger.warning(f"Tushare API failed after {MAX_RETRIES} attempts: {e}")
                if '没有接口' in str(e) or '权限' in str(e):
                    _DENIED_APIS.add(fn_name)
                    logger.info(f"已缓存无权限接口: {fn_name}")
                    return None
                raise


# API权限黑名单: 已知无权限的接口跳过重试
_DENIED_APIS = set()

# ── Tushare pro API ──

def _get_pro():
    """Get tushare pro API instance"""
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        return None
    try:
        import tushare as ts
        ts.set_token(token)
        return ts.pro_api()
    except Exception as e:
        logger.warning(f"Tushare init failed: {e}")
        return None


# ── Cache helpers for Tushare data ──

def _save_tushare_cache(prefix: str, date_key: str, df: pd.DataFrame):
    """Save Tushare result to parquet cache."""
    if df.empty:
        return
    path = _cache_path(f"tushare/{prefix}", date_key)
    df.to_parquet(path, index=False)
    logger.debug(f"Tushare cache saved: {prefix}/{date_key}")


def _load_tushare_cache(prefix: str, date_key: str, max_age_days: int = 1) -> pd.DataFrame:
    """Load Tushare result from cache. Default 1-day TTL (daily data)."""
    path = _cache_path(f"tushare/{prefix}", date_key)
    if path.exists() and not _is_expired(path, max_age_days):
        df = pd.read_parquet(path)
        logger.info(f"Tushare cache hit: {prefix}/{date_key} ({len(df)} rows)")
        return df
    return pd.DataFrame()


# ── Data fetchers ──

def fetch_northbound_top(date: str = None) -> pd.DataFrame:
    """Fetch northbound capital top 10 stocks by total amount

    Returns DataFrame: code, name, amount, close, change
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    # Try cache first
    cached = _load_tushare_cache("northbound", date)
    if not cached.empty:
        return cached

    pro = _get_pro()
    if not pro:
        # Fallback: try cache with longer TTL
        return _load_tushare_cache("northbound", date, max_age_days=7)

    try:
        for i in range(5):
            d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
            df = _retry_api_call(pro.hsgt_top10, trade_date=d)
            if df is not None and not df.empty:
                df['code'] = df['ts_code'].str[:6]
                df = df.sort_values('amount', ascending=False)
                logger.info(f"Northbound top10: {len(df)} stocks on {d}")
                result = df[['code', 'name', 'amount', 'close', 'change']].head(10)
                _save_tushare_cache("northbound", date, result)
                return result
    except Exception as e:
        logger.warning(f"Tushare northbound fetch failed after retries: {e}")

    return pd.DataFrame()


def fetch_sector_strength(date: str = None) -> pd.DataFrame:
    """Fetch Shenwan industry sector daily performance

    Returns: DataFrame with name, pct_change, vol, amount, pe, pb
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    cached = _load_tushare_cache("sector", date)
    if not cached.empty:
        return cached

    pro = _get_pro()
    if not pro:
        return _load_tushare_cache("sector", date, max_age_days=7)

    try:
        for i in range(5):
            d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
            df = _retry_api_call(pro.sw_daily, trade_date=d)
            if df is not None and not df.empty:
                df = df.rename(columns={'name': 'sector', 'pct_change': 'change_pct', 'vol': 'volume'})
                df = df.sort_values('change_pct', ascending=False)
                logger.info(f"Sector strength: {len(df)} sectors on {d}")
                result = df[['sector', 'change_pct', 'volume', 'amount', 'pe']].head(20)
                _save_tushare_cache("sector", date, result)
                return result
    except Exception as e:
        logger.warning(f"Tushare sector fetch failed after retries: {e}")

    return pd.DataFrame()


def fetch_dragon_tiger(date: str = None) -> pd.DataFrame:
    """Fetch dragon & tiger list (龙虎榜)

    Returns:
        DataFrame with hot stocks and their trading details
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    cached = _load_tushare_cache("dragon_tiger", date)
    if not cached.empty:
        return cached

    pro = _get_pro()
    if not pro:
        return _load_tushare_cache("dragon_tiger", date, max_age_days=7)

    try:
        for i in range(5):
            d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
            df = _retry_api_call(pro.top_list, trade_date=d)
            if df is not None and not df.empty:
                df['code'] = df['ts_code'].str[:6]
                df = df.rename(columns={
                    'name': 'name',
                    'close': 'close',
                    'pct_change': 'pct_change',
                    'amount': 'amount',
                    'net_amount': 'net_buy',
                    'reason': 'reason',
                })
                logger.info(f"Dragon tiger: {len(df)} entries on {d}")
                result = df[['code', 'name', 'close', 'pct_change', 'amount', 'net_buy', 'reason']].head(15)
                _save_tushare_cache("dragon_tiger", date, result)
                return result
    except Exception as e:
        logger.warning(f"Tushare dragon tiger fetch failed after retries: {e}")

    return pd.DataFrame()


def fetch_macro_indicator(indicator: str = "cpi") -> pd.DataFrame:
    """Fetch macro indicators: cpi, ppi, pmi, etc.

    Args:
        indicator: one of 'cpi', 'ppi', 'pmi', 'money_supply'
    """
    cached = _load_tushare_cache("macro", indicator, max_age_days=30)
    if not cached.empty:
        return cached

    pro = _get_pro()
    if not pro:
        return pd.DataFrame()

    try:
        if indicator == "cpi":
            df = _retry_api_call(pro.cn_cpi)
        elif indicator == "ppi":
            df = _retry_api_call(pro.cn_ppi)
        elif indicator == "pmi":
            df = _retry_api_call(pro.cn_pmi)
        else:
            return pd.DataFrame()

        if df is not None and not df.empty:
            result = df.tail(6)
            _save_tushare_cache("macro", indicator, result)
            return result
    except Exception as e:
        logger.warning(f"Tushare macro {indicator} fetch failed after retries: {e}")

    return pd.DataFrame()



def enrich_report_with_tushare() -> dict:
    """One-call enrichment for daily report"""
    result = {}

    # Northbound active stocks
    nb = fetch_northbound_top()
    if not nb.empty:
        top3 = nb.head(3)
        lines = ["📊 **北向活跃股Top3:**"]
        for _, row in top3.iterrows():
            amt = row["amount"] / 1e5  # 万元
            chg = row.get("change", 0)
            emoji = "🟢" if chg > 0 else "🔴"
            name = row["name"]
            lines.append(f"  {emoji} {name}: 成交{amt:.0f}万 {chg:+.2f}%")
        result["northbound"] = "\n".join(lines)

    # Sector strength
    sectors = fetch_sector_strength()
    if not sectors.empty:
        top5 = sectors.head(5)
        bot5 = sectors.tail(5)
        lines = ["🏭 **行业强弱:**"]
        for _, row in top5.iterrows():
            lines.append(f"  🟢 {row['sector']}: {row['change_pct']:+.2f}%")
        lines.append("  ...")
        for _, row in bot5.iterrows():
            lines.append(f"  🔴 {row['sector']}: {row['change_pct']:+.2f}%")
        result["sectors"] = "\n".join(lines)

    # Dragon Tiger (needs higher permission)
    dt = fetch_dragon_tiger()
    if not dt.empty:
        lines = [f"🐉 **龙虎榜** ({len(dt)}只):"]
        for _, row in dt.head(5).iterrows():
            lines.append(f"  {row['name']} {row['pct_change']:+.1f}%")
        result["dragon_tiger"] = "\n".join(lines)

    return result
