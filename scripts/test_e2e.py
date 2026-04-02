"""端到端测试 — 覆盖所有Bot命令"""

import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.system_init import create_system

TESTS = [
    # Router → Analyst
    ("评分排名", "analyst"),
    ("Top10", "analyst"),
    ("分析600519", "analyst"),
    ("因子", "analyst"),
    ("诊断", "analyst"),
    ("市场状态", "analyst"),
    ("市场", "analyst"),
    # Router → Trader
    ("持仓", "trader"),
    ("净值", "trader"),
    ("风控", "trader"),
    ("回测", "trader"),
    # Router → Reporter
    ("日报", "reporter"),
    ("周报", "reporter"),
    ("月报", "reporter"),
    # 无匹配
    ("你好", "router"),
    ("不知道什么", "router"),
]


async def run_tests():
    print("=" * 60)
    print("StockRadar 端到端测试")
    print("=" * 60)
    
    try:
        orch = create_system("full")
    except Exception as e:
        print(f"❌ 系统初始化失败: {e}")
        traceback.print_exc()
        return
    
    print(f"\n✅ 系统就绪: {len(orch.agents)}个Agent\n")
    
    passed = 0
    failed = 0
    errors = []
    
    for msg, expected_agent in TESTS:
        try:
            result = await asyncio.wait_for(
                orch.process_user_message(msg, user_id="test"),
                timeout=30,
            )
            
            # 检查结果
            has_error = "失败" in result or "❌" in result[:20]
            is_valid = len(result) > 10 and not has_error
            
            if is_valid:
                print(f"✅ [{expected_agent:8s}] {msg:12s} → {result[:60]}...")
                passed += 1
            else:
                print(f"⚠️ [{expected_agent:8s}] {msg:12s} → {result[:80]}")
                failed += 1
                errors.append((msg, result[:200]))
                
        except asyncio.TimeoutError:
            print(f"⏰ [{expected_agent:8s}] {msg:12s} → 超时(30s)")
            failed += 1
            errors.append((msg, "超时"))
        except Exception as e:
            print(f"❌ [{expected_agent:8s}] {msg:12s} → {e}")
            failed += 1
            errors.append((msg, str(e)))
            traceback.print_exc()
    
    print(f"\n{'=' * 60}")
    print(f"结果: {passed}通过 / {failed}失败 / {passed+failed}总计")
    print(f"{'=' * 60}")
    
    if errors:
        print("\n失败详情:")
        for msg, err in errors:
            print(f"  {msg}: {err}")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
