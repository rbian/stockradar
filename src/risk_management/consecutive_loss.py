"""Consecutive Loss Protection — 连续亏损仓位保护

当近期连续亏损达到阈值时，自动缩减新交易的仓位规模，防止情绪化交易和连续亏损放大。

规则:
- 统计最近N笔已平仓交易
- 如果连续亏损>=3笔，新买入仓位缩减为正常的50%
- 如果连续亏损>=5笔，暂停新买入
- 一笔盈利交易后恢复正常仓位
"""

import json
from pathlib import Path
from loguru import logger


class ConsecutiveLossProtection:
    """连续亏损保护器"""

    def __init__(self, config=None):
        cfg = config or {}
        self.lookback = cfg.get("lookback", 10)  # 检查最近N笔交易
        self.reduce_threshold = cfg.get("reduce_threshold", 3)  # 连续亏损>=3笔开始缩减
        self.halt_threshold = cfg.get("halt_threshold", 5)  # 连续亏损>=5笔暂停买入
        self.reduce_factor = cfg.get("reduce_factor", 0.5)  # 缩减到50%

    def check(self, tracker) -> dict:
        """检查是否需要缩减仓位

        Args:
            tracker: NAVTracker instance (needs .trade_log)

        Returns:
            {"allowed": bool, "position_scale": float, "consecutive_losses": int, "reason": str}
        """
        trade_log = getattr(tracker, 'trade_log', [])
        if not trade_log:
            return {"allowed": True, "position_scale": 1.0, "consecutive_losses": 0, "reason": "无交易历史"}

        # 找出已平仓的sell交易（按时间倒序）
        sell_trades = [t for t in trade_log if t.get('action') == 'sell']
        sell_trades.reverse()  # 最新的在前
        recent_sells = sell_trades[:self.lookback]

        if not recent_sells:
            return {"allowed": True, "position_scale": 1.0, "consecutive_losses": 0, "reason": "无卖出记录"}

        # 计算连续亏损（从最近一笔开始往前数）
        consecutive_losses = 0
        for t in recent_sells:
            pnl = t.get('pnl', 0)
            if isinstance(pnl, (int, float)) and pnl < 0:
                consecutive_losses += 1
            else:
                break  # 遇到盈利就中断

        if consecutive_losses >= self.halt_threshold:
            return {
                "allowed": False,
                "position_scale": 0.0,
                "consecutive_losses": consecutive_losses,
                "reason": f"连续亏损{consecutive_losses}笔>=阈值{self.halt_threshold}，暂停买入"
            }
        elif consecutive_losses >= self.reduce_threshold:
            return {
                "allowed": True,
                "position_scale": self.reduce_factor,
                "consecutive_losses": consecutive_losses,
                "reason": f"连续亏损{consecutive_losses}笔>=阈值{self.reduce_threshold}，仓位缩减至{self.reduce_factor*100:.0f}%"
            }
        else:
            return {
                "allowed": True,
                "position_scale": 1.0,
                "consecutive_losses": consecutive_losses,
                "reason": "正常"
            }
