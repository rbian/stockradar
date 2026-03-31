"""净值追踪模块

每日记录模拟账户的总资产、现金、持仓市值和净值变化，
用于计算收益率、回撤等绩效指标。
"""

from datetime import date, datetime

import pandas as pd
from loguru import logger

from src.data.store import DataStore
from src.infra.config import get_settings


class NAVTracker:
    """净值追踪器"""

    def __init__(self, store: DataStore = None):
        settings = get_settings()
        sim_cfg = settings.get("simulator", {})
        self.store = store or DataStore()
        self.initial_capital = sim_cfg.get("initial_capital", 1_000_000.0)

    def record_nav(self, cash: float, market_value: float,
                   trade_date=None) -> dict:
        """记录当日净值

        Args:
            cash: 可用现金
            market_value: 持仓总市值
            trade_date: 交易日

        Returns:
            净值记录dict
        """
        trade_date = trade_date or date.today()
        total_assets = cash + market_value
        nav = total_assets / self.initial_capital

        # 计算日收益率
        prev_nav = self._get_prev_nav(trade_date)
        if prev_nav and prev_nav > 0:
            daily_return = (nav - prev_nav) / prev_nav
        else:
            daily_return = 0.0

        # 计算累计收益率
        cumulative_return = (total_assets - self.initial_capital) / self.initial_capital

        row = {
            "date": pd.Timestamp(trade_date),
            "nav": round(nav, 6),
            "total_assets": round(total_assets, 2),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "daily_return": round(daily_return, 6),
            "cumulative_return": round(cumulative_return, 6),
            "created_at": datetime.now(),
        }

        df = pd.DataFrame([row])
        self.store.upsert_df("nav_history", df, pk_cols=["date"])
        logger.info(
            f"净值记录: NAV={nav:.4f}, 总资产={total_assets:.2f}, "
            f"日收益={daily_return*100:+.2f}%, 累计={cumulative_return*100:+.2f}%"
        )

        return row

    def get_nav_history(self, start_date=None, end_date=None) -> pd.DataFrame:
        """获取净值历史

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            净值历史DataFrame
        """
        conditions = []
        if start_date:
            conditions.append(f"date >= '{start_date}'")
        if end_date:
            conditions.append(f"date <= '{end_date}'")

        where = " AND ".join(conditions) if conditions else None
        df = self.store.get_table("nav_history", where=where)

        if not df.empty:
            df = df.sort_values("date")

        return df

    def get_latest_nav(self) -> dict | None:
        """获取最新净值"""
        df = self.store.get_table("nav_history")
        if df.empty:
            return None
        df = df.sort_values("date")
        return df.iloc[-1].to_dict()

    def get_performance_stats(self, days: int = 30) -> dict:
        """获取绩效统计

        Args:
            days: 统计天数

        Returns:
            {
                total_return: 累计收益率,
                annualized_return: 年化收益率,
                max_drawdown: 最大回撤,
                sharpe_ratio: 夏普比率,
                win_rate: 胜率,
                volatility: 年化波动率,
                trading_days: 交易日数,
            }
        """
        end = date.today()
        start = end - pd.Timedelta(days=days * 2)  # 多拉一些确保够
        df = self.get_nav_history(start_date=start, end_date=end)

        if df.empty or len(df) < 2:
            return self._empty_stats()

        # 只取最近 days 天
        df = df.tail(days)

        if len(df) < 2:
            return self._empty_stats()

        returns = df["daily_return"].dropna().values

        # 累计收益率
        total_return = (df["nav"].iloc[-1] / df["nav"].iloc[0] - 1)

        # 年化收益率
        trading_days = len(df)
        annualized_return = (1 + total_return) ** (252 / max(trading_days, 1)) - 1

        # 最大回撤
        nav_series = df["nav"].values
        peak = nav_series[0]
        max_dd = 0.0
        for nav in nav_series:
            if nav > peak:
                peak = nav
            dd = (nav - peak) / peak
            if dd < max_dd:
                max_dd = dd

        # 夏普比率（无风险利率按3%年化）
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() * 252 - 0.03) / (returns.std() * (252 ** 0.5))
        else:
            sharpe = 0.0

        # 胜率
        win_days = (returns > 0).sum()
        win_rate = win_days / len(returns) if len(returns) > 0 else 0.0

        # 年化波动率
        volatility = returns.std() * (252 ** 0.5) if len(returns) > 1 else 0.0

        return {
            "total_return": round(total_return, 4),
            "annualized_return": round(annualized_return, 4),
            "max_drawdown": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 2),
            "win_rate": round(win_rate, 4),
            "volatility": round(volatility, 4),
            "trading_days": trading_days,
        }

    def _get_prev_nav(self, trade_date) -> float | None:
        """获取前一交易日的净值"""
        df = self.store.get_table(
            "nav_history",
            where=f"date < '{trade_date}'"
        )
        if df.empty:
            return None
        df = df.sort_values("date")
        return float(df.iloc[-1]["nav"])

    @staticmethod
    def _empty_stats() -> dict:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "volatility": 0.0,
            "trading_days": 0,
        }
