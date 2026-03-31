"""配置加载模块 - YAML + 环境变量"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _resolve_env_vars(value):
    """递归解析 ${VAR} 格式的环境变量引用"""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            env_key = value[2:-1]
            return os.environ.get(env_key, "")
        return value
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_config(filename: str = "settings.yaml") -> dict:
    """加载并解析YAML配置文件"""
    config_path = CONFIG_DIR / filename
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return _resolve_env_vars(config)


def load_factors_config() -> dict:
    """加载因子配置"""
    return load_config("factors.yaml")


# 全局单例
_settings = None
_factors = None


def get_settings() -> dict:
    global _settings
    if _settings is None:
        _settings = load_config("settings.yaml")
    return _settings


def get_factors_config() -> dict:
    global _factors
    if _factors is None:
        _factors = load_config("factors.yaml")
    return _factors
