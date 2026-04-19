"""Kelly Criterion 仓位管理

根据历史胜率和盈亏比动态计算最优仓位比例。
核心公式: f* = (p * b - q) / b
其中 p=胜率, q=败率, b=平均盈利/平均亏损

Reference:
- Kelly, J. L. (1956). "A New Interpretation of Information Rate"
- Thorp, E. O. (1969). "Optimal Gambling Systems for Favorable Games"
- 实践中通常使用 fractional Kelly (1/4 ~ 1/2) 降低波动
"""

import json
from pathlib import Path
from loguru import logger
import numpy as np


class KellyPositionManager:
    """基于Kelly Criterion的动态仓位管理"""

    def __init__(self, config=None):
        config = config or {}
        self.fractional_kelly = config.get("fractional_kelly", 0.25)  # 使用1/4 Kelly
        self.max_position_pct = config.get("max_position_pct", 0.15)  # 单只最大15%
        self.min_position_pct = config.get("min_position_pct", 0.03)  # 单只最小3%
        self.min_trades = config.get("min_trades", 10)  # 最少需要10笔交易才启用
        self.default_position_pct = config.get("default_position_pct", 0.08)  # 默认8%

        # 状态持久化
        self.data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self.state_file = self.data_dir / "kelly_state.json"

        # 从历史加载
        self._load_state()

    def _load_state(self):
        """加载持久化状态"""
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.win_rate = d.get("win_rate", 0.0)
                self.avg_win = d.get("avg_win", 0.0)
                self.avg_loss = d.get("avg_loss", 0.0)
                self.total_trades = d.get("total_trades", 0)
                self.kelly_fraction = d.get("kelly_fraction", 0.0)
                return
            except Exception:
                pass

        self.win_rate = 0.0
        self.avg_win = 0.0
        self.avg_loss = 0.0
        self.total_trades = 0
        self.kelly_fraction = 0.0

    def _save_state(self):
        """持久化状态"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "total_trades": self.total_trades,
            "kelly_fraction": self.kelly_fraction,
        }, ensure_ascii=False))

    def update_from_trades(self, sells: list):
        """从交易记录更新Kelly参数

        Args:
            sells: 卖出交易列表, 每笔含 pnl 字段
        """
        if not sells:
            return

        pnl_list = [t.get("pnl", 0) for t in sells if "pnl" in t]
        if len(pnl_list) < self.min_trades:
            logger.info(f"Kelly: 交易不足{self.min_trades}笔({len(pnl_list)}笔), 使用默认仓位")
            self.total_trades = len(pnl_list)
            return

        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p < 0]

        self.win_rate = len(wins) / len(pnl_list)
        self.avg_win = np.mean(wins) if wins else 0
        self.avg_loss = abs(np.mean(losses)) if losses else 1  # 防除零
        self.total_trades = len(pnl_list)

        # Kelly formula: f* = (p*b - q) / b
        # b = avg_win / avg_loss (盈亏比)
        p = self.win_rate
        q = 1 - p
        b = self.avg_win / self.avg_loss if self.avg_loss > 0 else 1

        # 标准Kelly
        full_kelly = (p * b - q) / b if b > 0 else 0

        # Fractional Kelly (更保守)
        self.kelly_fraction = max(0, full_kelly * self.fractional_kelly)

        self._save_state()

        logger.info(
            f"Kelly更新: 胜率={self.win_rate:.1%}, 盈亏比={b:.2f}, "
            f"Full Kelly={full_kelly:.3f}, "
            f"Fractional({self.fractional_kelly})={self.kelly_fraction:.3f}"
        )

    def get_position_pct(self, signal_confidence: float = 1.0) -> float:
        """计算建议仓位百分比

        Args:
            signal_confidence: 信号置信度 0.0-1.0, 用于进一步调整

        Returns:
            建议仓位占总资金百分比
        """
        if self.total_trades < self.min_trades or self.kelly_fraction <= 0:
            # 数据不足或Kelly为负(说明策略亏钱)，使用保守默认值
            return self.default_position_pct * 0.5  # 更保守

        # Kelly仓位 × 信号置信度
        position = self.kelly_fraction * signal_confidence

        # 限制在合理范围
        position = max(self.min_position_pct, min(self.max_position_pct, position))

        return position

    def get_status(self) -> str:
        """返回Kelly状态摘要"""
        if self.total_trades < self.min_trades:
            return (
                f"📊 Kelly仓位管理\n"
                f"  交易笔数: {self.total_trades}/{self.min_trades} (数据不足)\n"
                f"  当前使用: 默认仓位 {self.default_position_pct:.1%}"
            )

        b = self.avg_win / self.avg_loss if self.avg_loss > 0 else 0
        return (
            f"📊 Kelly仓位管理\n"
            f"  胜率: {self.win_rate:.1%} | 盈亏比: {b:.2f}\n"
            f"  平均盈利: ¥{self.avg_win:+,.0f} | 平均亏损: ¥{self.avg_loss:,.0f}\n"
            f"  Kelly系数: {self.kelly_fraction:.3f} (fractional={self.fractional_kelly})\n"
            f"  建议单只仓位: {self.get_position_pct():.1%}"
        )
