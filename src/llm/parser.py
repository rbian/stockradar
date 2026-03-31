"""LLM输出解析与校验模块

核心原则：解析失败返回默认值而非抛异常，确保不影响核心流程。
"""

import json
import re
from typing import Any

from loguru import logger


# ============ 各分析类型的Schema定义 ============

SCHEMAS = {
    "earnings": {
        "required_fields": ["surprise", "confidence", "highlights", "risks", "trend", "one_line"],
        "defaults": {
            "surprise": "neutral",
            "confidence": 50,
            "highlights": [],
            "risks": [],
            "trend": "neutral",
            "one_line": "财报分析暂不可用",
        },
        "value_ranges": {
            "confidence": (0, 100),
            "surprise": ["positive", "neutral", "negative"],
            "trend": ["improving", "stable", "declining", "neutral"],
        },
    },
    "news_sentiment": {
        "required_fields": ["sentiment", "key_events", "summary", "action_hint"],
        "defaults": {
            "sentiment": 0.0,
            "key_events": [],
            "summary": "新闻情绪分析暂不可用",
            "action_hint": "hold",
        },
        "value_ranges": {
            "sentiment": (-1.0, 1.0),
            "action_hint": ["buy", "hold", "sell", "watch"],
        },
    },
    "stock_review": {
        "required_fields": ["decision", "reason", "strengths", "weaknesses", "risk_level"],
        "defaults": {
            "decision": "观望",
            "reason": "个股终审暂不可用",
            "strengths": [],
            "weaknesses": [],
            "risk_level": "medium",
        },
        "value_ranges": {
            "decision": ["关注", "观望", "回避"],
            "risk_level": ["low", "medium", "high"],
        },
    },
}


def extract_json(raw_text: str) -> str | None:
    """从LLM输出中提取JSON字符串

    容忍LLM在JSON前后加废话、markdown代码块等。
    策略：
    1. 尝试直接解析整个文本
    2. 提取 ```json ... ``` 代码块
    3. 提取 ``` ... ``` 代码块
    4. 查找最外层 { } 配对
    5. 查找最外层 [ ] 配对
    """
    if not raw_text or not raw_text.strip():
        return None

    text = raw_text.strip()

    # 1. 直接解析
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json ... ```
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 3. 提取 ``` ... ```
    m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 4. 查找最外层 { }
    start = text.find("{")
    if start != -1:
        # 从后往前找最后一个 }
        end = text.rfind("}")
        if end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

    # 5. 查找最外层 [ ]
    start = text.find("[")
    if start != -1:
        end = text.rfind("]")
        if end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

    return None


def validate_field(field: str, value: Any, schema: dict) -> Any:
    """校验单个字段的值范围，不合法则返回默认值"""
    ranges = schema.get("value_ranges", {})
    defaults = schema.get("defaults", {})

    if field not in ranges:
        return value

    constraint = ranges[field]

    if isinstance(constraint, tuple) and len(constraint) == 2:
        # 数值范围
        low, high = constraint
        if isinstance(value, (int, float)):
            return max(low, min(high, value))
        return defaults.get(field, value)

    if isinstance(constraint, list):
        # 枚举值
        if value in constraint:
            return value
        return defaults.get(field, value)

    return value


def parse_llm_json(raw_text: str, analysis_type: str) -> dict:
    """解析并校验LLM输出

    Args:
        raw_text: LLM原始输出文本
        analysis_type: 分析类型 (earnings / news_sentiment / stock_review)

    Returns:
        解析后的dict，解析失败返回默认值
    """
    schema = SCHEMAS.get(analysis_type)
    if schema is None:
        logger.warning(f"未知分析类型: {analysis_type}，返回空结果")
        return {}

    defaults = schema["defaults"]

    # 提取JSON
    json_str = extract_json(raw_text)
    if json_str is None:
        logger.warning(f"[{analysis_type}] 无法从LLM输出中提取JSON，使用默认值")
        return dict(defaults)

    # 解析JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning(f"[{analysis_type}] JSON解析失败，使用默认值")
        return dict(defaults)

    if not isinstance(data, dict):
        logger.warning(f"[{analysis_type}] JSON不是dict类型，使用默认值")
        return dict(defaults)

    # 补全缺失字段 + 校验值范围
    result = dict(defaults)
    for field in schema["required_fields"]:
        if field in data and data[field] is not None:
            validated = validate_field(field, data[field], schema)
            result[field] = validated

    return result
