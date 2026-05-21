#!/usr/bin/env python3
"""StockRadar策略回测 - 新配置验证

验证2026-05-20重构后的策略效果
"""

import sys
from pathlib import Path
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from loguru import logger

def analyze_historical_performance():
    """分析历史回测数据"""

    # 读取回测净值
    nav_file = Path(__file__).parent.parent / "output" / "nav_history.csv"
    if not nav_file.exists():
        logger.error("回测数据不存在")
        return

    nav = pd.read_csv(nav_file)
    nav['date'] = pd.to_datetime(nav['date'])

    print("=" * 60)
    print("StockRadar 历史回测分析")
    print("=" * 60)

    # 全周期
    print(f"\n📅 全周期 ({nav['date'].iloc[0].strftime('%Y-%m-%d')} ~ {nav['date'].iloc[-1].strftime('%Y-%m-%d')})")
    total_return = (nav['nav'].iloc[-1] / nav['nav'].iloc[0] - 1) * 100
    days = (nav['date'].iloc[-1] - nav['date'].iloc[0]).days
    annual_return = total_return * 365 / days

    nav['daily_return'] = nav['nav'].pct_change()
    sharpe = nav['daily_return'].mean() / nav['daily_return'].std() * np.sqrt(252) if nav['daily_return'].std() > 0 else 0

    nav['cummax'] = nav['nav'].cummax()
    nav['drawdown'] = (nav['nav'] - nav['cummax']) / nav['cummax']
    max_drawdown = nav['drawdown'].min() * 100

    print(f"  总收益: {total_return:+.2f}%")
    print(f"  年化收益: {annual_return:+.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    print(f"  最大回撤: {max_drawdown:.2f}%")
    print(f"  交易天数: {days}天")

    # 2024年
    nav_2024 = nav[nav['date'].dt.year == 2024]
    if len(nav_2024) > 0:
        ret_2024 = (nav_2024['nav'].iloc[-1] / nav_2024['nav'].iloc[0] - 1) * 100
        print(f"\n📅 2024年: {ret_2024:+.2f}%")

    # 2025年
    nav_2025 = nav[nav['date'].dt.year == 2025]
    if len(nav_2025) > 0:
        ret_2025 = (nav_2025['nav'].iloc[-1] / nav_2025['nav'].iloc[0] - 1) * 100
        print(f"📅 2025年: {ret_2025:+.2f}%")

    # 2026年
    nav_2026 = nav[nav['date'].dt.year == 2026]
    if len(nav_2026) > 0:
        ret_2026 = (nav_2026['nav'].iloc[-1] / nav_2026['nav'].iloc[0] - 1) * 100
        dd_2026 = nav_2026['drawdown'].min() * 100

        print(f"\n📅 2026年: {ret_2026:+.2f}%")
        print(f"  最大回撤: {dd_2026:.2f}%")

        # 2026年周度
        nav_2026['week'] = nav_2026['date'].dt.to_period('W')
        weekly = nav_2026.groupby('week').agg({'nav': ['first', 'last']}).reset_index()
        weekly.columns = ['week', 'first', 'last']
        weekly['return'] = (weekly['last'] / weekly['first'] - 1) * 100

        print("\n  周度表现:")
        for _, row in weekly.iterrows():
            ret = row['return']
            emoji = "🟢" if ret > 0 else "🔴"
            print(f"    {emoji} {row['week']}: {ret:+.2f}%")

    # 读取回测摘要
    summary_file = Path(__file__).parent.parent / "output" / "backtest_summary.csv"
    if summary_file.exists():
        summary = pd.read_csv(summary_file)
        print(f"\n📊 回测摘要:")
        print(f"  总交易: {summary['trades'].iloc[0]}笔")
        print(f"  调仓次数: {summary['rebalance_count'].iloc[0]}次")

    print("\n" + "=" * 60)
    print("📋 策略配置对比")
    print("=" * 60)

    import yaml
    with open('config/strategies.yaml') as f:
        strategies = yaml.safe_load(f)

    print("\n旧配置:")
    print("  基本面: 35%, 技术: 20%, 资金流: 20%, 情绪: 15%, LLM: 10%")
    print("  止损: -15%")

    print("\n新配置 (2026-05-20重构):")
    config = strategies['strategies']['balanced']
    print(f"  基本面: {config['weights']['fundamental']*100:.0f}%, 技术: {config['weights']['technical']*100:.0f}%, 资金流: {config['weights']['capital_flow']*100:.0f}%, 情绪: {config['weights']['market_sentiment']*100:.0f}%, LLM: {config['weights']['llm']*100:.0f}%")
    print(f"  止损: {config['stop_loss']*100:.0f}%")

    with open('config/settings.yaml') as f:
        settings = yaml.safe_load(f)

    print(f"\n策略级风控 (新增):")
    print(f"  净值回撤>10% → 停止买入")
    print(f"  本金回撤>15% → 停止买入")
    print(f"  冷却期: 7天")

    print("\n" + "=" * 60)
    print("🎯 预期效果")
    print("=" * 60)
    print("\n1. 2026年表现改善:")
    print("   - 降低技术权重 → 减少震荡市亏损")
    print("   - 提高基本面权重 → 捕捉真实价值")
    print("   - 收紧止损 → 单笔亏损减少")

    print("\n2. 风控加强:")
    print("   - 策略级风控 → 避免连续回撤")
    print("   - 本金保护 → 绝不亏完")

    print("\n3. 目标指标 (2026年重构后):")
    print("   - 年化收益: >10%")
    print("   - 夏普比率: >0.8")
    print("   - 最大回撤: <12%")
    print("   - d7命中率: >45%")

    print("\n⚠️  注意:")
    print("   - 当前回测是旧配置结果")
    print("   - 需要重新运行回测验证新配置")
    print("   - 建议用2025-10后数据重新回测")

if __name__ == "__main__":
    analyze_historical_performance()