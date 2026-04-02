"""Bot指令处理模块

处理所有 Telegram Bot 指令的回调逻辑。
"""

from datetime import date

import pandas as pd
from loguru import logger
from telegram import Update
from telegram.ext import CallbackContext

from src.bot.formatters import (
    format_portfolio,
    format_score_top20,
    format_watchlist,
    format_delta_top10,
    format_trades,
    format_daily_report,
    format_performance,
    format_help,
)
from src.data.store import DataStore
from src.simulator.portfolio import PortfolioManager
from src.simulator.trade_log import TradeLogger
from src.simulator.nav_tracker import NAVTracker


class CommandHandler:
    """Bot指令处理器

    持有对 store/portfolio/trade_logger/nav_tracker 的引用，
    每个指令对应一个方法，返回格式化的消息文本。
    """

    def __init__(self, store: DataStore = None):
        self.store = store or DataStore()
        self.portfolio_mgr = PortfolioManager(store=self.store)
        self.trade_logger = TradeLogger(store=self.store)
        self.nav_tracker = NAVTracker(store=self.store)
        self._stock_info_cache = None

    def _get_stock_info_map(self) -> dict:
        """获取 code → name 映射（缓存）"""
        if self._stock_info_cache is None:
            df = self.store.get_table("stock_info", columns="code, name")
            if not df.empty:
                self._stock_info_cache = dict(zip(df["code"], df["name"]))
            else:
                self._stock_info_cache = {}
        return self._stock_info_cache

    # ============ 指令实现 ============

    def cmd_portfolio(self) -> str:
        """持仓查询"""
        self.portfolio_mgr.load_portfolio()
        summary = self.portfolio_mgr.get_portfolio_summary()
        return format_portfolio(summary, self._get_stock_info_map())

    def cmd_score(self, limit: int = 20) -> str:
        """评分排名"""
        today = date.today()
        scores = self.store.get_table(
            "daily_score",
            where=f"date = '{today}'"
        )
        if scores.empty:
            # 尝试取最新一天
            latest = self.store.get_latest_date("daily_score")
            if latest:
                scores = self.store.get_table(
                    "daily_score",
                    where=f"date = '{latest.strftime('%Y-%m-%d')}'"
                )

        if scores.empty:
            return "*暂无评分数据，请等待数据更新后重试*"

        scores = scores.set_index("code")
        scores = scores.sort_values("score_total", ascending=False)
        return format_score_top20(scores, self._get_stock_info_map(), limit)

    def cmd_watchlist(self) -> str:
        """观察池"""
        today = date.today()
        scores = self.store.get_table(
            "daily_score",
            where=f"date = '{today}'"
        )
        if scores.empty:
            latest = self.store.get_latest_date("daily_score")
            if latest:
                scores = self.store.get_table(
                    "daily_score",
                    where=f"date = '{latest.strftime('%Y-%m-%d')}'"
                )

        if scores.empty:
            return "*暂无评分数据*"

        scores = scores.set_index("code")
        scores = scores.sort_values("score_total", ascending=False)
        # 排名11-20为观察池
        watchlist_codes = scores.iloc[10:20].index.tolist()
        return format_watchlist(watchlist_codes, scores, self._get_stock_info_map())

    def cmd_delta(self) -> str:
        """评分变化"""
        today = date.today()
        scores = self.store.get_table(
            "daily_score",
            where=f"date = '{today}'"
        )
        if scores.empty:
            latest = self.store.get_latest_date("daily_score")
            if latest:
                scores = self.store.get_table(
                    "daily_score",
                    where=f"date = '{latest.strftime('%Y-%m-%d')}'"
                )

        if scores.empty:
            return "*暂无评分变化数据*"

        scores = scores.set_index("code")
        return format_delta_top10(scores, self._get_stock_info_map())

    def cmd_trades(self) -> str:
        """今日交易记录"""
        trades = self.trade_logger.get_today_trades()
        return format_trades(trades, self._get_stock_info_map())

    def cmd_report(self) -> str:
        """每日报告"""
        self.portfolio_mgr.load_portfolio()
        summary = self.portfolio_mgr.get_portfolio_summary()
        trades = self.trade_logger.get_today_trades()

        # 评分
        today = date.today()
        scores = self.store.get_table(
            "daily_score",
            where=f"date = '{today}'"
        )
        scores_df = scores.set_index("code") if not scores.empty else pd.DataFrame()

        # 净值
        nav_info = self.nav_tracker.get_latest_nav()

        # 绩效
        performance = self.nav_tracker.get_performance_stats(days=30)

        return format_daily_report(
            summary=summary,
            trades_df=trades,
            scores_df=scores_df,
            nav_info=nav_info or {},
            performance=performance,
            stock_info=self._get_stock_info_map(),
        )

    def cmd_perf(self) -> str:
        """绩效统计"""
        performance = self.nav_tracker.get_performance_stats(days=30)
        return format_performance(performance)

    def cmd_alert_on(self) -> str:
        """开启预警"""
        return "实时预警已开启"

    def cmd_alert_off(self) -> str:
        """关闭预警"""
        return "实时预警已关闭"

    def cmd_analyze(self, code: str) -> str:
        """分析单只股票"""
        stock_info = self._get_stock_info_map()
        name = stock_info.get(code, code)

        # 获取最新评分
        scores = self.store.get_table(
            "daily_score",
            where=f"code = '{code}'"
        )

        if scores.empty:
            return f"*{name}({code})* 暂无评分数据"

        latest = scores.sort_values("date").iloc[-1]

        lines = [f"*{name}({code}) 分析*\n"]
        lines.append(f"日期: {latest['date']}")
        lines.append(f"总分: {latest['score_total']:.2f}")
        lines.append(f"排名: #{int(latest.get('rank', 0))}")

        if pd.notna(latest.get("score_fundamental")):
            lines.append(f"\n*分项评分:*")
            lines.append(f"  基本面: {latest['score_fundamental']:.2f}")
            lines.append(f"  技术面: {latest['score_technical']:.2f}")
            lines.append(f"  资金面: {latest['score_capital']:.2f}")
            if "score_llm" in latest.index and pd.notna(latest.get("score_llm")):
                lines.append(f"  LLM: {latest['score_llm']:.2f}")

        if pd.notna(latest.get("delta_s")):
            lines.append(f"\nΔS(动量): {latest['delta_s']:+.2f}")
        if pd.notna(latest.get("delta_s_accel")):
            lines.append(f"Δ²S(加速度): {latest['delta_s_accel']:+.2f}")

        return "\n".join(lines)

    def cmd_help(self) -> str:
        """帮助"""
        return format_help()

    def invalidate_cache(self):
        """清除缓存（数据更新后调用）"""
        self._stock_info_cache = None


# ============ Telegram 回调适配器 ============

def _make_callback(handler_method):
    """将 CommandHandler 方法包装为 telegram-bot 回调函数"""
    def callback(update: Update, context: CallbackContext):
        result = handler_method()
        update.message.reply_text(result, parse_mode="Markdown")
    return callback


def _make_analyze_callback(cmd_handler: CommandHandler):
    """处理 /analyze <code> 的回调"""
    def callback(update: Update, context: CallbackContext):
        if not context.args:
            update.message.reply_text("用法: /analyze <股票代码>\n例: /analyze 600519")
            return
        code = context.args[0]
        result = cmd_handler.cmd_analyze(code)
        update.message.reply_text(result, parse_mode="Markdown")
    return callback


def _make_alert_callback(cmd_handler: CommandHandler):
    """处理 /alert on/off 的回调"""
    def callback(update: Update, context: CallbackContext):
        if not context.args:
            update.message.reply_text("用法: /alert on|off")
            return
        arg = context.args[0].lower()
        if arg == "on":
            result = cmd_handler.cmd_alert_on()
        elif arg == "off":
            result = cmd_handler.cmd_alert_off()
        else:
            result = "用法: /alert on|off"
        update.message.reply_text(result, parse_mode="Markdown")
    return callback


def register_command_handlers(application, cmd_handler: CommandHandler):
    """将所有指令注册到 telegram Application

    Args:
        application: telegram.ext.Application
        cmd_handler: CommandHandler 实例
    """
    from telegram.ext import CommandHandler as TgCommandHandler

    application.add_handler(TgCommandHandler("start", _make_callback(cmd_handler.cmd_help)))
    application.add_handler(TgCommandHandler("help", _make_callback(cmd_handler.cmd_help)))
    application.add_handler(TgCommandHandler("portfolio", _make_callback(cmd_handler.cmd_portfolio)))
    application.add_handler(TgCommandHandler("score", _make_callback(cmd_handler.cmd_score)))
    application.add_handler(TgCommandHandler("watchlist", _make_callback(cmd_handler.cmd_watchlist)))
    application.add_handler(TgCommandHandler("delta", _make_callback(cmd_handler.cmd_delta)))
    application.add_handler(TgCommandHandler("trades", _make_callback(cmd_handler.cmd_trades)))
    application.add_handler(TgCommandHandler("report", _make_callback(cmd_handler.cmd_report)))
    application.add_handler(TgCommandHandler("perf", _make_callback(cmd_handler.cmd_perf)))
    application.add_handler(TgCommandHandler("analyze", _make_analyze_callback(cmd_handler)))
    application.add_handler(TgCommandHandler("alert", _make_alert_callback(cmd_handler)))

    logger.info("已注册 {} 个Bot指令", 11)
