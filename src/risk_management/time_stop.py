"""时间止损 (Time-based Stop Loss)

GitHub学习: 来自量化交易中经典的"时间止损"概念
- 参考: systematic-investing / portfolio-management 实践
- 核心思想: 持仓时间过长且收益未达预期 = 资金效率低 + 机会成本高
- 与价格止损互补: 价格止损管"亏多少"，时间止损管"等多久"

规则:
1. 持仓 > 20交易日 且 收益 < +2%  → 建议卖出 (资金效率低)
2. 持仓 > 10交易日 且 收益 < -3%  → 建议减仓 (趋势判断失误)
3. 持仓 > 30交易日 且 收益 < +5%  → 建议卖出 (错过主升浪)

A股特殊: 考虑到T+1和涨跌停，适当放宽时间窗口
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


class TimeStopManager:
    """时间止损管理器"""

    def __init__(self, config=None):
        config = config or {}
        # 持仓天数阈值
        self.long_hold_days = config.get("long_hold_days", 20)  # 长持未盈利
        self.medium_hold_days = config.get("medium_hold_days", 10)  # 中期亏损
        self.max_hold_days = config.get("max_hold_days", 30)  # 最大持仓期
        
        # 收益阈值
        self.long_hold_min_return = config.get("long_hold_min_return", 0.02)  # 2%
        self.medium_hold_max_loss = config.get("medium_hold_max_loss", -0.03)  # -3%
        self.max_hold_min_return = config.get("max_hold_min_return", 0.05)  # 5%
        
        # 持仓时间追踪文件
        self.data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self.state_file = self.data_dir / "time_stop_state.json"
        self._load_state()

    def _load_state(self):
        """加载持仓时间状态"""
        self.entry_dates = {}  # {code: "YYYY-MM-DD"}
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.entry_dates = d.get("entry_dates", {})
            except Exception:
                self.entry_dates = {}

    def _save_state(self):
        """持久化"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({
            "entry_dates": self.entry_dates,
        }, ensure_ascii=False, indent=2))

    def record_entry(self, code: str, date: str = None):
        """记录买入日期"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        self.entry_dates[code] = date
        self._save_state()
        logger.info(f"时间止损: 记录买入 {code} @ {date}")

    def remove_entry(self, code: str):
        """卖出后清除"""
        self.entry_dates.pop(code, None)
        self._save_state()

    def get_holding_days(self, code: str) -> int:
        """获取持仓天数"""
        entry = self.entry_dates.get(code)
        if not entry:
            return 0
        try:
            entry_date = datetime.strptime(entry, "%Y-%m-%d")
            # 只算交易日（粗略: 排除周末）
            days = (datetime.now() - entry_date).days
            # 粗略估算交易日: 5/7 * days
            trading_days = int(days * 5 / 7)
            return max(0, trading_days)
        except Exception:
            return 0

    def check_time_stop(self, code: str, current_return: float) -> dict:
        """检查是否触发时间止损
        
        Args:
            code: 股票代码
            current_return: 当前收益率 (如 0.05 = +5%)
        
        Returns:
            {"triggered": bool, "action": str, "ratio": float, "reason": str, "urgency": str}
        """
        days = self.get_holding_days(code)
        
        if days <= 0:
            return {"triggered": False, "action": "none", "ratio": 0, 
                    "reason": "", "urgency": "none"}
        
        # Rule 1: 长期持有未达预期
        if days >= self.max_hold_days and current_return < self.max_hold_min_return:
            return {
                "triggered": True,
                "action": "sell",
                "ratio": 1.0,
                "reason": f"持仓{days}天收益{current_return*100:+.1f}%未达{self.max_hold_min_return*100:.0f}%目标",
                "urgency": "high",
            }
        
        # Rule 2: 长持未盈利
        if days >= self.long_hold_days and current_return < self.long_hold_min_return:
            return {
                "triggered": True,
                "action": "sell",
                "ratio": 1.0,
                "reason": f"持仓{days}天收益仅{current_return*100:+.1f}%,资金效率低",
                "urgency": "medium",
            }
        
        # Rule 3: 中期仍在亏损
        if days >= self.medium_hold_days and current_return < self.medium_hold_max_loss:
            return {
                "triggered": True,
                "action": "reduce",
                "ratio": 0.5,
                "reason": f"持仓{days}天仍亏{current_return*100:+.1f}%,趋势判断失误",
                "urgency": "medium",
            }
        
        return {"triggered": False, "action": "none", "ratio": 0, 
                "reason": "", "urgency": "none"}

    def batch_check(self, holdings: dict, prices: dict) -> list:
        """批量检查时间止损
        
        Args:
            holdings: {code: {"shares": int, "cost_price": float}}
            prices: {code: current_price}
        
        Returns:
            list of alerts
        """
        alerts = []
        for code, pos in holdings.items():
            cost = pos.get("cost_price", 0)
            price = prices.get(code, 0)
            if cost <= 0 or price <= 0:
                continue
            
            current_return = (price / cost - 1)
            result = self.check_time_stop(code, current_return)
            
            if result["triggered"]:
                result["code"] = code
                result["holding_days"] = self.get_holding_days(code)
                result["current_return"] = current_return
                alerts.append(result)
        
        # 按紧急度排序
        urgency_order = {"high": 0, "medium": 1, "low": 2}
        alerts.sort(key=lambda x: urgency_order.get(x["urgency"], 3))
        
        return alerts


class ConsecutiveLossProtector:
    """连续亏损保护器
    
    GitHub学习: 来自赌注管理理论 ( Larry Hite / Ed Seykota )
    核心思想: 连续亏损时不是运气问题，而是市场环境或策略失效
    自动降低仓位/提高门槛，避免"追损"
    
    规则:
    - 连续3次亏损 → 进入防御模式: 仓位减半, 信号门槛+5
    - 连续5次亏损 → 进入保守模式: 仓位×0.3, 信号门槛+10, 只买大盘股
    - 连续盈利 → 逐步恢复正常
    """

    def __init__(self, config=None):
        config = config or {}
        self.defense_threshold = config.get("defense_threshold", 3)
        self.conservative_threshold = config.get("conservative_threshold", 5)
        self.lookback_trades = config.get("lookback_trades", 10)  # 看最近N笔
        
        self.data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self.state_file = self.data_dir / "loss_streak_state.json"
        self._load_state()

    def _load_state(self):
        self.loss_streak = 0
        self.mode = "normal"  # normal / defense / conservative
        if self.state_file.exists():
            try:
                d = json.loads(self.state_file.read_text())
                self.loss_streak = d.get("loss_streak", 0)
                self.mode = d.get("mode", "normal")
            except Exception:
                pass

    def _save_state(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({
            "loss_streak": self.loss_streak,
            "mode": self.mode,
        }, ensure_ascii=False, indent=2))

    def update_from_trades(self, recent_trades: list):
        """根据最近的卖出交易更新状态
        
        Args:
            recent_trades: 最近N笔卖出交易 [{action, pnl, ...}]
        """
        sells = [t for t in recent_trades if t.get("action") == "sell"]
        sells = sells[-self.lookback_trades:]  # 最近N笔
        
        streak = 0
        for t in reversed(sells):
            pnl = t.get("pnl", 0)
            if pnl < 0:
                streak += 1
            else:
                break
        
        self.loss_streak = streak
        
        # 更新模式
        if self.loss_streak >= self.conservative_threshold:
            self.mode = "conservative"
        elif self.loss_streak >= self.defense_threshold:
            self.mode = "defense"
        else:
            self.mode = "normal"
        
        self._save_state()
        logger.info(f"连续亏损保护: streak={self.loss_streak}, mode={self.mode}")

    def get_position_multiplier(self) -> float:
        """获取仓位调整系数"""
        if self.mode == "conservative":
            return 0.3
        elif self.mode == "defense":
            return 0.5
        return 1.0

    def get_signal_threshold_bonus(self) -> int:
        """获取信号门槛提升值"""
        if self.mode == "conservative":
            return 10
        elif self.mode == "defense":
            return 5
        return 0

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "mode": self.mode,
            "loss_streak": self.loss_streak,
            "position_multiplier": self.get_position_multiplier(),
            "signal_threshold_bonus": self.get_signal_threshold_bonus(),
        }
