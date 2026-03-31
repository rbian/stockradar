"""策略诊断 + 失败复盘模块

月度策略全面体检：
  - 收益、回撤、因子贡献分析
  - 亏损>5%交易逐笔回顾，提取失败模式
  - LLM生成诊断报告和改进建议
"""

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from src.llm.client import LLMClient
from src.llm.parser import extract_json


_SYSTEM_PROMPT = (
    "你是一位资深的量化策略分析师。你的任务是诊断策略的健康状况，分析失败原因，并提出可执行的改进建议。"
    "你必须严格按指定JSON格式输出，不要在JSON前后添加任何其他文字。"
)

_DIAGNOSIS_PROMPT = """请对以下A股模拟交易策略进行月度全面诊断。

## 策略概况（过去{lookback_months}个月）
{strategy_summary}

## 逐月表现
{monthly_performance}

## 因子贡献度
{factor_contribution}

## 失败交易回顾（亏损>5%）
{failure_trades}

## 已知失败模式（来自知识库）
{known_failures}

## 市场环境
{market_context}

请严格按以下JSON格式输出诊断报告：
```json
{{
  "health_score": 0到100的整数（策略健康度）,
  "diagnosis": "策略诊断结论（3-5句话）",
  "strengths": ["策略优势1", "策略优势2"],
  "weaknesses": ["策略弱点1", "策略弱点2"],
  "failure_patterns": [
    {{
      "pattern": "失败模式描述",
      "frequency": "出现频率",
      "suggestion": "改进建议"
    }}
  ],
  "improvements": [
    {{
      "priority": "high或medium或low",
      "action": "具体可执行的改进措施",
      "expected_impact": "预期效果"
    }}
  ],
  "new_factor_ideas": ["新因子或规则假设1", "假设2"],
  "risk_warnings": ["风险预警1"]
}}
```"""


class StrategyDoctor:
    """策略诊断医生

    用法:
        doctor = StrategyDoctor(llm_client, store)
        result = await doctor.monthly_checkup(date)
    """

    def __init__(self, llm_client: LLMClient, store=None):
        self.llm = llm_client
        self.store = store

    async def monthly_checkup(self, date: str,
                              lookback_months: int = 12) -> dict:
        """月度策略全面体检

        Args:
            date: 当前日期
            lookback_months: 回看月数

        Returns:
            诊断结果dict
        """
        logger.info(f"开始月度策略诊断 [{date}]")

        # 1. 收集数据
        strategy_summary = self._get_strategy_summary(lookback_months)
        monthly_performance = self._get_monthly_performance(lookback_months)
        factor_contribution = self._get_factor_contribution()
        failure_trades = self._get_failure_trades(lookback_months)
        known_failures = self._load_known_failures()
        market_context = self._get_market_context(date)

        # 2. LLM诊断
        user_prompt = _DIAGNOSIS_PROMPT.format(
            lookback_months=lookback_months,
            strategy_summary=strategy_summary,
            monthly_performance=monthly_performance,
            factor_contribution=factor_contribution,
            failure_trades=failure_trades,
            known_failures=known_failures,
            market_context=market_context,
        )

        raw_text = await self.llm._call_with_retry(_SYSTEM_PROMPT, user_prompt)
        if raw_text is None:
            logger.warning("策略诊断失败：LLM不可用")
            return self._default_diagnosis()

        # 3. 解析结果
        json_str = extract_json(raw_text)
        if json_str is None:
            logger.warning("策略诊断JSON解析失败")
            return self._default_diagnosis()

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("策略诊断JSON解析失败")
            return self._default_diagnosis()

        # 4. 补充分析结果
        result["date"] = date
        result["lookback_months"] = lookback_months
        result["raw_failure_analysis"] = self._analyze_failure_patterns()

        logger.info(f"策略诊断完成: 健康度 {result.get('health_score', '?')}/100")

        return result

    def _get_strategy_summary(self, months: int) -> str:
        """获取策略整体概况"""
        if self.store is None:
            return "数据存储不可用"

        try:
            # 获取净值历史
            nav_df = self.store.get_table("nav_history")
            if nav_df is None or nav_df.empty:
                return "暂无净值数据"

            total_return = (nav_df["nav"].iloc[-1] / nav_df["nav"].iloc[0] - 1) * 100
            max_dd = ((nav_df["nav"] / nav_df["nav"].cummax()) - 1).min() * 100
            daily_returns = nav_df["daily_return"].dropna()
            sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if len(daily_returns) > 1 and daily_returns.std() > 0 else 0

            # 胜率
            win_rate = (daily_returns > 0).mean() * 100 if len(daily_returns) > 0 else 0

            return (
                f"总收益率: {total_return:.2f}%\n"
                f"年化Sharpe: {sharpe:.2f}\n"
                f"最大回撤: {max_dd:.2f}%\n"
                f"胜率: {win_rate:.1f}%\n"
                f"交易天数: {len(nav_df)}"
            )
        except Exception as e:
            logger.debug(f"获取策略概况失败: {e}")
            return f"数据获取异常: {e}"

    def _get_monthly_performance(self, months: int) -> str:
        """获取逐月表现"""
        if self.store is None:
            return "数据存储不可用"

        try:
            nav_df = self.store.get_table("nav_history")
            if nav_df is None or nav_df.empty:
                return "暂无净值数据"

            nav_df["date"] = pd.to_datetime(nav_df["date"])
            nav_df["month"] = nav_df["date"].dt.to_period("M")

            monthly = nav_df.groupby("month").agg(
                start_nav=("nav", "first"),
                end_nav=("nav", "last"),
            )
            monthly["return_pct"] = (monthly["end_nav"] / monthly["start_nav"] - 1) * 100

            lines = []
            for period, row in monthly.tail(months).iterrows():
                lines.append(f"  {period}: {row['return_pct']:+.2f}%")

            return "\n".join(lines) if lines else "数据不足"
        except Exception as e:
            logger.debug(f"获取月度表现失败: {e}")
            return f"数据获取异常: {e}"

    def _get_factor_contribution(self) -> str:
        """获取因子贡献度分析"""
        if self.store is None:
            return "数据存储不可用"

        try:
            # 获取评分数据和交易记录，分析各因子的贡献
            trade_log = self.store.get_table("trade_log")
            daily_score = self.store.get_table("daily_score")

            if trade_log is None or trade_log.empty:
                return "暂无交易记录"

            if daily_score is None or daily_score.empty:
                return "暂无评分数据"

            # 分析买入后的因子得分
            buy_trades = trade_log[trade_log["action"] == "buy"]
            if buy_trades.empty:
                return "暂无买入记录"

            lines = []
            score_cols = ["score_fundamental", "score_technical", "score_capital", "score_llm"]
            for col in score_cols:
                if col in daily_score.columns:
                    avg_val = daily_score[col].mean()
                    lines.append(f"  {col}: 平均值 {avg_val:.3f}")

            return "\n".join(lines) if lines else "因子数据不完整"
        except Exception as e:
            logger.debug(f"获取因子贡献失败: {e}")
            return f"数据获取异常: {e}"

    def _get_failure_trades(self, months: int) -> str:
        """获取失败交易（亏损>5%）"""
        if self.store is None:
            return "数据存储不可用"

        try:
            trade_log = self.store.get_table("trade_log")
            if trade_log is None or trade_log.empty:
                return "暂无交易记录"

            # 查找卖出记录
            sell_trades = trade_log[trade_log["action"] == "sell"].copy()
            if sell_trades.empty:
                return "暂无卖出记录"

            # 尝试匹配买卖对计算收益
            buy_trades = trade_log[trade_log["action"] == "buy"].copy()
            if buy_trades.empty:
                return "暂无买入记录"

            failures = []
            for _, sell in sell_trades.iterrows():
                code = sell["code"]
                matching_buys = buy_trades[buy_trades["code"] == code]
                if matching_buys.empty:
                    continue

                buy = matching_buys.iloc[-1]  # 最近一次买入
                if sell["price"] > 0 and buy["price"] > 0:
                    pnl = (sell["price"] / buy["price"] - 1) * 100
                    if pnl < -5:
                        failures.append(
                            f"  {code}: 买入{buy['price']:.2f}({buy.get('date', '?')}), "
                            f"卖出{sell['price']:.2f}({sell.get('date', '?')}), "
                            f"亏损{pnl:.1f}%\n"
                            f"    买入理由: {buy.get('reason', '?')}\n"
                            f"    卖出理由: {sell.get('reason', '?')}"
                        )

            if not failures:
                return "过去期间无亏损>5%的交易（表现良好）"

            return "\n".join(failures[:20])  # 最多20条
        except Exception as e:
            logger.debug(f"获取失败交易失败: {e}")
            return f"数据获取异常: {e}"

    def _analyze_failure_patterns(self) -> list[dict]:
        """分析失败模式（不依赖LLM的统计分析）"""
        patterns = []

        if self.store is None:
            return patterns

        try:
            trade_log = self.store.get_table("trade_log")
            if trade_log is None or trade_log.empty:
                return patterns

            sell_trades = trade_log[trade_log["action"] == "sell"].copy()
            buy_trades = trade_log[trade_log["action"] == "buy"].copy()

            if sell_trades.empty or buy_trades.empty:
                return patterns

            # 分析持仓时间与收益的关系
            for _, sell in sell_trades.iterrows():
                code = sell["code"]
                matching_buys = buy_trades[buy_trades["code"] == code]
                if matching_buys.empty:
                    continue
                buy = matching_buys.iloc[-1]

                if sell["price"] > 0 and buy["price"] > 0:
                    pnl = (sell["price"] / buy["price"] - 1) * 100
                    if pnl < -5:
                        try:
                            hold_days = (pd.Timestamp(sell.get("date", sell.name))
                                         - pd.Timestamp(buy.get("date", buy.name))).days
                        except Exception:
                            hold_days = 0
                        patterns.append({
                            "code": code,
                            "pnl_pct": round(pnl, 2),
                            "hold_days": hold_days,
                            "buy_reason": buy.get("reason", ""),
                            "sell_reason": sell.get("reason", ""),
                        })

        except Exception as e:
            logger.debug(f"失败模式分析异常: {e}")

        return patterns

    def _load_known_failures(self) -> str:
        """从知识库加载已知失败模式"""
        from src.infra.config import PROJECT_ROOT
        failures_path = PROJECT_ROOT / "knowledge" / "failure_patterns.md"
        if failures_path.exists():
            content = failures_path.read_text(encoding="utf-8")
            if len(content) > 500:
                content = content[:500] + "\n...(更多见failure_patterns.md)"
            return content
        return "知识库暂无失败模式记录"

    def _get_market_context(self, date: str) -> str:
        """获取市场环境上下文"""
        if self.store is None:
            return "数据存储不可用"

        try:
            market_index = self.store.get_table("market_index_daily")
            if market_index is None or market_index.empty:
                return "暂无市场指数数据"

            market_index["date"] = pd.to_datetime(market_index["date"])
            date_ts = pd.Timestamp(date)

            # 近1个月大盘表现
            recent = market_index[
                (market_index["date"] <= date_ts) &
                (market_index["date"] >= date_ts - pd.Timedelta(days=35))
            ].sort_values("date")

            if recent.empty:
                return "无近期市场数据"

            month_return = (recent["close"].iloc[-1] / recent["close"].iloc[0] - 1) * 100
            volatility = recent["close"].pct_change().std() * np.sqrt(252) * 100

            return f"近1月大盘涨跌幅: {month_return:.2f}%, 年化波动率: {volatility:.1f}%"
        except Exception as e:
            logger.debug(f"获取市场环境失败: {e}")
            return f"数据获取异常: {e}"

    def _default_diagnosis(self) -> dict:
        """LLM不可用时的默认诊断"""
        return {
            "health_score": 50,
            "diagnosis": "LLM不可用，无法进行深度诊断。请检查LLM配置。",
            "strengths": [],
            "weaknesses": ["诊断系统依赖LLM，当前不可用"],
            "failure_patterns": [],
            "improvements": [],
            "new_factor_ideas": [],
            "risk_warnings": ["LLM诊断不可用，策略风险可能被低估"],
            "date": datetime.now().strftime("%Y-%m-%d"),
        }

    def format_diagnosis_report(self, result: dict) -> str:
        """将诊断结果格式化为可读报告"""
        lines = [
            f"# 策略诊断报告 ({result.get('date', '?')})",
            "",
            f"**健康度**: {result.get('health_score', '?')}/100",
            "",
            f"**诊断结论**: {result.get('diagnosis', '?')}",
            "",
        ]

        if result.get("strengths"):
            lines.append("## 优势")
            for s in result["strengths"]:
                lines.append(f"- {s}")
            lines.append("")

        if result.get("weaknesses"):
            lines.append("## 弱点")
            for w in result["weaknesses"]:
                lines.append(f"- {w}")
            lines.append("")

        if result.get("failure_patterns"):
            lines.append("## 失败模式")
            for fp in result["failure_patterns"]:
                lines.append(f"- **{fp.get('pattern', '?')}**: {fp.get('suggestion', '?')}")
            lines.append("")

        if result.get("improvements"):
            lines.append("## 改进建议")
            for imp in result["improvements"]:
                lines.append(f"- [{imp.get('priority', '?')}] {imp.get('action', '?')} — {imp.get('expected_impact', '?')}")
            lines.append("")

        if result.get("risk_warnings"):
            lines.append("## 风险预警")
            for rw in result["risk_warnings"]:
                lines.append(f"- {rw}")
            lines.append("")

        return "\n".join(lines)
