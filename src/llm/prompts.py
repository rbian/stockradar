"""Prompt模板管理模块

每个Prompt有版本号，版本变更时prompt_hash会变，缓存自动失效。
"""

import hashlib
from typing import Any

from loguru import logger


# ============ Prompt模板定义 ============

_PROMPTS = {
    "earnings": {
        "version": "v1.0",
        "system": (
            "你是一位专业的A股财务分析师。请根据提供的财务数据进行分析。"
            "你必须严格按指定JSON格式输出，不要在JSON前后添加任何其他文字。"
        ),
        "template": (
            "请分析以下A股公司的最新财务数据：\n\n"
            "股票代码：{code}\n"
            "报告期：{end_date}\n\n"
            "## 当期财务数据\n"
            "营业收入：{revenue} 元\n"
            "净利润：{net_profit} 元\n"
            "ROE(净资产收益率)：{roe}%\n"
            "毛利率：{gross_margin}%\n"
            "净利率：{net_margin}%\n"
            "资产负债率：{debt_ratio}%\n"
            "经营现金流/净利润：{ocf_ratio}\n"
            "营收同比增长：{revenue_yoy}%\n"
            "净利润同比增长：{profit_yoy}%\n"
            "应收账款/营收：{ar_ratio}%\n"
            "商誉/净资产：{goodwill_ratio}%\n\n"
            "## 上期对比\n"
            "上期ROE：{prev_roe}%\n"
            "上期毛利率：{prev_gross_margin}%\n"
            "上期营收同比增长：{prev_revenue_yoy}%\n"
            "上期净利润同比增长：{prev_profit_yoy}%\n\n"
            "请严格按以下JSON格式输出分析结果：\n"
            "```json\n"
            "{{\n"
            '  "surprise": "positive或neutral或negative",\n'
            '  "confidence": 0到100的整数（置信度）,\n'
            '  "highlights": ["亮点1", "亮点2"],\n'
            '  "risks": ["风险1", "风险2"],\n'
            '  "trend": "improving或stable或declining或neutral",\n'
            '  "one_line": "一句话总结"\n'
            "}}\n"
            "```"
        ),
    },
    "news_sentiment": {
        "version": "v1.0",
        "system": (
            "你是一位专业的A股市场新闻分析师。请分析相关新闻的市场情绪和影响。"
            "你必须严格按指定JSON格式输出，不要在JSON前后添加任何其他文字。"
        ),
        "template": (
            "请分析以下A股公司近期新闻的市场情绪：\n\n"
            "股票代码：{code}\n"
            "分析时间窗口：近{lookback_days}天\n\n"
            "## 新闻列表\n"
            "{news_list}\n\n"
            "请严格按以下JSON格式输出分析结果：\n"
            "```json\n"
            "{{\n"
            '  "sentiment": -1.0到1.0之间的浮点数（-1极度悲观，0中性，1极度乐观）,\n'
            '  "key_events": ["关键事件1", "关键事件2"],\n'
            '  "summary": "新闻情绪概要",\n'
            '  "action_hint": "buy或hold或sell或watch"\n'
            "}}\n"
            "```"
        ),
    },
    "stock_review": {
        "version": "v1.0",
        "system": (
            "你是一位资深A股投资顾问。请综合多维度信息给出个股投资建议。"
            "你必须严格按指定JSON格式输出，不要在JSON前后添加任何其他文字。"
        ),
        "template": (
            "请综合以下信息，对A股给出投资建议：\n\n"
            "股票代码：{code}\n\n"
            "## 多因子评分\n"
            "总评分：{score_total}（排名#{rank}）\n"
            "基本面评分：{score_fundamental}\n"
            "技术面评分：{score_technical}\n"
            "资金面评分：{score_capital}\n"
            "评分动量ΔS：{delta_s}\n\n"
            "## 近期行情\n"
            "最新收盘价：{close_price}\n"
            "20日涨跌幅：{change_20d}%\n"
            "20日波动率：{volatility_20d}%\n\n"
            "## 财报分析摘要\n"
            "{earnings_summary}\n\n"
            "## 近期新闻摘要\n"
            "{news_summary}\n\n"
            "请严格按以下JSON格式输出：\n"
            "```json\n"
            "{{\n"
            '  "decision": "关注或观望或回避",\n'
            '  "reason": "决策理由（2-3句话）",\n'
            '  "strengths": ["优势1", "优势2"],\n'
            '  "weaknesses": ["劣势1", "劣势2"],\n'
            '  "risk_level": "low或medium或high"\n'
            "}}\n"
            "```"
        ),
    },
}


class PromptManager:
    """Prompt模板管理器

    功能：
    - 获取渲染后的Prompt
    - 计算Prompt哈希（用于缓存失效）
    - 版本管理
    """

    def __init__(self):
        self._prompts = _PROMPTS

    def get(self, analysis_type: str, **kwargs: Any) -> tuple[str, str]:
        """获取渲染后的(system_prompt, user_prompt)

        Args:
            analysis_type: 分析类型
            **kwargs: 模板变量

        Returns:
            (system_prompt, user_prompt)
        """
        prompt_def = self._prompts.get(analysis_type)
        if prompt_def is None:
            raise ValueError(f"未知的分析类型: {analysis_type}")

        user_prompt = prompt_def["template"].format(**kwargs)
        return prompt_def["system"], user_prompt

    def get_version(self, analysis_type: str) -> str:
        """获取Prompt版本号"""
        prompt_def = self._prompts.get(analysis_type)
        if prompt_def is None:
            return "unknown"
        return prompt_def["version"]

    def get_prompt_hash(self, analysis_type: str) -> str:
        """计算Prompt模板的哈希值（版本+模板内容）

        Prompt变更后哈希变化，缓存自动失效。
        """
        prompt_def = self._prompts.get(analysis_type)
        if prompt_def is None:
            return ""
        content = f"{prompt_def['version']}|{prompt_def['system']}|{prompt_def['template']}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def list_types(self) -> list[str]:
        """列出所有支持的分析类型"""
        return list(self._prompts.keys())

    def format_news_list(self, news_items: list[dict]) -> str:
        """格式化新闻列表为Prompt输入

        Args:
            news_items: [{"title": ..., "source": ..., "publish_time": ..., "content": ...}]

        Returns:
            格式化后的新闻文本
        """
        if not news_items:
            return "暂无近期新闻"

        lines = []
        for i, item in enumerate(news_items[:10], 1):  # 最多10条
            time_str = item.get("publish_time", "未知时间")
            title = item.get("title", "无标题")
            source = item.get("source", "未知来源")
            content = item.get("content", "")
            # 截取内容前200字
            if content and len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{i}. [{time_str}] {title}（{source}）\n   {content}")

        return "\n".join(lines)
