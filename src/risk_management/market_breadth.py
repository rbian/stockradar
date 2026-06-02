"""市场宽度指标 — 诊断工具

计算HS300成分股涨跌比例，辅助判断市场整体强弱。
用于日志记录和买入决策参考，当前仅诊断不直接阻断交易。

核心指标:
- advance_ratio: 上涨股比例 (>0.5 偏多, <0.4 偏空)
- average_change: 平均涨跌幅
- breadth_signal: 市场宽度信号 (bullish/neutral/bearish)
"""

import pandas as pd
import numpy as np
from loguru import logger
from pathlib import Path


def calc_market_breadth(dq_full: pd.DataFrame, lookback_days: int = 1) -> dict:
    """计算市场宽度指标
    
    Args:
        dq_full: 完整行情数据 (code, date, close, open, etc.)
        lookback_days: 回看天数，1=今日
        
    Returns:
        dict: {advance_ratio, average_change, breadth_signal, total_stocks}
    """
    try:
        if dq_full is None or dq_full.empty:
            return _empty_result()
        
        # 获取最新交易日数据
        if 'date' in dq_full.columns:
            latest_date = dq_full['date'].max()
            today_data = dq_full[dq_full['date'] == latest_date]
        else:
            today_data = dq_full.tail(300)  # fallback
        
        if today_data.empty:
            return _empty_result()
        
        # 计算当日涨跌幅
        if 'pct_change' in today_data.columns:
            changes = today_data['pct_change'].dropna()
        elif 'close' in today_data.columns and 'open' in today_data.columns:
            changes = ((today_data['close'] - today_data['open']) / today_data['open'] * 100).dropna()
        elif 'close' in today_data.columns:
            # 需要前一日收盘价
            codes = today_data['code'].unique() if 'code' in today_data.columns else []
            prev_close = {}
            for code in codes:
                code_data = dq_full[dq_full['code'] == code].sort_values('date') if 'date' in dq_full.columns else dq_full[dq_full['code'] == code]
                if len(code_data) >= 2:
                    prev_close[code] = float(code_data.iloc[-2]['close'])
            changes_list = []
            for _, row in today_data.iterrows():
                code = row.get('code', '')
                if code in prev_close and prev_close[code] > 0:
                    chg = (row['close'] - prev_close[code]) / prev_close[code] * 100
                    changes_list.append(chg)
            changes = pd.Series(changes_list)
        else:
            return _empty_result()
        
        if len(changes) == 0:
            return _empty_result()
        
        advancing = (changes > 0).sum()
        declining = (changes < 0).sum()
        total = len(changes)
        advance_ratio = advancing / total if total > 0 else 0.5
        avg_change = changes.mean()
        
        # 市场宽度信号
        if advance_ratio >= 0.6 and avg_change > 0.3:
            signal = "bullish"
        elif advance_ratio <= 0.4 and avg_change < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"
        
        return {
            'advance_ratio': round(advance_ratio, 3),
            'average_change': round(avg_change, 3),
            'breadth_signal': signal,
            'total_stocks': total,
            'advancing': int(advancing),
            'declining': int(declining),
            'date': str(latest_date)[:10] if 'date' in dq_full.columns else 'unknown',
        }
    except Exception as e:
        logger.debug(f"市场宽度计算失败: {e}")
        return _empty_result()


def _empty_result() -> dict:
    return {
        'advance_ratio': 0.5,
        'average_change': 0.0,
        'breadth_signal': 'unknown',
        'total_stocks': 0,
        'advancing': 0,
        'declining': 0,
        'date': '',
    }


def log_market_breadth(dq_full: pd.DataFrame) -> dict:
    """计算并记录市场宽度（用于alert_check日志）
    
    Returns the breadth dict for further use.
    """
    breadth = calc_market_breadth(dq_full)
    if breadth['total_stocks'] > 0:
        logger.info(
            f"📊 市场宽度: {breadth['breadth_signal']} "
            f"(涨{breadth['advancing']}/跌{breadth['declining']}/{breadth['total_stocks']}只, "
            f"比例{breadth['advance_ratio']:.1%}, 均幅{breadth['average_change']:+.2f}%)"
        )
    return breadth
