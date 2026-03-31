"""LLM增强因子模块

三个LLM因子：
- calc_earnings_sentiment: 财报情绪因子
- calc_news_sentiment_7d: 7日新闻情绪因子
- calc_research_consensus: 研报一致性因子

这些函数被 engine.py 的 FactorEngine 调用，
返回 pd.Series (code → value)，值域 [-1, 1]。

降级策略：LLM不可用或无数据时返回0（中性），不影响核心流程。
"""

import asyncio
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.llm.client import LLMClient
from src.llm.parser import SCHEMAS


def _run_async(coro):
    """在同步上下文中运行异步函数"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已有事件循环（如Jupyter），用nest_asyncio或新线程
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


# ============ 财报情绪因子 ============

def _prepare_earnings_input(code: str, financial_df: pd.DataFrame) -> dict | None:
    """准备财报分析的输入数据"""
    if financial_df is None or financial_df.empty:
        return None

    code_data = financial_df[financial_df["code"] == code].sort_values("end_date")
    if len(code_data) < 1:
        return None

    latest = code_data.iloc[-1]
    prev = code_data.iloc[-2] if len(code_data) >= 2 else latest

    return {
        "code": code,
        "end_date": str(latest.get("end_date", "未知")),
        "revenue": f"{latest.get('revenue', 0):.0f}",
        "net_profit": f"{latest.get('net_profit', 0):.0f}",
        "roe": f"{latest.get('roe', 0):.2f}",
        "gross_margin": f"{latest.get('gross_margin', 0):.2f}",
        "net_margin": f"{latest.get('net_margin', 0):.2f}",
        "debt_ratio": f"{latest.get('debt_ratio', 0):.2f}",
        "ocf_ratio": f"{latest.get('ocf_ratio', 0):.2f}",
        "revenue_yoy": f"{latest.get('revenue_yoy', 0):.2f}",
        "profit_yoy": f"{latest.get('profit_yoy', 0):.2f}",
        "ar_ratio": f"{latest.get('ar_ratio', 0):.2f}",
        "goodwill_ratio": f"{latest.get('goodwill_ratio', 0):.2f}",
        "prev_roe": f"{prev.get('roe', 0):.2f}",
        "prev_gross_margin": f"{prev.get('gross_margin', 0):.2f}",
        "prev_revenue_yoy": f"{prev.get('revenue_yoy', 0):.2f}",
        "prev_profit_yoy": f"{prev.get('profit_yoy', 0):.2f}",
    }


def calc_earnings_sentiment(data: dict) -> pd.Series:
    """财报情绪因子

    从LLM缓存中获取财报分析结果，映射为 [-1, 1] 的情绪值。
    未分析的股票返回0（中性）。

    Args:
        data: engine传入的数据字典，包含:
            - codes: 股票代码列表
            - financial: 财务指标DataFrame
            - llm_client: LLMClient实例（可选）
            - store: DataStore实例（可选）

    Returns:
        pd.Series, index=code, values in [-1, 1]
    """
    codes = data.get("codes", [])
    financial = data.get("financial", pd.DataFrame())
    llm_client = data.get("llm_client")

    result = pd.Series(0.0, index=codes, name="earnings_sentiment")

    if llm_client is None or financial is None or financial.empty:
        return result

    # 构建批量任务（只处理有财务数据的股票）
    tasks = []
    task_codes = []
    for code in codes:
        input_data = _prepare_earnings_input(code, financial)
        if input_data is not None:
            tasks.append({
                "code": code,
                "analysis_type": "earnings",
                "input_data": input_data,
            })
            task_codes.append(code)

    if not tasks:
        return result

    # 批量调用
    try:
        responses = _run_async(llm_client.batch_analyze(tasks))
    except Exception as e:
        logger.warning(f"财报情绪批量分析失败: {e}")
        return result

    # 映射结果
    surprise_map = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
    for code, resp in zip(task_codes, responses):
        surprise = resp.get("surprise", "neutral")
        confidence = resp.get("confidence", 50)
        sentiment = surprise_map.get(surprise, 0.0) * (confidence / 100.0)
        result[code] = sentiment

    return result


# ============ 新闻情绪因子 ============

def calc_news_sentiment_7d(data: dict) -> pd.Series:
    """7日新闻情绪因子

    从LLM获取近7天新闻的情绪分析结果，返回 [-1, 1] 的情绪值。
    无新闻或LLM不可用返回0（中性）。

    Args:
        data: engine传入的数据字典，包含:
            - codes: 股票代码列表
            - news: 新闻DataFrame (code, title, source, publish_time, content)
            - llm_client: LLMClient实例（可选）

    Returns:
        pd.Series, index=code, values in [-1, 1]
    """
    codes = data.get("codes", [])
    news_df = data.get("news", pd.DataFrame())
    llm_client = data.get("llm_client")

    result = pd.Series(0.0, index=codes, name="news_sentiment_7d")

    if llm_client is None or news_df is None or news_df.empty:
        return result

    lookback_days = 7
    prompt_mgr = llm_client.prompt_mgr

    tasks = []
    task_codes = []
    for code in codes:
        code_news = news_df[news_df["code"] == code]
        if code_news.empty:
            continue

        news_items = code_news.to_dict("records")
        news_list_str = prompt_mgr.format_news_list(news_items)

        tasks.append({
            "code": code,
            "analysis_type": "news_sentiment",
            "input_data": {
                "code": code,
                "lookback_days": lookback_days,
                "news_list": news_list_str,
            },
        })
        task_codes.append(code)

    if not tasks:
        return result

    try:
        responses = _run_async(llm_client.batch_analyze(tasks))
    except Exception as e:
        logger.warning(f"新闻情绪批量分析失败: {e}")
        return result

    for code, resp in zip(task_codes, responses):
        sentiment = resp.get("sentiment", 0.0)
        # 已在parser中clamp到 [-1, 1]
        result[code] = float(sentiment)

    return result


# ============ 研报一致性因子 ============

def calc_research_consensus(data: dict) -> pd.Series:
    """研报一致性因子

    基于个股终审结果，综合评估研报/分析的一致性程度。
    返回 [-1, 1] 值：
      - decision="关注" → 正面
      - decision="观望" → 中性
      - decision="回避" → 负面
    结合risk_level进行调整。

    Args:
        data: engine传入的数据字典，包含:
            - codes: 股票代码列表
            - daily_score: 评分DataFrame (可选，用于终审输入)
            - llm_client: LLMClient实例（可选）

    Returns:
        pd.Series, index=code, values in [-1, 1]
    """
    codes = data.get("codes", [])
    llm_client = data.get("llm_client")
    daily_score = data.get("daily_score", pd.DataFrame())

    result = pd.Series(0.0, index=codes, name="research_consensus")

    if llm_client is None:
        return result

    # 构建终审任务（只处理有评分数据的股票）
    tasks = []
    task_codes = []
    for code in codes:
        input_data = _prepare_review_input(code, data)
        if input_data is not None:
            tasks.append({
                "code": code,
                "analysis_type": "stock_review",
                "input_data": input_data,
            })
            task_codes.append(code)

    if not tasks:
        return result

    try:
        responses = _run_async(llm_client.batch_analyze(tasks))
    except Exception as e:
        logger.warning(f"研报一致性批量分析失败: {e}")
        return result

    # 映射结果
    decision_map = {"关注": 1.0, "观望": 0.0, "回避": -1.0}
    risk_modifier = {"low": 0.1, "medium": 0.0, "high": -0.1}

    for code, resp in zip(task_codes, responses):
        decision = resp.get("decision", "观望")
        risk_level = resp.get("risk_level", "medium")

        base = decision_map.get(decision, 0.0)
        modifier = risk_modifier.get(risk_level, 0.0)
        value = np.clip(base + modifier, -1.0, 1.0)
        result[code] = value

    return result


def _prepare_review_input(code: str, data: dict) -> dict | None:
    """准备个股终审的输入数据"""
    daily_score = data.get("daily_score", pd.DataFrame())

    if daily_score is None or daily_score.empty:
        return None

    if code not in daily_score.index:
        return None

    row = daily_score.loc[code]

    return {
        "code": code,
        "score_total": f"{row.get('score_total', 0):.2f}",
        "rank": int(row.get("rank", 0)),
        "score_fundamental": f"{row.get('score_fundamental', 0):.2f}",
        "score_technical": f"{row.get('score_technical', 0):.2f}",
        "score_capital": f"{row.get('score_capital', 0):.2f}",
        "delta_s": f"{row.get('delta_s', 0):.2f}",
        "close_price": "N/A",
        "change_20d": "N/A",
        "volatility_20d": "N/A",
        "earnings_summary": "暂无财报分析",
        "news_summary": "暂无新闻分析",
    }
