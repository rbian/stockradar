"""统一数据采集接口 - 基于AKShare + Tushare"""

import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from loguru import logger


class DataFetchError(Exception):
    """数据采集异常"""
    pass


def _retry_fetch(fetch_fn, retries=3, delay=5, **kwargs):
    """带重试的数据获取"""
    last_error = None
    for i in range(retries):
        try:
            return fetch_fn(**kwargs)
        except Exception as e:
            last_error = e
            logger.warning(f"数据获取失败（第{i+1}次重试）: {e}")
            if i < retries - 1:
                time.sleep(delay)
    raise DataFetchError(f"重试{retries}次后仍失败: {last_error}")


# ============ 行情数据 ============

def fetch_daily_quote(symbol: str, start_date: str, end_date: str,
                      adjust: str = "qfq") -> pd.DataFrame:
    """获取单只股票日线行情（前复权）

    Args:
        symbol: 股票代码，如 "600519"
        start_date: 开始日期，如 "20200101"
        end_date: 结束日期，如 "20241231"
        adjust: 复权方式 "qfq"(前复权) / ""(不复权)

    Returns:
        DataFrame with columns: code, date, open, high, low, close, volume, amount, turnover, pre_close, change_pct
    """
    df = _retry_fetch(
        ak.stock_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "换手率": "turnover",
        "昨收": "pre_close", "涨跌幅": "change_pct",
    })
    df["code"] = symbol
    df["date"] = pd.to_datetime(df["date"])
    df = df[["code", "date", "open", "high", "low", "close",
             "volume", "amount", "turnover", "pre_close", "change_pct"]]
    return df


def fetch_daily_quote_batch(symbols: list, start_date: str, end_date: str) -> pd.DataFrame:
    """批量获取多只股票日线行情"""
    all_dfs = []
    total = len(symbols)
    for i, symbol in enumerate(symbols):
        try:
            df = fetch_daily_quote(symbol, start_date, end_date)
            if not df.empty:
                all_dfs.append(df)
        except DataFetchError as e:
            logger.warning(f"获取 {symbol} 行情失败: {e}")
        if (i + 1) % 100 == 0:
            logger.info(f"行情下载进度: {i+1}/{total}")
            time.sleep(1)  # 避免请求过快
    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


# ============ 股票列表 ============

def fetch_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    df = _retry_fetch(ak.stock_zh_a_spot_em)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name",
    })
    df = df[["code", "name"]]
    return df


# ============ 大盘指数 ============

def fetch_market_index(symbol: str = "000300", start_date: str = "20160101",
                       end_date: str = None) -> pd.DataFrame:
    """获取大盘指数日线（默认沪深300）"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    df = _retry_fetch(
        ak.index_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
    })
    df["index_code"] = symbol
    df["date"] = pd.to_datetime(df["date"])
    df = df[["index_code", "date", "open", "high", "low", "close", "volume", "amount"]]
    return df


# ============ 行业指数 ============

def fetch_industry_index(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取申万行业指数日线"""
    df = _retry_fetch(
        ak.index_zh_a_hist,
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
    })
    df["industry_code"] = symbol
    df["date"] = pd.to_datetime(df["date"])
    df = df[["industry_code", "date", "open", "high", "low", "close", "volume", "amount"]]
    return df


# ============ 北向资金 ============

def fetch_northbound_stock(date: str = None) -> pd.DataFrame:
    """获取北向资金个股明细

    Args:
        date: 日期字符串，如 "20240329"
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    try:
        df = _retry_fetch(ak.stock_hsgt_individual_em, symbol="北向")
        if df is None or df.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    df = df.rename(columns={
        "代码": "code", "日期": "date",
        "买入金额": "buy_amount", "卖出金额": "sell_amount",
        "净买金额": "net_amount", "持股数量": "hold_share",
        "持股市值": "hold_value",
    })
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    else:
        df["date"] = pd.to_datetime(date)

    if "hold_ratio" not in df.columns and "hold_value" in df.columns:
        df["hold_ratio"] = 0.0

    cols = [c for c in ["code", "date", "buy_amount", "sell_amount",
                         "net_amount", "hold_share", "hold_ratio"]
            if c in df.columns]
    return df[cols]


def fetch_northbound_daily(start_date: str, end_date: str) -> pd.DataFrame:
    """获取北向资金每日汇总"""
    try:
        df = _retry_fetch(ak.stock_hsgt_north_net_flow_in_em, symbol="北上")
        if df is None or df.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    df = df.rename(columns={
        "日期": "date", "当日资金净流入": "total_net",
    })
    df["date"] = pd.to_datetime(df["date"])
    df["sh_net"] = 0.0
    df["sz_net"] = 0.0
    df = df[["date", "total_net", "sh_net", "sz_net"]]

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    return df


# ============ 大盘情绪 ============

def fetch_market_sentiment(date: str = None) -> pd.DataFrame:
    """获取大盘情绪数据（涨跌家数等）"""
    try:
        df = _retry_fetch(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    change_col = "涨跌幅" if "涨跌幅" in df.columns else None
    if change_col is None:
        return pd.DataFrame()

    changes = df[change_col].astype(float)
    up_count = (changes > 0).sum()
    down_count = (changes < 0).sum()
    flat_count = (changes == 0).sum()
    limit_up = (changes >= 9.9).sum()
    limit_down = (changes <= -9.9).sum()
    total_amount = df["成交额"].sum() if "成交额" in df.columns else 0.0

    return pd.DataFrame([{
        "date": pd.Timestamp(date),
        "up_count": int(up_count),
        "down_count": int(down_count),
        "flat_count": int(flat_count),
        "limit_up": int(limit_up),
        "limit_down": int(limit_down),
        "total_amount": float(total_amount),
        "ad_ratio": round(up_count / max(up_count + down_count, 1), 4),
    }])


# ============ 停复牌 ============

def fetch_suspension(date: str = None) -> pd.DataFrame:
    """获取停牌信息"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    try:
        df = _retry_fetch(ak.stock_tfp_em, date=date)
        if df is None or df.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    df = df.rename(columns={"代码": "code"})
    df["date"] = pd.to_datetime(date)
    df["is_suspended"] = True
    df = df[["code", "date", "is_suspended"]]
    return df


# ============ 申万行业分类 ============

def fetch_industry_classification() -> pd.DataFrame:
    """获取申万行业分类"""
    try:
        df = _retry_fetch(ak.stock_board_industry_name_em)
        if df is None or df.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    return df


# ============ 财务数据 (Tushare) ============

def fetch_financial_indicator(ts_code: str = None, start_date: str = None,
                              end_date: str = None, tushare_token: str = None) -> pd.DataFrame:
    """获取财务指标数据（通过Tushare Pro）

    注意：需要有效的Tushare Pro Token
    """
    try:
        import tushare as ts
        if tushare_token:
            ts.set_token(tushare_token)
        pro = ts.pro_api()

        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")

        df = pro.fina_indicator(**params, fields=[
            "ts_code", "end_date", "roe", "roa",
            "grossprofit_margin", "netprofit_margin",
            "debt_to_assets", "ocf_to_or",
            "or_yoy", "netprofit_yoy",
            "revenue", "net_profit",
            "ar_ratio", "goodwill_ratio",
        ])

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={
            "ts_code": "code", "grossprofit_margin": "gross_margin",
            "netprofit_margin": "net_margin", "debt_to_assets": "debt_ratio",
            "ocf_to_or": "ocf_ratio", "or_yoy": "revenue_yoy",
            "netprofit_yoy": "profit_yoy",
        })

        # Tushare code格式: 600519.SH -> 600519
        df["code"] = df["code"].str[:6]
        df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d")

        return df[["code", "end_date", "roe", "roa", "gross_margin", "net_margin",
                    "debt_ratio", "ocf_ratio", "revenue_yoy", "profit_yoy",
                    "revenue", "net_profit", "ar_ratio", "goodwill_ratio"]]
    except ImportError:
        logger.warning("tushare未安装，跳过财务数据获取")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"获取财务数据失败: {e}")
        return pd.DataFrame()
