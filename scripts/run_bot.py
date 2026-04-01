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
    "📉 回测": "回测",
    "📈 净值图": "净值图",
    "📝 周报": "周报",
    "📊 月报": "月报",
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
            ["🏆 评分排名", "📈 持仓建议"],
            ["📊 市场概况", "📰 日报"],
            ["📉 回测", "📈 净值图"],
            ["📝 周报", "📊 月报"],
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
        "命令: /top /nav /report\n\n"
        "数据: QVeris(实时) + BaoStock(历史)",
        reply_markup=get_keyboard(),
    )


async def _quick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, msg: str):
    """快捷命令"""
    update.message.text = msg
    await handle_message(update, context)


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
        # 净值图请求 → 发送图片
        if any(kw in text for kw in ["净值图", "曲线", "走势图"]):
            chart = PROJECT_ROOT / "output" / "nav_chart.png"
            if chart.exists():
                await update.message.reply_photo(photo=open(chart, "rb"),
                    caption="📊 StockRadar 300只净值曲线 (2024-2026)\n年化18.5% | 回撤-21.7%",
                    reply_markup=get_keyboard())
                return

        result = await asyncio.wait_for(
            orch.process_user_message(text, user_id=user_id),
            timeout=90,
        )
        if len(result) > 4000:
            result = result[:4000] + "\n..."
        await update.message.reply_text(result, reply_markup=get_keyboard())
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ 分析超时（90秒），LLM或数据源响应慢，请稍后重试", reply_markup=get_keyboard())
    except ConnectionError:
        await update.message.reply_text("📡 网络连接失败，请检查网络后重试", reply_markup=get_keyboard())
    except Exception as e:
        logger.error(f"处理失败: {e}")
        await update.message.reply_text(f"❌ 处理失败，请重试或输入'帮助'", reply_markup=get_keyboard())


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
    
    # 注册Telegram命令菜单
    async def set_commands(app):
        from telegram import BotCommand
        await app.bot.set_my_commands([
            BotCommand("top", "📊 评分Top10"),
            BotCommand("nav", "💰 净值+收益"),
            BotCommand("report", "📰 今日日报"),
            BotCommand("help", "❓ 功能列表"),
        ])
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("top", lambda u, c: _quick_cmd(u, c, "评分排名")))
    app.add_handler(CommandHandler("nav", lambda u, c: _quick_cmd(u, c, "净值")))
    app.add_handler(CommandHandler("report", lambda u, c: _quick_cmd(u, c, "日报")))

    # 定时任务
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import asyncio

    async def daily_rebalance():
        """15:25 自动调仓"""
        logger.info("定时调仓...")
        try:
            result = await asyncio.wait_for(
                orch.process_user_message("调仓", user_id=list(ALLOWED_USERS)[0] if ALLOWED_USERS else ""), 
                timeout=120
            )
            logger.info(f"调仓完成: {result[:100]}")
        except Exception as e:
            logger.error(f"调仓失败: {e}")

    async def daily_push():
        """15:30 日报推送"""
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
        await set_commands(app)
        scheduler = AsyncIOScheduler()
        # 数据更新: 15:10 BaoStock免费更新
        async def data_update():
            logger.info("定时数据更新(BaoStock)...")
            try:
                from scripts.daily_update_bs import daily_update_bs
                daily_update_bs()
            except Exception as e:
                logger.error(f"数据更新失败: {e}")
        scheduler.add_job(data_update, "cron", hour=15, minute=10,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # 调仓: 15:25
        scheduler.add_job(daily_rebalance, "cron", hour=15, minute=25,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # 日报: 15:30
        scheduler.add_job(daily_push, "cron", hour=15, minute=30,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        scheduler.start()
        logger.info("Scheduler: 数据更新15:10 + 调仓15:25 + 日报15:30 Mon-Fri")

    app.post_init = post_init

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
