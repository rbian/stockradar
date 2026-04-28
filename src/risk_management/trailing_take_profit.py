"""移动止盈 (Trailing Take-Profit)

GitHub学习: 经典趋势跟踪策略中，移动止盈是锁定利润的核心机制
- 参考: 海龟交易法则 (Richard Dennis) + O'Neil CANSLIM策略
- 灵感: 赣锋锂业卖飞+11.8% — 固定止盈太早，需要随利润增长动态调整

规则:
- 盈利 0~10%: 允许回撤到成本-2%
- 盈利曾达10~20%后回落: 锁定+5% (从峰值回撤触发)
- 盈利曾达20~30%后回落: 峰值回撤8%止盈
- 盈利>30%后回落: 峰值回撤8%止盈
- 快速拉升保护: 5日涨幅>15%时，回撤5%即止盈

状态持久化: JSON文件记录每只股的最高价
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class TrailingTakeProfit:
    """移动止盈管理器 — 基于峰值追踪的阶梯止盈"""

    def __init__(self, config=None):
        config = config or {}
        self.state_file = DATA_DIR / "cache" / "trailing_tp_state.json"
        
        # 峰值盈利阶梯: (峰值盈利达到过, 触发条件: 从峰值回撤超过X)
        self.peak_tiers = [
            (0.30, 0.08),   # 曾达30%+: 峰值回撤8%清仓
            (0.20, 0.08),   # 曾达20%+: 峰值回撤8%清仓
            (0.10, 0.06),   # 曾达10%+: 峰值回撤6%清仓
        ]
        
        # 基础保护: 当前盈利低于此线触发
        self.base_lock = -0.02  # 亏损2%止损
        
        # 快速拉升保护
        self.rapid_gain_days = config.get("rapid_gain_days", 5)
        self.rapid_gain_threshold = config.get("rapid_gain_threshold", 0.15)
        self.rapid_pullback = config.get("rapid_pullback", 0.05)
        
        self.state = {}
        self._load_state()

    def _load_state(self):
        try:
            if self.state_file.exists():
                with open(self.state_file) as f:
                    self.state = json.load(f)
        except Exception:
            self.state = {}

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def update_peak(self, code: str, current_price: float, entry_price: float):
        if code not in self.state:
            self.state[code] = {"peak_price": current_price, "entry_price": entry_price, "updated": datetime.now().isoformat()}
        else:
            if current_price > self.state[code]["peak_price"]:
                self.state[code]["peak_price"] = current_price
            self.state[code]["entry_price"] = entry_price
            self.state[code]["updated"] = datetime.now().isoformat()
        self._save_state()

    def check(self, code: str, current_price: float, entry_price: float,
              recent_returns: list = None) -> dict:
        self.update_peak(code, current_price, entry_price)
        peak = self.state[code]["peak_price"]
        
        pnl_pct = (current_price / entry_price - 1)
        peak_pnl = (peak / entry_price - 1)
        drawdown_from_peak = (peak / current_price - 1) if current_price > 0 else 0
        
        # 快速拉升保护
        if recent_returns and len(recent_returns) >= self.rapid_gain_days:
            recent_gain = sum(recent_returns[-self.rapid_gain_days:])
            if recent_gain >= self.rapid_gain_threshold and drawdown_from_peak >= self.rapid_pullback:
                return {
                    "triggered": True,
                    "reason": f"快速拉升保护 (近{self.rapid_gain_days}日涨{recent_gain*100:.1f}%，回撤{drawdown_from_peak*100:.1f}%)",
                    "action": "sell", "sell_ratio": 0.5,
                }
        
        # 峰值阶梯止盈: 根据历史最高盈利水平决定保护力度
        for peak_threshold, max_drawdown in self.peak_tiers:
            if peak_pnl >= peak_threshold and drawdown_from_peak >= max_drawdown:
                return {
                    "triggered": True,
                    "reason": f"峰值回撤止盈 (峰值盈利{peak_pnl*100:.1f}%，当前{pnl_pct*100:.1f}%，回撤{drawdown_from_peak*100:.1f}%)",
                    "action": "sell", "sell_ratio": 1.0,
                }
        
        # 基础保护: 跌破成本-2%
        if pnl_pct <= self.base_lock:
            return {
                "triggered": True,
                "reason": f"跌破基础保护线 (盈利{pnl_pct*100:.1f}%)",
                "action": "reduce", "sell_ratio": 0.5,
            }
        
        return {"triggered": False, "reason": "", "action": "", "sell_ratio": 0}

    def batch_check(self, holdings: dict, prices: dict) -> list:
        alerts = []
        for code, pos in holdings.items():
            entry = pos.get("cost_price", 0)
            price = prices.get(code, 0)
            if entry <= 0 or price <= 0:
                continue
            result = self.check(code, price, entry)
            if result["triggered"]:
                alerts.append({
                    "code": code, "action": result["action"],
                    "ratio": result["sell_ratio"],
                    "reason": f"📈 {result['reason']}", "urgency": "medium",
                })
        return alerts

    def remove(self, code: str):
        self.state.pop(code, None)
        self._save_state()
