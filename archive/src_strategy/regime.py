"""市场状态识别 - Regime Detection

基于大盘指数和情绪指标判断当前市场状态：
- trend: 趋势市（上涨或下跌趋势明确）
- range: 震荡市（无明显趋势）
- volatile: 高波动市（波动率异常升高）
- crisis: 危机模式（急跌、恐慌性抛售）

影响：
- trend → 正常交易
- range → 谨慎交易，降低换仓频率
- volatile → 减仓，收紧止损
- crisis → 风控优先，全体减仓
"""

import numpy as np
import pandas as pd
from loguru import logger


def detect_regime(data: dict, date, lookback: int = 20) -> str:
    """识别当前市场状态

    Args:
        data: 数据字典，需含:
            - market_index: 大盘指数日线DataFrame（沪深300或上证指数）
            - market_sentiment: 大盘情绪DataFrame（涨跌家数等，可选）
        date: 当前日期
        lookback: 回看天数（默认20）

    Returns:
        市场状态: "trend" / "range" / "volatile" / "crisis"
    """
    market_index = data.get("market_index", pd.DataFrame())
    market_sentiment = data.get("market_sentiment", pd.DataFrame())

    if market_index is None or market_index.empty:
        logger.warning("大盘指数数据为空，默认range模式")
        return "range"

    date_ts = pd.Timestamp(date)

    # 取最近lookback天的大盘数据
    recent = market_index[market_index["date"] <= date_ts].sort_values("date")
    if len(recent) < lookback:
        lookback = len(recent)
    recent = recent.tail(lookback)

    if recent.empty or len(recent) < 5:
        logger.warning("大盘指数数据不足，默认range模式")
        return "range"

    # ====== 危机检测（最高优先级） ======
    crisis_score = _calc_crisis_score(recent, market_sentiment, date_ts)
    if crisis_score >= 3:
        logger.warning(f"市场状态: crisis（危机评分{crisis_score}）")
        return "crisis"

    # ====== 波动率检测 ======
    volatility_score = _calc_volatility_score(recent)

    # ====== 趋势检测 ======
    trend_score = _calc_trend_score(recent)

    # ====== 综合判断 ======
    if volatility_score > 0.7:
        regime = "volatile"
    elif abs(trend_score) > 0.5:
        regime = "trend"
    else:
        regime = "range"

    # 情绪修正
    sentiment_mod = _calc_sentiment_modifier(market_sentiment, date_ts)
    if sentiment_mod < -0.5 and regime == "trend" and trend_score < 0:
        regime = "crisis"
    elif sentiment_mod < -0.3 and regime == "range":
        regime = "volatile"

    logger.info(
        f"市场状态: {regime} "
        f"(趋势{trend_score:+.2f}, 波动{volatility_score:.2f}, "
        f"情绪修正{sentiment_mod:+.2f})"
    )

    return regime


def _calc_crisis_score(recent_index: pd.DataFrame,
                       sentiment: pd.DataFrame,
                       date_ts: pd.Timestamp) -> int:
    """计算危机评分

    危机信号：
    1. 近5日累计跌幅 > 10%
    2. 单日跌幅 > 5%
    3. 跌停家数 > 涨停家数 × 3
    4. AD比率（涨跌比）< 0.2
    5. 近20日最大回撤 > 15%
    """
    score = 0
    closes = recent_index["close"].values

    # 1. 近5日累计跌幅
    if len(closes) >= 5:
        recent_5d_return = (closes[-1] / closes[-6] - 1) if len(closes) > 5 else 0
        if recent_5d_return < -0.10:
            score += 2
        elif recent_5d_return < -0.05:
            score += 1

    # 2. 单日跌幅 > 5%
    if len(closes) >= 2:
        last_day_return = closes[-1] / closes[-2] - 1
        if last_day_return < -0.05:
            score += 2
        elif last_day_return < -0.03:
            score += 1

    # 3. 近20日最大回撤 > 15%
    peak = np.maximum.accumulate(closes)
    drawdown = (closes - peak) / peak
    max_dd = drawdown.min()
    if max_dd < -0.15:
        score += 2
    elif max_dd < -0.10:
        score += 1

    # 4. 情绪数据：跌停 >> 涨停
    if sentiment is not None and not sentiment.empty:
        sentiment_today = sentiment[sentiment["date"] == date_ts]
        if not sentiment_today.empty:
            row = sentiment_today.iloc[0]
            limit_up = int(row.get("limit_up", 0))
            limit_down = int(row.get("limit_down", 0))
            if limit_down > max(limit_up * 3, 50):
                score += 2

            # 5. AD比率 < 0.2
            ad_ratio = float(row.get("ad_ratio", 0.5))
            if ad_ratio < 0.2:
                score += 1

    return score


def _calc_volatility_score(recent_index: pd.DataFrame) -> float:
    """计算波动率评分 (0~1)

    使用近20日收益率标准差，与历史正常水平对比
    """
    closes = recent_index["close"].values
    if len(closes) < 2:
        return 0.0

    returns = np.diff(closes) / closes[:-1]
    vol = np.std(returns) * np.sqrt(252)  # 年化波动率

    # 正常市场波动率约 15-25%
    # 高波动 > 35%
    # 评分映射：vol 20% → 0.3, 40% → 0.7, 60% → 1.0
    score = min(max((vol - 0.15) / 0.45, 0.0), 1.0)

    return score


def _calc_trend_score(recent_index: pd.DataFrame) -> float:
    """计算趋势评分 (-1 ~ 1)

    正值=上涨趋势，负值=下跌趋势，接近0=震荡
    使用均线偏离度和动量判断
    """
    closes = recent_index["close"].values
    if len(closes) < 10:
        return 0.0

    # 短期均线 vs 长期均线
    ma_short = np.mean(closes[-5:])
    ma_long = np.mean(closes[-20:]) if len(closes) >= 20 else np.mean(closes)
    ma_deviation = (ma_short / ma_long - 1) * 10  # 放大信号

    # 动量（近10日涨跌幅）
    momentum = (closes[-1] / closes[-min(10, len(closes)-1)] - 1) * 10

    # 综合评分
    score = (ma_deviation + momentum) / 2
    return np.clip(score, -1.0, 1.0)


def _calc_sentiment_modifier(sentiment: pd.DataFrame,
                             date_ts: pd.Timestamp) -> float:
    """情绪修正因子 (-1 ~ 0)

    极端恐慌时返回强负值
    """
    if sentiment is None or sentiment.empty:
        return 0.0

    recent = sentiment[sentiment["date"] <= date_ts].sort_values("date").tail(5)
    if recent.empty:
        return 0.0

    # AD比率均值
    ad_mean = recent["ad_ratio"].mean() if "ad_ratio" in recent.columns else 0.5

    # 正常 AD 约 0.5，极端恐慌 < 0.2
    # 修正值: 0.5→0, 0.2→-0.5, 0.1→-1.0
    modifier = min((ad_mean - 0.5) / 0.3, 0.0)

    return modifier


def get_regime_description(regime: str) -> str:
    """获取市场状态中文描述"""
    descriptions = {
        "trend": "趋势市",
        "range": "震荡市",
        "volatile": "高波动",
        "crisis": "危机模式",
    }
    return descriptions.get(regime, "未知")


def get_regime_action_hint(regime: str) -> str:
    """获取市场状态对应的操作建议"""
    hints = {
        "trend": "正常交易，跟随趋势",
        "range": "谨慎交易，降低换仓频率",
        "volatile": "减仓操作，收紧止损",
        "crisis": "风控优先，考虑全体减仓",
    }
    return hints.get(regime, "默认策略")
