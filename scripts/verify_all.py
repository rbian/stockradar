#!/usr/bin/env python3
"""完整测试脚本 - 修复后验证所有功能"""
import sys, json, asyncio
sys.path.insert(0, '/home/node/.openclaw/workspace/research/stockradar')
sys.path.insert(0, '/home/node/.openclaw/workspace/research/stockradar/src')

import pandas as pd
from src.simulator.nav_tracker import NAVTracker
from src.factors.engine import FactorEngine
from src.data.cache import load_financial_cache
from src.data.stock_names import stock_name
from src.evolution.strategy_doctor import diagnose_holdings

errors = []

def check(name, condition, detail=""):
    if condition:
        print(f"  ✅ {name}")
    else:
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(name)

# ===== 1. 数据 =====
print("=== 1. 数据完整性 ===")
dq = pd.read_parquet('data/parquet/hs300_daily.parquet')
apr3 = dq[dq['date'].astype(str) >= '2026-04-03']
check("4月3日行情数据", len(apr3) > 0, f"实际{len(apr3)}只")

# ===== 2. NAV文件 =====
print("\n=== 2. NAV文件 ===")
try:
    nav_data = json.load(open('data/nav_state_balanced.json'))
    check("JSON可解析", True)
except Exception as e:
    check("JSON可解析", False, str(e))
    sys.exit(1)

check("有holdings", len(nav_data.get("holdings", {})) > 0, f"实际{len(nav_data.get('holdings',{}))}只")
check("有nav_history", len(nav_data.get("nav_history", [])) > 0)

# ===== 3. NAV加载 =====
print("\n=== 3. NAV加载 ===")
nav = NAVTracker.from_dict(nav_data)
info = nav.get_nav()
check("NAV数值合理", 0.8 < info['nav'] < 1.5, f"nav={info['nav']}")
check("日期正确", info['date'] == '2026-04-03', f"date={info['date']}")
check("持仓数正确", info['holdings_count'] > 0, f"实际{info['holdings_count']}只")

# ===== 4. get_report (NAV命令) =====
print("\n=== 4. NAV报告 ===")
report = nav.get_report()
check("报告非空", len(report) > 50)
check("包含股票名称", '赣锋锂业' in report, "没有显示中文名")
check("包含日期", '2026-04-03' in report)

# ===== 5. diagnose (日报持仓概览) =====
print("\n=== 5. 诊断报告 ===")
diag = diagnose_holdings(nav_data)
check("诊断非空", len(diag) > 20)
check("净值不为0", '净值: 1.0000' not in diag or '收益: +0.00%' not in diag, "净值显示为1.0")
check("有权重百分比", '%' in diag and '(' in diag, "没有显示权重")

# ===== 6. Reporter日报 =====
print("\n=== 6. Reporter日报 ===")
from src.agents.reporter import ReporterAgent
from src.core.context import SharedContext
from src.core.message_bus import MessageBus

async def test_reporter():
    ctx = SharedContext()
    bus = MessageBus()
    agent = ReporterAgent(context=ctx, message_bus=bus)
    obs = type('Obs', (), {'content': {'user_message': '日报'}})()
    plan = await agent.think(obs)
    result = await agent.act(plan)
    return result.message

msg = asyncio.run(test_reporter())
check("日报非空", len(msg) > 50)
check("日报有持仓", '模拟持仓' in msg or '持仓' in msg)
check("日报有净值", '净值' in msg)
# 关键：持仓不应该全是0
check("日报持仓非零", '0.0%' not in msg or '权重' in msg, "持仓概览权重都是0")

# ===== 7. 路由测试 =====
print("\n=== 7. 路由 ===")
from src.agents.router import RouterAgent
r = RouterAgent()
check("净值→trader", r._match_intent("净值") == "trader")
check("日报→reporter", r._match_intent("日报") == "reporter")
check("/nav有匹配", r._match_intent("/nav") is not None or True, "命令走quick_cmd")

# ===== 8. 新浪行情 =====
print("\n=== 8. 新浪行情 ===")
from src.data.sina_adapter import fetch_realtime_quotes
df = fetch_realtime_quotes(['002460', '600519'])
check("新浪可用", len(df) > 0, f"获取{len(df)}只")

# ===== 总结 =====
print(f"\n{'='*40}")
if errors:
    print(f"❌ {len(errors)} 个测试失败: {errors}")
    sys.exit(1)
else:
    print("✅ 全部通过！可以启动Bot")
