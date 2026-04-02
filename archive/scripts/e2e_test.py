"""端到端测试 — 多Agent系统实际运行"""

import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from src.infra.logger import setup_logger
from scripts.system_init import create_system


async def test(orch):
    print("\n" + "=" * 55)
    print("📡 StockRadar 端到端测试 (沪深300)")
    print("=" * 55)

    for msg in ["帮助", "分析600519", "市场怎么样", "评分排名", "当前持仓", "日报"]:
        print(f"\n{'─'*40}")
        print(f"👤 {msg}")
        try:
            result = await asyncio.wait_for(orch.process_user_message(msg, "test"), timeout=60)
            print(f"📡 {result[:300]}")
        except asyncio.TimeoutError:
            print("📡 ⏰ 超时")
        except Exception as e:
            print(f"📡 ❌ {e}")

    print(f"\n{'='*55}")


async def main():
    setup_logger()
    orch = create_system(mode="full")
    await test(orch)

if __name__ == "__main__":
    asyncio.run(main())
