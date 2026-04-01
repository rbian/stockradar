"""系统初始化 — 支持全量沪深300或Watchlist模式"""

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


def load_hs300_data() -> tuple:
    """加载沪深300全量数据（从parquet）"""
    p = PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        codes = df["code"].unique().tolist()
        logger.info(f"沪深300数据: {len(df)}条, {len(codes)}只")
        return df, codes
    return pd.DataFrame(), []


def load_financial_data() -> pd.DataFrame:
    """加载财务数据"""
    fin_list = []
    for y in [2024, 2023]:
        for q in [4, 3, 2, 1]:
            f = load_financial_cache(y, q, max_age_days=9999)
            if not f.empty:
                fin_list.append(f)
    return pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()


def create_system(mode: str = "full"):
    """创建系统

    mode:
      "full" — 沪深300全量（从parquet加载）
      "watchlist" — 仅10只关注股
      "live" — Watchlist + QVeris实时补充
    """
    engine = FactorEngine()
    orch = AgentOrchestrator()
    orch.context.write("factor_engine", engine, writer="system")
    orch.context.write("mode", "simulation", writer="system")

    for cls in [RouterAgent, AnalystAgent, TraderAgent, ReporterAgent]:
        agent = cls(context=orch.context, message_bus=orch.bus)
        orch.register_agent(agent)

    # 加载数据
    if mode == "full":
        quote, codes = load_hs300_data()
        if quote.empty:
            logger.warning("无全量数据，降级为watchlist")
            mode = "watchlist"

    if mode in ("watchlist", "live"):
        codes = WATCHLIST
        quote = fetch_daily_quote_batch_bs(WATCHLIST, "20240101", "20260401", delay=0.01)
        quote = quote[quote["code"].isin(WATCHLIST)]

    # QVeris实时补充（仅live模式，只补3只省credits）
    if mode == "live":
        qveris_key = os.environ.get("QVERIS_API_KEY", "")
        if qveris_key:
            try:
                from src.data.qveris_adapter import fetch_daily_quote_qv
                qv_codes = ["600519", "000333", "601318"]
                logger.info(f"QVeris补{len(qv_codes)}只...")
                qv = fetch_daily_quote_qv(qv_codes, delay=0.8)
                if not qv.empty:
                    quote = pd.concat([quote, qv], ignore_index=True)
                    quote = quote.drop_duplicates(subset=["code", "date"], keep="last")
                    quote = quote.sort_values(["code", "date"])
            except Exception as e:
                logger.warning(f"QVeris失败: {e}")

    financial = load_financial_data()

    orch.context.write("quote_data", quote, writer="system")
    orch.context.write("financial_data", financial, writer="system")
    orch.context.write("codes", codes, writer="system")
    orch.context.write("data.daily_quote", quote, writer="system")
    logger.info(f"模式: {mode} | 行情: {len(quote)}条 | 财务: {len(financial)}条 | 股票: {len(codes)}只")

    # 注册工具
    def score_all_fn(data=None, date_str=None):
        if data is None:
            data = {"daily_quote": quote[quote["code"].isin(codes)],
                    "codes": codes, "financial": financial, "northbound": pd.DataFrame()}
        return engine.score_all(data, date_str or "2025-02-17")

    def fetch_quote_fn(symbol=None, **kwargs):
        return quote[quote["code"] == symbol] if symbol else quote

    orch.register_tool("score_all", score_all_fn, "全市场评分", "factor")
    orch.register_tool("fetch_daily_quote", fetch_quote_fn, "获取行情", "data")
    logger.info(f"✅ 系统就绪: {len(orch.agents)}个Agent, {len(orch.tools._tools)}个工具")
    return orch
