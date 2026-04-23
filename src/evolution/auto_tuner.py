"""自动调参闭环 - 从周度复盘建议自动调整交易参数

流程:
1. 读取 data/weekly_reviews/ 最新报告
2. 解析参数调整建议
3. 生成新的参数配置(不直接修改，先保存到pending)
4. 下次开盘前加载pending配置
"""

import json
import os
from datetime import datetime
from loguru import logger

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "weekly_reviews")
PENDING_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "pending_params.json")
PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "auto_params.json")


class AutoTuner:
    """自动调参器
    
    根据周度复盘建议自动调整:
    - 信号门槛 (signal_threshold)
    - 止损百分比 (stop_loss_pct)
    - 单只上限 (max_position_pct)
    - 防御模式 (defensive_mode)
    """

    # 参数安全边界
    BOUNDS = {
        "signal_threshold": (60, 95),
        "stop_loss_pct": (3, 20),
        "max_position_pct": (5, 25),
        "max_portfolio_usage": (50, 95),
    }

    def __init__(self):
        os.makedirs(os.path.dirname(PENDING_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(PARAMS_PATH), exist_ok=True)

    def load_latest_review(self) -> dict | None:
        """加载最新的周度复盘报告"""
        if not os.path.exists(DATA_DIR):
            return None
        
        files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".json")])
        if not files:
            return None

        latest = os.path.join(DATA_DIR, files[-1])
        with open(latest) as f:
            return json.load(f)

    def parse_suggestions(self, review: dict) -> list[dict]:
        """解析复盘建议为参数调整"""
        suggestions = review.get("suggestions", [])
        adjustments = []

        for sug in suggestions:
            text = sug.get("text", "").lower() if isinstance(sug, dict) else str(sug).lower()
            
            if "信号门槛" in text or "signal_threshold" in text:
                # "信号门槛 75→80"
                import re
                m = re.search(r'(\d+)', text.split("→")[-1] if "→" in text else text)
                if m:
                    val = int(m.group(1))
                    adjustments.append({
                        "param": "signal_threshold",
                        "value": val,
                        "reason": sug.get("text", str(sug)),
                    })

            elif "止损" in text or "stop_loss" in text:
                import re
                m = re.search(r'(\d+)', text.split("→")[-1] if "→" in text else text)
                if m:
                    val = int(m.group(1))
                    adjustments.append({
                        "param": "stop_loss_pct",
                        "value": val,
                        "reason": sug.get("text", str(sug)),
                    })

            elif "上限" in text or "position" in text:
                import re
                m = re.search(r'(\d+)', text.split("→")[-1] if "→" in text else text)
                if m:
                    val = int(m.group(1))
                    adjustments.append({
                        "param": "max_position_pct",
                        "value": val,
                        "reason": sug.get("text", str(sug)),
                    })

            elif "防御" in text or "defensive" in text:
                adjustments.append({
                    "param": "defensive_mode",
                    "value": True,
                    "reason": sug.get("text", str(sug)),
                })

        return adjustments

    def validate_and_apply(self, adjustments: list[dict]) -> dict:
        """验证参数边界并保存pending配置"""
        current = self._load_current_params()
        applied = []
        rejected = []

        for adj in adjustments:
            param = adj["param"]
            val = adj["value"]

            if param in self.BOUNDS:
                lo, hi = self.BOUNDS[param]
                if not (lo <= val <= hi):
                    rejected.append({
                        **adj,
                        "reason_rejected": f"值{val}超出安全范围[{lo},{hi}]",
                    })
                    continue

            applied.append(adj)
            current[param] = val
            logger.info(f"自动调参: {param} → {val} ({adj.get('reason', '')})")

        # 保存pending配置
        current["_updated_at"] = datetime.now().isoformat()
        current["_source"] = "auto_tuner"
        with open(PENDING_PATH, "w") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)

        return {"applied": applied, "rejected": rejected}

    def promote_pending(self) -> dict | None:
        """将pending配置提升为正式配置（开盘前调用）"""
        if not os.path.exists(PENDING_PATH):
            return None

        with open(PENDING_PATH) as f:
            pending = json.load(f)

        with open(PARAMS_PATH, "w") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)

        # 清除pending
        os.remove(PENDING_PATH)
        logger.info(f"自动调参已生效: {list(pending.keys())}")
        return pending

    def _load_current_params(self) -> dict:
        """加载当前正式参数"""
        if os.path.exists(PARAMS_PATH):
            with open(PARAMS_PATH) as f:
                return json.load(f)
        return {
            "signal_threshold": 75,
            "stop_loss_pct": 10,
            "max_position_pct": 15,
            "max_portfolio_usage": 80,
        }

    def run(self) -> dict:
        """执行完整的自动调参流程"""
        review = self.load_latest_review()
        if not review:
            logger.info("无周度复盘报告，跳过自动调参")
            return {"status": "no_review"}

        adjustments = self.parse_suggestions(review)
        if not adjustments:
            logger.info("复盘报告无参数调整建议")
            return {"status": "no_suggestions"}

        result = self.validate_and_apply(adjustments)
        result["status"] = "adjusted"
        result["review_date"] = review.get("date")
        return result
