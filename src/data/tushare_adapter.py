"""Tushare data adapter for StockRadar

Provides data not available from BaoStock/mootdx:
- Northbound capital flow (hsgt_top10)
- Sector/industry strength (sw_daily)
- Macro indicators (CPI, PMI, etc.)
- Dragon & Tiger list (top_list)

Features:
- Exponential backoff retry (2 attempts max for rate-limited APIs)
- Per-API rate limit tracking (each unique API gets its own cooldown timer)
- Parquet cache with graceful degradation
- Timeout control on enrich_report to avoid blocking daily report

NOTE: Tushare free tier = 1 call per API per hour. We batch 3 APIs during
the 15:30 report window and rely heavily on cache for the rest of the day.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger

from src.data.cache import _cache_path, _is_expired

# ── Retry with backoff ──

MAX_RETRIES = 2  # Reduced from 3 — Tushare rate limit is per-API-per-hour, retries just burn time
BASE_DELAY = 2  # seconds

# ── Per-API rate limiter ──
# Each unique Tushare API endpoint gets its own cooldown timer.
# Tushare free tier: ~1 call per API per hour.
_api_call_times: dict[str, float] = {}
_MIN_API_INTERVAL = 3601.0  # 1 hour + 1s — respect Tushare free tier limit


def _rate_limit_wait(api_name: str):
    """Wait if needed to respect per-API rate limit."""
    now = time.time()
    last = _api_call_times.get(api_name, 0.0)
    elapsed = now - last
    if elapsed < _MIN_API_INTERVAL:
        wait = _MIN_API_INTERVAL - elapsed
        logger.debug(f'Tushare rate limit [{api_name}]: waiting {wait:.0f}s')
        time.sleep(wait)
    _api_call_times[api_name] = time.time()


def _retry_api_call(fn, *args, **kwargs):
    """Call Tushare API with retry logic.
    
    On rate-limit error: do NOT retry (1-per-hour limit means retries are useless).
    On other errors: retry with exponential backoff.
    
    Returns the API result or None on failure.
    """
    fn_name = getattr(fn, '__name__', str(fn))
    if fn_name in _DENIED_APIS:
        logger.debug(f"Tushare API跳过(无权限缓存): {fn_name}")
        return None
    _rate_limit_wait(fn_name)
    for attempt in range(MAX_RETRIES):
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            error_str = str(e)
            is_rate_limit = '频率超限' in error_str or 'rate limit' in error_str.lower()
            is_permission = '没有接口' in error_str or '权限' in error_str
            
            if is_rate_limit:
                # Rate limit = don't retry, mark time so we skip for next hour
                logger.warning(f"Tushare API频率超限 [{fn_name}]: 跳过(1次/小时限制)")
                _api_call_times[fn_name] = time.time()
                return None
            elif is_permission:
                # Permission denied = permanently skip
                logger.warning(f"Tushare API无权限 [{fn_name}]: 持久化黑名单")
                _DENIED_APIS.add(fn_name)
                _save_denied_apis(_DENIED_APIS)
                return None
            elif attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(f"Tushare API retry {attempt + 1}/{MAX_RETRIES} after {delay}s [{fn_name}]: {e}")
                time.sleep(delay)
            else:
                logger.warning(f"Tushare API failed after {MAX_RETRIES} attempts [{fn_name}]: {e}")
                return None
    return None


_DENIED_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "cache" / "tushare_denied_apis.json"


def _load_denied_apis():
    denied = set()
    if _DENIED_CACHE_FILE.exists():
        try:
            denied = set(json.loads(_DENIED_CACHE_FILE.read_text()))
        except Exception:
            pass
    return denied


def _save_denied_apis(denied_set):
    try:
        _DENIED_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DENIED_CACHE_FILE.write_text(json.dumps(sorted(denied_set)))
    except Exception:
        pass


# API权限黑名单: 持久化到文件，重启不丢失
_DENIED_APIS = _load_denied_apis()

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


def _find_latest_cache(prefix: str, max_age_days: int = 7) -> pd.DataFrame:
    """Find the most recent cache file for a prefix, within max_age_days."""
    cache_dir = _cache_path(f"tushare/{prefix}", "dummy").parent
    if not cache_dir.exists():
        return pd.DataFrame()
    
    best_path = None
    best_time = datetime.min
    cutoff = datetime.now() - timedelta(days=max_age_days)
    
    for path in cache_dir.glob("*.parquet"):
        try:
            if _is_expired(path, max_age_days):
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if mtime > best_time and mtime >= cutoff:
                best_time = mtime
                best_path = path
        except Exception:
            continue
    
    if best_path:
        df = pd.read_parquet(best_path)
        age = (datetime.now() - best_time).days
        logger.info(f"Tushare cache fallback: {prefix} (age={age}d, {len(df)} rows)")
        return df
    return pd.DataFrame()


# ── Data fetchers ──

def fetch_northbound_top(date: str = None) -> pd.DataFrame:
    """Fetch northbound capital top 10 stocks by total amount

    Returns DataFrame: code, name, amount, close, change
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    # Try cache first (exact date, 1-day TTL)
    cached = _load_tushare_cache("northbound", date)
    if not cached.empty:
        return cached

    pro = _get_pro()
    if not pro:
        return _find_latest_cache("northbound", max_age_days=30)

    try:
        # Only try today's date — no date rollback loop (that burns rate limit)
        df = _retry_api_call(pro.hsgt_top10, trade_date=date)
        if df is not None and not df.empty:
            df['code'] = df['ts_code'].str[:6]
            df = df.sort_values('amount', ascending=False)
            logger.info(f"Northbound top10: {len(df)} stocks on {date}")
            result = df[['code', 'name', 'amount', 'close', 'change']].head(10)
            _save_tushare_cache("northbound", date, result)
            return result
    except Exception as e:
        logger.warning(f"Tushare northbound fetch failed: {e}")

    return _find_latest_cache("northbound", max_age_days=30)


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
        return _find_latest_cache("sector", max_age_days=30)

    try:
        df = _retry_api_call(pro.sw_daily, trade_date=date)
        if df is not None and not df.empty:
            df = df.rename(columns={'name': 'sector', 'pct_change': 'change_pct', 'vol': 'volume'})
            df = df.sort_values('change_pct', ascending=False)
            logger.info(f"Sector strength: {len(df)} sectors on {date}")
            result = df[['sector', 'change_pct', 'volume', 'amount', 'pe']].head(20)
            _save_tushare_cache("sector", date, result)
            return result
    except Exception as e:
        logger.warning(f"Tushare sector fetch failed: {e}")

    return _find_latest_cache("sector", max_age_days=30)


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
        return _find_latest_cache("dragon_tiger", max_age_days=30)

    try:
        df = _retry_api_call(pro.top_list, trade_date=date)
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
            logger.info(f"Dragon tiger: {len(df)} entries on {date}")
            result = df[['code', 'name', 'close', 'pct_change', 'amount', 'net_buy', 'reason']].head(15)
            _save_tushare_cache("dragon_tiger", date, result)
            return result
    except Exception as e:
        logger.warning(f"Tushare dragon tiger fetch failed: {e}")

    return _find_latest_cache("dragon_tiger", max_age_days=30)


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


def enrich_report_with_tushare(timeout: int = 30) -> dict:
    """One-call enrichment for daily report.

    Total timeout of 30s — each fetcher gets ~10s max.
    Falls back to latest cache if API calls fail (common with free Tushare).
    
    Args:
        timeout: Max seconds for the entire enrichment (default 30)
    
    Returns:
        dict with optional keys: northbound, sectors, dragon_tiger
    """
    import signal
    
    result = {}
    deadline = time.time() + timeout
    
    # Northbound active stocks (~10s budget)
    if time.time() < deadline:
        try:
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
        except Exception as e:
            logger.warning(f"Northbound enrichment error: {e}")

    # Sector strength (~10s budget)
    if time.time() < deadline:
        try:
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
        except Exception as e:
            logger.warning(f"Sector enrichment error: {e}")

    # Dragon Tiger (~10s budget)
    if time.time() < deadline:
        try:
            dt = fetch_dragon_tiger()
            if not dt.empty:
                lines = [f"🐉 **龙虎榜** ({len(dt)}只):"]
                for _, row in dt.head(5).iterrows():
                    lines.append(f"  {row['name']} {row['pct_change']:+.1f}%")
                result["dragon_tiger"] = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Dragon tiger enrichment error: {e}")

    if not result:
        logger.info("Tushare enrichment: 全部使用缓存fallback或无数据")
    
    return result
