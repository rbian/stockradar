"""净值追踪器 — 模拟组合净值计算

功能:
- 基于评分Top10持仓，定期调仓
- 计算每日净值、收益率、回撤
- 持仓记录、交易日志
"""

import pandas as pd
import numpy as np
from datetime import datetime
from loguru import logger


class NAVTracker:
    """净值追踪器"""

    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.holdings = {}  # code -> {shares, cost_price}
        self.nav_history = []  # [{date, nav, cash, market_value, holdings_count}]
        self.trade_log = []  # [{date, code, action, shares, price, reason}]
        self.rebalance_days = 10
        self.top_n = 10
        self.commission_rate = 0.001
        self.stop_loss = -0.18
        self.max_swaps_per_week = 2

    def get_nav(self) -> dict:
        """获取最新净值信息"""
        if not self.nav_history:
            return {"nav": 1.0, "total_return": 0, "drawdown": 0,
                    "holdings": [], "trades": len(self.trade_log)}
        latest = self.nav_history[-1]
        peak = max(h["nav"] for h in self.nav_history)
        dd = (latest["nav"] - peak) / peak if peak > 0 else 0
        return {
            "nav": latest["nav"],
            "total_return": (latest["nav"] - 1) * 100,
            "drawdown": dd * 100,
            "market_value": latest["market_value"],
            "cash": latest["cash"],
            "holdings_count": latest["holdings_count"],
            "peak_nav": peak,
            "date": str(latest["date"])[:10],
            "trades": len(self.trade_log),
        }

    def get_holdings(self) -> list:
        """获取当前持仓"""
        result = []
        for code, h in self.holdings.items():
            result.append({
                "code": code,
                "shares": h["shares"],
                "cost_price": h["cost_price"],
                "cost_total": h["shares"] * h["cost_price"],
            })
        return result

    def rebalance(self, date, scores: pd.DataFrame, prices: dict, reason: str = "定期调仓"):
        """调仓
        
        Args:
            date: 当前日期
            scores: 评分DataFrame (index=code, has score_total)
            prices: {code: close_price}
            reason: 调仓原因
        """
        if scores.empty:
            return

        # 目标持仓: Top N
        target_codes = set(scores.head(self.top_n).index.tolist())
        current_codes = set(self.holdings.keys())

        # 止损检查
        for code in list(self.holdings.keys()):
            h = self.holdings[code]
            if code in prices and prices[code] > 0:
                pnl = (prices[code] - h["cost_price"]) / h["cost_price"]
                if pnl <= self.stop_loss:
                    self._sell(code, prices[code], date, f"止损({pnl:+.1f}%)")

        # 卖出: 不在目标的
        for code in list(self.holdings.keys()):
            if code not in target_codes:
                if code in prices and prices[code] > 0:
                    self._sell(code, prices[code], date, reason)

        # 买入: 新进目标的
        new_codes = target_codes - set(self.holdings.keys())
        if new_codes and self.cash > 0:
            # 等权重分配
            per_stock = self.cash / max(len(new_codes), 1)
            for code in new_codes:
                if code in prices and prices[code] > 0:
                    price = prices[code]
                    shares = int(per_stock / price / 100) * 100  # 整手
                    if shares >= 100:
                        self._buy(code, shares, price, date, reason)

    def _buy(self, code: str, shares: int, price: float, date, reason: str):
        cost = shares * price * (1 + self.commission_rate)
        if cost > self.cash:
            shares = int(self.cash / (price * (1 + self.commission_rate)) / 100) * 100
            cost = shares * price * (1 + self.commission_rate)
        if shares < 100:
            return

        self.cash -= cost
        if code in self.holdings:
            old = self.holdings[code]
            total_shares = old["shares"] + shares
            avg_cost = (old["shares"] * old["cost_price"] + cost) / total_shares
            self.holdings[code] = {"shares": total_shares, "cost_price": avg_cost}
        else:
            self.holdings[code] = {"shares": shares, "cost_price": price}

        self.trade_log.append({
            "date": str(date)[:10], "code": code, "action": "buy",
            "shares": shares, "price": price, "reason": reason,
        })

    def _sell(self, code: str, price: float, date, reason: str):
        h = self.holdings.get(code)
        if not h:
            return
        proceeds = h["shares"] * price * (1 - self.commission_rate)
        self.cash += proceeds
        self.trade_log.append({
            "date": str(date)[:10], "code": code, "action": "sell",
            "shares": h["shares"], "price": price, "reason": reason,
        })
        del self.holdings[code]

    def update_nav(self, date, prices: dict):
        """更新每日净值"""
        market_value = 0
        for code, h in self.holdings.items():
            if code in prices:
                market_value += h["shares"] * prices[code]
            else:
                market_value += h["shares"] * h["cost_price"]

        total = self.cash + market_value
        nav = total / self.initial_capital

        self.nav_history.append({
            "date": date,
            "nav": nav,
            "cash": self.cash,
            "market_value": market_value,
            "holdings_count": len(self.holdings),
        })

    def get_report(self) -> str:
        """生成净值报告"""
        info = self.get_nav()
        if not self.nav_history:
            return "净值追踪暂未启动"

        lines = [
            f"💰 **净值报告** ({info['date']})",
            f"",
            f"📊 **净值:** {info['nav']:.4f}",
            f"📈 **总收益:** {info['total_return']:+.2f}%",
            f"📉 **最大回撤:** {info['drawdown']:+.2f}%",
            f"💵 **市值:** ¥{info['market_value']:,.0f} | 现金: ¥{info['cash']:,.0f}",
            f"📦 **持仓:** {info['holdings_count']}只 | 交易: {info['trades']}笔",
        ]

        # 持仓明细
        if self.holdings:
            lines.append(f"\n📋 **持仓明细:**")
            for code, h in sorted(self.holdings.items()):
                lines.append(f"  {code}: {h['shares']}股 @¥{h['cost_price']:.2f}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """序列化"""
        return {
            "cash": self.cash,
            "holdings": self.holdings,
            "nav_history": self.nav_history,
            "trade_log": self.trade_log,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NAVTracker":
        tracker = cls()
        tracker.cash = d.get("cash", 1_000_000)
        tracker.holdings = d.get("holdings", {})
        tracker.nav_history = d.get("nav_history", [])
        tracker.trade_log = d.get("trade_log", [])
        return tracker
