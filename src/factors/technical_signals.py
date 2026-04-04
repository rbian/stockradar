"""Technical buy/signal scoring for StockRadar

Based on stock-daily-analysis skill's framework:
- MA trend scoring (bullish/bearish alignment)
- MACD signal scoring
- RSI zone scoring
- Bias (乖离率) scoring
- Volume-price divergence
- Composite buy signal score (0-100)

Enhances Trader agent's decision-making.
"""

import numpy as np
import pandas as pd
from loguru import logger


def calc_ma(prices: pd.Series, window: int) -> pd.Series:
    return prices.rolling(window=window).mean()


def calc_ema(prices: pd.Series, window: int) -> pd.Series:
    return prices.ewm(span=window, adjust=False).mean()


def calc_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """Returns (macd_line, signal_line, histogram)"""
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_bias(prices: pd.Series, ma: pd.Series) -> pd.Series:
    """Bias = (price - MA) / MA * 100"""
    return (prices - ma) / ma * 100


def score_stock(stock_data: pd.DataFrame) -> dict:
    """Score a single stock's technical signals

    Args:
        stock_data: DataFrame with columns close, high, low, volume (at least 30 rows)

    Returns:
        Dict with individual scores and composite signal_score (0-100)
    """
    if len(stock_data) < 30:
        return {"signal_score": 50, "signal": "数据不足", "details": {}}

    close = stock_data["close"]
    volume = stock_data.get("volume", pd.Series(dtype=float))

    # ── 1. MA Trend Score (0-25) ──
    ma5 = calc_ma(close, 5)
    ma10 = calc_ma(close, 10)
    ma20 = calc_ma(close, 20)

    latest = close.iloc[-1]
    ma5_v = ma5.iloc[-1]
    ma10_v = ma10.iloc[-1]
    ma20_v = ma20.iloc[-1]

    # Bullish alignment: price > MA5 > MA10 > MA20
    if latest > ma5_v > ma10_v > ma20_v:
        ma_score = 25
        ma_status = "多头排列"
    elif latest > ma5_v > ma10_v:
        ma_score = 20
        ma_status = "短多"
    elif latest > ma20_v:
        ma_score = 15
        ma_status = "偏多"
    elif latest < ma5_v < ma10_v < ma20_v:
        ma_score = 5
        ma_status = "空头排列"
    else:
        ma_score = 12
        ma_status = "震荡"

    # ── 2. MACD Score (0-20) ──
    macd_line, signal_line, histogram = calc_macd(close)
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_val = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0

    if macd_val > signal_val and hist_val > 0:
        if prev_hist <= 0:
            macd_score = 20  # Fresh golden cross
            macd_status = "金叉"
        else:
            macd_score = 16
            macd_status = "多头"
    elif macd_val < signal_val and hist_val < 0:
        if prev_hist >= 0:
            macd_score = 3  # Fresh death cross
            macd_status = "死叉"
        else:
            macd_score = 6
            macd_status = "空头"
    else:
        macd_score = 10
        macd_status = "中性"

    # ── 3. RSI Score (0-20) ──
    rsi = calc_rsi(close)
    rsi_val = rsi.iloc[-1]

    if pd.isna(rsi_val):
        rsi_score = 10
        rsi_status = "N/A"
    elif 40 <= rsi_val <= 60:
        rsi_score = 18
        rsi_status = "中性偏强"
    elif 30 <= rsi_val < 40:
        rsi_score = 15
        rsi_status = "偏弱(潜在反弹)"
    elif 20 <= rsi_val < 30:
        rsi_score = 20  # Oversold = buy opportunity
        rsi_status = "超卖(买入机会)"
    elif 60 < rsi_val <= 70:
        rsi_score = 14
        rsi_status = "偏强"
    elif rsi_val > 70:
        rsi_score = 8  # Overbought = caution
        rsi_status = "超买(注意回调)"
    else:
        rsi_score = 10
        rsi_status = "中性"

    # ── 4. Bias Score (0-15) ──
    bias5 = calc_bias(close, ma5).iloc[-1]
    bias20 = calc_bias(close, ma20).iloc[-1]

    if -2 <= bias5 <= 2 and -5 <= bias20 <= 5:
        bias_score = 12
        bias_status = "合理区间"
    elif bias5 < -3:
        bias_score = 15  # Oversold = opportunity
        bias_status = f"乖离偏大({bias5:+.1f}%)，可能反弹"
    elif bias5 > 5:
        bias_score = 5
        bias_status = f"乖离过大({bias5:+.1f}%)，注意回落"
    else:
        bias_score = 10
        bias_status = "正常"

    # ── 5. Volume-Price Score (0-20) ──
    if not volume.empty and len(volume) >= 10:
        vol_ma5 = volume.tail(6).iloc[:-1].mean()
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / vol_ma5 if vol_ma5 > 0 else 1
        price_up = close.iloc[-1] > close.iloc[-2]

        if price_up and vol_ratio > 1.5:
            vp_score = 20  # 量价齐升
            vp_status = "放量上涨"
        elif not price_up and vol_ratio < 0.7:
            vp_score = 16  # 缩量下跌(正常调整)
            vp_status = "缩量回调"
        elif price_up and vol_ratio < 0.7:
            vp_score = 10
            vp_status = "缩量上涨"
        elif not price_up and vol_ratio > 1.5:
            vp_score = 4  # 放量下跌
            vp_status = "放量下跌"
        else:
            vp_score = 12
            vp_status = "量价正常"
    else:
        vp_score = 10
        vp_status = "N/A"

    # ── Composite ──
    total = ma_score + macd_score + rsi_score + bias_score + vp_score

    if total >= 80:
        signal = "强烈买入"
    elif total >= 65:
        signal = "买入"
    elif total >= 50:
        signal = "观望"
    elif total >= 35:
        signal = "卖出"
    else:
        signal = "强烈卖出"

    return {
        "signal_score": total,
        "signal": signal,
        "details": {
            "ma": {"score": ma_score, "status": ma_status},
            "macd": {"score": macd_score, "status": macd_status},
            "rsi": {"score": rsi_score, "status": rsi_status, "value": round(rsi_val, 1) if not pd.isna(rsi_val) else None},
            "bias": {"score": bias_score, "status": bias_status},
            "volume_price": {"score": vp_score, "status": vp_status},
        },
    }


def batch_score(daily_quote: pd.DataFrame, codes: list[str] = None) -> pd.DataFrame:
    """Score multiple stocks

    Returns DataFrame with code, signal_score, signal for each stock
    """
    results = []
    if codes is None:
        codes = daily_quote["code"].unique()

    for code in codes:
        stock_data = daily_quote[daily_quote["code"] == code].tail(60)
        if len(stock_data) < 30:
            continue
        result = score_stock(stock_data)
        results.append({
            "code": code,
            "signal_score": result["signal_score"],
            "signal": result["signal"],
            "ma": result["details"]["ma"]["status"],
            "macd": result["details"]["macd"]["status"],
            "rsi": result["details"]["rsi"].get("value"),
        })

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("signal_score", ascending=False)
    return df


def format_signal_report(scores: list[dict], stock_names: dict = None) -> str:
    """Format signal scores into readable report"""
    if not scores:
        return "暂无技术信号数据"

    names = stock_names or {}
    lines = ["📊 **技术信号评分**\n"]

    for s in scores[:10]:
        name = names.get(s["code"], s["code"])
        score = s["signal_score"]
        bar = "█" * (score // 5) + "░" * (20 - score // 5)
        lines.append(f"  **{name}** [{bar}] {score}分 {s['signal']}")

    return "\n".join(lines)
