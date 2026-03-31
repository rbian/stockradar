"""Telegram Bot — StockRadar多Agent系统"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from src.infra.logger import setup_logger
from scripts.e2e_test import create_system

orch = None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户消息"""
    global orch
    text = update.message.text
    user_id = str(update.effective_user.id)

    logger.info(f"[{user_id}] {text}")

    # 仅允许主人
    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if allowed and allowed[0] and user_id not in allowed:
        await update.message.reply_text("⛔ 未授权")
        return

    try:
        result = await asyncio.wait_for(
            orch.process_user_message(text, user_id=user_id),
            timeout=60,
        )
        if len(result) > 4000:
            result = result[:4000] + "\n..."
        await update.message.reply_text(result)
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ 超时，请稍后再试")
    except Exception as e:
        logger.error(f"处理失败: {e}")
        await update.message.reply_text(f"❌ {e}")


def main():
    global orch
    setup_logger()

    # 加载.env
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set")
        return

    logger.info("Starting StockRadar Bot...")

    # 创建Agent系统
    orch = create_system()
    logger.info(f"System ready: {len(orch.agents)} agents")

    # 启动Bot
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
