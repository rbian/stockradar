"""Intraday Position Filter — 日内位置过滤

灵感来源: aurumq-rl (GitHub) board-aware price limit proximity check
核心发现: A股±10%/±20%涨跌停机制下，在日内高位(接近当日最高价)买入的股票
次日反转概率高，是"买入失误"模式的重要原因。

规则:
- 计算当前价格在当日(high-low)区间中的位置
- 如果位置>80%（即接近当日最高价），跳过买入
- 如果当日振幅<1%（近平盘），不做过滤（信号不明显）
"""

import pandas as pd
import numpy as np
from loguru import logger


def check_intraday_position(stock_data: pd.DataFrame, current_price: float = None) -> dict:
    """检查股票当前价格在日内区间的位置

    Args:
        stock_data: 含OHLC的DataFrame，最后一条是当日数据
        current_price: 实时价格（可选，默认用最新close）

    Returns:
        {"pass": bool, "position": float, "reason": str}
        position: 0.0=最低价, 1.0=最高价
    """
    if stock_data is None or len(stock_data) == 0:
        return {"pass": True, "position": 0.5, "reason": "无数据，放行"}

    latest = stock_data.iloc[-1]
    
    # 使用实时价格或最新收盘价
    price = current_price if current_price else latest.get('close', 0)
    
    today_high = latest.get('high', price)
    today_low = latest.get('low', price)
    today_open = latest.get('open', price)
    
    if today_high == today_low:
        # 平盘，无法判断位置
        return {"pass": True, "position": 0.5, "reason": "日内无振幅"}
    
    position = (price - today_low) / (today_high - today_low)
    
    # 振幅检查
    amplitude = (today_high - today_low) / today_open if today_open > 0 else 0
    if amplitude < 0.01:
        return {"pass": True, "position": position, "reason": f"振幅{amplitude*100:.1f}%过小"}
    
    # 涨幅检查: 相对开盘价
    daily_return = (price - today_open) / today_open if today_open > 0 else 0
    
    # 位置>85%且涨幅>5%: 追高风险
    if position > 0.85 and daily_return > 0.05:
        return {
            "pass": False,
            "position": position,
            "reason": f"日内位置{position*100:.0f}%+涨幅{daily_return*100:.1f}%，追高风险"
        }
    
    # 涨幅>7%: 接近涨停板（不管位置），极高风险
    if daily_return > 0.07:
        return {
            "pass": False,
            "position": position,
            "reason": f"日涨幅{daily_return*100:.1f}%，接近涨停板"
        }
    
    return {"pass": True, "position": position, "reason": f"位置{position*100:.0f}% 涨幅{daily_return*100:.1f}%"}


def should_skip_buy(stock_data: pd.DataFrame, current_price: float = None) -> tuple[bool, str]:
    """便捷接口: 是否应该跳过买入
    
    Returns:
        (skip: bool, reason: str)
    """
    result = check_intraday_position(stock_data, current_price)
    return (not result["pass"], result["reason"])
