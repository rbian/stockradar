"""日志模块 - 基于loguru"""

import sys
from loguru import logger

from src.infra.config import get_settings


def setup_logger():
    """初始化日志配置"""
    settings = get_settings()
    log_config = settings.get("logging", {})

    level = log_config.get("level", "INFO")
    rotation = log_config.get("rotation", "100 MB")
    retention = log_config.get("retention", "30 days")
    log_dir = log_config.get("log_dir", "logs")

    logger.remove()

    # 控制台输出
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )

    # 文件输出
    logger.add(
        f"{log_dir}/stockradar.log",
        level=level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    return logger


# 模块级函数，方便其他模块调用
def get_logger(name: str = "stockradar"):
    """获取logger（兼容性别名）"""
    setup_logger()
    return logger.bind(name=name)
