"""Telegram Bot 主程序

启动 Bot，注册指令，提供消息推送接口。
集成模拟交易执行流程。
"""

from datetime import date, datetime

import pandas as pd
from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.bot.commands import CommandHandler, register_command_handlers
from src.bot.formatters import format_daily_report, format_trades
from src.data.store import DataStore
from src.infra.config import get_settings
from src.simulator.portfolio import PortfolioManager
from src.simulator.trade_log import TradeLogger
from src.simulator.nav_tracker import NAVTracker
from src.strategy.regime import detect_regime


class TelegramBot:
    """Telegram Bot 主控

    职责：
    1. 启动/停止 Bot
    2. 注册指令处理
    3. 推送消息（日报、预警等）
    4. 执行模拟交易流程
    """

    def __init__(self, store: DataStore = None):
        settings = get_settings()
        tg_cfg = settings.get("telegram", {})
        sim_cfg = settings.get("simulator", {})

        self.bot_token = tg_cfg.get("bot_token", "")
        self.chat_id = tg_cfg.get("chat_id", "")
        self.alert_enabled = tg_cfg.get("alert_enabled", True)
        self.daily_report_enabled = tg_cfg.get("daily_report", True)

        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置")

        self.store = store or DataStore()
        self.portfolio_mgr = PortfolioManager(store=self.store)
        self.trade_logger = TradeLogger(store=self.store)
        self.nav_tracker = NAVTracker(store=self.store)
        self.initial_capital = sim_cfg.get("initial_capital", 1_000_000.0)

        self._application = None
        self._bot = None

    def build(self) -> "TelegramBot":
        """构建 Application（不启动）"""
        self._application = (
            Application.builder()
            .token(self.bot_token)
            .build()
        )

        # 注册指令
        cmd_handler = CommandHandler(store=self.store)
        register_command_handlers(self._application, cmd_handler)

        self._bot = self._application.bot
        logger.info("Telegram Bot 构建完成")
        return self

    def run(self):
        """启动 Bot（阻塞运行）"""
        if self._application is None:
            self.build()

        logger.info("Telegram Bot 启动中...")
        self._application.run_polling(allowed_updates=Update.ALL_TYPES)

    async def send_message(self, text: str, chat_id: str = None):
        """发送消息

        Args:
            text: 消息文本（Markdown格式）
            chat_id: 目标chat_id，默认使用配置中的chat_id
        """
        target = chat_id or self.chat_id
        if not target:
            logger.warning("chat_id 未配置，无法发送消息")
            return

        try:
            if self._bot is None:
                self._bot = self._application.bot

            # 截断过长消息（Telegram限制4096字符）
            if len(text) > 4000:
                # 分段发送
                chunks = self._split_message(text, 3800)
                for chunk in chunks:
                    await self._bot.send_message(
                        chat_id=target,
                        text=chunk,
                        parse_mode="Markdown",
                    )
            else:
                await self._bot.send_message(
                    chat_id=target,
                    text=text,
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    def send_message_sync(self, text: str, chat_id: str = None):
        """同步发送消息（用于非async环境）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在事件循环中，创建任务
                asyncio.ensure_future(self.send_message(text, chat_id))
            else:
                loop.run_until_complete(self.send_message(text, chat_id))
        except RuntimeError:
            asyncio.run(self.send_message(text, chat_id))

    async def push_daily_report(self):
        """推送每日报告"""
        if not self.daily_report_enabled:
            return

        cmd_handler = CommandHandler(store=self.store)
        report_text = cmd_handler.cmd_report()
        await self.send_message(report_text)
        logger.info("日报推送完成")

    async def push_alert(self, code: str, alert_type: str, message: str):
        """推送预警消息

        Args:
            code: 股票代码
            alert_type: 预警类型
            message: 预警消息
        """
        if not self.alert_enabled:
            return

        stock_info_map = self._get_stock_info_map()
        name = stock_info_map.get(code, code)

        alert_emoji = {
            "score_breakout": "⚡",
            "score_drop": "🔴",
            "risk_stop_loss": "🛑",
            "risk_reduce": "⚠️",
            "regime_crisis": "🚨",
        }.get(alert_type, "📢")

        text = f"{alert_emoji}【{alert_type}】{name}({code})\n{message}"
        await self.send_message(text)

    # ============ 模拟交易执行 ============

    def execute_daily_trades(self, actions: list, daily_quote_df: pd.DataFrame,
                             trade_date=None) -> list:
        """执行每日交易动作

        Args:
            actions: 策略产出的交易动作列表
            daily_quote_df: 当日行情数据
            trade_date: 交易日期

        Returns:
            交易记录列表
        """
        self.portfolio_mgr.load_portfolio()
        positions = self.portfolio_mgr.get_positions()
        trade_date = trade_date or date.today()

        # 计算可用资金
        market_value = self.portfolio_mgr.get_total_market_value()
        # 从净值获取总资产
        nav_info = self.nav_tracker.get_latest_nav()
        if nav_info:
            total_assets = nav_info.get("total_assets", self.initial_capital)
            cash = total_assets - market_value
        else:
            cash = self.initial_capital - market_value

        trade_records = []

        # 先执行卖出
        for action in actions:
            if action.get("action") not in ("sell", "reduce"):
                continue

            code = action["code"]
            price = self._get_price(code, daily_quote_df, trade_date)
            if price is None:
                logger.warning(f"无法获取 {code} 价格，跳过卖出")
                continue

            shares = None
            if action.get("action") == "reduce":
                # 部分减仓
                current_pos = positions.get(code, {})
                current_shares = current_pos.get("shares", 0)
                reduce_ratio = action.get("ratio", 0.5)
                shares = int(current_shares * reduce_ratio // 100 * 100)
                if shares <= 0:
                    continue

            record = self.portfolio_mgr.sell(
                code=code,
                price=price,
                shares=shares,
                trade_date=trade_date,
                reason=action.get("reason", ""),
                score_at_action=action.get("score", 0.0),
            )

            if record:
                trade_records.append(record)
                cash += record["amount"]

        # 再执行买入
        buy_actions = [a for a in actions if a.get("action") == "buy"]
        if buy_actions:
            capital_per_stock = self.portfolio_mgr.calc_buy_amount(
                cash, len(buy_actions) + self.portfolio_mgr.get_portfolio_summary()["position_count"]
            )

            for action in buy_actions:
                code = action["code"]
                price = self._get_price(code, daily_quote_df, trade_date)
                if price is None:
                    logger.warning(f"无法获取 {code} 价格，跳过买入")
                    continue

                record = self.portfolio_mgr.buy(
                    code=code,
                    price=price,
                    capital_per_stock=capital_per_stock,
                    trade_date=trade_date,
                    reason=action.get("reason", ""),
                    score_at_action=action.get("score", 0.0),
                )

                if record:
                    trade_records.append(record)

        # 记录交易
        self.trade_logger.log_trades(trade_records)

        # 更新持仓价格
        self.portfolio_mgr.update_prices(daily_quote_df, trade_date)

        # 更新净值
        new_market_value = self.portfolio_mgr.get_total_market_value()
        # 重新计算现金
        total_assets = (nav_info.get("total_assets", self.initial_capital)
                        if nav_info else self.initial_capital)
        # 调整现金：总资产 - 当前市值 - 交易费用
        total_trade_cost = sum(
            r["amount"] for r in trade_records if r["action"] == "buy"
        )
        total_trade_income = sum(
            r["amount"] for r in trade_records if r["action"] == "sell"
        )
        new_cash = cash - total_trade_cost + total_trade_income
        if new_cash < 0:
            new_cash = 0.0

        self.nav_tracker.record_nav(
            cash=new_cash,
            market_value=new_market_value,
            trade_date=trade_date,
        )

        logger.info(
            f"模拟交易执行完成: {len(trade_records)}笔, "
            f"市值{new_market_value:,.0f}, 现金{new_cash:,.0f}"
        )

        return trade_records

    # ============ 工具方法 ============

    def _get_price(self, code: str, daily_quote_df: pd.DataFrame,
                   trade_date) -> float | None:
        """获取股票当日价格"""
        if daily_quote_df is None or daily_quote_df.empty:
            return None

        date_ts = pd.Timestamp(trade_date)
        code_data = daily_quote_df[
            (daily_quote_df["code"] == code) &
            (daily_quote_df["date"] == date_ts)
        ]

        if code_data.empty:
            # 取最近一天
            code_data = daily_quote_df[
                daily_quote_df["code"] == code
            ].sort_values("date")

        if code_data.empty:
            return None

        # 用次日开盘价作为模拟成交价（T+1约束下更现实）
        row = code_data.iloc[-1]
        open_price = row.get("open")
        close_price = row.get("close")

        # 优先用开盘价（模拟次日开盘成交）
        if pd.notna(open_price) and open_price > 0:
            return float(open_price)
        if pd.notna(close_price) and close_price > 0:
            return float(close_price)
        return None

    def _get_stock_info_map(self) -> dict:
        """获取 code → name 映射"""
        df = self.store.get_table("stock_info", columns="code, name")
        if df.empty:
            return {}
        return dict(zip(df["code"], df["name"]))

    @staticmethod
    def _split_message(text: str, max_length: int) -> list:
        """将长消息拆分为多段"""
        lines = text.split("\n")
        chunks = []
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > max_length:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line

        if current:
            chunks.append(current)

        return chunks
