"""端到端测试 — 多Agent系统实际运行

场景：用户消息 → Router路由 → Agent执行 → 返回结果
"""

import asyncio
import os
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger
from src.infra.logger import setup_logger
from src.factors.engine import FactorEngine
from src.data.baostock_adapter import fetch_daily_quote_batch_bs
from src.data.cache import load_financial_cache
from src.core.orchestrator import AgentOrchestrator
from src.agents import RouterAgent, AnalystAgent, TraderAgent, ReporterAgent


WATCHLIST = ["600519", "000333", "600036", "601318", "000858",
             "600276", "601127", "600030", "601166", "600887"]


def create_system():
    """创建完整系统 + 注册工具"""
    engine = FactorEngine()
    orch = AgentOrchestrator()
    orch.context.write("factor_engine", engine, writer="system")
    orch.context.write("mode", "simulation", writer="system")

    for cls in [RouterAgent, AnalystAgent, TraderAgent, ReporterAgent]:
        agent = cls(context=orch.context, message_bus=orch.bus)
        orch.register_agent(agent)

    # 行情：QVeris拉3只实时 + BaoStock缓存补齐
    quote = pd.DataFrame()
    qveris_key = os.environ.get("QVERIS_API_KEY", "")
    if qveris_key:
        try:
            from src.data.qveris_adapter import fetch_daily_quote_qv
            qv_codes = ["600519", "000333", "601318"]  # 只拉3只省credits
            logger.info(f"QVeris拉取实时行情({len(qv_codes)}只)...")
            qv_quote = fetch_daily_quote_qv(qv_codes, delay=0.8)
            if not qv_quote.empty:
                qv_quote = qv_quote[qv_quote["code"].isin(qv_codes)]
                quote = qv_quote
                logger.info(f"QVeris: {len(quote)}条")
        except Exception as e:
            logger.warning(f"QVeris失败: {e}")

    # BaoStock缓存补齐剩余股票
    if not quote.empty:
        fetched = set(quote["code"].unique())
        bs_codes = [c for c in WATCHLIST if c not in fetched]
    else:
        bs_codes = WATCHLIST
    if bs_codes or quote.empty:
        logger.info(f"BaoStock缓存补齐({len(bs_codes) if not quote.empty else len(WATCHLIST)}只)...")
        bs_quote = fetch_daily_quote_batch_bs(
            bs_codes if not quote.empty else WATCHLIST,
            "20240101", "20250301", delay=0.01
        )
        if not bs_quote.empty:
            bs_quote = bs_quote[bs_quote["code"].isin(bs_codes if not quote.empty else WATCHLIST)]
            if not quote.empty:
                quote = pd.concat([quote, bs_quote], ignore_index=True)
                quote = quote.drop_duplicates(subset=["code", "date"]).sort_values("date")
            else:
                quote = bs_quote

    # 财务
    fin_list = []
    for y in [2024, 2023]:
        for q in [4, 3, 2, 1]:
            f = load_financial_cache(y, q, max_age_days=9999)
            if not f.empty:
                fin_list.append(f)
    financial = pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()

    orch.context.write("quote_data", quote, writer="system")
    orch.context.write("financial_data", financial, writer="system")
    orch.context.write("codes", WATCHLIST, writer="system")
    orch.context.write("data.daily_quote", quote, writer="system")
    logger.info(f"行情: {len(quote)}条 | 财务: {len(financial)}条")

    def score_all_fn(data=None, date_str=None):
        if data is None:
            q_filtered = quote[quote["code"].isin(WATCHLIST)]
            data = {"daily_quote": q_filtered, "codes": WATCHLIST,
                    "financial": financial, "northbound": pd.DataFrame()}
        return engine.score_all(data, date_str or "2025-02-17")

    orch.register_tool("score_all", score_all_fn, "全市场评分", "factor")

    def fetch_quote_fn(symbol=None, **kwargs):
        if symbol:
            return quote[quote["code"] == symbol]
        return quote

    orch.register_tool("fetch_daily_quote", fetch_quote_fn, "获取行情", "data")
    logger.info(f"✅ 系统就绪: {len(orch.agents)}个Agent, {len(orch.tools._tools)}个工具")
    return orch


async def test(orch):
    print("\n" + "=" * 55)
    print("📡 StockRadar 端到端测试")
    print("=" * 55)

    for msg in ["帮助", "分析600519", "市场怎么样", "评分排名", "当前持仓", "净值", "回测", "日报"]:
        print(f"\n{'─'*40}")
        print(f"👤 {msg}")
        try:
            result = await asyncio.wait_for(orch.process_user_message(msg, "test"), timeout=30)
            print(f"📡 {result[:300]}")
        except asyncio.TimeoutError:
            print("📡 ⏰ 超时")
        except Exception as e:
            print(f"📡 ❌ {e}")

    print(f"\n{'='*55}")


async def main():
    setup_logger()
    orch = create_system()
    await test(orch)

if __name__ == "__main__":
    asyncio.run(main())
