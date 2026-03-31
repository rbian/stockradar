"""回测引擎

核心原则：
- 策略代码与回测共用同一套逻辑
- 策略函数只接收"截止某日的数据"，不知道自己在回测
- 循环每个交易日，调用策略函数，记录每日持仓、净值、交易

支持 Walk-Forward 验证防止过拟合。
"""

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.a_share_constraints import (
    AShareConstraints,
    Position,
    TradeRecord,
)
from src.factors.engine import FactorEngine
from src.strategy.continuous_score import ContinuousScoreStrategy
from src.infra.config import get_settings


@dataclass
class DailyState:
    """每日状态快照"""
    date: str
    nav: float  # 净值
    cash: float  # 现金
    market_value: float  # 持仓市值
    total_assets: float  # 总资产
    daily_return: float  # 日收益率
    holdings: list  # 持仓代码列表
    num_positions: int  # 持仓数量
    trades: list  # 当日交易列表


class BacktestEngine:
    """回测引擎

    用法：
        engine = BacktestEngine(store=DataStore())
        result = engine.run(
            start_date="2020-01-01",
            end_date="2024-12-31",
        )
        report = engine.generate_report(result)
    """

    def __init__(self, store=None, strategy=None, constraints=None):
        settings = get_settings()
        sim_cfg = settings.get("simulator", {})

        self.store = store
        self.initial_capital = sim_cfg.get("initial_capital", 1_000_000.0)
        self.constraints = constraints or AShareConstraints(settings)

        if strategy is None:
            factor_engine = FactorEngine()
            self.strategy = ContinuousScoreStrategy(engine=factor_engine)
        else:
            self.strategy = strategy

    def run(self, start_date: str, end_date: str,
            initial_capital: float = None,
            benchmark_code: str = "000300") -> dict:
        """运行回测

        Args:
            start_date: 回测开始日期
            end_date: 回测结束日期
            initial_capital: 初始资金
            benchmark_code: 基准指数代码

        Returns:
            {
                "daily_states": [DailyState, ...],
                "trades": [TradeRecord, ...],
                "positions": 最终持仓,
                "nav_series": pd.Series(净值序列),
                "benchmark_series": pd.Series(基准净值序列),
            }
        """
        if initial_capital is None:
            initial_capital = self.initial_capital

        logger.info(
            f"回测开始: {start_date} ~ {end_date}, "
            f"初始资金: {initial_capital:,.0f}"
        )

        # 加载数据
        data = self._load_data(start_date, end_date)
        trading_dates = self._get_trading_dates(data["daily_quote"], start_date, end_date)

        if trading_dates.empty:
            logger.error("无交易日数据")
            return self._empty_result(start_date, end_date)

        # 初始化
        cash = initial_capital
        positions: dict[str, Position] = {}  # code -> Position
        daily_states: list[DailyState] = []
        all_trades: list[TradeRecord] = []
        prev_total_assets = initial_capital

        # 重置策略状态（每次回测都是全新开始）
        self.strategy.prev_scores = None
        self.strategy.prev_delta = None
        self.strategy.current_portfolio = []
        self.strategy.buffer_tracker = {}

        for i, date in enumerate(trading_dates):
            date_str = str(date.date()) if hasattr(date, "date") else str(date)

            # 重置T+1追踪
            self.constraints.reset_daily()

            # 截取截止当日的数据（策略函数不知道自己在回测）
            cutoff_data = self._slice_data_until(data, date_str)

            # 获取当日行情（用于交易执行和持仓估值）
            current_quote = self._get_date_quote(data["daily_quote"], date_str)

            # 1. 策略评估（和实盘共用同一套代码）
            result = self.strategy.daily_evaluate(
                data=cutoff_data,
                date=date_str,
                current_portfolio=list(positions.keys()),
            )

            # 2. 执行交易（应用A股约束）
            day_trades = self._execute_trades(
                result["actions"],
                positions,
                cash,
                data["daily_quote"],
                date_str,
                data.get("stock_info", pd.DataFrame()),
                current_quote,
            )

            # 更新持仓和现金
            for trade in day_trades:
                all_trades.append(trade)
                if trade.action == "buy":
                    cash -= (trade.amount + trade.commission + trade.slippage_cost)
                    positions[trade.code] = Position(
                        code=trade.code,
                        shares=trade.shares,
                        buy_date=date_str,
                        buy_price=trade.price,
                        current_price=trade.price,
                    )
                elif trade.action == "sell":
                    cash += (trade.amount - trade.commission - trade.stamp_tax - trade.slippage_cost)
                    remaining = positions[trade.code].shares - trade.shares
                    if remaining <= 0:
                        del positions[trade.code]
                    else:
                        positions[trade.code].shares = remaining

            # 3. 更新持仓市值
            total_market_value = 0.0
            for code, pos in positions.items():
                if current_quote is not None and code in current_quote:
                    pos.current_price = current_quote[code]
                total_market_value += pos.market_value

            total_assets = cash + total_market_value
            daily_return = (total_assets - prev_total_assets) / prev_total_assets if prev_total_assets > 0 else 0.0

            # 4. 记录每日状态
            state = DailyState(
                date=date_str,
                nav=total_assets / initial_capital,
                cash=cash,
                market_value=total_market_value,
                total_assets=total_assets,
                daily_return=daily_return,
                holdings=list(positions.keys()),
                num_positions=len(positions),
                trades=[t for t in day_trades],
            )
            daily_states.append(state)

            prev_total_assets = total_assets

            # 进度日志
            if (i + 1) % 50 == 0 or i == len(trading_dates) - 1:
                logger.info(
                    f"回测进度: {date_str} ({i + 1}/{len(trading_dates)}), "
                    f"净值: {state.nav:.4f}, 持仓: {state.num_positions}只"
                )

        # 构建结果
        nav_series = pd.Series(
            {s.date: s.nav for s in daily_states},
            dtype=float,
        )

        benchmark_series = self._build_benchmark(
            data.get("market_index", pd.DataFrame()),
            benchmark_code,
            trading_dates,
        )

        logger.info(
            f"回测完成: {len(daily_states)} 个交易日, "
            f"{len(all_trades)} 笔交易, "
            f"最终净值: {nav_series.iloc[-1]:.4f}"
        )

        return {
            "daily_states": daily_states,
            "trades": all_trades,
            "positions": positions,
            "nav_series": nav_series,
            "benchmark_series": benchmark_series,
            "initial_capital": initial_capital,
            "start_date": start_date,
            "end_date": end_date,
        }

    def run_walk_forward(self, start_year: int = 2016,
                         end_year: int = 2025,
                         train_years: int = 3,
                         test_years: int = 1,
                         benchmark_code: str = "000300") -> dict:
        """Walk-Forward 验证

        滚动窗口回测，防止过拟合：
        训练期（3年）→ 测试期（1年）→ 滚动

        Args:
            start_year: 起始年份
            end_year: 结束年份
            train_years: 训练窗口年数
            test_years: 测试窗口年数
            benchmark_code: 基准指数

        Returns:
            {
                "windows": [...],
                "combined_nav": pd.Series,
                "summary": dict,
            }
        """
        windows = []
        combined_states = []
        combined_nav = {}

        year = start_year + train_years
        while year + test_years - 1 <= end_year:
            train_start = f"{year - train_years}-01-01"
            train_end = f"{year - 1}-12-31"
            test_start = f"{year}-01-01"
            test_end = f"{year + test_years - 1}-12-31"

            logger.info(
                f"Walk-Forward: 训练 {train_start}~{train_end} → "
                f"测试 {test_start}~{test_end}"
            )

            # 测试期回测
            test_result = self.run(
                start_date=test_start,
                end_date=test_end,
                benchmark_code=benchmark_code,
            )

            windows.append({
                "train_period": (train_start, train_end),
                "test_period": (test_start, test_end),
                "result": test_result,
                "final_nav": test_result["nav_series"].iloc[-1] if len(test_result["nav_series"]) > 0 else 1.0,
            })

            # 拼接测试期净值
            for date_str, nav in test_result["nav_series"].items():
                combined_nav[date_str] = nav * (len(windows) if len(windows) > 1 else 1.0)

            year += test_years

        # 归一化组合净值
        combined_series = pd.Series(combined_nav, dtype=float).sort_index()
        if len(combined_series) > 0:
            combined_series = combined_series / combined_series.iloc[0]

        summary = self._walk_forward_summary(windows)

        return {
            "windows": windows,
            "combined_nav": combined_series,
            "summary": summary,
        }

    def _walk_forward_summary(self, windows: list) -> dict:
        """Walk-Forward汇总"""
        if not windows:
            return {}

        navs = [w["final_nav"] for w in windows]
        profitable = sum(1 for n in navs if n > 1.0)
        total = len(navs)

        return {
            "total_windows": total,
            "profitable_windows": profitable,
            "win_rate": profitable / total if total > 0 else 0,
            "avg_nav": np.mean(navs),
            "median_nav": np.median(navs),
            "min_nav": np.min(navs),
            "max_nav": np.max(navs),
            "all_positive": all(n > 1.0 for n in navs),
        }

    def _execute_trades(self, actions: list,
                        positions: dict[str, Position],
                        cash: float,
                        daily_quote: pd.DataFrame,
                        date: str,
                        stock_info: pd.DataFrame,
                        current_quote: dict = None) -> list[TradeRecord]:
        """根据策略动作执行交易（应用A股约束）

        Args:
            actions: 策略输出的交易动作列表
            positions: 当前持仓
            cash: 当前现金
            daily_quote: 行情数据
            date: 日期
            stock_info: 股票信息
            current_quote: 当日行情 {code: close_price}

        Returns:
            实际执行的交易列表
        """
        executed = []

        # 先处理卖出（释放资金）
        for action in actions:
            if action.get("action") != "sell":
                continue

            code = action["code"]
            if code not in positions:
                continue

            trade = self.constraints.execute_sell(
                position=positions[code],
                daily_quote=daily_quote,
                date=date,
                stock_info=stock_info,
            )
            if trade is not None:
                trade.reason = action.get("reason", "")
                executed.append(trade)

        # 再处理买入
        # 等权分配现金给所有买入目标
        buy_actions = [a for a in actions if a.get("action") == "buy"]
        if buy_actions:
            # 计算卖出后可用现金（近似）
            sell_proceeds = sum(
                t.amount - t.commission - t.stamp_tax - t.slippage_cost
                for t in executed if t.action == "sell"
            )
            available_cash = cash + sell_proceeds

            # 等权分配（考虑已有持仓数量）
            n_buys = len(buy_actions)
            if n_buys > 0:
                per_stock_amount = available_cash / n_buys

                for action in buy_actions:
                    code = action["code"]
                    if code in positions:
                        continue

                    trade = self.constraints.execute_buy(
                        code=code,
                        target_amount=per_stock_amount,
                        daily_quote=daily_quote,
                        date=date,
                        stock_info=stock_info,
                    )
                    if trade is not None:
                        trade.reason = action.get("reason", "")
                        executed.append(trade)

        # 减仓处理（风控减仓）
        for action in actions:
            if action.get("action") == "reduce":
                code = action["code"]
                ratio = action.get("ratio", 0.5)
                if code not in positions:
                    continue

                sell_shares = int(positions[code].shares * ratio)
                trade = self.constraints.execute_sell(
                    position=positions[code],
                    daily_quote=daily_quote,
                    date=date,
                    sell_shares=sell_shares,
                    stock_info=stock_info,
                )
                if trade is not None:
                    trade.reason = action.get("reason", "")
                    executed.append(trade)

        return executed

    def _load_data(self, start_date: str, end_date: str) -> dict:
        """加载回测所需数据"""
        data = {}

        if self.store is not None:
            # 从DataStore加载
            data["daily_quote"] = self.store.get_daily_quote_with_cold(
                start_date=start_date, end_date=end_date
            )
            data["financial"] = self.store.get_table("financial_indicator")
            data["stock_info"] = self.store.get_table("stock_info")
            data["northbound"] = self.store.get_table("northbound_stock")
            data["market_index"] = self.store.get_table("market_index_daily")
            data["market_sentiment"] = self.store.get_table("market_sentiment")
        else:
            # 无store时使用空DataFrame
            for key in ["daily_quote", "financial", "stock_info",
                        "northbound", "market_index", "market_sentiment"]:
                data[key] = pd.DataFrame()

        return data

    def _get_trading_dates(self, daily_quote: pd.DataFrame,
                           start_date: str, end_date: str) -> pd.DatetimeIndex:
        """从行情数据中提取交易日列表（自动跳过非交易日）"""
        if daily_quote.empty or "date" not in daily_quote.columns:
            return pd.DatetimeIndex([])

        dates = pd.to_datetime(daily_quote["date"]).sort_values().unique()
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        mask = (dates >= start_ts) & (dates <= end_ts)
        return pd.DatetimeIndex(dates[mask])

    def _slice_data_until(self, data: dict, date: str) -> dict:
        """截取截止某日的数据（策略只能看到历史数据）"""
        result = {}
        date_ts = pd.Timestamp(date)

        for key, df in data.items():
            if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns:
                df_copy = df.copy()
                df_copy["date"] = pd.to_datetime(df_copy["date"])
                result[key] = df_copy[df_copy["date"] <= date_ts]
            else:
                result[key] = df

        return result

    def _get_date_quote(self, daily_quote: pd.DataFrame,
                        date: str) -> dict | None:
        """获取某日所有股票的收盘价 {code: close}"""
        if daily_quote.empty:
            return None

        dq = daily_quote.copy()
        dq["date"] = pd.to_datetime(dq["date"])
        date_ts = pd.Timestamp(date)
        day_data = dq[dq["date"] == date_ts]

        if day_data.empty:
            return None

        return dict(zip(day_data["code"], day_data["close"]))

    def _build_benchmark(self, market_index: pd.DataFrame,
                         code: str,
                         trading_dates: pd.DatetimeIndex) -> pd.Series:
        """构建基准净值序列"""
        if market_index.empty:
            return pd.Series(dtype=float)

        mi = market_index.copy()
        mi["date"] = pd.to_datetime(mi["date"])

        if "index_code" in mi.columns:
            mi = mi[mi["index_code"] == code]

        if mi.empty:
            return pd.Series(dtype=float)

        # 归一化为净值
        first_close = mi["close"].iloc[0]
        benchmark = (mi.set_index("date")["close"] / first_close)

        # 对齐交易日
        benchmark = benchmark.reindex(trading_dates, method="ffill")
        return benchmark.dropna()

    def _empty_result(self, start_date: str, end_date: str) -> dict:
        """空结果"""
        return {
            "daily_states": [],
            "trades": [],
            "positions": {},
            "nav_series": pd.Series(dtype=float),
            "benchmark_series": pd.Series(dtype=float),
            "initial_capital": self.initial_capital,
            "start_date": start_date,
            "end_date": end_date,
        }
