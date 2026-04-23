"""双动量策略 (Dual Momentum)

来源: Gary Antonacci《Dual Momentum Investing》+ schlafen318/dual-momentum (GitHub)
思路: 绝对动量(趋势过滤) + 相对动量(排名选股)，双重确认

绝对动量: 价格 > 12个月均线 → 市场处于上升趋势，允许买入
相对动量: 在上升趋势中，选评分最高的股票
退出: 绝对动量转负 → 全部清仓转入现金

与ContinuousScoreStrategy互补:
- ContinuousScore: 纯评分驱动，不管大盘方向
- DualMomentum: 大盘不好时自动空仓，避免30%胜率的根源问题
"""

import pandas as pd
import numpy as np
from loguru import logger

from src.factors.engine import FactorEngine
from src.factors.filter import hard_filter
from src.infra.config import get_settings


class DualMomentumStrategy:
    """双动量策略

    每日评估流程:
    1. 计算大盘绝对动量(沪深300 vs 12月均线)
    2. 绝对动量>0 → 允许买入，用相对动量(评分)选股
    3. 绝对动量<0 → 建议清仓转现金
    4. 评分动量辅助确认
    """

    def __init__(self, engine: FactorEngine = None, portfolio_size: int = None):
        settings = get_settings()
        portfolio_cfg = settings.get("portfolio", {})

        self.engine = engine or FactorEngine()
        self.portfolio_size = portfolio_size or portfolio_cfg.get("size", 10)

        # 动量参数
        self.lookback_months = 12  # 绝对动量回看月数
        self.smooth_window = 20  # 均线平滑天数
        self.absolute_momentum_threshold = 0.0  # 零线以上=看多

        self.prev_scores = None
        self.current_portfolio = []

    def calculate_absolute_momentum(self, market_index: pd.DataFrame) -> dict:
        """计算大盘绝对动量

        Args:
            market_index: 大盘指数数据，需包含 date, close 列

        Returns:
            dict with momentum_pct, signal (bull/bear/neutral), ma_value
        """
        if market_index is None or market_index.empty:
            return {"momentum_pct": 0.0, "signal": "neutral", "ma_value": None}

        df = market_index.sort_values("date").tail(self.lookback_months * 22)
        if len(df) < self.smooth_window:
            return {"momentum_pct": 0.0, "signal": "neutral", "ma_value": None}

        current_price = df["close"].iloc[-1]
        ma = df["close"].rolling(self.smooth_window).mean().iloc[-1]

        momentum_pct = (current_price / ma - 1) * 100
        # 额外: 6个月收益率作为辅助
        lookback_price = df["close"].iloc[max(0, len(df) - 120)]
        return_6m = (current_price / lookback_price - 1) * 100

        # 双确认: MA趋势 + 6月收益
        if momentum_pct > self.absolute_momentum_threshold and return_6m > 0:
            signal = "bull"
        elif momentum_pct < -self.absolute_momentum_threshold or return_6m < -5:
            signal = "bear"
        else:
            signal = "neutral"

        return {
            "momentum_pct": round(momentum_pct, 2),
            "signal": signal,
            "ma_value": round(ma, 2),
            "return_6m": round(return_6m, 2),
        }

    def daily_evaluate(self, data: dict, date, current_portfolio: list = None) -> dict:
        """每日评估

        Returns:
            dict with target_portfolio, actions, market_signal, scores_snapshot
        """
        if current_portfolio is not None:
            self.current_portfolio = list(current_portfolio)

        # 1. 绝对动量判断
        market_index = data.get("market_index", pd.DataFrame())
        market_momentum = self.calculate_absolute_momentum(market_index)
        signal = market_momentum["signal"]

        logger.info(
            f"双动量判断: signal={signal}, "
            f"momentum={market_momentum['momentum_pct']}%, "
            f"6m_return={market_momentum.get('return_6m', 'N/A')}%"
        )

        # 2. 熊市 → 建议清仓
        if signal == "bear":
            logger.warning("🐻 绝对动量看空，建议清仓转现金")
            return {
                "target_portfolio": [],
                "actions": self._generate_exit_actions(self.current_portfolio, data),
                "watchlist": [],
                "scores_snapshot": pd.DataFrame(),
                "market_signal": market_momentum,
                "date": date,
                "strategy": "dual_momentum",
            }

        # 3. 牛市/中性 → 用评分选股
        stock_info = data.get("stock_info", pd.DataFrame())
        daily_quote = data.get("daily_quote", pd.DataFrame())
        financial = data.get("financial", pd.DataFrame())

        valid_codes = hard_filter(stock_info, daily_quote, financial, date)
        if not valid_codes:
            return self._empty_result(date, market_momentum)

        data["codes"] = sorted(valid_codes)
        scores = self.engine.score_all(data, str(date))
        scores = scores[scores.index.isin(valid_codes)]

        if scores.empty:
            return self._empty_result(date, market_momentum)

        # 4. 中性市场降低仓位
        target_size = self.portfolio_size
        if signal == "neutral":
            target_size = max(3, self.portfolio_size // 2)
            logger.info(f"中性市场，减半持仓目标: {target_size}")

        # 5. 相对动量排名选股
        score_col = "total_score" if "total_score" in scores.columns else scores.columns[0]
        scores = scores.sort_values(score_col, ascending=False)
        target = scores.head(target_size).index.tolist()
        watchlist = scores.head(target_size + 10).index.tolist()[target_size:]

        # 6. 生成交易动作
        actions = self._generate_actions(
            current_portfolio=self.current_portfolio,
            target=target,
            scores=scores,
            data=data,
        )

        self.prev_scores = scores.copy()

        return {
            "target_portfolio": target,
            "actions": actions,
            "watchlist": watchlist,
            "scores_snapshot": scores,
            "market_signal": market_momentum,
            "date": date,
            "strategy": "dual_momentum",
        }

    def _generate_exit_actions(self, portfolio: list, data: dict) -> list:
        """生成清仓动作"""
        actions = []
        for code in portfolio:
            actions.append({
                "code": code,
                "action": "sell",
                "reason": "dual_momentum_bear_exit",
                "urgency": "high",
            })
        return actions

    def _generate_actions(self, current_portfolio, target, scores, data):
        """生成买卖动作"""
        actions = []
        to_sell = set(current_portfolio) - set(target)
        to_buy = set(target) - set(current_portfolio)

        score_col = "total_score" if "total_score" in scores.columns else scores.columns[0]

        for code in to_sell:
            row = scores.loc[code] if code in scores.index else None
            score = row[score_col] if row is not None else 0
            actions.append({
                "code": code,
                "action": "sell",
                "reason": f"dual_momentum_replace,score={score:.1f}",
                "urgency": "normal",
            })

        for code in to_buy:
            row = scores.loc[code] if code in scores.index else None
            score = row[score_col] if row is not None else 0
            actions.append({
                "code": code,
                "action": "buy",
                "reason": f"dual_momentum_buy,score={score:.1f}",
                "urgency": "normal",
            })

        return actions

    def _empty_result(self, date, market_signal=None):
        return {
            "target_portfolio": [],
            "actions": [],
            "watchlist": [],
            "scores_snapshot": pd.DataFrame(),
            "market_signal": market_signal or {"signal": "neutral"},
            "date": date,
            "strategy": "dual_momentum",
        }
