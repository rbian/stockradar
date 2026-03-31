"""Telegram Bot 轻量版 — 直接连接多Agent系统

不需要DuckDB，直接用BaoStock缓存 + FactorEngine + MultiAgent
"""

import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from src.infra.logger import setup_logger
from scripts.e2e_test import create_system


# 全局Agent系统
orch = None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户消息"""
    global orch
    text = update.message.text
    user_id = str(update.effective_user.id)
    
    logger.info(f"📩 [{user_id}] {text}")
    
    try:
        result = await asyncio.wait_for(
            orch.process_user_message(text, user_id=user_id),
            timeout=60
        )
        # 截断
        if len(result) > 4000:
            result = result[:4000] + "\n...(截断)"
        await update.message.reply_text(result)
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ 处理超时，请稍后再试")
    except Exception as e:
        logger.error(f"处理失败: {e}")
        await update.message.reply_text(f"❌ {e}")


def main():
    global orch
    
    setup_logger()
    
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        # 尝试从.env加载
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'')
                    break
    
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN 未设置")
        print("用法: TELEGRAM_BOT_TOKEN=xxx python3 scripts/run_bot.py")
        return
    
    logger.info("🚀 启动 StockRadar Telegram Bot...")
    
    # 创建Agent系统
    orch = create_system()
    logger.info(f"✅ Agent系统就绪: {len(orch.agents)}个Agent")
    
    # 启动Bot
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("📡 Bot正在监听消息...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
