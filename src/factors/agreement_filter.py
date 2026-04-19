"""多因子一致性过滤器 (Multi-Factor Agreement Filter)

灵感来源: GitHub ashare-neural-network项目的ensemble方法
核心思想: 只在多个因子维度(技术/基本面/资金)一致看多时才买入，
         降低单一维度假信号导致的错误交易。

A股30%胜率的根本原因: 单维度信号噪音太大。
解决方案: 要求至少3个维度中有2个看多才允许买入。
"""

import pandas as pd
import numpy as np
from loguru import logger


def check_factor_agreement(code: str, daily_df: pd.DataFrame,
                           financial_df: pd.DataFrame = None,
                           northbound_df: pd.DataFrame = None) -> dict:
    """检查多因子一致性

    Args:
        code: 股票代码
        daily_df: 日线行情
        financial_df: 财务数据
        northbound_df: 北向资金数据

    Returns:
        {
            "agree_count": 看多维度数,
            "total_dimensions": 总维度数,
            "agreement_ratio": 一致性比率,
            "pass": 是否通过一致性检查,
            "details": 各维度详情,
            "signal": "strong_buy" | "buy" | "neutral" | "reject"
        }
    """
    dimensions = {}

    stock_daily = daily_df[daily_df["code"] == code].tail(60) if "code" in daily_df.columns else daily_df.tail(60)

    # === 维度1: 技术面趋势 ===
    dimensions["trend"] = _check_trend(stock_daily)

    # === 维度2: 量价配合 ===
    dimensions["volume_price"] = _check_volume_price(stock_daily)

    # === 维度3: 基本面估值 ===
    if financial_df is not None and not financial_df.empty:
        dimensions["fundamental"] = _check_fundamental(code, financial_df)
    else:
        dimensions["fundamental"] = {"signal": 0, "reason": "无财务数据"}

    # === 维度4: 资金流向 ===
    if northbound_df is not None and not northbound_df.empty:
        dimensions["capital_flow"] = _check_capital_flow(code, northbound_df)
    else:
        dimensions["capital_flow"] = {"signal": 0, "reason": "无资金数据"}

    # === 维度5: 动量 ===
    dimensions["momentum"] = _check_momentum(stock_daily)

    # 汇总
    signals = [d["signal"] for d in dimensions.values()]
    agree_count = sum(1 for s in signals if s > 0)
    disagree_count = sum(1 for s in signals if s < 0)
    total = len(signals)
    agreement_ratio = agree_count / total if total > 0 else 0

    # 判定
    if agree_count >= 4 and disagree_count == 0:
        signal = "strong_buy"
        pass_check = True
    elif agree_count >= 3 and disagree_count <= 1:
        signal = "buy"
        pass_check = True
    elif agree_count >= 2 and disagree_count <= 1:
        signal = "neutral"
        pass_check = False  # 需要更多确认
    else:
        signal = "reject"
        pass_check = False

    return {
        "agree_count": agree_count,
        "disagree_count": disagree_count,
        "total_dimensions": total,
        "agreement_ratio": agreement_ratio,
        "pass": pass_check,
        "signal": signal,
        "details": dimensions,
    }


def _check_trend(daily: pd.DataFrame) -> dict:
    """趋势维度: MA5 > MA20 > MA60"""
    if len(daily) < 60:
        return {"signal": 0, "reason": "数据不足60天"}

    close = daily["close"].values
    ma5 = np.mean(close[-5:])
    ma20 = np.mean(close[-20:])
    ma60 = np.mean(close[-60:])
    current = close[-1]

    # 多头排列: MA5 > MA20 > MA60
    if ma5 > ma20 > ma60 and current > ma5:
        return {"signal": 1, "reason": f"多头排列 MA5={ma5:.2f}>MA20={ma20:.2f}>MA60={ma60:.2f}"}
    elif ma5 > ma20:
        return {"signal": 0.5, "reason": f"短期多头 MA5={ma5:.2f}>MA20={ma20:.2f}"}
    elif ma5 < ma20 < ma60:
        return {"signal": -1, "reason": f"空头排列 MA5={ma5:.2f}<MA20={ma20:.2f}<MA60={ma60:.2f}"}
    else:
        return {"signal": 0, "reason": "趋势不明确"}


def _check_volume_price(daily: pd.DataFrame) -> dict:
    """量价配合: 上涨放量 + 下跌缩量"""
    if len(daily) < 10 or "volume" not in daily.columns:
        return {"signal": 0, "reason": "无成交量数据"}

    recent = daily.tail(10)
    close = recent["close"].values
    vol = recent["volume"].values

    # 上涨天数 vs 下跌天数的量比
    up_vol = np.mean(vol[1:][np.diff(close) > 0]) if np.any(np.diff(close) > 0) else 0
    down_vol = np.mean(vol[1:][np.diff(close) < 0]) if np.any(np.diff(close) < 0) else 1

    if up_vol == 0 or down_vol == 0:
        return {"signal": 0, "reason": "量价数据不足"}

    ratio = up_vol / down_vol

    if ratio > 1.5 and close[-1] > close[0]:
        return {"signal": 1, "reason": f"上涨放量(量比={ratio:.1f})"}
    elif ratio > 1.2:
        return {"signal": 0.5, "reason": f"量价尚可(量比={ratio:.1f})"}
    elif ratio < 0.7:
        return {"signal": -1, "reason": f"下跌放量(量比={ratio:.1f})"}
    else:
        return {"signal": 0, "reason": f"量价中性(量比={ratio:.1f})"}


def _check_fundamental(code: str, financial: pd.DataFrame) -> dict:
    """基本面: PE/PB估值 + ROE"""
    if "code" in financial.columns:
        stock_fin = financial[financial["code"] == code]
    else:
        stock_fin = financial

    if stock_fin.empty:
        return {"signal": 0, "reason": "无该股财务数据"}

    row = stock_fin.iloc[-1]

    # PE评估
    pe = row.get("pe_ttm", row.get("pe", 0))
    if pe <= 0:
        pe_signal = -1
        pe_reason = f"亏损(PE={pe:.1f})"
    elif pe < 15:
        pe_signal = 1
        pe_reason = f"低估值(PE={pe:.1f})"
    elif pe < 30:
        pe_signal = 0.5
        pe_reason = f"合理估值(PE={pe:.1f})"
    elif pe > 60:
        pe_signal = -1
        pe_reason = f"高估值(PE={pe:.1f})"
    else:
        pe_signal = 0
        pe_reason = f"估值偏高(PE={pe:.1f})"

    # ROE评估
    roe = row.get("roe", 0)
    if roe > 15:
        roe_signal = 1
    elif roe > 8:
        roe_signal = 0.5
    elif roe < 0:
        roe_signal = -1
    else:
        roe_signal = 0

    signal = (pe_signal + roe_signal) / 2
    return {"signal": signal, "reason": f"{pe_reason}, ROE={roe:.1f}%"}


def _check_capital_flow(code: str, northbound: pd.DataFrame) -> dict:
    """资金流向: 北向资金近期是否流入"""
    if "code" in northbound.columns:
        stock_nb = northbound[northbound["code"] == code].tail(10)
    else:
        return {"signal": 0, "reason": "无个股北向数据"}

    if stock_nb.empty:
        return {"signal": 0, "reason": "无北向数据"}

    # 近5日净买入
    if "net_amount" in stock_nb.columns:
        recent_net = stock_nb["net_amount"].tail(5).sum()
        if recent_net > 1e7:  # 净流入>1000万
            return {"signal": 1, "reason": f"北向5日净流入¥{recent_net/1e6:.0f}M"}
        elif recent_net < -1e7:
            return {"signal": -1, "reason": f"北向5日净流出¥{recent_net/1e6:.0f}M"}

    return {"signal": 0, "reason": "北向资金中性"}


def _check_momentum(daily: pd.DataFrame) -> dict:
    """动量: 近5日/20日涨幅"""
    if len(daily) < 20:
        return {"signal": 0, "reason": "数据不足"}

    close = daily["close"].values
    ret_5 = (close[-1] / close[-6] - 1) * 100 if len(close) >= 6 else 0
    ret_20 = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0

    # 温和上涨最佳，暴涨有风险
    if 2 < ret_5 < 8 and ret_20 > 5:
        return {"signal": 1, "reason": f"温和上涨 5日+{ret_5:.1f}% 20日+{ret_20:.1f}%"}
    elif ret_5 > 10:
        return {"signal": -0.5, "reason": f"短期涨幅过大 5日+{ret_5:.1f}%"}  # 追高风险
    elif -3 < ret_5 < 2 and ret_20 > 0:
        return {"signal": 0.5, "reason": f"盘整偏强 20日+{ret_20:.1f}%"}
    elif ret_5 < -5:
        return {"signal": -1, "reason": f"短期下跌 5日{ret_5:.1f}%"}
    else:
        return {"signal": 0, "reason": f"动量中性 5日{ret_5:+.1f}%"}


def filter_by_agreement(scores: pd.DataFrame, daily_df: pd.DataFrame,
                        financial_df: pd.DataFrame = None,
                        northbound_df: pd.DataFrame = None,
                        min_agreement: float = 0.5) -> pd.DataFrame:
    """批量过滤: 只保留多因子一致性达标的股票

    Args:
        scores: 评分结果DataFrame
        daily_df: 日线行情
        financial_df: 财务数据
        northbound_df: 北向资金
        min_agreement: 最低一致性比率 (默认50%)

    Returns:
        过滤后的scores
    """
    rejected = []
    passed_codes = []

    for code in scores.index[:30]:  # 只检查Top30，减少计算
        result = check_factor_agreement(code, daily_df, financial_df, northbound_df)
        if result["pass"]:
            passed_codes.append(code)
        else:
            rejected.append((code, result["signal"], result["agree_count"]))

    if rejected:
        logger.info(
            f"多因子一致性过滤: {len(passed_codes)}只通过, "
            f"{len(rejected)}只被拒: "
            + ", ".join(f"{c}({s}/{5})" for c, s, _ in rejected[:5])
        )

    # 只保留通过的
    filtered = scores[scores.index.isin(passed_codes)]
    if filtered.empty:
        # 如果全部被过滤，放宽到neutral
        logger.warning("多因子一致性过滤: 全部被拒，保留Top5评分")
        return scores.head(5)

    return filtered
