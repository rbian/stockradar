"""Recovery-Aware Stop Loss (恢复感知止损)

GitHub学习来源: Qlib (microsoft/qlib) 的 CAT (Cluster-Aware Trading) 和
增量信息概念 — 在止损触发前，检查是否有恢复信号，避免在短期恐慌低点止损。

核心思路：
- 传统ATR止损只看当前价 vs 止损价，容易在短期恐慌低点触发
- Recovery-aware增加了3层检查：
  1. 价格恢复检查：近3天是否已从最低点回升
  2. 缩量下跌检查：下跌时成交量萎缩 = 恐慌释放
  3. RSI超卖检查：RSI<30时暂缓止损，给反弹机会

解决痛点：立讯精密两次过早止损后反弹+22.2%的问题
"""

import numpy as np
from loguru import logger


class RecoveryStop:
    """恢复感知止损管理器"""

    def __init__(self, config=None):
        config = config or {}
        # 恢复容忍度：价格从低点回升比例超过此值则暂缓止损
        self.recovery_threshold = config.get("recovery_threshold", 0.02)  # 2%
        # 缩量阈值：当前量 < 5日均量的此比例视为缩量
        self.volume_shrink_ratio = config.get("volume_shrink_ratio", 0.7)
        # RSI超卖阈值
        self.rsi_oversold = config.get("rsi_oversold", 30)
        # 最大宽限天数（不能无限等待恢复）
        self.max_grace_days = config.get("max_grace_days", 3)
        # 恢复检查回看天数
        self.lookback = config.get("lookback", 5)

        # 跟踪每只股票的宽限天数
        self.grace_days = {}  # {code: remaining_grace_days}

    def check_recovery(self, code: str, price_history: np.ndarray,
                       volume_history: np.ndarray = None) -> dict:
        """检查是否有恢复信号

        Args:
            code: 股票代码
            price_history: 近期收盘价序列 (最新在末尾)
            volume_history: 近期成交量序列 (最新在末尾)

        Returns:
            {
                "should_delay": bool,  # 是否暂缓止损
                "reasons": list,       # 暂缓原因
                "grace_remaining": int # 剩余宽限天数
            }
        """
        if len(price_history) < self.lookback + 1:
            return {"should_delay": False, "reasons": [], "grace_remaining": 0}

        reasons = []
        recent_prices = price_history[-(self.lookback + 1):]

        # 1. 价格恢复检查：最近3天是否从低点回升
        low_idx = np.argmin(recent_prices)
        if low_idx < len(recent_prices) - 1:  # 最低点不在最后一天
            recovery_pct = (recent_prices[-1] - recent_prices[low_idx]) / recent_prices[low_idx]
            if recovery_pct > self.recovery_threshold:
                reasons.append(f"价格从低点回升{recovery_pct:.1%}")

        # 2. 缩量下跌检查
        if volume_history is not None and len(volume_history) >= 5:
            recent_vol = volume_history[-5:]
            avg_vol = np.mean(recent_vol)
            current_vol = recent_vol[-1]
            if avg_vol > 0 and current_vol < avg_vol * self.volume_shrink_ratio:
                reasons.append(f"缩量下跌(量比{current_vol/avg_vol:.2f})")

        # 3. RSI超卖检查
        if len(price_history) >= 14:
            rsi = self._calc_rsi(price_history[-15:])
            if rsi < self.rsi_oversold:
                reasons.append(f"RSI超卖({rsi:.1f})")

        # 决定是否暂缓
        should_delay = len(reasons) >= 1  # 至少1个恢复信号

        if should_delay:
            # 更新宽限天数
            if code not in self.grace_days:
                self.grace_days[code] = self.max_grace_days

            if self.grace_days[code] > 0:
                self.grace_days[code] -= 1
                if self.grace_days[code] == 0:
                    # 宽限用尽，不再暂缓
                    should_delay = False
                    logger.info(f"[RecoveryStop] {code} 宽限天数用尽，执行止损")
            else:
                should_delay = False
        else:
            # 没有恢复信号，不宽限
            self.grace_days.pop(code, None)

        return {
            "should_delay": should_delay,
            "reasons": reasons,
            "grace_remaining": self.grace_days.get(code, 0),
        }

    def _calc_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """计算RSI"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_position_closed(self, code: str):
        """持仓平仓时清理"""
        self.grace_days.pop(code, None)

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "active_grace": {k: v for k, v in self.grace_days.items()},
            "config": {
                "recovery_threshold": self.recovery_threshold,
                "volume_shrink_ratio": self.volume_shrink_ratio,
                "rsi_oversold": self.rsi_oversold,
                "max_grace_days": self.max_grace_days,
            }
        }
