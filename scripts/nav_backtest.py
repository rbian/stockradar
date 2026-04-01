"""历史净值回放 — 300只沪深300模拟交易

用现有历史数据回放每日评分→调仓→净值
验证策略在全量300只上的真实收益
"""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from src.infra.logger import setup_logger
from src.factors.engine import FactorEngine
from src.simulator.nav_tracker import NAVTracker
from src.data.cache import load_financial_cache


def run_backtest(start_date: str = "2024-01-01", end_date: str = "2026-03-31",
                 rebalance_days: int = 10, top_n: int = 10, initial_capital: float = 1_000_000):
    """运行历史回测"""
    setup_logger()
    
    # 加载数据
    logger.info("加载数据...")
    quote = pd.read_parquet(PROJECT_ROOT / "data/parquet/hs300_daily.parquet")
    quote = quote[(quote["date"] >= start_date) & (quote["date"] <= end_date)]
    codes = quote["code"].unique().tolist()
    
    fin_list = []
    for y in [2024, 2023, 2022]:
        for q in [4, 3, 2, 1]:
            f = load_financial_cache(y, q, max_age_days=9999)
            if not f.empty:
                fin_list.append(f)
    financial = pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()
    
    logger.info(f"行情: {len(quote)}条 | 财务: {len(financial)}条 | 股票: {len(codes)}只")
    
    # 初始化
    engine = FactorEngine()
    nav = NAVTracker(initial_capital)
    nav.rebalance_days = rebalance_days
    nav.top_n = top_n
    
    dates = sorted(quote["date"].unique())
    logger.info(f"回测区间: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')} ({len(dates)}天)")
    
    rebalance_count = 0
    
    for i, date in enumerate(dates):
        # 每日更新净值
        day = quote[quote["date"] == date]
        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))
        nav.update_nav(date, prices)
        
        # 定期调仓
        if i > 0 and i % rebalance_days == 0:
            # 用截至当日的数据评分
            hist = quote[quote["date"] <= date]
            
            # 取最近60个交易日的数据（加速）
            recent_dates = sorted(hist["date"].unique())[-60:]
            hist = hist[hist["date"].isin(recent_dates)]
            
            data = {
                "daily_quote": hist,
                "codes": codes,
                "financial": financial,
                "northbound": pd.DataFrame(),
            }
            
            try:
                scores = engine.score_all(data, date=date.strftime("%Y-%m-%d"))
                nav.rebalance(date, scores, prices, f"定期调仓#{rebalance_count+1}")
                rebalance_count += 1
            except Exception as e:
                logger.warning(f"{date.strftime('%Y-%m-%d')} 评分失败: {e}")
        
        if (i + 1) % 50 == 0:
            latest_nav = nav.nav_history[-1]["nav"]
            logger.info(f"进度: {i+1}/{len(dates)} | 净值: {latest_nav:.4f}")
    
    # 统计结果
    navs = pd.DataFrame(nav.nav_history)
    navs["date"] = pd.to_datetime(navs["date"])
    
    total_return = (navs["nav"].iloc[-1] - 1) * 100
    peak = navs["nav"].cummax()
    dd = ((navs["nav"] - peak) / peak * 100).min()
    
    # 年化
    days = (navs["date"].iloc[-1] - navs["date"].iloc[0]).days
    annual = ((navs["nav"].iloc[-1]) ** (365 / max(days, 1)) - 1) * 100
    
    # Sharpe
    daily_returns = navs["nav"].pct_change().dropna()
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0
    calmar = annual / abs(dd) if dd != 0 else 0
    
    # 保存净值曲线
    out_dir = PROJECT_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    navs[["date", "nav"]].to_csv(out_dir / "nav_history.csv", index=False)
    
    # 交易统计
    buys = sum(1 for t in nav.trade_log if t["action"] == "buy")
    sells = sum(1 for t in nav.trade_log if t["action"] == "sell")
    
    # 月度收益
    navs["month"] = navs["date"].dt.to_period("M")
    monthly = navs.groupby("month")["nav"].last()
    monthly_return = monthly.pct_change().dropna() * 100
    
    print("\n" + "=" * 55)
    print(f"📡 StockRadar 历史回测报告")
    print(f"   {start_date} ~ {end_date} | {len(codes)}只 | {rebalance_days}天调仓")
    print("=" * 55)
    print(f"📊 总收益:  {total_return:+.2f}%")
    print(f"📈 年化收益: {annual:.1f}%")
    print(f"📉 最大回撤: {dd:.1f}%")
    print(f"📏 Sharpe:   {sharpe:.2f}")
    print(f"📐 Calmar:   {calmar:.2f}")
    print(f"🔄 调仓:     {rebalance_count}次")
    print(f"📋 交易:     买入{buys}笔 卖出{sells}笔")
    print(f"📅 回测天数: {len(dates)}天")
    
    # 月度收益表
    print(f"\n📅 月度收益:")
    for m, r in monthly_return.items():
        emoji = "🟢" if r > 0 else "🔴"
        print(f"  {m} {emoji} {r:+.1f}%")
    
    # 最终持仓
    print(f"\n📦 最终持仓:")
    for code, h in sorted(nav.holdings.items()):
        from src.data.stock_names import stock_name
        pnl = 0
        if code in prices:
            pnl = (prices[code] - h["cost_price"]) / h["cost_price"] * 100
        print(f"  {stock_name(code)} {h['shares']}股@¥{h['cost_price']:.2f} ({pnl:+.1f}%)")
    
    print("=" * 55)
    
    # 保存结果
    result = {
        "total_return": total_return,
        "annual_return": annual,
        "max_drawdown": dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "rebalance_count": rebalance_count,
        "trades": len(nav.trade_log),
    }
    pd.DataFrame([result]).to_csv(out_dir / "backtest_summary.csv", index=False)
    logger.info(f"净值曲线保存: output/nav_history.csv")
    
    return navs, nav


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-03-31")
    parser.add_argument("--rebalance", type=int, default=10)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()
    
    run_backtest(args.start, args.end, args.rebalance, args.top)
