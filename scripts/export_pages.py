#!/usr/bin/env python3
"""导出持仓数据供GitHub Pages使用

生成 docs/data.json: { nav_history, holdings, trades, stats }
"""
import sys, json
sys.path.insert(0, '/home/node/.openclaw/workspace/research/stockradar')
sys.path.insert(0, '/home/node/.openclaw/workspace/research/stockradar/src')

import pandas as pd
from pathlib import Path
from src.data.stock_names import stock_name

PROJECT = Path('/home/node/.openclaw/workspace/research/stockradar')

def export():
    nav_data = json.load(open(PROJECT / 'data/nav_state_balanced.json'))
    dq = pd.read_parquet(PROJECT / 'data/parquet/hs300_daily.parquet')

    # 最新价格
    latest = dq[dq['date'] == dq['date'].max()]
    prices = dict(zip(latest['code'].astype(str), latest['close']))
    latest_date = str(dq['date'].max())[:10]

    # 净值曲线
    nav_history = []
    for h in nav_data['nav_history']:
        nav_history.append({
            "date": str(h["date"])[:10],
            "nav": round(h["nav"], 4),
            "market_value": round(h["market_value"], 0),
            "holdings_count": h.get("holdings_count", 0),
        })

    # 当前持仓
    holdings = []
    total_cost = sum(h["shares"] * h["cost_price"] for h in nav_data["holdings"].values())
    for code, h in nav_data["holdings"].items():
        name = stock_name(code)
        current_price = prices.get(code, h["cost_price"])
        cost = h["shares"] * h["cost_price"]
        market_val = h["shares"] * current_price
        pnl = (current_price - h["cost_price"]) / h["cost_price"] * 100
        weight = cost / total_cost * 100 if total_cost > 0 else 0
        holdings.append({
            "code": code,
            "name": name,
            "shares": h["shares"],
            "cost_price": round(h["cost_price"], 2),
            "current_price": round(current_price, 2),
            "market_value": round(market_val, 0),
            "pnl_pct": round(pnl, 2),
            "weight": round(weight, 1),
        })

    # 交易记录（最近30笔）
    trades = []
    for t in nav_data.get("trade_log", [])[-30:]:
        trades.append({
            "date": str(t["date"])[:10],
            "code": t["code"],
            "name": stock_name(t["code"]),
            "action": t["action"],
            "shares": t["shares"],
            "price": round(t["price"], 2),
            "reason": t.get("reason", ""),
        })

    # 统计
    latest_nav = nav_history[-1]["nav"] if nav_history else 1.0
    peak = max(h["nav"] for h in nav_history) if nav_history else 1.0
    stats = {
        "latest_date": latest_date,
        "nav": round(latest_nav, 4),
        "total_return": round((latest_nav - 1) * 100, 2),
        "max_drawdown": round((latest_nav - peak) / peak * 100, 2) if peak > 0 else 0,
        "holdings_count": len(holdings),
        "total_trades": len(nav_data.get("trade_log", [])),
        "initial_capital": 1000000,
        "current_value": round(sum(h["market_value"] for h in holdings) + nav_data.get("cash", 0), 0),
        "cash": round(nav_data.get("cash", 0), 0),
    }

    output = {
        "updated": latest_date,
        "stats": stats,
        "nav_history": nav_history,
        "holdings": holdings,
        "trades": list(reversed(trades)),  # 最新在前
    }

    # 写入 docs/
    docs_dir = PROJECT / 'docs'
    docs_dir.mkdir(exist_ok=True)
    with open(docs_dir / 'data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"导出完成: {len(nav_history)}条净值, {len(holdings)}只持仓, {len(trades)}笔交易")
    print(f"最新: NAV={stats['nav']}, 收益={stats['total_return']}%, 日期={stats['latest_date']}")
    return output

if __name__ == '__main__':
    export()
