"""Consecutive Loss Protection — 连续亏损仓位保护

当近期连续亏损达到阈值时，自动缩减新交易的仓位规模，防止情绪化交易和连续亏损放大。

规则:
- 统计最近N笔已平仓交易
- 如果连续亏损>=3笔，新买入仓位缩减为正常的50%
- 如果连续亏损>=5笔，暂停新买入
- 一笔盈利交易后恢复正常仓位
- 冷却恢复: 连续亏损达到halt阈值后，经过N个交易日无新亏损交易，自动降级到缩减模式
  （防止"0持仓+0交易=永久lockout"的死锁）
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


class ConsecutiveLossProtection:
    """连续亏损保护器"""

    def __init__(self, config=None):
        cfg = config or {}
        self.lookback = cfg.get("lookback", 10)  # 检查最近N笔交易
        self.reduce_threshold = cfg.get("reduce_threshold", 3)  # 连续亏损>=3笔开始缩减
        self.halt_threshold = cfg.get("halt_threshold", 5)  # 连续亏损>=5笔暂停买入
        self.reduce_factor = cfg.get("reduce_factor", 0.5)  # 缩减到50%
        self.cooldown_days = cfg.get("cooldown_days", 5)  # 冷却期: N个交易日后降级

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
            # 冷却恢复检查: 距离最近一笔亏损卖出已过N个交易日，降级到缩减模式
            # 这解决"0持仓+halt锁死=永不恢复"的死锁
            latest_sell_date = self._parse_date(recent_sells[0].get('date', ''))
            if latest_sell_date:
                today = datetime.now().date()
                calendar_days = (today - latest_sell_date).days
                # 估算交易日: calendar_days * 5/7
                trading_days = int(calendar_days * 5 / 7)
                if trading_days >= self.cooldown_days:
                    logger.info(
                        f"连续亏损冷却恢复: {consecutive_losses}笔亏损，已过{trading_days}个交易日"
                        f"(≥{self.cooldown_days})，降级到缩减模式({self.reduce_factor*100:.0f}%)"
                    )
                    return {
                        "allowed": True,
                        "position_scale": self.reduce_factor,
                        "consecutive_losses": consecutive_losses,
                        "reason": f"连续亏损{consecutive_losses}笔已冷却{trading_days}天，降级到缩减模式"
                    }
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

    @staticmethod
    def _parse_date(date_str: str):
        """Parse date string, return date object or None"""
        if not date_str:
            return None
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(date_str[:19], fmt).date()
            except ValueError:
                continue
        return None
