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
from scripts.system_init import create_system

orch = None
ALLOWED_USERS = set()

# 按钮文字 → Agent消息映射
BUTTON_MAP = {
    "📊 市场概况": "市场怎么样",
    "🏆 评分排名": "评分排名",
    "📈 持仓建议": "当前持仓建议",
    "📰 日报": "日报",
    "📉 回测结果": "回测",
    "❓ 帮助": "帮助",
}


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
        "功能:\n"
        "• 实时沪深300行情\n"
        "• 36因子智能评分\n"
        "• 个股分析（输入代码或名称）\n"
        "• 持仓建议和回测\n\n"
        "点击按钮或直接输入 👇",
        reply_markup=get_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 **StockRadar**\n\n"
        "📊 市场 — 实时沪深300\n"
        "🏆 评分 — 36因子排名\n"
        "📈 持仓 — Top10建议\n"
        "📰 日报 — 每日总结\n"
        "📉 回测 — 历史表现\n"
        "🔍 个股 — 600519 或 茅台\n\n"
        "数据: QVeris(实时) + BaoStock(历史)",
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

    # 按钮映射
    text = BUTTON_MAP.get(text, text)

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

    # 定时日报
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import asyncio

    async def daily_push():
        for uid in ALLOWED_USERS:
            try:
                result = await asyncio.wait_for(
                    orch.process_user_message("日报", user_id=uid), timeout=60
                )
                await app.bot.send_message(chat_id=uid, text=result, reply_markup=get_keyboard())
                logger.info(f"日报推送: {uid}")
            except Exception as e:
                logger.error(f"日报推送失败 {uid}: {e}")

    async def post_init(app):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(daily_push, "cron", hour=15, minute=30,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        scheduler.start()
        logger.info("Scheduler: 日报 15:30 CST Mon-Fri")

    app.post_init = post_init

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
