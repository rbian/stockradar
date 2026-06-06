"""新浪财经实时行情适配器

优势：
  - 盘中实时更新（3秒延迟）
  - 批量查询（每次约50只）
  - 稳定可靠，比东方财富API限制少
"""

import time
from pathlib import Path

import pandas as pd
import requests
from loguru import logger


def _code_to_sina(code: str) -> str:
    """转新浪代码格式: 002460 → sz002460, 600519 → sh600519"""
    code = str(code).zfill(6)
    if code.startswith(('6',)):
        return f"sh{code}"
    return f"sz{code}"


_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

BATCH_SIZE = 50  # 新浪单次查询上限约800，保守50


def fetch_realtime_quotes(codes: list[str]) -> pd.DataFrame:
    """批量获取实时行情

    Returns:
        DataFrame with columns: code, date, open, high, low, close, volume, amount
    """
    all_records = []
    total = len(codes)

    for i in range(0, total, BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        sina_codes = [_code_to_sina(c) for c in batch]
        url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()

            for line in resp.text.strip().split('\n'):
                if '="' not in line or len(line) < 10:
                    continue

                sina_code = line.split('=')[0].split('_')[-1]
                code = sina_code[2:]  # sz002460 → 002460
                data_str = line.split('"')[1]
                fields = data_str.split(',')

                if len(fields) < 33:
                    continue

                try:
                    record = {
                        "code": code,
                        "date": pd.Timestamp(fields[30]),
                        "open": float(fields[1]) if fields[1] else 0,
                        "high": float(fields[4]) if fields[4] else 0,
                        "low": float(fields[5]) if fields[5] else 0,
                        "close": float(fields[3]) if fields[3] else 0,
                        "volume": float(fields[8]) if fields[8] else 0,
                        "amount": float(fields[9]) if fields[9] else 0,
                    }
                    # 过滤无效数据
                    if record["close"] > 0:
                        all_records.append(record)
                except (ValueError, IndexError):
                    continue

        except Exception as e:
            logger.warning(f"新浪行情批次 {i}-{i+len(batch)} 失败: {e}")

        # 间隔避免被ban
        if i + BATCH_SIZE < total:
            time.sleep(0.3)

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    logger.info(f"新浪实时行情: {len(df)}只, 日期={df['date'].max()}")
    return df


def update_daily_from_sina(
    existing: pd.DataFrame,
    codes: list[str],
    parquet_path: str | Path = None,
) -> pd.DataFrame:
    """用新浪实时行情更新日线数据

    Args:
        existing: 现有日线数据
        codes: 需要更新的股票代码列表
        parquet_path: 保存路径（可选）

    Returns:
        更新后的 DataFrame
    """
    quotes = fetch_realtime_quotes(codes)
    if quotes.empty:
        logger.warning("新浪行情为空，跳过更新")
        return existing

    date_str = str(quotes["date"].iloc[0])[:10]
    updated = existing.copy()
    new_rows = 0
    start = time.time()

    for _, q in quotes.iterrows():
        code = q["code"]
        mask = (updated["code"] == code) & (updated["date"].astype(str).str[:10] == date_str)

        row_data = {
            "code": code,
            "date": q["date"],
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": q["volume"],
            "amount": q["amount"],
        }

        if mask.any():
            for col, val in row_data.items():
                if col not in ("code", "date"):
                    updated.loc[mask, col] = val
        else:
            updated = pd.concat([updated, pd.DataFrame([row_data])], ignore_index=True)
            new_rows += 1

    elapsed = time.time() - start
    logger.info(f"新浪行情更新: {len(quotes)}只, 新增{new_rows}条, {elapsed:.1f}s")

    if parquet_path:
        updated.to_parquet(parquet_path, index=False)
        logger.info(f"已保存到 {parquet_path}")

    return updated
