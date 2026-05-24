"""回填已平仓交易的因子/信号数据

针对历史交易中factors/signals为空的记录，回填买入时的因子评分和信号评分。
这为后续因子分析提供数据基础。
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TRADE_LOG = PROJECT_ROOT / "data" / "tracking" / "closed_trades.json"


def enrich_trades():
    """为factors/signals为空的已平仓交易回填因子数据"""
    if not TRADE_LOG.exists():
        print("No closed_trades.json found")
        return 0

    log = json.loads(TRADE_LOG.read_text())
    trades = log.get("trades", [])
    if not trades:
        print("No trades to enrich")
        return 0

    # 尝试加载因子引擎和行情数据
    try:
        from src.factors.engine import FactorEngine
        # SinaAdapter not needed for backfill
    except Exception as e:
        print(f"Cannot import engine: {e}")
        return 0

    enriched = 0
    for trade in trades:
        if trade.get("factors") and any(v for v in trade["factors"].values()):
            continue  # 已有因子数据
        code = trade["code"]
        buy_date = trade["buy_date"]
        try:
            # 加载行情数据
            parquet = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
            if not parquet.exists():
                continue
            dq = pd.read_parquet(parquet)
            stock_data = dq[dq["code"] == code]

            # 只用买入日期之前的数据（避免前视偏差）
            buy_dt = pd.Timestamp(buy_date)
            stock_data = stock_data[stock_data["date"] < buy_dt].tail(60)

            if len(stock_data) < 30:
                continue

            # 计算技术信号
            from src.factors.technical_signals import score_stock
            tech = score_stock(stock_data)

            # 记录因子快照
            trade["factors"] = {
                "enriched": True,
                "enriched_from": "backfill",
            }
            trade["signals"] = {
                "signal_score": tech.get("signal_score", 0),
                "signal": tech.get("signal", ""),
                "rsi": tech.get("details", {}).get("rsi", {}).get("value", 0) if isinstance(tech.get("details", {}).get("rsi"), dict) else 0,
            }
            enriched += 1

        except Exception as e:
            print(f"  Failed to enrich {code}: {e}")
            continue

    if enriched > 0:
        _save(TRADE_LOG, log)
        print(f"Enriched {enriched}/{len(trades)} trades")

    return enriched


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    count = enrich_trades()
    print(f"Done: {count} trades enriched")
