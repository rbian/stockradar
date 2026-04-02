"""消息格式化模块

将持仓、交易、评分等数据格式化为 Telegram 消息文本。
支持 Markdown 格式。
"""

from datetime import date, datetime

import pandas as pd


def format_portfolio(summary: dict, stock_info: dict = None) -> str:
    """格式化持仓信息

    Args:
        summary: PortfolioManager.get_portfolio_summary() 返回值
        stock_info: {code: name} 股票名称映射
    """
    lines = [f"*模拟持仓 ({summary['position_count']}只)*\n"]

    total_pnl = summary["total_pnl"]
    total_pnl_pct = summary["total_pnl_pct"]
    emoji = "+" if total_pnl >= 0 else ""

    lines.append(
        f"总市值: {summary['total_market_value']:,.0f}\n"
        f"总盈亏: {emoji}{total_pnl:,.0f} ({emoji}{total_pnl_pct*100:.2f}%)\n"
    )

    for i, pos in enumerate(summary["positions"], 1):
        name = (stock_info or {}).get(pos["code"], pos["code"])
        pnl_emoji = "+" if pos["pnl_pct"] >= 0 else ""
        lines.append(
            f"{i}. {name}({pos['code']}) "
            f"{pos['shares']}股\n"
            f"   买{pos['buy_price']:.2f} → 现{pos['current_price']:.2f} "
            f"{pnl_emoji}{pos['pnl_pct']*100:.2f}% "
            f"市值{pos['market_value']:,.0f}"
        )

    return "\n".join(lines)


def format_score_top20(scores_df: pd.DataFrame, stock_info: dict = None,
                       limit: int = 20) -> str:
    """格式化评分Top20

    Args:
        scores_df: 评分DataFrame（需含score_total, rank, delta_s列）
        stock_info: {code: name} 股票名称映射
        limit: 显示数量
    """
    if scores_df.empty:
        return "*评分数据为空*"

    lines = [f"*今日评分 Top {min(limit, len(scores_df))}*\n"]

    top = scores_df.head(limit)
    for _, row in top.iterrows():
        code = row.name if isinstance(row.name, str) else row.get("code", "?")
        name = (stock_info or {}).get(code, code)
        score = row.get("score_total", 0)
        rank = row.get("rank", 0)
        delta_s = row.get("delta_s", 0)

        # 动量标识
        if delta_s > 0.5:
            momentum = "↑"
        elif delta_s < -0.5:
            momentum = "↓"
        else:
            momentum = "→"

        delta_str = f"{delta_s:+.2f}" if pd.notna(delta_s) else "N/A"

        lines.append(
            f"#{rank:>2d} {name}({code}) "
            f"评分{score:.2f} {momentum} ΔS{delta_str}"
        )

    return "\n".join(lines)


def format_watchlist(watchlist_codes: list, scores_df: pd.DataFrame,
                     stock_info: dict = None) -> str:
    """格式化观察池信息"""
    if not watchlist_codes:
        return "*观察池为空*"

    lines = [f"*观察池 ({len(watchlist_codes)}只)*\n"]

    for code in watchlist_codes:
        if code in scores_df.index:
            row = scores_df.loc[code]
            name = (stock_info or {}).get(code, code)
            score = row.get("score_total", 0)
            rank = row.get("rank", 0)
            delta_s = row.get("delta_s", 0)

            lines.append(
                f"#{rank} {name}({code}) "
                f"评分{score:.2f} ΔS{delta_s:+.2f}"
            )

    return "\n".join(lines)


def format_delta_top10(scores_df: pd.DataFrame, stock_info: dict = None) -> str:
    """格式化评分变化最大的10只（上升+下降）

    Args:
        scores_df: 需含 delta_s 列
        stock_info: {code: name} 映射
    """
    if scores_df.empty or "delta_s" not in scores_df.columns:
        return "*评分变化数据为空*"

    valid = scores_df[scores_df["delta_s"].notna()].copy()
    if valid.empty:
        return "*无评分变化数据*"

    lines = ["*评分变化 Top 10*\n"]

    # 上升最多
    rising = valid.nlargest(5, "delta_s")
    lines.append("*上升最多:*")
    for _, row in rising.iterrows():
        code = row.name if isinstance(row.name, str) else row.get("code", "?")
        name = (stock_info or {}).get(code, code)
        delta = row["delta_s"]
        score = row.get("score_total", 0)
        lines.append(f"  {name}({code}) ΔS{delta:+.2f} 评分{score:.2f}")

    # 下降最多
    falling = valid.nsmallest(5, "delta_s")
    lines.append("\n*下降最多:*")
    for _, row in falling.iterrows():
        code = row.name if isinstance(row.name, str) else row.get("code", "?")
        name = (stock_info or {}).get(code, code)
        delta = row["delta_s"]
        score = row.get("score_total", 0)
        lines.append(f"  {name}({code}) ΔS{delta:+.2f} 评分{score:.2f}")

    return "\n".join(lines)


def format_trades(trades_df: pd.DataFrame, stock_info: dict = None) -> str:
    """格式化交易记录"""
    if trades_df.empty:
        return "*今日无交易*"

    lines = [f"*交易记录 ({len(trades_df)}笔)*\n"]

    for _, row in trades_df.iterrows():
        code = row.get("code", "?")
        name = (stock_info or {}).get(code, code)
        action = row.get("action", "?")
        price = row.get("price", 0)
        shares = row.get("shares", 0)
        reason = row.get("reason", "")

        action_emoji = "买入" if action == "buy" else "卖出"

        lines.append(
            f"{action_emoji} {name}({code}) "
            f"{shares}股@{price:.2f}\n"
            f"  原因: {reason}"
        )

    return "\n".join(lines)


def format_daily_report(summary: dict, trades_df: pd.DataFrame,
                        scores_df: pd.DataFrame, nav_info: dict,
                        performance: dict,
                        market_regime: str = None,
                        stock_info: dict = None,
                        benchmark_return: float = None) -> str:
    """格式化每日报告

    Args:
        summary: 持仓汇总
        trades_df: 今日交易
        scores_df: 今日评分
        nav_info: 净值信息
        performance: 绩效统计
        market_regime: 市场状态
        stock_info: 股票名称映射
        benchmark_return: 基准收益率
    """
    today = date.today()
    lines = [f"*{today} 盯盘日报*\n"]

    # 市场状态
    if market_regime:
        regime_desc = {
            "trend": "趋势市",
            "range": "震荡市",
            "volatile": "高波动",
            "crisis": "危机模式",
        }.get(market_regime, market_regime)
        lines.append(f"市场状态: {regime_desc}")

    # 持仓收益
    pnl_pct = summary["total_pnl_pct"]
    pnl_emoji = "+" if pnl_pct >= 0 else ""
    lines.append(
        f"\n*持仓({summary['position_count']}只):* "
        f"{pnl_emoji}{pnl_pct*100:.2f}%"
    )

    if benchmark_return is not None:
        bm_emoji = "+" if benchmark_return >= 0 else ""
        lines.append(f"基准: {bm_emoji}{benchmark_return*100:.2f}%")

    # 净值信息
    if nav_info:
        cum_ret = nav_info.get("cumulative_return", 0)
        cum_emoji = "+" if cum_ret >= 0 else ""
        lines.append(f"\nNAV: {nav_info.get('nav', 1.0):.4f} "
                      f"累计{cum_emoji}{cum_ret*100:.2f}%")

    # 今日操作
    if not trades_df.empty:
        lines.append("\n*今日操作:*")
        for _, row in trades_df.iterrows():
            code = row.get("code", "?")
            name = (stock_info or {}).get(code, code)
            action = row.get("action", "?")
            reason = row.get("reason", "")
            action_text = "买入" if action == "buy" else "卖出"
            lines.append(f"  {action_text} {name}({code}) - {reason}")
    else:
        lines.append("\n今日无操作")

    # 绩效统计
    if performance and performance.get("trading_days", 0) > 0:
        lines.append(
            f"\n*近{performance['trading_days']}日绩效:*\n"
            f"  年化收益: {performance['annualized_return']*100:+.2f}%\n"
            f"  最大回撤: {performance['max_drawdown']*100:.2f}%\n"
            f"  夏普比率: {performance['sharpe_ratio']:.2f}\n"
            f"  胜率: {performance['win_rate']*100:.1f}%"
        )

    return "\n".join(lines)


def format_performance(performance: dict) -> str:
    """格式化绩效统计"""
    if not performance or performance.get("trading_days", 0) == 0:
        return "*暂无绩效数据*"

    lines = [
        f"*绩效统计 ({performance['trading_days']}日)*\n",
        f"累计收益: {performance['total_return']*100:+.2f}%",
        f"年化收益: {performance['annualized_return']*100:+.2f}%",
        f"最大回撤: {performance['max_drawdown']*100:.2f}%",
        f"夏普比率: {performance['sharpe_ratio']:.2f}",
        f"年化波动率: {performance['volatility']*100:.2f}%",
        f"胜率: {performance['win_rate']*100:.1f}%",
    ]

    return "\n".join(lines)


def format_help() -> str:
    """格式化帮助信息"""
    return (
        "*A股智能盯盘Agent*\n\n"
        "指令列表:\n"
        "/portfolio - 当前模拟持仓\n"
        "/score - 今日评分Top20\n"
        "/watchlist - 观察池(排名11-20)\n"
        "/delta - 评分变化Top10\n"
        "/report - 今日日报\n"
        "/trades - 今日交易记录\n"
        "/perf - 绩效统计\n"
        "/alert on - 开启实时预警\n"
        "/alert off - 关闭实时预警\n"
        "/analyze <code> - 分析某只股票\n"
        "/help - 帮助\n\n"
        "数据每日15:30自动更新，16:40推送日报。"
    )
