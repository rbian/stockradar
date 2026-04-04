#!/usr/bin/env python3
"""Weekend offline test — simulate a full trading day with historical data

Usage: python3 scripts/weekend_test.py [--date 2026-04-02]

Simulates the full daily flow:
1. Data update (skip, use existing parquet)
2. Scoring → Technical signal filter → Rebalance
3. IC tracking
4. Report generation
5. Alert check
6. Pages export
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

# Load env
env_file = PROJECT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

from loguru import logger
logger.info("=== Weekend Offline Test ===")


def test_scoring_and_rebalance(test_date=None):
    """Test scoring + technical signal filter + rebalance"""
    import pandas as pd
    from src.factors.engine import FactorEngine
    from src.simulator.nav_tracker import NAVTracker
    from src.factors.technical_signals import batch_score
    from src.data.stock_names import stock_name

    engine = FactorEngine()
    dq = pd.read_parquet(PROJECT / "data/parquet/hs300_daily.parquet")
    
    if test_date:
        dq = dq[dq["date"] <= pd.Timestamp(test_date)]
    
    latest_date = dq["date"].max()
    logger.info(f"Data: {len(dq)} rows, latest={latest_date}")

    # Load codes and financial data
    codes = pd.read_csv(PROJECT / "data/hs300_codes.txt", header=None)[0].tolist()
    
    # Score
    data = {
        "daily_quote": dq[dq["code"].isin(codes)],
        "codes": codes,
        "financial": pd.DataFrame(),
        "northbound": pd.DataFrame(),
    }
    scores = engine.score_all(data)
    logger.info(f"Scored {len(scores)} stocks, top: {scores.index[0]} = {scores.iloc[0]['score_total']:.2f}")

    # Technical signal filter
    sig_df = batch_score(dq, codes)
    logger.info(f"Technical signals: {len(sig_df)} stocks scored")
    
    # Show top signals
    for _, row in sig_df.head(5).iterrows():
        name = stock_name(row["code"])
        logger.info(f"  {name}: signal={row['signal_score']} {row['signal']}")

    # Load NAV and rebalance
    nav_file = PROJECT / "data" / "nav_state_balanced.json"
    nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
    
    day = dq[dq["date"] == latest_date]
    prices = dict(zip(day["code"].astype(str), day["close"]))
    
    nav.rebalance(latest_date, scores, prices, "离线测试调仓")
    nav.update_nav(latest_date, prices)
    
    info = nav.get_nav()
    logger.info(f"After rebalance: NAV={info['nav']:.4f}, return={info['total_return']:+.2f}%, holdings={info['holdings_count']}")
    
    return True


def test_alerts():
    """Test alert system"""
    import pandas as pd
    from src.simulator.alert_system import check_alerts, format_alerts
    from src.data.stock_names import stock_name

    nav_data = json.load(open(PROJECT / "data/nav_state_balanced.json"))
    dq = pd.read_parquet(PROJECT / "data/parquet/hs300_daily.parquet")
    
    holdings = nav_data.get("holdings", {})
    alerts = check_alerts(holdings, dq)
    
    if alerts:
        names = {c: stock_name(c) for c in holdings}
        msg = format_alerts(alerts, names)
        logger.info(f"Alerts found: {len(alerts)}")
        print(msg)
    else:
        logger.info("No alerts triggered")
    
    return True


def test_report():
    """Test daily report generation"""
    async def _test():
        from src.agents.reporter import ReporterAgent
        from src.core.context import SharedContext
        from src.core.message_bus import MessageBus
        
        ctx = SharedContext()
        bus = MessageBus()
        agent = ReporterAgent(context=ctx, message_bus=bus)
        
        obs = type('Obs', (), {'content': {'user_message': '日报'}})()
        plan = await agent.think(obs)
        result = await agent.act(plan)
        
        # Print key sections
        lines = result.message.split("\n")
        logger.info(f"Report: {len(lines)} lines")
        for line in lines[:5]:
            print(line)
        print("...")
        # Check tushare data is included
        if "北向" in result.message:
            logger.info("✅ Tushare northbound data in report")
        if "行业" in result.message:
            logger.info("✅ Sector strength data in report")
        
        return result.success
    
    return asyncio.run(_test())


def test_ic_tracking():
    """Test factor IC tracking"""
    import pandas as pd
    from src.evolution.factor_tracker import FactorTracker
    from src.factors.engine import FactorEngine
    
    tracker = FactorTracker()
    engine = FactorEngine()
    dq = pd.read_parquet(PROJECT / "data/parquet/hs300_daily.parquet")
    codes = pd.read_csv(PROJECT / "data/hs300_codes.txt", header=None)[0].tolist()
    
    data = {
        "daily_quote": dq[dq["code"].isin(codes)],
        "codes": codes,
        "financial": pd.DataFrame(),
        "northbound": pd.DataFrame(),
    }
    scores = engine.score_all(data)
    
    # Run IC tracking
    latest_date = dq["date"].max()
    tracker.track(scores, dq, latest_date)
    
    ic_summary = tracker.get_ic_summary()
    logger.info(f"IC tracking: {len(ic_summary)} factors")
    for factor, ic_data in list(ic_summary.items())[:3]:
        avg_ic = ic_data.get("avg_ic", 0)
        logger.info(f"  {factor}: avg_IC={avg_ic:.4f}")
    
    return True


def test_pages_export():
    """Test pages data export"""
    from scripts.export_pages import export
    try:
        output = export()
        logger.info(f"✅ Pages export: {len(output['nav_history'])} nav points, HS300 benchmark: {len(output.get('hs300_benchmark', []))} points")
        return True
    except Exception as e:
        logger.error(f"❌ Pages export failed: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Simulate up to this date (YYYY-MM-DD)")
    parser.add_argument("--skip", nargs="*", help="Skip tests: scoring alerts report ic pages")
    args = parser.parse_args()
    
    skip = set(args.skip or [])
    results = {}
    
    tests = [
        ("scoring", "Scoring + Rebalance", test_scoring_and_rebalance),
        ("alerts", "Alert System", test_alerts),
        ("report", "Daily Report", test_report),
        ("ic", "IC Tracking", test_ic_tracking),
        ("pages", "Pages Export", test_pages_export),
    ]
    
    for key, name, fn in tests:
        if key in skip:
            logger.info(f"⏭️  Skip: {name}")
            continue
        logger.info(f"\n{'='*40}")
        logger.info(f"Testing: {name}")
        logger.info(f"{'='*40}")
        try:
            if key == "scoring":
                ok = fn(args.date)
            else:
                ok = fn()
            results[key] = "✅ PASS" if ok else "❌ FAIL"
        except Exception as e:
            results[key] = f"❌ ERROR: {e}"
            logger.error(f"Failed: {e}")
    
    logger.info(f"\n{'='*40}")
    logger.info("SUMMARY")
    logger.info(f"{'='*40}")
    for key, status in results.items():
        logger.info(f"  {key}: {status}")
    
    all_pass = all("✅" in v for v in results.values())
    logger.info(f"\nResult: {'ALL PASS ✅' if all_pass else 'SOME FAILED ❌'}")
    return all_pass


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
