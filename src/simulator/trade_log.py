"""轻量交易记录 — JSON文件存储

记录每笔交易: code/action/price/shares/pnl/reason/date
统计: 胜率/盈亏比/总交易数
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def log_trade(code: str, action: str, price: float, shares: int,
              reason: str = "", pnl: float = 0.0):
    """记录一笔交易"""
    log_file = DATA_DIR / "trade_log.json"
    trades = []
    if log_file.exists():
        try:
            trades = json.loads(log_file.read_text())
        except Exception:
            trades = []
    
    trades.append({
        "code": code,
        "action": action,  # buy/sell
        "price": round(price, 2),
        "shares": shares,
        "amount": round(price * shares, 2),
        "pnl": round(pnl, 2),
        "reason": reason,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    
    log_file.write_text(json.dumps(trades, ensure_ascii=False, indent=2))
    logger.info(f"交易记录: {action} {code} {shares}@{price:.2f} PnL={pnl:+.2f}")


def get_trade_stats() -> dict:
    """交易统计"""
    log_file = DATA_DIR / "trade_log.json"
    if not log_file.exists():
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "pnl_total": 0}
    
    try:
        trades = json.loads(log_file.read_text())
    except Exception:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "pnl_total": 0}
    
    sells = [t for t in trades if t["action"] == "sell" and t.get("pnl", 0) != 0]
    wins = [t for t in sells if t["pnl"] > 0]
    losses = [t for t in sells if t["pnl"] < 0]
    pnl_total = sum(t["pnl"] for t in sells)
    
    return {
        "total": len(trades),
        "buys": len([t for t in trades if t["action"] == "buy"]),
        "sells": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(sells) * 100 if sells else 0,
        "avg_win": sum(t["pnl"] for t in wins) / len(wins) if wins else 0,
        "avg_loss": sum(t["pnl"] for t in losses) / len(losses) if losses else 0,
        "pnl_total": round(pnl_total, 2),
        "profit_factor": abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else 0,
    }


def get_recent_trades(limit: int = 10) -> list:
    """最近N笔交易"""
    log_file = DATA_DIR / "trade_log.json"
    if not log_file.exists():
        return []
    try:
        trades = json.loads(log_file.read_text())
        return trades[-limit:]
    except Exception:
        return []
