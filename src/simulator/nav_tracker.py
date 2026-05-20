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

    def __init__(self, initial_capital: float = 1_000_000, strategy: str = "balanced"):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.holdings = {}  # code -> {shares, cost_price}
        self.nav_history = []  # [{date, nav, cash, market_value, holdings_count}]
        self.peak_nav = 1.0  # 历史最高NAV，用于回撤计算
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
        if scores.empty:
            return

        target_codes = set(scores.head(self.top_n).index.tolist())
        watchlist = set(scores.head(self.top_n + 10).index.tolist()) - target_codes  # 11-20名缓冲区
        current_codes = set(self.holdings.keys())

        # 止损检查
        for code in list(self.holdings.keys()):
            h = self.holdings[code]
            if code in prices and prices[code] > 0:
                pnl = (prices[code] - h["cost_price"]) / h["cost_price"]
                if pnl <= self.stop_loss:
                    self._sell(code, prices[code], date, f"止损({pnl:+.1f}%)")

        # 卖出: 不在目标也不在缓冲区的 (T+1检查)
        today_str = str(date)[:10]
        for code in list(self.holdings.keys()):
            if code not in target_codes and code not in watchlist:
                # T+1: 今天买入的不能卖出
                h = self.holdings.get(code, {})
                if h.get("buy_date") == today_str:
                    continue
                if code in prices and prices[code] > 0:
                    self._sell(code, prices[code], date, reason)

        # 买入: 新进目标的
        new_codes = target_codes - set(self.holdings.keys())
        if new_codes and self.cash > 0:
            # 如果超持仓数，先卖掉排名最低的
            while len(self.holdings) + len(new_codes) > self.top_n:
                # 卖掉不在目标中的
                sold = False
                for code in list(self.holdings.keys()):
                    if code not in target_codes:
                        # T+1: 今天买入的不能卖出
                        bh = self.holdings.get(code, {})
                        if bh.get("buy_date") == today_str:
                            continue
                        if code in prices and prices[code] > 0:
                            self._sell(code, prices[code], date, "腾位")
                            sold = True
                            break
                if not sold:
                    break

            per_stock = self.cash / max(len(new_codes), 1)
            for code in new_codes:
                if code in prices and prices[code] > 0:
                    # 最低评分门槛: 排除评分过低的股票
                    if code in scores.index:
                        code_score = scores.loc[code, "score_total"]
                        median_score = scores["score_total"].median()
                        if code_score < median_score * 0.5:
                            logger.info(f"跳过{code}: 评分{code_score:.2f}低于中位数的50%({median_score:.2f})")
                            continue
                    shares = int(per_stock / prices[code] / 100) * 100
                    if shares >= 100:
                        self._buy(code, shares, prices[code], date, reason)

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
            avg_cost = (old["shares"] * old["cost_price"] + shares * price) / total_shares
            self.holdings[code] = {"shares": total_shares, "cost_price": avg_cost, "buy_date": old.get("buy_date", str(date)[:10])}
        else:
            self.holdings[code] = {"shares": shares, "cost_price": price, "buy_date": str(date)[:10]}

        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "buy",
            "shares": shares, "price": price, "reason": reason,
        })
        # 记录买入时间给时间止损
        try:
            from src.risk_management.time_stop import TimeStopManager
            tsm = TimeStopManager()
            tsm.record_entry(code, str(date)[:10])
        except Exception:
            pass
        # 记录到JSON交易日志
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "buy", price, shares, reason)
        except Exception:
            pass

    def _sell(self, code: str, price: float, date, reason: str):
        h = self.holdings.get(code)
        if not h:
            return
        cost_price = h.get("cost_price", price)
        pnl = (price - cost_price) * h["shares"]
        proceeds = h["shares"] * price * (1 - self.commission_rate)
        self.cash += proceeds
        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "sell",
            "shares": h["shares"], "price": price, "reason": reason,
        })
        # 记录到JSON交易日志(含盈亏)
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "sell", price, h["shares"], reason, pnl)
        except Exception:
            pass
        # 记录到策略跟踪系统（闭环）
        try:
            from src.simulator.trade_tracker import record_trade
            buy_date_str = str(h.get("buy_date", ""))[:10]
            if buy_date_str:
                from src.data.stock_names import stock_name as _sn
                record_trade(
                    code=code, name=_sn(code), action="sell",
                    buy_price=cost_price, sell_price=price,
                    shares=h["shares"], buy_date=buy_date_str,
                    sell_date=str(date)[:10], reason=reason,
                )
        except Exception:
            pass
        del self.holdings[code]

    def _partial_sell(self, code: str, shares: int, price: float, date, reason: str):
        """卖出部分持仓"""
        h = self.holdings.get(code)
        if not h or shares <= 0 or shares >= h["shares"]:
            return
        cost_price = h.get("cost_price", price)
        pnl = (price - cost_price) * shares
        proceeds = shares * price * (1 - self.commission_rate)
        self.cash += proceeds
        h["shares"] -= shares
        # 如果减到0股，清除持仓
        if h["shares"] <= 0:
            del self.holdings[code]
        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "sell",
            "shares": shares, "price": price, "reason": reason,
        })
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "sell", price, shares, reason, pnl)
        except Exception:
            pass
        # 记录减仓到策略跟踪（与_sell一致）
        try:
            from src.simulator.trade_tracker import record_trade
            from src.data.stock_names import stock_name as _sn
            record_trade(
                code=code, name=_sn(code), action="partial_sell",
                buy_price=cost_price, sell_price=price,
                shares=shares, buy_date=str(h.get("buy_date", ""))[:10],
                sell_date=str(date)[:10], reason=reason,
            )
        except Exception:
            pass

    def _add_position(self, code: str, shares: int, price: float, date, reason: str):
        """加仓（已有持仓增持）"""
        h = self.holdings.get(code)
        if not h:
            return
        cost = shares * price * (1 + self.commission_rate)
        if cost > self.cash:
            return
        self.cash -= cost
        # 加权平均成本 (不含佣金，与_buy保持一致)
        total_shares = h["shares"] + shares
        h["cost_price"] = round((h["cost_price"] * h["shares"] + price * shares) / total_shares, 2)
        h["shares"] = total_shares
        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "buy",
            "shares": shares, "price": price, "reason": reason,
        })
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "buy", price, shares, reason, 0)
        except Exception:
            pass


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

        # 更新peak_nav
        if nav > self.peak_nav:
            self.peak_nav = nav

        self.nav_history.append({
            "date": date,
            "nav": nav,
            "cash": self.cash,
            "market_value": market_value,
            "holdings_count": len(self.holdings),
        })
        # Deduplicate: keep last entry per date
        seen = {}
        for h in self.nav_history:
            d = h["date"] if isinstance(h["date"], str) else str(h["date"])
            seen[d] = h
        self.nav_history = list(seen.values())

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
            from src.data.stock_names import stock_name
            lines.append(f"\n📋 **持仓明细:**")
            for code, h in sorted(self.holdings.items()):
                name = stock_name(code)
                lines.append(f"  {name}({code}): {h['shares']}股 @¥{h['cost_price']:.2f}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """序列化"""
        return {
            "cash": self.cash,
            "holdings": self.holdings,
            "nav_history": self.nav_history,
            "trade_log": self.trade_log,
            "peak_nav": self.peak_nav,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NAVTracker":
        tracker = cls()
        tracker.cash = d.get("cash", 1_000_000)
        tracker.holdings = d.get("holdings", {})
        tracker.nav_history = d.get("nav_history", [])
        tracker.trade_log = d.get("trade_log", [])
        return tracker
