"""QVeris数据适配器 — 海外可用，实时A股数据

数据源: QVeris API (https://qveris.ai/api/v1)
优势: 海外可用、实时数据、不被限流、10000+工具
成本: 10 credits/次 (注册送1000, $19=10000)

工具列表:
- mcp_gildata.stockdailyquote.v1 — 日行情
- mcp_gildata.asharelivequote.v1 — 实时行情
- mcp_gildata.stockrangequotation.v1 — 区间行情
- mcp_gildata.indexlivequote.v1 — 指数实时行情
"""

import os
import re
import json
import json
import time
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from loguru import logger


QVERIS_BASE = "https://qveris.ai/api/v1"
QVERIS_KEY = os.environ.get("QVERIS_API_KEY", "")

# 工具ID
TOOL_DAILY = "mcp_gildata.stockdailyquote.v1"
TOOL_LIVE = "mcp_gildata.asharelivequote.v1"
TOOL_RANGE = "mcp_gildata.stockrangequotation.v1"
TOOL_INDEX = "mcp_gildata.indexlivequote.v1"


def _headers():
    return {"Authorization": f"Bearer {QVERIS_KEY}", "Content-Type": "application/json"}


def _execute(tool_id: str, query: str, timeout: int = 30) -> dict:
    """调用QVeris工具"""
    r = requests.post(
        f"{QVERIS_BASE}/tools/execute?tool_id={tool_id}",
        headers=_headers(),
        json={"parameters": {"query": query}},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("remaining_credits") is not None:
        logger.debug(f"QVeris credits剩余: {data['remaining_credits']}")
    return data


def _parse_table(data: dict) -> pd.DataFrame:
    """从QVeris返回的markdown table解析DataFrame"""
    result = data.get("result", {})
    results = result.get("data", {}).get("results", [])
    if not results:
        return pd.DataFrame()
    
    # 拼接所有markdown表格
    md = ""
    for r in results:
        md += r.get("table_markdown", "")
    
    if not md:
        return pd.DataFrame()
    
    # 解析markdown table
    try:
        # 去掉分隔行(---)
        clean_lines = [l for l in md.split("\n") if not re.match(r'^[\s|:-]+$', l)]
        clean_md = "\n".join(clean_lines)
        tables = pd.read_table(StringIO(clean_md), sep="|", header=0)
        # 清理：去掉空列
        tables = tables.dropna(axis=1, how="all")
        # 过滤掉含 --- 的行
        for col in tables.columns:
            tables = tables[~tables[col].astype(str).str.contains(r'^-{3,}$', na=False)]
        return tables
    except Exception:
        pass
    
    # 备用：手动解析
    lines = md.strip().split("\n")
    if len(lines) < 3:
        return pd.DataFrame()
    
    headers_line = lines[0]
    cols = [c.strip() for c in headers_line.split("|") if c.strip()]
    
    rows = []
    for line in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if cells:
            rows.append(dict(zip(cols, cells)))
    
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_daily_quote_qv(codes: list, start_date: str = "", end_date: str = "",
                          delay: float = 0.5) -> pd.DataFrame:
    """获取日行情（批量）
    
    Args:
        codes: 股票代码列表 ['600519', '000333', ...]
        start_date: 开始日期 YYYY-MM-DD (可选)
        end_date: 结束日期 YYYY-MM-DD (可选)
        delay: 每次调用间隔(秒)
    
    Returns:
        DataFrame: code, date, open, high, low, close, pre_close, 
                   change_pct, volume, amount, turnover
    """
    all_dfs = []
    
    for i, code in enumerate(codes):
        try:
            query = f"{code} 最近日行情数据"
            if start_date:
                query += f" 从{start_date}"
            if end_date:
                query += f" 到{end_date}"
            
            data = _execute(TOOL_DAILY, query)
            df = _parse_table(data)
            
            if df.empty:
                continue
            
            # 标准化列名
            col_map = {
                "股票代码": "code", "交易日": "date",
                "今开盘（元）": "open", "最高价（元）": "high",
                "最低价（元）": "low", "收盘价（元）": "close",
                "前收盘（元）": "pre_close", "涨跌幅（%）": "change_pct",
                "成交量（万股）": "volume", "成交额（万元）": "amount",
                "换手率（%）": "turnover",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            
            # 转换类型
            for col in ["open", "high", "low", "close", "pre_close", "change_pct", "volume", "amount", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            
            if "code" in df.columns:
                df["code"] = df["code"].astype(str).str.zfill(6)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            if "volume" in df.columns:
                df["volume"] = df["volume"] * 10000  # 万股 → 股
            if "amount" in df.columns:
                df["amount"] = df["amount"] * 10000  # 万元 → 元
            
            all_dfs.append(df)
            
        except Exception as e:
            logger.warning(f"QVeris {code} 失败: {e}")
        
        if (i + 1) % 10 == 0:
            logger.info(f"QVeris行情进度: {i+1}/{len(codes)}")
        if delay > 0:
            time.sleep(delay)
    
    if all_dfs:
        total = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"QVeris行情: {len(total)}条, {len(all_dfs)}只")
        return total
    return pd.DataFrame()


def fetch_live_quote_qv(code: str) -> dict:
    """获取实时行情（单只）
    
    Returns:
        dict: code, name, price, change_pct, volume, amount, turnover, ...
    """
    data = _execute(TOOL_LIVE, f"{code} 实时行情")
    df = _parse_table(data)
    if df.empty:
        return {}
    
    row = df.iloc[0].to_dict()
    return row


def fetch_index_quote_qv(index_code: str = "000300") -> dict:
    """获取指数实时行情
    
    Args:
        index_code: 指数代码 (000300=沪深300, 000001=上证指数)
    """
    data = _execute(TOOL_INDEX, f"{index_code} 指数实时行情")
    df = _parse_table(data)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def fetch_range_quote_qv(code: str, start: str, end: str) -> pd.DataFrame:
    """获取区间行情"""
    data = _execute(TOOL_RANGE, f"{code} {start}到{end} 区间行情")
    return _parse_table(data)
