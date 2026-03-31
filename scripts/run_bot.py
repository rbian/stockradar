"""启动 Telegram Bot 入口脚本

用法:
    python scripts/run_bot.py
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infra.logger import setup_logger
from src.infra.config import get_settings
from src.bot.telegram_bot import TelegramBot


def main():
    logger = setup_logger()

    settings = get_settings()
    tg_cfg = settings.get("telegram", {})

    if not tg_cfg.get("bot_token"):
        logger.error("TELEGRAM_BOT_TOKEN 未配置，请在 .env 中设置")
        sys.exit(1)

    logger.info("启动 A股智能盯盘 Telegram Bot...")

    bot = TelegramBot()
    bot.build()
    bot.run()


if __name__ == "__main__":
    main()
