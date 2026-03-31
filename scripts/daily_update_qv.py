"""每日数据更新脚本 — QVeris实时 + BaoStock历史

用法:
  python scripts/daily_update_qv.py              # 更新沪深300
  python scripts/daily_update_qv.py --codes 600519,000333  # 指定股票
  python scripts/daily_update_qv.py --full       # 全量历史+今日
"""

import os
import sys
import time
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger
from src.infra.logger import setup_logger

# 加载.env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_hs300_codes() -> list:
    """获取沪深300成分股"""
    try:
        import baostock as bs
        bs.login()
        rs = bs.query_hs300_stocks()
        codes = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            code = row[1].replace("sh.", "").replace("sz.", "")
            codes.append(code)
        bs.logout()
        logger.info(f"沪深300成分股: {len(codes)}只")
        return codes
    except Exception as e:
        logger.error(f"获取沪深300失败: {e}")
        return []


def fetch_today_qv(codes: list, batch_size: int = 20, delay: float = 0.5) -> pd.DataFrame:
    """QVeris批量拉取当日行情"""
    from src.data.qveris_adapter import fetch_daily_quote_qv
    all_dfs = []
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        logger.info(f"QVeris批次 {i//batch_size + 1}/{(len(codes)-1)//batch_size + 1}: {len(batch)}只")
        df = fetch_daily_quote_qv(batch, delay=delay)
        if not df.empty:
            all_dfs.append(df)
        time.sleep(1)  # 批次间休息
    
    if all_dfs:
        total = pd.concat(all_dfs, ignore_index=True)
        total = total.drop_duplicates(subset=["code", "date"])
        logger.info(f"QVeris总计: {len(total)}条, {total['code'].nunique()}只")
        return total
    return pd.DataFrame()


def save_to_parquet(df: pd.DataFrame, name: str = "daily_quote"):
    """保存到parquet"""
    out_dir = PROJECT_ROOT / "data" / "parquet"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 合并已有数据
    existing_file = out_dir / f"{name}.parquet"
    if existing_file.exists():
        old = pd.read_parquet(existing_file)
        combined = pd.concat([old, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["code", "date"], keep="last")
        combined = combined.sort_values(["code", "date"])
        combined.to_parquet(existing_file, index=False)
        logger.info(f"合并保存: {len(old)}+{len(df)} → {len(combined)}条 → {existing_file}")
    else:
        df.to_parquet(existing_file, index=False)
        logger.info(f"新建保存: {len(df)}条 → {existing_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", help="指定股票代码，逗号分隔")
    parser.add_argument("--full", action="store_true", help="全量拉取")
    parser.add_argument("--top", type=int, default=50, help="拉取前N只（默认50）")
    args = parser.parse_args()
    
    setup_logger()
    
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        codes = get_hs300_codes()
        if not codes:
            logger.error("无法获取股票列表")
            return
        codes = codes[:args.top]
    
    logger.info(f"开始更新 {len(codes)} 只股票")
    
    df = fetch_today_qv(codes, batch_size=10, delay=0.5)
    if not df.empty:
        save_to_parquet(df)
        # 显示今日行情概览
        today = df[df["date"] == df["date"].max()]
        if not today.empty:
            top5 = today.nlargest(5, "change_pct")
            bot5 = today.nsmallest(5, "change_pct")
            logger.info(f"\n📈 涨幅Top5:")
            for _, r in top5.iterrows():
                logger.info(f"  {r['code']} {r['close']:.2f} ({r['change_pct']:+.2f}%)")
            logger.info(f"\n📉 跌幅Top5:")
            for _, r in bot5.iterrows():
                logger.info(f"  {r['code']} {r['close']:.2f} ({r['change_pct']:+.2f}%)")
    else:
        logger.warning("未获取到数据")


if __name__ == "__main__":
    main()
