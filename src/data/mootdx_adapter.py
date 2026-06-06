"""mootdx数据适配器 — 通达信实时行情

优势:
- 数据T+0（当天收盘后即有，不用等T+1）
- 速度: 300只~74s (BaoStock需要5min+)
- 免费，无credits限制
- 支持实时行情批量获取

用于:
- 每日数据更新(替代BaoStock)
- 实时行情查询(替代QVeris)
"""

import pandas as pd
import time
from pathlib import Path
from loguru import logger
from mootdx.quotes import Quotes

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_client = None


def get_client() -> Quotes:
    """获取mootdx客户端（单例）"""
    global _client
    if _client is None:
        _client = Quotes.factory(market="std")
        logger.info("mootdx客户端已连接")
    return _client


def fetch_realtime_quote(codes: list) -> pd.DataFrame:
    """批量获取实时行情
    
    Args:
        codes: 股票代码列表 ['600519', '000001', ...]
    Returns:
        DataFrame: code/name/price/open/high/low/volume/amount/turnover
    """
    client = get_client()
    
    # mootdx需要str格式的symbol
    all_rows = []
    # 每批50只
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        try:
            df = client.quotes(symbol=batch)
            if df is not None and not df.empty:
                all_rows.append(df)
        except Exception as e:
            logger.warning(f"mootdx实时行情失败({len(batch)}只): {e}")
        time.sleep(0.1)
    
    if not all_rows:
        return pd.DataFrame()
    
    result = pd.concat(all_rows, ignore_index=True)
    # 统一列名
    result = result.rename(columns={
        "code": "code", "name": "name",
        "price": "close", "open": "open",
        "high": "high", "low": "low",
        "vol": "volume", "amount": "amount",
    })
    # 去掉前缀
    result["code"] = result["code"].astype(str).str.replace(r"^(sh|sz)", "", regex=True)
    return result


def fetch_daily_kline(code: str, days: int = 5, market: int = None) -> pd.DataFrame:
    """获取单只股票日K线
    
    Args:
        code: 股票代码
        days: 获取天数
        market: 1=沪 0=深 (None自动判断)
    """
    client = get_client()
    if market is None:
        market = 1 if code.startswith("6") else 0
    
    try:
        df = client.bars(symbol=code, category=9, market=market, offset=days)
        if df is None or df.empty:
            return pd.DataFrame()
        
        df = df.reset_index()
        df = df.rename(columns={
            "datetime": "date",
            "open": "open", "high": "high", "low": "low",
            "close": "close", "vol": "volume", "amount": "amount",
        })
        df["code"] = code
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["turn"] = 0.0
        df["pctChg"] = df["close"].pct_change() * 100
        
        return df[["date","code","open","high","low","close","volume","amount","turn","pctChg"]]
    except Exception as e:
        logger.warning(f"mootdx K线失败({code}): {e}")
        return pd.DataFrame()


def daily_update_mootdx(codes: list = None):
    """每日数据更新 — 增量拉取最新K线
    
    比BaoStock优势: T+0(当天数据当天有), 速度快3倍
    """
    parquet_path = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
    if not parquet_path.exists():
        logger.warning("无hs300_daily.parquet")
        return
    
    old = pd.read_parquet(parquet_path)
    old["date"] = pd.to_datetime(old["date"]).dt.normalize()
    latest_date = old["date"].max()
    
    if codes is None:
        codes_file = PROJECT_ROOT / "data" / "hs300_codes.txt"
        codes = [l.strip() for l in codes_file.read_text().splitlines() if l.strip()]
    
    client = get_client()
    new_rows = []
    t0 = time.time()
    
    for i, code in enumerate(codes):
        market = 1 if code.startswith("6") else 0
        try:
            df = client.bars(symbol=code, category=9, market=market, offset=5)
            if df is not None and not df.empty:
                df = df.reset_index()
                for _, row in df.iterrows():
                    dt = pd.Timestamp(row["datetime"])
                    if dt > latest_date:
                        new_rows.append({
                            "date": dt.normalize(),
                            "code": code,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row["vol"]),
                            "amount": float(row["amount"]),
                            "turn": 0.0,
                            "pctChg": float(row["close"]) / float(row["open"]) * 100 - 100 if float(row["open"]) > 0 else 0,
                        })
        except Exception as e:
            logger.debug(f"mootdx {code} 失败: {e}")
        
        if (i + 1) % 100 == 0:
            logger.info(f"进度: {i+1}/{len(codes)}, 新数据: {len(new_rows)}条, {time.time()-t0:.0f}s")
    
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        new_df = new_df.drop_duplicates(subset=["code", "date"])
        combined = pd.concat([old, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
        combined = combined.sort_values(["code", "date"])
        combined.to_parquet(parquet_path, index=False)
        logger.info(f"✅ mootdx更新: +{len(new_df)}条, 总{len(combined)}条, {time.time()-t0:.0f}s")
    else:
        logger.info(f"mootdx: 无新数据 (最新{latest_date}), {time.time()-t0:.0f}s")


if __name__ == "__main__":
    from src.infra.logger import setup_logger
    setup_logger()
    daily_update_mootdx()
