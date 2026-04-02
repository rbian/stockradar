"""Yahoo Finance数据适配器

当服务器在海外（东方财富API不可用）时使用Yahoo Finance获取A股数据。
A股代码格式：上交所 .SS，深交所 .SZ

用法：
    from src.data.yahoo_adapter import YahooAdapter
    adapter = YahooAdapter()
    df = adapter.fetch_daily_quote("600519", "2024-01-01", "2024-12-31")
"""

import time
from datetime import datetime

import pandas as pd
from loguru import logger

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False


def _to_yf_code(code: str) -> str:
    """转换A股代码为Yahoo Finance格式

    600519 → 600519.SS (上交所)
    000001 → 000001.SZ (深交所)
    300750 → 300750.SZ (创业板)
    688xxx → 688xxx.SS (科创板)
    """
    code = code.replace(".SH", "").replace(".SZ", "")
    if code.startswith(("6", "9")):
        return f"{code}.SS"
    else:
        return f"{code}.SZ"


def _from_yf_code(yf_code: str) -> str:
    """Yahoo Finance代码转回纯数字"""
    return yf_code.replace(".SS", "").replace(".SZ", "")


def fetch_daily_quote_yf(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过Yahoo Finance获取单只股票日线行情

    Args:
        symbol: 6位股票代码
        start_date: YYYYMMDD 或 YYYY-MM-DD
        end_date: YYYYMMDD 或 YYYY-MM-DD

    Returns:
        DataFrame with columns: code, date, open, high, low, close, volume, amount
    """
    if not YF_AVAILABLE:
        raise ImportError("yfinance未安装: pip install yfinance")

    yf_code = _to_yf_code(symbol)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    try:
        ticker = yf.Ticker(yf_code)
        hist = ticker.history(start=start, end=end, auto_adjust=True)

        if hist.empty:
            return pd.DataFrame()

        df = hist.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"date": "date"})

        # 标准化列名
        result = pd.DataFrame({
            "code": symbol,
            "date": pd.to_datetime(df["date"]),
            "open": df["open"].values,
            "high": df["high"].values,
            "low": df["low"].values,
            "close": df["close"].values,
            "volume": df["volume"].values.astype(float),
            "amount": df.get("volume", 0).values.astype(float),  # YF没有amount
        })

        # 计算涨跌幅
        result["pre_close"] = result["close"].shift(1)
        result["change_pct"] = (result["close"] / result["pre_close"] - 1) * 100
        result["change_pct"] = result["change_pct"].fillna(0)
        # 换手率（YF没有，用volume占流通股本比例近似，这里先填0）
        result["turnover"] = 0.0

        return result[["code", "date", "open", "high", "low", "close",
                        "pre_close", "change_pct", "volume", "amount", "turnover"]]

    except Exception as e:
        logger.warning(f"Yahoo Finance获取 {symbol} 失败: {e}")
        return pd.DataFrame()


def fetch_daily_quote_batch_yf(symbols: list, start_date: str, end_date: str,
                               delay: float = 0.5) -> pd.DataFrame:
    """批量获取日线行情

    Args:
        symbols: 股票代码列表
        start_date/end_date: 日期
        delay: 每次请求间隔（秒），避免被限流
    """
    all_dfs = []

    for i, code in enumerate(symbols):
        df = fetch_daily_quote_yf(code, start_date, end_date)
        if not df.empty:
            all_dfs.append(df)

        if (i + 1) % 50 == 0:
            logger.info(f"Yahoo Finance进度: {i+1}/{len(symbols)}")

        if delay > 0:
            time.sleep(delay)

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def fetch_stock_list_yf() -> pd.DataFrame:
    """获取A股股票列表（通过预定义列表+YF验证）

    由于Yahoo Finance没有直接的A股列表API，
    这里使用常见指数成分股 + 手动维护列表。
    实际使用中建议用AKShare（国内环境）或Tushare。
    """
    # 沪深300成分股 + 常用股票（示例）
    # 实际应从AKShare或本地文件获取完整列表
    common_stocks = [
        "600519", "000858", "601318", "600036", "000333",
        "600276", "601166", "000651", "600030", "601888",
        "300750", "002594", "000001", "600900", "601012",
        "600887", "601398", "600000", "000568", "002475",
        "603259", "688981", "300059", "002415", "600050",
        "601857", "600809", "000002", "600309", "002352",
    ]

    return pd.DataFrame({
        "code": common_stocks,
        "name": [f"股票{c}" for c in common_stocks],
    })


def fetch_market_index_yf(symbol: str = "000300",
                          start_date: str = "20200101",
                          end_date: str = None) -> pd.DataFrame:
    """获取市场指数

    Yahoo Finance指数代码:
    000300.SS (沪深300)
    000001.SS (上证指数)
    399006.SZ (创业板指)
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    yf_code = _to_yf_code(symbol)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    try:
        ticker = yf.Ticker(f"^{yf_code}")
        hist = ticker.history(start=start, end=end, auto_adjust=True)

        if hist.empty:
            # 尝试不带^前缀
            ticker = yf.Ticker(yf_code)
            hist = ticker.history(start=start, end=end, auto_adjust=True)

        if hist.empty:
            return pd.DataFrame()

        df = hist.reset_index()
        return pd.DataFrame({
            "index_code": symbol,
            "date": pd.to_datetime(df["Date"]),
            "open": df["Open"].values,
            "high": df["High"].values,
            "low": df["Low"].values,
            "close": df["Close"].values,
            "volume": df["Volume"].values.astype(float),
        })

    except Exception as e:
        logger.warning(f"指数 {symbol} 获取失败: {e}")
        return pd.DataFrame()
