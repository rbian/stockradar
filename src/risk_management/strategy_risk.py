"""策略级风控 - 净值回撤监控

职责：
1. 监控净值回撤，超过阈值停止买入
2. 监控本金回撤，超过阈值停止买入
3. 提供恢复评估逻辑
"""

from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, Tuple


class StrategyRiskControl:
    """策略级风控控制器"""

    def __init__(self, max_nav_drawdown: float = -0.10, min_capital_ratio: float = 0.85):
        self.max_nav_drawdown = max_nav_drawdown  # 净值最大回撤
        self.min_capital_ratio = min_capital_ratio  # 本金最低比例
        self.state_file = Path(__file__).resolve().parent.parent.parent / "data" / "strategy_risk_state.json"
        self._load_state()

    def _load_state(self):
        """加载风控状态"""
        if self.state_file.exists():
            try:
                import json
                self.state = json.loads(self.state_file.read_text())
            except:
                self.state = {"buy_disabled": False, "trigger_reason": None, "trigger_date": None, "last_check": None}
        else:
            self.state = {"buy_disabled": False, "trigger_reason": None, "trigger_date": None, "last_check": None}

    def _save_state(self):
        """保存风控状态"""
        import json
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state["last_check"] = datetime.now().isoformat()
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    def check(self, nav: float, initial_nav: float = 1.0) -> Tuple[bool, str]:
        """
        检查是否允许买入

        Args:
            nav: 当前净值
            initial_nav: 初始净值

        Returns:
            (allowed, reason): True允许买入, False禁止买入
        """
        # 1. 检查净值回撤
        nav_drawdown = (nav - initial_nav) / initial_nav
        if nav_drawdown < self.max_nav_drawdown:
            self._trigger_buy_disabled(f"净值回撤{nav_drawdown*100:.1f}%超过阈值{self.max_nav_drawdown*100:.0f}%")
            return False, f"⚠️ 净值回撤{nav_drawdown*100:.1f}%，已停止买入"

        # 2. 检查本金回撤
        capital_ratio = nav / initial_nav
        if capital_ratio < self.min_capital_ratio:
            self._trigger_buy_disabled(f"本金比例{capital_ratio*100:.1f}%低于阈值{self.min_capital_ratio*100:.0f}%")
            return False, f"⚠️ 本金比例{capital_ratio*100:.1f}%，已停止买入"

        # 3. 检查是否在冷却期
        if self.state["buy_disabled"]:
            trigger_date = datetime.fromisoformat(self.state["trigger_date"])
            cooldown_days = 7  # 默认冷却7天
            days_since = (datetime.now() - trigger_date).days

            if days_since < cooldown_days:
                logger.info(f"策略风控冷却中: {days_since}/{cooldown_days}天")
                return False, f"⚠️ 风控冷却中 ({days_since}/{cooldown_days}天)"

            # 冷却期结束，尝试恢复
            if self._can_recover(nav, initial_nav):
                self.state["buy_disabled"] = False
                self.state["trigger_reason"] = None
                self._save_state()
                logger.info("策略风控已恢复")
                return True, "✅ 风控已恢复，允许买入"
            else:
                return False, f"⚠️ 未达到恢复条件，继续停止买入"

        # 正常情况，允许买入
        return True, ""

    def _trigger_buy_disabled(self, reason: str):
        """触发买入禁用"""
        if not self.state["buy_disabled"]:
            logger.warning(f"🛡️ 策略风控触发: {reason}")
            self.state["buy_disabled"] = True
            self.state["trigger_reason"] = reason
            self.state["trigger_date"] = datetime.now().isoformat()
            self._save_state()

    def _can_recover(self, nav: float, initial_nav: float = 1.0) -> bool:
        """检查是否可以恢复"""
        # 净值回撤小于5%
        nav_drawdown = (nav - initial_nav) / initial_nav
        if nav_drawdown < -0.05:
            return False

        # 本金比例大于90%
        capital_ratio = nav / initial_nav
        if capital_ratio < 0.90:
            return False

        return True

    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            "buy_disabled": self.state["buy_disabled"],
            "trigger_reason": self.state["trigger_reason"],
            "trigger_date": self.state["trigger_date"],
            "last_check": self.state["last_check"]
        }