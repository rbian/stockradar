"""共享上下文 — 黑板模式

所有Agent共享的运行时状态，类似"黑板"。
Agent可以读取和写入自己负责的区域。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from loguru import logger

from src.infra.config import PROJECT_ROOT


class SharedContext:
    """共享上下文（黑板模式）

    用法:
        ctx = SharedContext()
        ctx.write("market.regime", "bullish", writer="analyst")
        regime = ctx.read("market.regime")
    """

    def __init__(self, store=None):
        self.store = store  # DuckDB DataStore
        self._blackboard: dict[str, Any] = {}
        self._writers: dict[str, str] = {}  # key → 上一次写入的Agent
        self._timestamps: dict[str, str] = {}
        self._knowledge = None  # KnowledgeStore引用

    # ──── 读写操作 ────

    def write(self, key: str, value: Any, writer: str = ""):
        """写入黑板"""
        self._blackboard[key] = value
        self._writers[key] = writer
        self._timestamps[key] = datetime.now().isoformat()

    def read(self, key: str, default: Any = None) -> Any:
        """读取黑板"""
        return self._blackboard.get(key, default)

    def delete(self, key: str):
        """删除黑板条目"""
        self._blackboard.pop(key, None)
        self._writers.pop(key, None)
        self._timestamps.pop(key, None)

    # ──── 批量操作 ────

    def write_batch(self, items: dict[str, Any], writer: str = ""):
        """批量写入"""
        for key, value in items.items():
            self.write(key, value, writer)

    def read_batch(self, keys: list[str]) -> dict[str, Any]:
        """批量读取"""
        return {k: self.read(k) for k in keys}

    # ──── 按命名空间读取 ────

    def read_namespace(self, prefix: str) -> dict[str, Any]:
        """读取一个命名空间下的所有数据

        例: read_namespace("market.") → {"market.regime": ..., "market.sentiment": ...}
        """
        return {
            k: v for k, v in self._blackboard.items()
            if k.startswith(prefix)
        }

    # ──── 标准化的数据接口 ────

    def set_daily_data(self, daily_quote: pd.DataFrame, date: str):
        """设置当日行情数据"""
        self.write("data.daily_quote", daily_quote, writer="data_fetcher")
        self.write("data.date", date, writer="data_fetcher")

    def get_daily_data(self) -> tuple[Optional[pd.DataFrame], str]:
        """获取当日行情数据"""
        return self.read("data.daily_quote"), self.read("data.date", "")

    def set_scores(self, scores: pd.DataFrame):
        """设置评分结果"""
        self.write("scores", scores, writer="factor_engine")

    def get_scores(self) -> Optional[pd.DataFrame]:
        """获取评分结果"""
        return self.read("scores")

    def set_portfolio(self, portfolio: dict):
        """设置持仓信息"""
        self.write("portfolio", portfolio, writer="trader")

    def get_portfolio(self) -> dict:
        """获取持仓信息"""
        return self.read("portfolio", {"holdings": [], "cash": 0})

    def set_market_regime(self, regime: str, confidence: float):
        """设置市场状态"""
        self.write("market.regime", regime, writer="analyst")
        self.write("market.regime_confidence", confidence, writer="analyst")

    def get_market_regime(self) -> tuple[str, float]:
        """获取市场状态"""
        return self.read("market.regime", "unknown"), self.read("market.regime_confidence", 0.0)

    # ──── 状态快照 ────

    def snapshot(self) -> dict:
        """获取完整黑板快照（用于调试）"""
        return {
            "data": {k: (f"DataFrame({len(v)} rows)" if isinstance(v, pd.DataFrame) else str(v)[:100])
                     for k, v in self._blackboard.items()},
            "writers": dict(self._writers),
            "timestamps": dict(self._timestamps),
        }

    def clear(self):
        """清空黑板"""
        self._blackboard.clear()
        self._writers.clear()
        self._timestamps.clear()

    # ──── knowledge代理 ────

    @property
    def knowledge(self):
        """延迟加载KnowledgeStore"""
        if self._knowledge is None:
            from src.evolution.knowledge import KnowledgeStore
            self._knowledge = KnowledgeStore()
        return self._knowledge
