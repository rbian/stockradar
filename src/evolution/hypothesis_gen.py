"""LLM驱动的因子假设生成模块

每周回顾市场表现，用LLM提出3个新因子假设，自动验证有效性。

流程：
  1. LLM回顾本周市场（行业涨跌、持仓表现、因子状态）
  2. LLM提出3个新因子假设（有经济学直觉、可用现有数据计算）
  3. 自动验证假设（优先执行pandas表达式计算IC，回退到关键词匹配）
"""

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats

from src.infra.config import PROJECT_ROOT
from src.llm.client import LLMClient
from src.llm.parser import extract_json


# ---- 安全执行环境：只允许 pandas/numpy 操作 ----
_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "len": len,
    "range": range, "round": round, "sorted": sorted,
    "True": True, "False": False, "None": None,
    "float": float, "int": int, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "zip": zip, "enumerate": enumerate, "sum": sum,
}

_FORBIDDEN_NAMES = {
    "os", "sys", "subprocess", "shutil", "pathlib", "importlib",
    "eval", "exec", "compile", "open", "globals", "locals",
    "getattr", "setattr", "delattr", "__import__", "breakpoint",
    "input", "memoryview", "type", "object", "classmethod",
    "staticmethod", "property", "super",
}


def _safe_execute_pandas(expr: str, local_vars: dict) -> pd.Series | None:
    """在受限环境中执行pandas表达式

    Args:
        expr: pandas表达式字符串，例如 'recent.groupby("code").apply(...)'
        local_vars: 局部变量字典，提供 recent / daily_quote 等 DataFrame

    Returns:
        计算结果（pd.Series），失败返回None
    """
    # 静态检查：禁止危险名称
    expr_lower = expr.lower()
    for forbidden in _FORBIDDEN_NAMES:
        if forbidden in expr_lower:
            logger.warning(f"安全拒绝：表达式包含禁止名称 '{forbidden}'")
            return None

    # 禁止属性访问危险模块
    for dangerous in ["__", "import", "eval", "exec", "open(", "system"]:
        if dangerous in expr:
            logger.warning(f"安全拒绝：表达式包含危险模式 '{dangerous}'")
            return None

    safe_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
    }

    try:
        result = eval(expr, safe_globals, local_vars)  # noqa: S307
        if isinstance(result, (pd.Series, pd.DataFrame)):
            return result
        logger.debug(f"pandas表达式返回了非Series类型: {type(result)}")
        return None
    except Exception as e:
        logger.debug(f"pandas表达式执行失败: {e}")
        return None


# 因子假设的Prompt（不经过PromptManager，直接调用LLM API）
_SYSTEM_PROMPT = (
    "你是一位资深的A股量化研究员。你的任务是分析市场数据，提出有创意但可验证的因子假设。"
    "你必须严格按指定JSON格式输出，不要在JSON前后添加任何其他文字。"
)

_HYPOTHESIS_PROMPT = """请回顾本周A股市场表现，并提出3个新的量化因子假设。

## 本周市场概况
{market_summary}

## 当前因子状态
{factor_status}

## 持仓表现
{portfolio_summary}

## 知识库中已发现的因子
{known_factors}

## 可用数据说明
执行环境中提供以下变量（均为pandas DataFrame/Series）：
- recent: 筛选到指定日期的日线行情（包含 code, date, open, high, low, close, volume, amount, turnover 等列）
- daily_quote: 全量日线行情
- financial: 财务指标（包含 code, end_date, roe, gross_margin, debt_ratio, revenue_yoy, profit_yoy 等）
- northbound: 北向资金（包含 code, date, net_amount, hold_share 等）
- industry_index: 行业指数（包含 industry_code, date, close 等）

## 要求
每个因子假设必须满足：
1. 有清晰的经济学直觉（为什么这个因子应该有效？）
2. 可以用我们已有的数据计算（日线行情、财务指标、北向资金、行业指数）
3. 给出具体的计算方法（伪代码或公式）
4. **必须提供pandas_expr字段**：一个可执行的pandas表达式，用上面提供的变量计算，
   返回一个以股票代码(code)为index的Series。
   示例："recent.groupby(\\"code\\").apply(lambda g: g[\\"close\\"].pct_change(20).iloc[-1])"
   注意：只能使用 pandas 和 numpy 操作，禁止 import 或文件操作。

请严格按以下JSON格式输出：
```json
{{
  "market_insight": "本周市场洞察（2-3句话）",
  "hypotheses": [
    {{
      "name": "因子名称（英文snake_case）",
      "category": "fundamental或technical或capital_flow",
      "intuition": "经济学直觉",
      "calculation": "具体计算方法（伪代码）",
      "pandas_expr": "可执行的pandas表达式，使用recent/daily_quote/financial/northbound/industry_index变量",
      "expected_direction": "higher_better或lower_better",
      "data_required": ["daily_quote", "financial_indicator", ...]
    }}
  ]
}}
```"""


class HypothesisGenerator:
    """LLM驱动的因子假设生成器

    用法:
        gen = HypothesisGenerator(llm_client, store)
        result = await gen.weekly_run(data, date)
    """

    def __init__(self, llm_client: LLMClient, store=None):
        self.llm = llm_client
        self.store = store

    async def weekly_run(self, data: dict, date: str) -> dict:
        """每周执行一次：生成假设 → 验证 → 记录

        Args:
            data: 数据字典
            date: 当前日期（YYYY-MM-DD）

        Returns:
            {"hypotheses": [...], "validations": [...], "report": "..."}
        """
        # Step 1: 准备上下文
        market_summary = self._build_market_summary(data, date)
        factor_status = self._build_factor_status(data)
        portfolio_summary = self._build_portfolio_summary(data, date)
        known_factors = self._load_known_factors()

        user_prompt = _HYPOTHESIS_PROMPT.format(
            market_summary=market_summary,
            factor_status=factor_status,
            portfolio_summary=portfolio_summary,
            known_factors=known_factors,
        )

        # Step 2: LLM生成假设
        raw_text = await self.llm._call_with_retry(_SYSTEM_PROMPT, user_prompt)
        if raw_text is None:
            logger.warning("因子假设生成失败：LLM不可用")
            return {"hypotheses": [], "validations": [], "report": "LLM不可用，跳过本周因子研究"}

        # Step 3: 解析输出
        json_str = extract_json(raw_text)
        hypotheses = []
        market_insight = ""
        if json_str:
            try:
                parsed = json.loads(json_str)
                market_insight = parsed.get("market_insight", "")
                hypotheses = parsed.get("hypotheses", [])
            except json.JSONDecodeError:
                logger.warning("因子假设JSON解析失败")

        if not hypotheses:
            logger.warning("未获得有效的因子假设")
            return {"hypotheses": [], "validations": [], "report": "未获得有效假设"}

        # Step 4: 自动验证每个假设
        validations = []
        for hyp in hypotheses[:3]:
            validation = self._validate_hypothesis(hyp, data, date)
            validations.append(validation)

        # Step 5: 生成报告
        report = self._build_report(market_insight, hypotheses, validations)

        logger.info(f"本周因子研究完成：提出{len(hypotheses)}个假设，"
                     f"有效{sum(1 for v in validations if v.get('is_valid'))}个")

        return {
            "hypotheses": hypotheses,
            "validations": validations,
            "report": report,
            "market_insight": market_insight,
            "date": date,
        }

    def _build_market_summary(self, data: dict, date: str) -> str:
        """构建市场概况文本"""
        parts = []

        # 大盘指数
        market_index = data.get("market_index", pd.DataFrame())
        if market_index is not None and not market_index.empty:
            date_ts = pd.Timestamp(date)
            recent = market_index[market_index["date"] <= date_ts].sort_values("date").tail(5)
            if not recent.empty:
                week_return = (recent["close"].iloc[-1] / recent["close"].iloc[0] - 1) * 100
                parts.append(f"大盘近5日涨跌幅: {week_return:.2f}%")

        # 行业表现
        industry_index = data.get("industry_index", pd.DataFrame())
        if industry_index is not None and not industry_index.empty:
            date_ts = pd.Timestamp(date)
            recent = industry_index[industry_index["date"] <= date_ts].sort_values("date").tail(5)
            if not recent.empty:
                industry_returns = recent.groupby("industry_code").apply(
                    lambda g: (g["close"].iloc[-1] / g["close"].iloc[0] - 1) * 100
                    if len(g) >= 2 else 0
                ).sort_values(ascending=False)
                top3 = industry_returns.head(3)
                bottom3 = industry_returns.tail(3)
                parts.append(f"领涨行业: {dict(top3.round(2))}")
                parts.append(f"领跌行业: {dict(bottom3.round(2))}")

        if not parts:
            return "暂无足够的市场数据"

        return "\n".join(parts)

    def _build_factor_status(self, data: dict) -> str:
        """构建因子状态文本"""
        tracker_data = data.get("factor_tracker_status")
        if tracker_data is not None and not tracker_data.empty:
            lines = []
            for _, row in tracker_data.iterrows():
                status = "暂停" if row.get("is_suspended") else "活跃"
                lines.append(
                    f"  {row['factor']}({row['category']}): "
                    f"权重{row['current_weight']:.3f}, "
                    f"IC={row.get('ic_today', 0):.4f}, "
                    f"IC20日均值={row.get('ic_20d_avg', 0):.4f}, "
                    f"状态={status}"
                )
            return "\n".join(lines)

        return "因子追踪数据暂不可用"

    def _build_portfolio_summary(self, data: dict, date: str) -> str:
        """构建持仓表现文本"""
        portfolio = data.get("portfolio")
        if portfolio is not None and not portfolio.empty:
            active = portfolio[portfolio["status"] == "holding"]
            if not active.empty:
                avg_pnl = active["pnl_pct"].mean()
                best = active.loc[active["pnl_pct"].idxmax()]
                worst = active.loc[active["pnl_pct"].idxmin()]
                return (
                    f"持仓{len(active)}只, 平均收益{avg_pnl:.2f}%\n"
                    f"最佳: {best.get('code', '?')} +{best['pnl_pct']:.2f}%\n"
                    f"最差: {worst.get('code', '?')} {worst['pnl_pct']:.2f}%"
                )
        return "暂无持仓数据"

    def _load_known_factors(self) -> str:
        """从知识库加载已知因子"""
        knowledge_dir = PROJECT_ROOT / "knowledge"
        discoveries_path = knowledge_dir / "factor_discoveries.md"
        if discoveries_path.exists():
            content = discoveries_path.read_text(encoding="utf-8")
            # 只取前500字避免过长
            if len(content) > 500:
                content = content[:500] + "\n...(更多见factor_discoveries.md)"
            return content
        return "知识库暂无因子发现记录"

    def _validate_hypothesis(self, hypothesis: dict,
                             data: dict, date: str) -> dict:
        """验证单个因子假设

        优先使用pandas_expr执行计算，失败则回退到关键词匹配。
        """
        name = hypothesis.get("name", "unknown")
        category = hypothesis.get("category", "unknown")
        data_required = hypothesis.get("data_required", [])

        result = {
            "name": name,
            "category": category,
            "is_valid": False,
            "ic": None,
            "ic_interpretation": "",
            "can_calculate": False,
            "notes": "",
        }

        # 检查数据是否可用
        daily_quote = data.get("daily_quote", pd.DataFrame())
        if daily_quote is None or daily_quote.empty:
            result["notes"] = "行情数据不可用，无法验证"
            return result

        # 优先：尝试执行pandas表达式
        factor_values = None
        pandas_expr = hypothesis.get("pandas_expr", "")
        if pandas_expr:
            factor_values = self._try_pandas_expr(pandas_expr, data, date)
            if factor_values is not None:
                result["notes"] = "通过pandas表达式计算"
                logger.info(f"因子 {name}: pandas表达式执行成功")

        # 降级：关键词匹配
        if factor_values is None or (isinstance(factor_values, pd.Series) and factor_values.empty):
            factor_values = self._try_calculate(hypothesis, data, date)
            if factor_values is not None:
                result["notes"] = "通过关键词匹配降级计算"

        if factor_values is None or (isinstance(factor_values, pd.Series) and factor_values.empty):
            result["notes"] = "无法用现有数据计算，需要新数据源"
            return result

        result["can_calculate"] = True

        # 计算IC
        ic = self._calc_ic(factor_values, daily_quote, date)
        result["ic"] = ic

        # 评估有效性
        if ic is None or np.isnan(ic):
            result["ic_interpretation"] = "样本不足，无法计算IC"
        elif abs(ic) > 0.03:
            result["is_valid"] = True
            direction = "正相关" if ic > 0 else "负相关"
            result["ic_interpretation"] = f"IC={ic:.4f}（{direction}，显著）"
        elif abs(ic) > 0.01:
            result["ic_interpretation"] = f"IC={ic:.4f}（弱相关，需继续观察）"
        else:
            result["ic_interpretation"] = f"IC={ic:.4f}（不显著）"

        return result

    def _try_pandas_expr(self, expr: str, data: dict, date: str) -> pd.Series | None:
        """尝试执行LLM生成的pandas表达式

        Args:
            expr: pandas表达式字符串
            data: 数据字典
            date: 截止日期

        Returns:
            计算结果Series（index=code），失败返回None
        """
        daily_quote = data.get("daily_quote", pd.DataFrame())
        if daily_quote is None or daily_quote.empty:
            return None

        date_ts = pd.Timestamp(date)
        recent = daily_quote[daily_quote["date"] <= date_ts].copy()
        if recent.empty:
            return None

        # 构建局部变量环境
        local_vars = {
            "recent": recent,
            "daily_quote": daily_quote,
            "np": np,
            "pd": pd,
        }

        # 可选数据源
        financial = data.get("financial", pd.DataFrame())
        if financial is not None and not financial.empty:
            local_vars["financial"] = financial

        northbound = data.get("northbound_stock", pd.DataFrame())
        if northbound is None:
            northbound = data.get("northbound", pd.DataFrame())
        if northbound is not None and not northbound.empty:
            nb_recent = northbound[northbound["date"] <= date_ts].copy()
            local_vars["northbound"] = nb_recent

        industry_index = data.get("industry_index", pd.DataFrame())
        if industry_index is not None and not industry_index.empty:
            local_vars["industry_index"] = industry_index

        result = _safe_execute_pandas(expr, local_vars)
        if result is not None and isinstance(result, pd.Series):
            return result.dropna()
        return None

    def _try_calculate(self, hypothesis: dict, data: dict,
                       date: str) -> pd.Series | None:
        """尝试根据假设描述计算因子值（关键词匹配降级方案）

        使用简单的关键词匹配来尝试计算。
        如果无法计算，返回None。
        """
        name = hypothesis.get("name", "").lower()
        calculation = hypothesis.get("calculation", "").lower()
        combined = f"{name} {calculation}"

        daily_quote = data.get("daily_quote", pd.DataFrame())
        if daily_quote is None or daily_quote.empty:
            return None

        date_ts = pd.Timestamp(date)
        recent = daily_quote[daily_quote["date"] <= date_ts].copy()
        if recent.empty:
            return None

        # 基于关键词尝试简单因子计算
        if "volatility" in combined or "波动" in combined:
            # 波动率类因子
            period = 20
            if "10" in calculation:
                period = 10
            def calc_vol(g):
                if len(g) < period:
                    return np.nan
                returns = g["close"].pct_change().dropna().tail(period)
                return returns.std() * np.sqrt(252)
            result = recent.groupby("code").apply(calc_vol)
            return result.dropna()

        if "momentum" in combined or "动量" in combined or "涨幅" in combined:
            period = 20
            if "10" in calculation:
                period = 10
            elif "5" in calculation:
                period = 5
            def calc_mom(g):
                if len(g) < period + 1:
                    return np.nan
                return (g["close"].iloc[-1] / g["close"].iloc[-period - 1] - 1)
            result = recent.groupby("code").apply(calc_mom)
            return result.dropna()

        if "volume" in combined or "成交" in combined or "量" in combined:
            # 成交量相关
            def calc_vol_ratio(g):
                if len(g) < 10:
                    return np.nan
                recent_vol = g["volume"].iloc[-5:].mean()
                hist_vol = g["volume"].iloc[-20:-5].mean()
                if hist_vol == 0:
                    return np.nan
                return recent_vol / hist_vol
            result = recent.groupby("code").apply(calc_vol_ratio)
            return result.dropna()

        if "turnover" in combined or "换手" in combined:
            def calc_turnover(g):
                if len(g) < 5:
                    return np.nan
                return g["turnover"].tail(5).mean()
            result = recent.groupby("code").apply(calc_turnover)
            return result.dropna()

        if "northbound" in combined or "北向" in combined:
            northbound = data.get("northbound_stock", pd.DataFrame())
            if northbound is not None and not northbound.empty:
                nb_recent = northbound[northbound["date"] <= date_ts]
                result = nb_recent.groupby("code")["net_amount"].sum()
                return result.dropna()
            return None

        if "ma" in combined or "均线" in combined or "moving_average" in combined:
            period = 20
            if "60" in calculation:
                period = 60
            elif "10" in calculation:
                period = 10
            def calc_ma_dev(g):
                if len(g) < period:
                    return np.nan
                ma = g["close"].rolling(period).mean().iloc[-1]
                return (g["close"].iloc[-1] / ma - 1) * 100
            result = recent.groupby("code").apply(calc_ma_dev)
            return result.dropna()

        # 无法识别的因子类型
        return None

    def _calc_ic(self, factor_values: pd.Series,
                 daily_quote: pd.DataFrame, date: str) -> float | None:
        """计算因子的IC（Spearman rank相关性 vs 未来5日收益）"""
        try:
            date_ts = pd.Timestamp(date)
            dq = daily_quote.copy()
            dq["date"] = pd.to_datetime(dq["date"])

            today_prices = dq[dq["date"] == date_ts].set_index("code")["close"]
            # 未来5-10个交易日的价格
            future_date = date_ts + pd.Timedelta(days=15)
            future_prices = dq[
                (dq["date"] > date_ts) & (dq["date"] <= future_date)
            ].groupby("code")["close"].first()

            if today_prices.empty or future_prices.empty:
                return None

            future_returns = (future_prices - today_prices) / today_prices
            future_returns = future_returns.dropna()

            common = factor_values.index.intersection(future_returns.index)
            if len(common) < 30:
                return None

            aligned_f = factor_values.reindex(common).dropna()
            aligned_r = future_returns.reindex(common).dropna()
            common2 = aligned_f.index.intersection(aligned_r.index)
            if len(common2) < 30:
                return None

            corr, _ = stats.spearmanr(
                aligned_f.reindex(common2).values,
                aligned_r.reindex(common2).values,
            )
            return corr if not np.isnan(corr) else None

        except Exception as e:
            logger.debug(f"IC计算失败: {e}")
            return None

    def _build_report(self, market_insight: str,
                      hypotheses: list[dict],
                      validations: list[dict]) -> str:
        """生成因子研究报告"""
        lines = [
            f"## 因子研究报告 ({datetime.now().strftime('%Y-%m-%d')})",
            "",
            f"**市场洞察**: {market_insight}",
            "",
        ]

        for i, (hyp, val) in enumerate(zip(hypotheses, validations), 1):
            status = "有效" if val["is_valid"] else "无效/待观察"
            lines.append(f"### 假设{i}: {hyp.get('name', '?')} [{status}]")
            lines.append(f"- 类别: {hyp.get('category', '?')}")
            lines.append(f"- 直觉: {hyp.get('intuition', '?')}")
            lines.append(f"- 计算: {hyp.get('calculation', '?')}")
            lines.append(f"- 验证: {val.get('ic_interpretation', '未验证')}")
            if val.get("notes"):
                lines.append(f"- 备注: {val['notes']}")
            lines.append("")

        return "\n".join(lines)
