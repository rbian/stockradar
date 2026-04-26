"""Stock Blacklist Manager (股票黑名单管理)

从交易复盘中自动识别"毒股"——反复亏损的股票，自动加入黑名单。
灵感来源: Qlib中因子无效自动淘汰的思路，延伸到个股级别。

规则:
- 近30天内对同一股票亏损N次 → 加入黑名单
- 黑名单中的股票降低买入信号权重（不直接禁止，而是需要更高的信号强度）
- 黑名单有效期30天，到期自动解除
"""

import json
import time
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta


class StockBlacklist:
    """股票黑名单管理器"""

    def __init__(self, config=None):
        config = config or {}
        self.loss_threshold = config.get("loss_threshold", 2)  # N次亏损后拉黑
        self.lookback_days = config.get("lookback_days", 30)  # 统计窗口
        self.ban_days = config.get("ban_days", 30)  # 黑名单有效期
        self.penalty_weight = config.get("penalty_weight", 0.5)  # 信号惩罚（乘以此值）
        self._path = Path("data/cache/stock_blacklist.json")
        self._loss_history = []  # [{code, date, loss_pct}]
        self._blacklist = {}  # {code: expiry_date_str}
        self._load()

    def _load(self):
        """加载持久化数据"""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._loss_history = data.get("loss_history", [])
                self._blacklist = data.get("blacklist", {})
                # 清理过期的黑名单
                today = datetime.now().strftime("%Y-%m-%d")
                expired = [k for k, v in self._blacklist.items() if v < today]
                for k in expired:
                    del self._blacklist[k]
                    logger.info(f"[Blacklist] {k} 黑名单过期，已解除")
            except Exception as e:
                logger.warning(f"[Blacklist] 加载失败: {e}")

    def _save(self):
        """持久化"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "loss_history": self._loss_history[-200:],  # 保留最近200条
            "blacklist": self._blacklist,
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def record_loss(self, code: str, date: str, loss_pct: float):
        """记录一次亏损交易"""
        self._loss_history.append({"code": code, "date": date, "loss_pct": loss_pct})
        
        # 检查是否达到黑名单阈值
        cutoff = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        recent_losses = [
            h for h in self._loss_history
            if h["code"] == code and h["date"] >= cutoff
        ]
        
        if len(recent_losses) >= self.loss_threshold:
            expiry = (datetime.now() + timedelta(days=self.ban_days)).strftime("%Y-%m-%d")
            self._blacklist[code] = expiry
            logger.warning(
                f"[Blacklist] {code} 近{self.lookback_days}天{len(recent_losses)}次亏损，"
                f"加入黑名单至{expiry}"
            )
        
        self._save()

    def record_win(self, code: str, date: str, win_pct: float):
        """记录盈利交易（可用于早期解除黑名单）"""
        # 连续2次盈利可提前解除
        cutoff = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        recent = [
            h for h in self._loss_history
            if h["code"] == code and h["date"] >= cutoff
        ]
        # 如果最近只有1次亏损且有盈利，解除
        if code in self._blacklist and len(recent) <= 1:
            del self._blacklist[code]
            logger.info(f"[Blacklist] {code} 交易改善，提前解除黑名单")
            self._save()

    def get_signal_modifier(self, code: str) -> float:
        """获取信号修正系数

        Returns:
            1.0 = 正常, <1.0 = 在黑名单中（降低信号强度）
        """
        if code in self._blacklist:
            return self.penalty_weight
        return 1.0

    def is_blacklisted(self, code: str) -> bool:
        """是否在黑名单中"""
        return code in self._blacklist

    def get_status(self) -> dict:
        """获取状态"""
        return {
            "blacklist": dict(self._blacklist),
            "total_tracked": len(self._loss_history),
        }
