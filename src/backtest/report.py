"""回测报告生成

核心指标：
- 总收益率 / 年化收益率
- 夏普比率（Sharpe Ratio）
- 最大回撤（Max Drawdown）
- 卡玛比率（Calmar）
- 胜率 / 盈亏比
- 分年度收益明细
- Walk-Forward汇总
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_return: float  # 总收益率
    annual_return: float  # 年化收益率
    sharpe_ratio: float  # 夏普比率
    max_drawdown: float  # 最大回撤
    max_drawdown_duration: int  # 最大回撤持续天数
    calmar_ratio: float  # 卡玛比率
    win_rate: float  # 胜率
    profit_loss_ratio: float  # 盈亏比
    total_trades: int  # 总交易次数
    monthly_turnover: float  # 月换手率
    benchmark_return: float  # 基准收益率
    alpha: float  # 超额收益
    beta: float  # Beta
    information_ratio: float  # 信息比率


class BacktestReport:
    """回测报告生成器"""

    def __init__(self, risk_free_rate: float = 0.03):
        """
        Args:
            risk_free_rate: 无风险利率（年化，默认3%）
        """
        self.risk_free_rate = risk_free_rate

    def generate(self, result: dict) -> dict:
        """生成完整回测报告

        Args:
            result: BacktestEngine.run() 的返回结果

        Returns:
            {
                "metrics": PerformanceMetrics,
                "yearly_returns": pd.DataFrame,
                "monthly_returns": pd.DataFrame,
                "drawdown_periods": list,
                "trade_analysis": dict,
                "top_trades": dict,
                "summary_text": str,
            }
        """
        daily_states = result.get("daily_states", [])
        trades = result.get("trades", [])
        nav_series = result.get("nav_series", pd.Series(dtype=float))
        benchmark_series = result.get("benchmark_series", pd.Series(dtype=float))

        if not daily_states:
            return {"error": "无回测数据"}

        # 核心绩效指标
        metrics = self._calc_metrics(nav_series, benchmark_series, trades)

        # 分年度收益
        yearly_returns = self._calc_yearly_returns(daily_states)

        # 分月度收益
        monthly_returns = self._calc_monthly_returns(daily_states)

        # 回撤分析
        drawdown_periods = self._calc_drawdown_periods(nav_series)

        # 交易分析
        trade_analysis = self._analyze_trades(trades)

        # 最佳/最差交易
        top_trades = self._top_and_bottom_trades(trades)

        # 文字报告
        summary_text = self._generate_summary_text(metrics, yearly_returns, trade_analysis)

        return {
            "metrics": metrics,
            "yearly_returns": yearly_returns,
            "monthly_returns": monthly_returns,
            "drawdown_periods": drawdown_periods,
            "trade_analysis": trade_analysis,
            "top_trades": top_trades,
            "summary_text": summary_text,
        }

    def generate_walk_forward_report(self, wf_result: dict) -> dict:
        """生成Walk-Forward报告

        Args:
            wf_result: BacktestEngine.run_walk_forward() 的返回结果

        Returns:
            {
                "summary": dict,
                "window_details": list,
                "summary_text": str,
            }
        """
        summary = wf_result.get("summary", {})
        windows = wf_result.get("windows", [])

        window_details = []
        for w in windows:
            test_result = w.get("result", {})
            report = self.generate(test_result)
            window_details.append({
                "train_period": w["train_period"],
                "test_period": w["test_period"],
                "final_nav": w["final_nav"],
                "metrics": report.get("metrics"),
                "summary_text": report.get("summary_text", ""),
            })

        # 汇总文字
        lines = [
            "══════ Walk-Forward 验证报告 ══════",
            f"总窗口数: {summary.get('total_windows', 0)}",
            f"盈利窗口: {summary.get('profitable_windows', 0)}/{summary.get('total_windows', 0)}",
            f"胜率: {summary.get('win_rate', 0):.1%}",
            f"平均净值: {summary.get('avg_nav', 0):.4f}",
            f"中位净值: {summary.get('median_nav', 0):.4f}",
            f"最差窗口: {summary.get('min_nav', 0):.4f}",
            f"最好窗口: {summary.get('max_nav', 0):.4f}",
            f"所有窗口均盈利: {'是' if summary.get('all_positive', False) else '否'}",
            "",
            "── 各窗口详情 ──",
        ]

        for wd in window_details:
            lines.append(
                f"  训练 {wd['train_period'][0]}~{wd['train_period'][1]} → "
                f"测试 {wd['test_period'][0]}~{wd['test_period'][1]}: "
                f"净值 {wd['final_nav']:.4f}"
            )
            m = wd.get("metrics")
            if m:
                lines.append(
                    f"    年化{m.annual_return:.1%} | "
                    f"夏普{m.sharpe_ratio:.2f} | "
                    f"回撤{m.max_drawdown:.1%}"
                )

        if summary.get("all_positive"):
            lines.append("")
            lines.append("结论: 策略在所有Walk-Forward窗口中均盈利，大概率有效（非过拟合）。")
        else:
            lines.append("")
            lines.append("警告: 部分窗口亏损，策略可能存在过拟合风险，需进一步检查。")

        return {
            "summary": summary,
            "window_details": window_details,
            "summary_text": "\n".join(lines),
        }

    def _calc_metrics(self, nav_series: pd.Series,
                      benchmark_series: pd.Series,
                      trades: list) -> PerformanceMetrics:
        """计算核心绩效指标"""
        if len(nav_series) < 2:
            return PerformanceMetrics(
                total_return=0, annual_return=0, sharpe_ratio=0,
                max_drawdown=0, max_drawdown_duration=0, calmar_ratio=0,
                win_rate=0, profit_loss_ratio=0, total_trades=0,
                monthly_turnover=0, benchmark_return=0, alpha=0,
                beta=0, information_ratio=0,
            )

        # 日收益率
        daily_returns = nav_series.pct_change().dropna()
        total_days = len(nav_series)
        trading_days_per_year = 244

        # 总收益率
        total_return = nav_series.iloc[-1] / nav_series.iloc[0] - 1.0

        # 年化收益率
        years = total_days / trading_days_per_year
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # 夏普比率
        rf_daily = self.risk_free_rate / trading_days_per_year
        excess_returns = daily_returns - rf_daily
        sharpe_ratio = (
            excess_returns.mean() / excess_returns.std() * np.sqrt(trading_days_per_year)
            if excess_returns.std() > 0 else 0
        )

        # 最大回撤
        cummax = nav_series.cummax()
        drawdown = (nav_series - cummax) / cummax
        max_drawdown = abs(drawdown.min())

        # 最大回撤持续天数
        max_dd_duration = self._calc_max_dd_duration(drawdown)

        # 卡玛比率
        calmar_ratio = annual_return / max_drawdown if max_drawdown > 0 else 0

        # 胜率 / 盈亏比
        sell_trades = [t for t in trades if hasattr(t, "action") and t.action == "sell"]
        if sell_trades:
            wins = [t for t in sell_trades if t.pnl > 0]
            losses = [t for t in sell_trades if t.pnl <= 0]
            win_rate = len(wins) / len(sell_trades)

            avg_win = np.mean([t.pnl for t in wins]) if wins else 0
            avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 1
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        else:
            win_rate = 0
            profit_loss_ratio = 0

        # 月换手率
        total_buy_amount = sum(
            t.amount for t in trades if hasattr(t, "action") and t.action == "buy"
        )
        avg_capital = nav_series.mean() * 1_000_000  # 近似
        months = total_days / 20  # 约每月20个交易日
        monthly_turnover = (total_buy_amount / avg_capital / months) if avg_capital > 0 and months > 0 else 0

        # 基准对比
        benchmark_return = 0
        alpha = 0
        beta = 0
        information_ratio = 0

        if len(benchmark_series) >= 2:
            # 对齐
            common_idx = nav_series.index.intersection(benchmark_series.index)
            if len(common_idx) >= 2:
                aligned_nav = nav_series.reindex(common_idx)
                aligned_bench = benchmark_series.reindex(common_idx)

                bench_returns = aligned_bench.pct_change().dropna()
                strat_returns = aligned_nav.pct_change().dropna()

                benchmark_return = aligned_bench.iloc[-1] / aligned_bench.iloc[0] - 1.0
                alpha = annual_return - (
                    (aligned_bench.iloc[-1] / aligned_bench.iloc[0]) ** (1 / years) - 1
                ) if years > 0 else 0

                # Beta
                cov_matrix = np.cov(strat_returns, bench_returns)
                bench_var = np.var(bench_returns, ddof=1)
                beta = cov_matrix[0, 1] / bench_var if bench_var > 0 else 0

                # Information Ratio
                active_returns = strat_returns - bench_returns
                ir = (
                    active_returns.mean() / active_returns.std() * np.sqrt(trading_days_per_year)
                    if active_returns.std() > 0 else 0
                )
                information_ratio = ir

        return PerformanceMetrics(
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_dd_duration,
            calmar_ratio=calmar_ratio,
            win_rate=win_rate,
            profit_loss_ratio=profit_loss_ratio,
            total_trades=len(trades),
            monthly_turnover=monthly_turnover,
            benchmark_return=benchmark_return,
            alpha=alpha,
            beta=beta,
            information_ratio=information_ratio,
        )

    def _calc_max_dd_duration(self, drawdown: pd.Series) -> int:
        """计算最大回撤持续天数"""
        in_drawdown = drawdown < 0
        max_duration = 0
        current_duration = 0

        for val in in_drawdown:
            if val:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0

        return max_duration

    def _calc_yearly_returns(self, daily_states: list) -> pd.DataFrame:
        """分年度收益明细"""
        records = []
        for state in daily_states:
            records.append({
                "date": state.date,
                "nav": state.nav,
                "daily_return": state.daily_return,
            })

        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year

        yearly = df.groupby("year").agg(
            start_nav=("nav", "first"),
            end_nav=("nav", "last"),
            trading_days=("date", "count"),
        )
        yearly["return"] = yearly["end_nav"] / yearly["start_nav"] - 1.0
        yearly = yearly[["return", "trading_days"]]

        return yearly

    def _calc_monthly_returns(self, daily_states: list) -> pd.DataFrame:
        """分月度收益"""
        records = []
        for state in daily_states:
            records.append({
                "date": state.date,
                "nav": state.nav,
            })

        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])
        df["year_month"] = df["date"].dt.to_period("M")

        monthly = df.groupby("year_month").agg(
            start_nav=("nav", "first"),
            end_nav=("nav", "last"),
        )
        monthly["return"] = monthly["end_nav"] / monthly["start_nav"] - 1.0

        return monthly[["return"]]

    def _calc_drawdown_periods(self, nav_series: pd.Series) -> list:
        """计算回撤区间"""
        if len(nav_series) < 2:
            return []

        cummax = nav_series.cummax()
        drawdown = (nav_series - cummax) / cummax

        periods = []
        in_dd = False
        start = None
        min_dd = 0
        min_date = None

        for date, dd_val in drawdown.items():
            if dd_val < 0 and not in_dd:
                in_dd = True
                start = date
                min_dd = dd_val
                min_date = date
            elif dd_val < 0 and in_dd:
                if dd_val < min_dd:
                    min_dd = dd_val
                    min_date = date
            elif dd_val >= 0 and in_dd:
                in_dd = False
                periods.append({
                    "start": str(start),
                    "end": str(date),
                    "max_drawdown": abs(min_dd),
                    "max_dd_date": str(min_date),
                    "duration": len(nav_series[start:date]),
                })

        # 如果最后还在回撤中
        if in_dd:
            periods.append({
                "start": str(start),
                "end": str(nav_series.index[-1]),
                "max_drawdown": abs(min_dd),
                "max_dd_date": str(min_date),
                "duration": len(nav_series[start:]),
            })

        # 按回撤深度排序
        periods.sort(key=lambda x: x["max_drawdown"], reverse=True)
        return periods[:10]  # 返回最严重的10次回撤

    def _analyze_trades(self, trades: list) -> dict:
        """交易分析"""
        if not trades:
            return {
                "total_trades": 0,
                "buy_count": 0,
                "sell_count": 0,
                "total_commission": 0,
                "total_stamp_tax": 0,
                "total_slippage": 0,
                "total_cost": 0,
            }

        buy_trades = [t for t in trades if hasattr(t, "action") and t.action == "buy"]
        sell_trades = [t for t in trades if hasattr(t, "action") and t.action == "sell"]

        total_commission = sum(t.commission for t in trades)
        total_stamp_tax = sum(t.stamp_tax for t in trades)
        total_slippage = sum(t.slippage_cost for t in trades)

        # 平均持仓天数
        avg_hold_days = 0
        if sell_trades:
            hold_days_list = []
            buy_dates = {t.code: t.date for t in buy_trades}
            for st in sell_trades:
                buy_date = buy_dates.get(st.code)
                if buy_date:
                    try:
                        bd = pd.Timestamp(buy_date)
                        sd = pd.Timestamp(st.date)
                        hold_days_list.append((sd - bd).days)
                    except Exception:
                        pass
            if hold_days_list:
                avg_hold_days = np.mean(hold_days_list)

        return {
            "total_trades": len(trades),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "total_commission": total_commission,
            "total_stamp_tax": total_stamp_tax,
            "total_slippage": total_slippage,
            "total_cost": total_commission + total_stamp_tax + total_slippage,
            "avg_hold_days": avg_hold_days,
        }

    def _top_and_bottom_trades(self, trades: list) -> dict:
        """最佳和最差交易"""
        sell_trades = [
            t for t in trades
            if hasattr(t, "action") and t.action == "sell"
        ]

        if not sell_trades:
            return {"best": [], "worst": []}

        sorted_trades = sorted(sell_trades, key=lambda t: t.pnl, reverse=True)

        best = [
            {
                "code": t.code,
                "date": t.date,
                "pnl": t.pnl,
                "pnl_pct": t.pnl / (t.buy_price * t.shares) if t.buy_price * t.shares > 0 else 0,
                "reason": t.reason,
            }
            for t in sorted_trades[:5]
        ]

        worst = [
            {
                "code": t.code,
                "date": t.date,
                "pnl": t.pnl,
                "pnl_pct": t.pnl / (t.buy_price * t.shares) if t.buy_price * t.shares > 0 else 0,
                "reason": t.reason,
            }
            for t in sorted_trades[-5:]
        ]

        return {"best": best, "worst": worst}

    def _generate_summary_text(self, metrics: PerformanceMetrics,
                               yearly_returns: pd.DataFrame,
                               trade_analysis: dict) -> str:
        """生成文字报告"""
        lines = [
            "══════ 回测报告 ══════",
            "",
            f"总收益率:     {metrics.total_return:>8.2%}",
            f"年化收益率:   {metrics.annual_return:>8.2%}",
            f"夏普比率:     {metrics.sharpe_ratio:>8.2f}",
            f"最大回撤:     {metrics.max_drawdown:>8.2%}",
            f"回撤持续天数: {metrics.max_drawdown_duration:>8d}",
            f"卡玛比率:     {metrics.calmar_ratio:>8.2f}",
            f"胜率:         {metrics.win_rate:>8.2%}",
            f"盈亏比:       {metrics.profit_loss_ratio:>8.2f}",
            f"总交易次数:   {metrics.total_trades:>8d}",
            f"月换手率:     {metrics.monthly_turnover:>8.2%}",
            "",
            f"基准收益率:   {metrics.benchmark_return:>8.2%}",
            f"超额收益Alpha:{metrics.alpha:>8.2%}",
            f"Beta:         {metrics.beta:>8.2f}",
            f"信息比率:     {metrics.information_ratio:>8.2f}",
            "",
            f"总手续费:     {trade_analysis.get('total_commission', 0):>10,.0f}",
            f"总印花税:     {trade_analysis.get('total_stamp_tax', 0):>10,.0f}",
            f"总滑点成本:   {trade_analysis.get('total_slippage', 0):>10,.0f}",
            f"总交易成本:   {trade_analysis.get('total_cost', 0):>10,.0f}",
        ]

        # 分年度
        if not yearly_returns.empty:
            lines.append("")
            lines.append("── 分年度收益 ──")
            for year, row in yearly_returns.iterrows():
                ret = row["return"]
                marker = "+" if ret > 0 else " "
                lines.append(f"  {year}: {marker}{ret:.2%} ({int(row['trading_days'])}交易日)")

        return "\n".join(lines)
