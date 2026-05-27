"""止损确认机制 — 防止过早止损

复盘发现: 立讯精密两次过早止损，每次损失¥920
问题: 单日急跌触发止损后反弹，属于噪音而非趋势

方案: 
- 止损信号需要连续2天确认才执行
- 第1天触发: 记录到确认队列
- 第2天仍触发: 执行止损
- 中间回升: 取消确认

极端保护: 亏损超过-20%时立即执行，不需要确认
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class StopLossConfirmation:
    """止损确认管理器"""

    def __init__(self):
        self.state_file = DATA_DIR / "stop_loss_confirm.json"
        self.confirmations = {}  # {code: {"date": str, "pnl_pct": float}}
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                self.confirmations = json.loads(self.state_file.read_text())
            except Exception:
                self.confirmations = {}

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.confirmations, ensure_ascii=False))

    def check(self, code: str, pnl_pct: float, today: str = None) -> dict:
        """检查止损是否应该执行

        Args:
            code: 股票代码
            pnl_pct: 当前盈亏比例 (e.g. -0.15 for -15%)
            today: 当前日期 YYYY-MM-DD

        Returns:
            {"execute": bool, "reason": str, "status": str}
        """
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")

        # 极端保护: 亏损超过-18%立即执行（从-20%收紧，防止长春高新式持续亏损）
        if pnl_pct <= -0.18:
            self.confirmations.pop(code, None)
            self._save()
            return {"execute": True, "reason": f"极端止损({pnl_pct*100:.1f}%)", "status": "extreme"}

        # 止损线-15%: 需要确认
        if pnl_pct <= -0.15:
            existing = self.confirmations.get(code)
            if existing and existing["date"] == today:
                # 今天已经记录过了，不重复
                return {"execute": False, "reason": "等待确认(已记录今日)", "status": "waiting"}

            if existing and existing["date"] != today:
                # 之前记录过且不是今天 → 检查是否连续
                prev_date = existing["date"]
                # 简单检查: 只要之前有记录就确认（跨交易日）
                self.confirmations.pop(code, None)
                self._save()
                return {"execute": True, "reason": f"确认止损({pnl_pct*100:.1f}%,首次{prev_date})", "status": "confirmed"}

            # 首次触发，记录
            self.confirmations[code] = {"date": today, "pnl_pct": pnl_pct}
            self._save()
            return {"execute": False, "reason": f"止损待确认({pnl_pct*100:.1f}%)", "status": "pending"}

        # 回升到-15%以上，取消确认
        if code in self.confirmations:
            self.confirmations.pop(code, None)
            self._save()
            return {"execute": False, "reason": "止损取消(价格回升)", "status": "cancelled"}

        return {"execute": False, "reason": "", "status": "normal"}

    def get_status(self) -> dict:
        return {"pending": len(self.confirmations), "codes": list(self.confirmations.keys())}
