"""连续评分策略 - 核心策略模块

每天给全市场股票打分，动态维护 Top 10 持仓。
评分上升 → 纳入关注/买入
评分下降 → 减仓/卖出
评分变化速度（动量） → 替代传统择时信号
"""

import pandas as pd
from loguru import logger

from src.factors.engine import FactorEngine
from src.factors.filter import hard_filter
from src.infra.config import get_settings


class ContinuousScoreStrategy:
    """连续评分策略

    每日收盘后执行：
    1. 硬筛选排除不合格股票
    2. 全市场评分排名
    3. 计算评分动量 ΔS 和加速度 Δ²S
    4. 确定目标持仓 Top N
    5. 对比当前持仓生成交易建议
    """

    def __init__(self, engine: FactorEngine = None, portfolio_size: int = None):
        settings = get_settings()
        portfolio_cfg = settings.get("portfolio", {})
        scoring_cfg = settings.get("scoring", {})
        rebalance_cfg = settings.get("rebalance", {})

        self.engine = engine or FactorEngine()
        self.portfolio_size = portfolio_size or portfolio_cfg.get("size", 10)
        self.watchlist_size = portfolio_cfg.get("watchlist_size", 10)
        self.max_per_industry = portfolio_cfg.get("max_per_industry", 3)

        self.delta_lookback = scoring_cfg.get("delta_lookback", 5)
        self.accel_lookback = scoring_cfg.get("accel_lookback", 5)
        self.urgent_delta_threshold = scoring_cfg.get("urgent_delta_threshold", -1.5)
        self.strong_delta_threshold = scoring_cfg.get("strong_delta_threshold", 1.0)
        self.buffer_days = scoring_cfg.get("buffer_days", 3)

        self.buffer_rank_start = rebalance_cfg.get("buffer_rank_start", 11)
        self.buffer_rank_end = rebalance_cfg.get("buffer_rank_end", 20)
        self.max_weekly_change = rebalance_cfg.get("max_weekly_change", 2)

        # 状态
        self.prev_scores = None
        self.prev_delta = None
        self.current_portfolio = []  # 当前持仓代码列表
        self.buffer_tracker = {}  # 观察池连续在榜天数追踪

    def daily_evaluate(self, data: dict, date, current_portfolio: list = None) -> dict:
        """每日评估，返回交易建议

        Args:
            data: 数据字典，包含:
                - daily_quote: 日线行情DataFrame
                - financial: 财务指标DataFrame
                - stock_info: 股票基础信息DataFrame
                - northbound: 北向资金DataFrame（可选）
                - market_index: 大盘指数DataFrame（可选）
                - market_sentiment: 大盘情绪DataFrame（可选）
            date: 当前日期
            current_portfolio: 当前持仓代码列表

        Returns:
            dict:
                target_portfolio: 目标持仓代码列表
                actions: 交易动作列表
                watchlist: 观察池代码列表
                scores_snapshot: 评分快照DataFrame
                date: 日期
        """
        if current_portfolio is not None:
            self.current_portfolio = list(current_portfolio)

        # 1. 硬筛选
        stock_info = data.get("stock_info", pd.DataFrame())
        daily_quote = data.get("daily_quote", pd.DataFrame())
        financial = data.get("financial", pd.DataFrame())

        valid_codes = hard_filter(stock_info, daily_quote, financial, date)
        if not valid_codes:
            logger.warning("硬筛选后无有效股票")
            return self._empty_result(date)

        data["codes"] = sorted(valid_codes)

        # 2. 全市场评分
        scores = self.engine.score_all(data, str(date))
        scores = scores[scores.index.isin(valid_codes)]

        if scores.empty:
            logger.warning("评分结果为空")
            return self._empty_result(date)

        # 3. 计算评分动量
        if self.prev_scores is not None:
            scores = self.engine.calc_delta(scores, self.prev_scores, self.delta_lookback)
            if self.prev_delta is not None:
                scores = self.engine.calc_acceleration(scores, self.prev_delta)
            else:
                scores["delta_s_accel"] = 0.0
        else:
            scores["delta_s"] = 0.0
            scores["delta_s_accel"] = 0.0

        # 4. 行业分散约束 → 确定目标持仓
        target = self._select_portfolio(scores, stock_info)
        watchlist = scores.iloc[
            self.portfolio_size: self.portfolio_size + self.watchlist_size
        ].index.tolist()

        # 5. 换仓缓冲区检查
        target = self._apply_rebalance_buffer(target, watchlist, scores)

        # 6. 生成交易动作
        actions = self._generate_actions(
            current_portfolio=self.current_portfolio,
            target=target,
            scores=scores,
            data=data,
            date=date,
        )

        # 7. 保存状态
        self.prev_scores = scores.copy()
        if "delta_s" in scores.columns:
            self.prev_delta = scores["delta_s"].copy()

        logger.info(
            f"策略评估完成: 目标持仓{len(target)}只, "
            f"交易动作{len(actions)}个, 观察池{len(watchlist)}只"
        )

        return {
            "target_portfolio": target,
            "actions": actions,
            "watchlist": watchlist,
            "scores_snapshot": scores,
            "date": date,
        }

    def _select_portfolio(self, scores: pd.DataFrame,
                          stock_info: pd.DataFrame) -> list:
        """根据评分排名和行业分散约束选择目标持仓"""
        if stock_info is None or stock_info.empty:
            return scores.head(self.portfolio_size).index.tolist()

        return enforce_industry_diversity(
            target_list=scores.index.tolist(),
            scores=scores,
            stock_info=stock_info,
            max_per_industry=self.max_per_industry,
            portfolio_size=self.portfolio_size,
        )

    def _apply_rebalance_buffer(self, target: list, watchlist: list,
                                scores: pd.DataFrame) -> list:
        """换仓缓冲区：避免频繁换仓"""
        current_set = set(self.current_portfolio)
        target_set = set(target)
        watchlist_set = set(watchlist)

        if current_set == target_set:
            return target

        if not current_set:
            return target

        to_sell = current_set - target_set
        to_buy = target_set - current_set

        final_target = list(target_set)

        for code in to_sell:
            if code not in scores.index:
                continue
            score_info = scores.loc[code]
            delta_s = score_info.get("delta_s", 0) if isinstance(score_info, pd.Series) else 0

            if delta_s < self.urgent_delta_threshold:
                continue

            if code in current_set:
                has_replacement = False
                for wl_code in to_buy:
                    if wl_code in watchlist_set:
                        days = self.buffer_tracker.get(wl_code, {}).get("consecutive_days", 0)
                        if days >= self.buffer_days:
                            has_replacement = True
                            break
                if not has_replacement:
                    final_target.append(code)

        new_buffer_tracker = {}
        for code in watchlist_set:
            prev_info = self.buffer_tracker.get(code, {})
            prev_days = prev_info.get("consecutive_days", 0)
            new_buffer_tracker[code] = {"consecutive_days": prev_days + 1}

        if final_target and len(final_target) > self.portfolio_size:
            held_scores = scores.reindex(
                [c for c in final_target if c in scores.index]
            )
            if not held_scores.empty:
                min_score = held_scores["score_total"].min()
                for wl_code in watchlist_set:
                    if wl_code in scores.index:
                        wl_score = scores.loc[wl_code, "score_total"]
                        if wl_score <= min_score:
                            new_buffer_tracker.pop(wl_code, None)

        self.buffer_tracker = new_buffer_tracker

        if len(final_target) > self.portfolio_size:
            scored = scores.reindex(final_target).dropna()
            scored = scored.sort_values("score_total", ascending=False)
            final_target = scored.head(self.portfolio_size).index.tolist()

        return final_target

    def _generate_actions(self, current_portfolio: list, target: list,
                          scores: pd.DataFrame, data: dict, date) -> list:
        """对比当前持仓和目标持仓，生成交易动作"""
        actions = []
        current_set = set(current_portfolio)
        target_set = set(target)

        for code in current_set - target_set:
            if code not in scores.index:
                actions.append({
                    "code": code,
                    "action": "sell",
                    "reason": f"{code} 已不在目标持仓中（无评分数据）",
                    "urgency": "medium",
                    "score": 0.0,
                    "delta_s": 0.0,
                })
                continue

            score_info = scores.loc[code]
            delta_s = float(score_info.get("delta_s", 0)) if isinstance(score_info, pd.Series) else 0.0

            if delta_s < self.urgent_delta_threshold:
                urgency = "high"
            else:
                urgency = "medium"

            actions.append({
                "code": code,
                "action": "sell",
                "reason": self._sell_reason(score_info),
                "urgency": urgency,
                "score": float(score_info["score_total"]),
                "delta_s": delta_s,
            })

        for code in target_set - current_set:
            if code not in scores.index:
                continue

            score_info = scores.loc[code]
            delta_s = float(score_info.get("delta_s", 0)) if isinstance(score_info, pd.Series) else 0.0

            if delta_s >= 0:
                urgency = "high" if delta_s > self.strong_delta_threshold else "medium"
                actions.append({
                    "code": code,
                    "action": "buy",
                    "reason": self._buy_reason(score_info),
                    "urgency": urgency,
                    "score": float(score_info["score_total"]),
                    "delta_s": delta_s,
                })
            else:
                actions.append({
                    "code": code,
                    "action": "watch",
                    "reason": (
                        f"评分高({score_info['score_total']:.1f})但动量为负"
                        f"({delta_s:.2f})，等动量转正"
                    ),
                })

        for code in current_set & target_set:
            if code not in scores.index:
                continue

            score_info = scores.loc[code]
            delta_s = float(score_info.get("delta_s", 0)) if isinstance(score_info, pd.Series) else 0.0

            if delta_s < 0:
                hold_status = "观察"
                reason_suffix = f"，动量为负({delta_s:+.2f})，标记观察"
            else:
                hold_status = "正常"
                reason_suffix = ""

            actions.append({
                "code": code,
                "action": "hold",
                "reason": (
                    f"继续持有，评分{score_info['score_total']:.1f}"
                    f"，动量{delta_s:+.2f}{reason_suffix}"
                ),
                "score": float(score_info["score_total"]),
                "delta_s": delta_s,
                "hold_status": hold_status,
            })

        return actions

    def _sell_reason(self, score_info) -> str:
        delta = float(score_info.get("delta_s", 0)) if isinstance(score_info, pd.Series) else 0.0
        rank = int(score_info.get("rank", 0)) if isinstance(score_info, pd.Series) else 0
        if delta < self.urgent_delta_threshold:
            return f"评分急剧下降({delta:.2f})，触发快速卖出"
        return f"评分跌出Top{self.portfolio_size}，排名{rank}"

    def _buy_reason(self, score_info) -> str:
        delta = float(score_info.get("delta_s", 0)) if isinstance(score_info, pd.Series) else 0.0
        rank = int(score_info.get("rank", 0)) if isinstance(score_info, pd.Series) else 0
        score = float(score_info["score_total"]) if isinstance(score_info, pd.Series) else 0.0
        return f"评分{score:.1f}(排名{rank})，动量{delta:+.2f}"

    def _empty_result(self, date) -> dict:
        return {
            "target_portfolio": [],
            "actions": [],
            "watchlist": [],
            "scores_snapshot": pd.DataFrame(),
            "date": date,
        }

    def update_portfolio(self, new_portfolio: list):
        self.current_portfolio = list(new_portfolio)


def enforce_industry_diversity(target_list: list, scores: pd.DataFrame,
                               stock_info: pd.DataFrame,
                               max_per_industry: int = 3,
                               portfolio_size: int = 10) -> list:
    """行业分散：单一行业最多持仓 max_per_industry 只"""
    if stock_info is None or stock_info.empty or "sw_l1" not in stock_info.columns:
        return target_list[:portfolio_size]

    industry_map = stock_info.set_index("code")["sw_l1"].to_dict()

    industry_count = {}
    final_list = []

    for code in target_list:
        if len(final_list) >= portfolio_size:
            break

        industry = industry_map.get(code, "未知")
        current = industry_count.get(industry, 0)

        if current < max_per_industry:
            final_list.append(code)
            industry_count[industry] = current + 1

    if len(final_list) < portfolio_size:
        remaining = [c for c in target_list if c not in final_list]
        for code in remaining:
            if len(final_list) >= portfolio_size:
                break
            final_list.append(code)

    return final_list
