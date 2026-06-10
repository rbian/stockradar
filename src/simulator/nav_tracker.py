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
        # 单日新建仓限制（防止2026-05-12式同日3只全亏）
        self._daily_new_buys = {}  # {date_str: count}
        self.max_new_buys_per_day = 2

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

        # 止损检查 (ATR动态止损 + 最小持仓期3天)
        today_str_sl = str(date)[:10]
        for code in list(self.holdings.keys()):
            h = self.holdings[code]
            if code in prices and prices[code] > 0:
                pnl = (prices[code] - h["cost_price"]) / h["cost_price"]
                # ATR动态止损线: 2倍ATR/price，限制在[-10%, -25%]区间
                # 高波动股给更多空间，低波动股止损更紧
                try:
                    atr_stop = self._calc_atr_stop(code)
                except Exception:
                    atr_stop = self.stop_loss
                if pnl <= atr_stop:
                    # 最小持仓期保护: 持仓<3天且跌幅<20%时不止损，等确认
                    buy_dt = h.get("buy_date", "")
                    try:
                        from datetime import datetime as _dt
                        hold_days = (_dt.strptime(today_str_sl, "%Y-%m-%d") - _dt.strptime(buy_dt, "%Y-%m-%d")).days
                    except Exception:
                        hold_days = 99
                    if hold_days < 3 and pnl > -0.20:
                        continue  # 跳过，等待确认
                    reason = f"止损({pnl:+.1f}%, ATR线{atr_stop*100:.1f}%)"
                    self._sell(code, prices[code], date, reason)

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

            # 评分加权仓位: 评分高的给更多仓位，评分低的给更少
            base_alloc = self.cash / max(len(new_codes), 1)
            try:
                score_weights = {}
                for code in new_codes:
                    if code in scores.index:
                        s = max(scores.loc[code, "score_total"], 0.1)
                        score_weights[code] = s
                total_w = sum(score_weights.values()) if score_weights else 1
            except Exception:
                score_weights = {}
                total_w = 1

            for code in new_codes:
                if code in prices and prices[code] > 0:
                    # 最低评分门槛: 排除评分过低的股票
                    if code in scores.index:
                        code_score = scores.loc[code, "score_total"]
                        median_score = scores["score_total"].median()
                        if code_score < median_score * 0.5:
                            logger.info(f"跳过{code}: 评分{code_score:.2f}低于中位数的50%({median_score:.2f})")
                            continue
                    # 评分加权分配: 高分多配，低分少配
                    w = score_weights.get(code, 1)
                    alloc = base_alloc * (w / (total_w / max(len(score_weights), 1)))
                    shares = int(alloc / prices[code] / 100) * 100
                    if shares >= 100:
                        self._buy(code, shares, prices[code], date, reason)

    def _check_daily_buy_limit(self, code: str, date_str: str) -> bool:
        """检查单日新建仓是否超限（已有持仓的加仓不受限）"""
        if code in self.holdings:
            return True  # 加仓不受限制
        count = self._daily_new_buys.get(date_str, 0)
        if count >= self.max_new_buys_per_day:
            logger.info(f"单日新建仓限制: 今日已建{count}仓，跳过{code}")
            return False
        return True

    def _record_daily_buy(self, code: str, date_str: str):
        """记录今日新建仓"""
        if code not in self.holdings:
            return  # _buy failed
        # 只有新建仓（不是加仓）才计数
        self._daily_new_buys[date_str] = self._daily_new_buys.get(date_str, 0) + 1

    def _buy(self, code: str, shares: int, price: float, date, reason: str,
             factor_score: float = None, signal_score: float = None):
        cost = shares * price * (1 + self.commission_rate)
        if cost > self.cash:
            shares = int(self.cash / (price * (1 + self.commission_rate)) / 100) * 100
            cost = shares * price * (1 + self.commission_rate)
        if shares < 100:
            return

        # 单日新建仓限制
        date_str = str(date)[:10]
        if not self._check_daily_buy_limit(code, date_str):
            return

        self.cash -= cost
        is_new = code not in self.holdings
        if code in self.holdings:
            old = self.holdings[code]
            total_shares = old["shares"] + shares
            avg_cost = (old["shares"] * old["cost_price"] + shares * price) / total_shares
            self.holdings[code] = {"shares": total_shares, "cost_price": avg_cost, "buy_date": old.get("buy_date", str(date)[:10]), "peak_price": max(old.get("peak_price", price), price)}
        else:
            self.holdings[code] = {"shares": shares, "cost_price": price, "buy_date": str(date)[:10], "peak_price": price, "original_shares": shares}

        # 存储因子快照到持仓（供_sell时传递给trade_tracker）
        if factor_score is not None:
            self.holdings[code]["factor_score"] = factor_score
        if signal_score is not None:
            self.holdings[code]["signal_score"] = signal_score

        # 记录新建仓
        if is_new:
            self._record_daily_buy(code, date_str)

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
            "shares": h["shares"], "price": price, "reason": reason, "pnl": pnl,
        })
        # 记录到JSON交易日志(含盈亏)
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "sell", price, h["shares"], reason, pnl)
        except Exception:
            pass
        # 记录到策略跟踪系统（闭环）— 含因子快照
        try:
            from src.simulator.trade_tracker import record_trade
            buy_date_str = str(h.get("buy_date", ""))[:10]
            if buy_date_str:
                from src.data.stock_names import stock_name as _sn
                # 从持仓中提取因子快照
                factors = {}
                signals = {}
                if h.get("factor_score") is not None:
                    factors["total_score"] = h["factor_score"]
                if h.get("signal_score") is not None:
                    signals["signal_score"] = h["signal_score"]
                _orig_shares = h.get("original_shares", h["shares"])
                record_trade(
                    code=code, name=_sn(code), action="sell",
                    buy_price=cost_price, sell_price=price,
                    shares=_orig_shares, buy_date=buy_date_str,
                    sell_date=str(date)[:10], reason=reason,
                    factors=factors, signals=signals,
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
        original_shares = h.get("original_shares", h["shares"])
        h["shares"] -= shares
        # 更新peak_price（部分卖出时价格可能是新高）
        if price > h.get("peak_price", price):
            h["peak_price"] = price

        is_full_close = h["shares"] <= 0
        if is_full_close:
            del self.holdings[code]

        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "sell",
            "shares": shares, "price": price, "reason": reason, "pnl": pnl,
        })
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "sell", price, shares, reason, pnl)
        except Exception:
            pass

        # 记录到策略跟踪
        if is_full_close:
            # 完整平仓: 记录原始总仓位（而非仅最后部分），确保trade_tracker P&L准确
            try:
                from src.simulator.trade_tracker import record_trade
                from src.data.stock_names import stock_name as _sn
                record_trade(
                    code=code, name=_sn(code), action="sell",
                    buy_price=cost_price, sell_price=price,
                    shares=original_shares, buy_date=str(h.get("buy_date", ""))[:10],
                    sell_date=str(date)[:10], reason=reason + "_final",
                )
            except Exception:
                pass
        else:
            # 部分减仓: 只记录部分信息（trade_tracker dedup会自动处理）
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
        h["peak_price"] = max(h.get("peak_price", price), price)
        h["shares"] = total_shares
        h["original_shares"] = h.get("original_shares", 0) + shares
        self.trade_log.append({
            "date": str(date)[:16] if len(str(date)) > 10 else str(date), "code": code, "action": "buy",
            "shares": shares, "price": price, "reason": reason,
        })
        try:
            from src.simulator.trade_log import log_trade
            log_trade(code, "buy", price, shares, reason, 0)
        except Exception:
            pass


    def _calc_atr_stop(self, code: str) -> float:
        """Calculate ATR-based dynamic stop loss for a stock.
        Returns stop loss threshold (negative), clamped to [-10%, -25%].
        Uses 2x ATR(14) / cost_price as the stop distance.
        """
        try:
            import numpy as np
            from pathlib import Path
            import pandas as pd
            h = self.holdings.get(code, {})
            cost_price = h.get("cost_price", 0)
            if cost_price <= 0:
                return self.stop_loss
            # Load recent daily data from parquet cache
            pq_dir = Path(__file__).parent.parent.parent / "data" / "cache" / "daily_quote"
            pq_files = sorted(pq_dir.glob("*.parquet"))[-20:]  # last 20 files
            if not pq_files:
                return self.stop_loss
            dfs = [pd.read_parquet(f) for f in pq_files]
            df = pd.concat(dfs, ignore_index=True)
            stock_df = df[df["code"] == code].tail(20).sort_values("date" if "date" in df.columns else df.columns[0])
            if len(stock_df) < 5:
                return self.stop_loss
            # Simple ATR proxy: average daily range over last 14 days
            if "high" in stock_df.columns and "low" in stock_df.columns:
                daily_range = (stock_df["high"] - stock_df["low"]).tail(14)
            else:
                # Fallback: use close-to-close absolute changes
                daily_range = stock_df["close"].diff().abs().tail(14)
            atr = daily_range.mean()
            if atr <= 0 or np.isnan(atr):
                return self.stop_loss
            # 2x ATR as stop distance, as fraction of cost_price
            atr_stop_pct = -(2 * atr / cost_price)
            # Clamp to [-10%, -25%]
            atr_stop_pct = max(-0.25, min(-0.10, atr_stop_pct))
            return atr_stop_pct
        except Exception:
            return self.stop_loss

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
        tracker.peak_nav = d.get("peak_nav", 1.0)
        # 补全缺失的peak_price（旧数据迁移/保存丢失时fallback到cost_price）
        for code, h in tracker.holdings.items():
            if "peak_price" not in h or h["peak_price"] is None:
                h["peak_price"] = h.get("cost_price", 0)
        return tracker
