"""沪深300实时行情批量拉取 — 用实时行情工具(高效)

10 credits返回~20只，300只需~15次=150 credits
"""

import os
import sys
import time
import json
import re
from io import StringIO
from pathlib import Path
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

# 加载.env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE = "https://qveris.ai/api/v1"
TOOL_LIVE = "mcp_gildata.asharelivequote.v1"


def _headers():
    return {"Authorization": f"Bearer {os.environ['QVERIS_API_KEY']}", "Content-Type": "application/json"}


def _parse_md_table(md: str) -> pd.DataFrame:
    lines = [l for l in md.split("\n") if l.strip() and not re.match(r'^[\s|:\-]+$', l)]
    if len(lines) < 2:
        return pd.DataFrame()
    cols = [c.strip() for c in lines[0].split("|") if c.strip()]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if cells:
            rows.append(dict(zip(cols, cells)))
    return pd.DataFrame(rows)


def fetch_batch(codes: list) -> pd.DataFrame:
    """拉一批股票实时行情"""
    import requests
    r = requests.post(
        f"{BASE}/tools/execute?tool_id={TOOL_LIVE}",
        headers=_headers(),
        json={"parameters": {"query": f"获取以下股票实时行情: {','.join(codes)}"}},
        timeout=60,
    )
    d = r.json()
    results = d.get("result", {}).get("data", {}).get("results", [])
    all_dfs = []
    for res in results:
        md = res.get("table_markdown", "")
        df = _parse_md_table(md)
        if not df.empty:
            all_dfs.append(df)
    
    if not all_dfs:
        return pd.DataFrame()
    
    total = pd.concat(all_dfs, ignore_index=True)
    
    # 标准化
    col_map = {
        "股票代码": "code", "股票名称": "name",
        "最新(元)": "close", "涨跌幅(%)": "change_pct",
        "涨跌(元)": "change", "成交额": "amount",
        "换手率(%)": "turnover", "量比": "volume_ratio",
        "今开(元)": "open", "最高(元)": "high", "最低(元)": "low",
        "昨收(元)": "pre_close",
    }
    total = total.rename(columns={k: v for k, v in col_map.items() if k in total.columns})
    
    for c in ["close", "change_pct", "open", "high", "low", "pre_close", "turnover"]:
        if c in total.columns:
            total[c] = pd.to_numeric(total[c], errors="coerce")
    
    return total


def fetch_hs300_realtime(batch_size: int = 20) -> pd.DataFrame:
    """拉沪深300全部实时行情"""
    codes_file = PROJECT_ROOT / "data" / "hs300_codes.txt"
    if not codes_file.exists():
        # 先获取列表
        import baostock as bs
        bs.login()
        rs = bs.query_hs300_stocks()
        codes = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            codes.append(row[1].replace("sh.", "").replace("sz.", ""))
        bs.logout()
        codes_file.parent.mkdir(parents=True, exist_ok=True)
        codes_file.write_text("\n".join(codes))
    else:
        codes = codes_file.read_text().strip().split("\n")
    
    logger.info(f"沪深300: {len(codes)}只")
    
    all_dfs = []
    fetched_codes = set()
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(codes) - 1) // batch_size + 1
        
        try:
            df = fetch_batch(batch)
            got = set()
            if not df.empty and "code" in df.columns:
                got = set(df["code"].tolist())
                all_dfs.append(df)
            fetched_codes.update(got)
            missing = len(batch) - len(got)
            logger.info(f"批次 {batch_num}/{total_batches}: {len(got)}/{len(batch)}只" +
                       (f" (缺{missing})" if missing else ""))
        except Exception as e:
            logger.warning(f"批次 {batch_num} 失败: {e}")
        
        time.sleep(0.5)
    
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = result.drop_duplicates(subset=["code"])
        logger.info(f"✅ 总计: {len(result)}只")
        
        # 保存
        out_dir = PROJECT_ROOT / "data" / "parquet"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "hs300_realtime.parquet"
        result.to_parquet(out_file, index=False)
        logger.info(f"保存: {out_file}")
        
        # 涨跌统计
        if "change_pct" in result.columns:
            up = (result["change_pct"] > 0).sum()
            down = (result["change_pct"] < 0).sum()
            flat = len(result) - up - down
            avg_chg = result["change_pct"].mean()
            logger.info(f"涨跌: {up}涨 {down}跌 {flat}平 | 均值{avg_chg:+.2f}%")
            
            top5 = result.nlargest(5, "change_pct")
            logger.info("涨幅Top5:")
            for _, r in top5.iterrows():
                logger.info(f"  {r.get('name','')}({r['code']}) {r['change_pct']:+.2f}%")
        
        return result
    
    return pd.DataFrame()


if __name__ == "__main__":
    from src.infra.logger import setup_logger
    setup_logger()
    fetch_hs300_realtime()
