"""Enhanced alert system for StockRadar

Based on stock-monitor skill's 7-rule alert framework:
1. Cost percentage (profit/loss vs cost)
2. Daily price change
3. Volume anomaly (surge/shrink)
4. MA golden/death cross
5. RSI overbought/oversold
6. Gap detection
7. Dynamic trailing stop

Integrates with NAVTracker holdings and risk_control.py
"""

import numpy as np
import pandas as pd
from loguru import logger


# ── Technical helpers ──

def calc_ma(prices: pd.Series, window: int) -> pd.Series:
    return prices.rolling(window=window).mean()


def calc_rsi(prices: pd.Series, period: int = 14) -> float:
    """Calculate latest RSI value"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    return round(100 - (100 / (1 + rs)), 1)


def detect_ma_cross(ma5: pd.Series, ma10: pd.Series) -> str:
    """Detect MA5/MA10 golden cross or death cross"""
    if len(ma5) < 2 or len(ma10) < 2:
        return ""
    prev_diff = ma5.iloc[-2] - ma10.iloc[-2]
    curr_diff = ma5.iloc[-1] - ma10.iloc[-1]
    if prev_diff <= 0 and curr_diff > 0:
        return "golden_cross"
    elif prev_diff >= 0 and curr_diff < 0:
        return "death_cross"
    return ""


def detect_gap(today_open: float, prev_high: float, prev_low: float) -> str:
    """Detect price gap"""
    if prev_high > 0 and today_open > prev_high * 1.01:
        return f"gap_up +{(today_open/prev_high-1)*100:.1f}%"
    if prev_low > 0 and today_open < prev_low * 0.99:
        return f"gap_down -{(1-today_open/prev_low)*100:.1f}%"
    return ""


# ── Main alert checker ──

def check_alerts(holdings: dict, daily_quote: pd.DataFrame) -> list[dict]:
    """Check all alert rules for current holdings

    Args:
        holdings: {code: {shares, cost_price}}
        daily_quote: DataFrame with columns code, date, open, high, low, close, volume

    Returns:
        List of alert dicts: [{code, name, type, level, message}]
    """
    alerts = []

    for code, pos in holdings.items():
        cost = pos.get("cost_price", 0)
        shares = pos.get("shares", 0)
        if cost <= 0 or shares <= 0:
            continue

        # Get stock data (last 30 days)
        stock_data = daily_quote[daily_quote["code"] == code].tail(30)
        if len(stock_data) < 2:
            continue

        latest = stock_data.iloc[-1]
        prev = stock_data.iloc[-2]
        price = latest["close"]
        prev_close = prev["close"]

        # 1. Cost percentage
        cost_pct = (price - cost) / cost * 100
        if cost_pct >= 15:
            alerts.append({
                "code": code, "type": "cost_above",
                "level": "🚨", "pct": cost_pct,
                "message": f"盈利+{cost_pct:.1f}% (成本¥{cost:.2f}→现价¥{price:.2f})",
            })
        elif cost_pct <= -12:
            alerts.append({
                "code": code, "type": "cost_below",
                "level": "🚨", "pct": cost_pct,
                "message": f"亏损{cost_pct:.1f}% (成本¥{cost:.2f}→现价¥{price:.2f})，建议止损",
            })

        # 2. Daily change
        change_pct = (price - prev_close) / prev_close * 100
        if abs(change_pct) >= 5:
            emoji = "📈" if change_pct > 0 else "📉"
            alerts.append({
                "code": code, "type": "daily_change",
                "level": "⚠️", "pct": change_pct,
                "message": f"{emoji} 日涨跌{change_pct:+.1f}%",
            })

        # 3. Volume anomaly
        if "volume" in stock_data.columns:
            vol_ma5 = stock_data["volume"].tail(6).iloc[:-1].mean()
            current_vol = latest["volume"]
            if vol_ma5 > 0:
                vol_ratio = current_vol / vol_ma5
                if vol_ratio >= 2.0:
                    alerts.append({
                        "code": code, "type": "volume_surge",
                        "level": "📢", "pct": 0,
                        "message": f"📊 放量{vol_ratio:.1f}倍 (5日均量对比)",
                    })
                elif vol_ratio <= 0.5:
                    alerts.append({
                        "code": code, "type": "volume_shrink",
                        "level": "📢", "pct": 0,
                        "message": f"📉 缩量{vol_ratio:.1f}倍",
                    })

        # 4 & 5. MA cross and RSI
        if len(stock_data) >= 20:
            ma5 = calc_ma(stock_data["close"], 5)
            ma10 = calc_ma(stock_data["close"], 10)

            cross = detect_ma_cross(ma5, ma10)
            if cross == "golden_cross":
                alerts.append({
                    "code": code, "type": "golden_cross",
                    "level": "⚠️", "pct": 0,
                    "message": f"🌟 MA5金叉MA10 (MA5={ma5.iloc[-1]:.2f})",
                })
            elif cross == "death_cross":
                alerts.append({
                    "code": code, "type": "death_cross",
                    "level": "⚠️", "pct": 0,
                    "message": f"⚠️ MA5死叉MA10 (MA5={ma5.iloc[-1]:.2f})",
                })

            # RSI
            rsi = calc_rsi(stock_data["close"])
            if rsi > 70:
                alerts.append({
                    "code": code, "type": "rsi_overbought",
                    "level": "📢", "pct": 0,
                    "message": f"🔥 RSI超买({rsi})，注意回调风险",
                })
            elif rsi < 30:
                alerts.append({
                    "code": code, "type": "rsi_oversold",
                    "level": "📢", "pct": 0,
                    "message": f"❄️ RSI超卖({rsi})，可能反弹",
                })

        # 6. Gap detection
        today_open = latest.get("open", price)
        gap = detect_gap(today_open, prev.get("high", prev_close), prev.get("low", prev_close))
        if gap:
            alerts.append({
                "code": code, "type": "gap",
                "level": "📢", "pct": 0,
                "message": f"⬆️ 跳空{gap}" if "up" in gap else f"⬇️ 跳空{gap}",
            })

        # 7. Dynamic trailing stop (profit > 10%, then trailing 5%)
        if cost_pct > 10:
            recent_high = stock_data["high"].tail(5).max()
            drawdown_from_high = (price - recent_high) / recent_high * 100
            if drawdown_from_high <= -5:
                alerts.append({
                    "code": code, "type": "trailing_stop",
                    "level": "🚨", "pct": drawdown_from_high,
                    "message": f"🛑 动态止盈触发: 从近期高点回落{drawdown_from_high:.1f}%",
                })

    # Sort by level priority
    level_order = {"🚨": 0, "⚠️": 1, "📢": 2}
    alerts.sort(key=lambda a: level_order.get(a["level"], 9))

    return alerts


# ── Auto-sell rules ──
# Auto-sell on stop-loss / trailing stop
AUTO_SELL_TYPES = {"cost_below", "trailing_stop"}

# Auto-buy signals
AUTO_BUY_TYPES = {"rsi_oversold", "golden_cross", "gap_up"}


def get_auto_sell_codes(alerts: list[dict]) -> list[str]:
    """Extract codes that should be auto-sold"""
    return [a["code"] for a in alerts if a["type"] in AUTO_SELL_TYPES]


def get_buy_signals(alerts: list[dict]) -> list[dict]:
    """Extract buy signals from alerts (for held stocks showing reversal)"""
    return [a for a in alerts if a["type"] in AUTO_BUY_TYPES]


def format_alerts(alerts: list[dict], stock_names: dict = None) -> str:
    """Format alerts into Telegram-friendly message"""
    if not alerts:
        return "✅ 持仓无预警，整体健康"

    names = stock_names or {}
    lines = [f"🔔 **持仓预警** ({len(alerts)}条)\n"]

    for a in alerts:
        name = names.get(a["code"], a["code"])
        lines.append(f"  {a['level']} **{name}**: {a['message']}")

    return "\n".join(lines)
