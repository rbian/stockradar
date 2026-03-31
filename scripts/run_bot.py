"""Telegram Bot — StockRadar多Agent系统"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from src.infra.logger import setup_logger
from scripts.e2e_test import create_system

orch = None
ALLOWED_USERS = set()


def load_env():
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📊 市场概况", "🏆 评分排名"],
            ["📈 持仓建议", "📰 日报"],
            ["📉 回测结果", "❓ 帮助"],
        ],
        resize_keyboard=True,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ 未授权")
        return

    await update.message.reply_text(
        "📡 **StockRadar 已上线！**\n\n"
        "我可以帮你:\n"
        "• 查看市场行情（实时数据）\n"
        "• A股智能评分排名\n"
        "• 持仓建议和回测\n"
        "• 个股分析（输入6位代码）\n\n"
        "点击下方按钮或直接输入问题 👇",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 **StockRadar 使用指南**\n\n"
        "📊 **市场** — 实时沪深300 + 涨跌\n"
        "🏆 **评分** — 36因子智能排名\n"
        "📈 **持仓** — Top10建议\n"
        "📰 **日报** — 每日市场总结\n"
        "📉 **回测** — 历史回测结果\n"
        "🔍 **个股** — 输入代码如 600519\n\n"
        "数据源: QVeris(实时) + BaoStock(历史)",
        parse_mode="Markdown",
        reply_markup=get_keyboard(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global orch
    user_id = str(update.effective_user.id)

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        return

    text = update.message.text.strip()
    if not text:
        return

    logger.info(f"[{user_id}] {text}")

    try:
        result = await asyncio.wait_for(
            orch.process_user_message(text, user_id=user_id),
            timeout=60,
        )
        if len(result) > 4000:
            result = result[:4000] + "\n..."
        await update.message.reply_text(result, reply_markup=get_keyboard())
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ 超时，请稍后再试")
    except Exception as e:
        logger.error(f"处理失败: {e}")
        await update.message.reply_text(f"❌ {e}")


def main():
    global orch, ALLOWED_USERS
    setup_logger()
    load_env()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set")
        return

    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    if allowed:
        ALLOWED_USERS = set(allowed.split(","))

    logger.info("Starting StockRadar Bot...")

    orch = create_system()
    logger.info(f"System ready: {len(orch.agents)} agents")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
