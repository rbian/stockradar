"""风控规则 - 独立于策略，最高优先级

风控指令会覆盖策略建议，确保：
- 单票止损
- 大盘危机模式降仓
- 行业集中度控制
- 单日异常跌幅保护
"""

from collections import Counter

import pandas as pd
from loguru import logger

from src.infra.config import get_settings


class RiskController:
    """风控控制器

    在策略评估之后、交易执行之前运行。
    风控指令 source="risk"，优先级高于 source="strategy"。
    """

    def __init__(self):
        settings = get_settings()
        risk_cfg = settings.get("risk", {})
        portfolio_cfg = settings.get("portfolio", {})

        self.stop_loss = risk_cfg.get("stop_loss", -0.15)
        self.reduce_loss = risk_cfg.get("reduce_loss", -0.08)
        self.reduce_ratio = risk_cfg.get("reduce_ratio", 0.5)
        self.crisis_reduce_ratio = risk_cfg.get("crisis_reduce_ratio", 0.7)
        self.max_single_day_drop = risk_cfg.get("max_single_day_drop", -0.08)
        self.max_per_industry = portfolio_cfg.get("max_per_industry", 3)

    def check(self, portfolio: dict, data: dict, date,
              market_regime: str = None) -> list:
        """执行风控检查

        Args:
            portfolio: 持仓字典 {code: position_info}
                position_info 需含: buy_price, industry
            data: 数据字典，需含:
                daily_quote: 日线行情（用于获取当前价格）
            date: 当前日期
            market_regime: 当前市场状态（由regime模块提供）

        Returns:
            风控指令列表，每项:
                code, action(sell/reduce), reason, source="risk",
                ratio(减仓比例，可选), urgency
        """
        orders = []

        if not portfolio:
            return orders

        daily_quote = data.get("daily_quote", pd.DataFrame())

        # 1. 单票止损/减仓检查
        orders.extend(self._check_stop_loss(portfolio, daily_quote, date))

        # 2. 单日异常跌幅保护
        orders.extend(self._check_single_day_drop(portfolio, daily_quote, date))

        # 3. 大盘危机模式
        if market_regime == "crisis":
            orders.extend(self._check_crisis_mode(portfolio))

        # 4. 行业集中度
        orders.extend(self._check_industry_concentration(portfolio))

        if orders:
            logger.warning(f"风控触发 {len(orders)} 条指令")
            for o in orders:
                logger.warning(f"  风控: {o['action']} {o['code']} - {o['reason']}")

        return orders

    def _check_stop_loss(self, portfolio: dict, daily_quote: pd.DataFrame,
                         date) -> list:
        """单票止损检查

        规则：
        - 亏损 > 15% → 止损清仓
        - 亏损 > 8%  → 减仓50%
        """
        orders = []

        for code, pos in portfolio.items():
            buy_price = self._get_buy_price(pos)
            current_price = self._get_current_price(code, daily_quote, date)

            if buy_price is None or current_price is None or buy_price <= 0:
                continue

            pnl = (current_price - buy_price) / buy_price

            if pnl < self.stop_loss:
                orders.append({
                    "code": code,
                    "action": "sell",
                    "reason": f"止损清仓(亏损{pnl*100:.1f}%>{self.stop_loss*100:.0f}%)",
                    "source": "risk",
                    "urgency": "high",
                })
            elif pnl < self.reduce_loss:
                orders.append({
                    "code": code,
                    "action": "reduce",
                    "ratio": self.reduce_ratio,
                    "reason": f"减仓{self.reduce_ratio*100:.0f}%(亏损{pnl*100:.1f}%>{self.reduce_loss*100:.0f}%)",
                    "source": "risk",
                    "urgency": "medium",
                })

        return orders

    def _check_single_day_drop(self, portfolio: dict,
                               daily_quote: pd.DataFrame, date) -> list:
        """单日异常跌幅保护

        规则：单日跌幅 > 8% → 止损减仓
        """
        orders = []

        if daily_quote is None or daily_quote.empty:
            return orders

        date_ts = pd.Timestamp(date)
        today_data = daily_quote[daily_quote["date"] == date_ts]

        for code in portfolio:
            code_data = today_data[today_data["code"] == code]
            if code_data.empty:
                continue

            change_pct = code_data.iloc[0].get("change_pct", 0.0)
            if pd.notna(change_pct) and change_pct / 100 < self.max_single_day_drop:
                orders.append({
                    "code": code,
                    "action": "reduce",
                    "ratio": self.reduce_ratio,
                    "reason": (
                        f"单日跌幅{change_pct:.1f}%>{self.max_single_day_drop*100:.0f}%，"
                        f"触发风控减仓"
                    ),
                    "source": "risk",
                    "urgency": "high",
                })

        return orders

    def _check_crisis_mode(self, portfolio: dict) -> list:
        """大盘危机模式 - 全体减仓

        规则：市场状态为 crisis 时，所有持仓减仓70%
        """
        orders = []

        for code in portfolio:
            orders.append({
                "code": code,
                "action": "reduce",
                "ratio": self.crisis_reduce_ratio,
                "reason": f"大盘危机模式，全体减仓{self.crisis_reduce_ratio*100:.0f}%",
                "source": "risk",
                "urgency": "high",
            })

        return orders

    def _check_industry_concentration(self, portfolio: dict) -> list:
        """行业集中度检查

        规则：单一行业最多持仓 max_per_industry 只
        超过的按评分从低到高卖出多余部分
        """
        orders = []

        # 统计各行业持仓数量
        industry_stocks = {}
        for code, pos in portfolio.items():
            industry = self._get_industry(pos)
            if industry not in industry_stocks:
                industry_stocks[industry] = []
            industry_stocks[industry].append(code)

        for industry, codes in industry_stocks.items():
            if len(codes) > self.max_per_industry:
                # 超限：标记多余部分（实际卖出排序由调用方根据评分决定）
                excess = len(codes) - self.max_per_industry
                orders.append({
                    "code": codes,  # 传递该行业全部代码，由调用方选择保留哪些
                    "action": "industry_reduce",
                    "reason": (
                        f"行业[{industry}]集中度超限"
                        f"({len(codes)}只>限{self.max_per_industry}只)，"
                        f"需减{excess}只"
                    ),
                    "source": "risk",
                    "urgency": "low",
                    "industry": industry,
                    "excess": excess,
                })

        return orders

    @staticmethod
    def _get_buy_price(pos) -> float:
        """从持仓信息中获取买入价格"""
        if isinstance(pos, dict):
            return pos.get("buy_price")
        return getattr(pos, "buy_price", None)

    @staticmethod
    def _get_industry(pos) -> str:
        """从持仓信息中获取行业"""
        if isinstance(pos, dict):
            return pos.get("industry", "未知")
        return getattr(pos, "industry", "未知")

    @staticmethod
    def _get_current_price(code: str, daily_quote: pd.DataFrame,
                           date) -> float:
        """获取最新价格"""
        if daily_quote is None or daily_quote.empty:
            return None

        date_ts = pd.Timestamp(date)
        code_data = daily_quote[
            (daily_quote["code"] == code) & (daily_quote["date"] == date_ts)
        ]

        if code_data.empty:
            # 取最新一天的价格
            code_data = daily_quote[daily_quote["code"] == code].sort_values("date")

        if code_data.empty:
            return None

        return float(code_data.iloc[-1]["close"])

    def merge_risk_orders(self, strategy_actions: list,
                          risk_orders: list) -> list:
        """合并策略建议和风控指令，风控优先

        规则：
        - 风控 sell 指令直接覆盖策略的 hold/buy
        - 风控 reduce 指令追加到策略动作列表
        - 同一代码已有风控 sell 的，忽略策略动作
        """
        risk_sell_codes = set()
        risk_reduce_codes = set()

        for order in risk_orders:
            if order["action"] == "sell":
                risk_sell_codes.add(order["code"])
            elif order["action"] == "reduce":
                risk_reduce_codes.add(order["code"])

        # 过滤策略动作（被风控sell的不再执行策略动作）
        filtered = []
        for action in strategy_actions:
            code = action.get("code")
            if code in risk_sell_codes:
                continue  # 被风控清仓了
            filtered.append(action)

        # 追加风控指令
        for order in risk_orders:
            if order["action"] in ("sell", "reduce"):
                filtered.append(order)

        return filtered
