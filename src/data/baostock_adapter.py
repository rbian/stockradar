"""BaoStock数据适配器 — 海外可用，带本地缓存

数据：日线行情（含换手率、涨跌幅）+ 完整财务指标（4类） + 股票列表 + 指数
缓存：Parquet本地缓存，避免重复拉取，"""

import time
import baostock as bs
import pandas as pd
from loguru import logger

from src.data.cache import (
    save_quote_cache, load_quote_cache,
    save_financial_cache, load_financial_cache,
    save_stock_list_cache, load_stock_list_cache,
    save_index_cache, load_index_cache,
)


def _to_bs_code(code: str) -> str:
    code = code.replace(".SH", "").replace(".SZ", "")
    return f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"


def _from_bs_code(bs_code: str) -> str:
    return bs_code.split(".")[-1]


def _fmt_date(d: str) -> str:
    d = d.replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def _sf(val) -> float:
    if val is None or val == '' or val == 'None':
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def fetch_stock_list_bs() -> pd.DataFrame:
    """获取全部A股股票列表"""
    # 先查缓存
    cached = load_stock_list_cache()
    if not cached.empty:
        logger.info(f"股票列表缓存命中: {len(cached)}只")
        return cached

    bs.login()
    try:
        rs = bs.query_stock_basic()
        rows = []
        while (rs.error_code == '0') and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df[(df["type"] == "1") & (df["status"] == "1")].copy()
        df["code"] = df["code"].apply(_from_bs_code)
        result = df[["code", "code_name", "ipoDate"]].rename(columns={"code_name": "name"})
        # 保存缓存
        save_stock_list_cache(result)
        logger.info(f"BaoStock股票列表: {len(result)}只")
        return result
    finally:
        bs.logout()


def fetch_daily_quote_batch_bs(symbols: list, start_date: str, end_date: str,
                                delay: float = 0.05) -> pd.DataFrame:
    """批量获取日线行情（带缓存）"""
    sd = _fmt_date(start_date)
    ed = _fmt_date(end_date)

    # 先从缓存加载
    all_cached = []
    need_fetch = []
    for code in symbols:
        cached = load_quote_cache(code, sd, ed)
        if not cached.empty:
            all_cached.append(cached)
        else:
            need_fetch.append(code)

    if all_cached:
        logger.info(f"行情缓存命中: {len(all_cached)}只, {sum(len(d) for d in all_cached)}条")

    if not need_fetch:
        total = pd.concat(all_cached, ignore_index=True)
        logger.info(f"全部命中缓存: {len(total)}条")
        return total

    # 拉取缓存未命中的
    logger.info(f"需拉取: {len(need_fetch)}只, 缓存已有: {len(all_cached)}只")
    sd_raw = start_date.replace("-", "")
    ed_raw = end_date.replace("-", "")

    lg = bs.login()
    if lg.error_code != '0':
        logger.error(f"BaoStock登录失败: {lg.error_msg}")
        if all_cached:
            return pd.concat(all_cached, ignore_index=True)
        return pd.DataFrame()
    try:
        new_dfs = []
        for i, code in enumerate(need_fetch):
            bs_code = _to_bs_code(code)
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,preclose,volume,amount,turn,pctChg",
                    start_date=sd, end_date=ed,
                    frequency="d", adjustflag="2"
                )
                rows = []
                while (rs.error_code == '0') and rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    df = pd.DataFrame(rows, columns=rs.fields)
                    for col in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    result = pd.DataFrame({
                        "code": code, "date": pd.to_datetime(df["date"]),
                        "open": df["open"].values, "high": df["high"].values,
                        "low": df["low"].values, "close": df["close"].values,
                        "pre_close": df["preclose"].values, "change_pct": df["pctChg"].values,
                        "volume": df["volume"].values, "amount": df["amount"].values,
                        "turnover": df["turn"].values,
                    })
                    new_dfs.append(result)
                    # 保存缓存
                    save_quote_cache(code, result, sd, ed)
            except Exception:
                pass
            if (i + 1) % 20 == 0:
                logger.info(f"行情进度: {i+1}/{len(need_fetch)}")
            if delay > 0:
                time.sleep(delay)
        if new_dfs:
            all_dfs = all_cached + new_dfs
            total = pd.concat(all_dfs, ignore_index=True)
            logger.info(f"行情: {len(total)}条 (缓存{sum(len(d) for d in all_cached)}+新拉{sum(len(d) for d in new_dfs)})")
            return total
        elif all_cached:
            return pd.concat(all_cached, ignore_index=True)
        return pd.DataFrame()
    finally:
        bs.logout()


def fetch_financial_bs(codes: list, year: int = 2024, quarter: int = 4) -> pd.DataFrame:
    """拉4类BaoStock财务数据（带缓存）"""
    # 先查缓存
    cached = load_financial_cache(year, quarter)
    if not cached.empty and set(cached["code"]).issuperset(set(codes)):
        result = cached[cached["code"].isin(codes)]
        logger.info(f"财务缓存命中: {len(result)}只")
        return result

    bs.login()
    try:
        records = {}
        for i, code in enumerate(codes):
            bs_code = _to_bs_code(code)
            rec = {"code": code}

            try:
                rs = bs.query_profit_data(code=bs_code, year=year, quarter=quarter)
                while (rs.error_code == '0') and rs.next():
                    r = rs.get_row_data()
                    rec["roe"] = _sf(r[3])
                    rec["net_margin"] = _sf(r[4])
                    rec["gross_margin"] = _sf(r[5])
                    rec["net_profit"] = _sf(r[6])
                    rec["eps"] = _sf(r[7])
                    rec["end_date"] = r[2]
            except Exception:
                pass

            try:
                rs = bs.query_growth_data(code=bs_code, year=year, quarter=quarter)
                while (rs.error_code == '0') and rs.next():
                    r = rs.get_row_data()
                    rec["profit_yoy"] = _sf(r[5]) * 100
                    rec["revenue_yoy"] = _sf(r[4]) * 100
            except Exception:
                pass

            try:
                rs = bs.query_balance_data(code=bs_code, year=year, quarter=quarter)
                while (rs.error_code == '0') and rs.next():
                    r = rs.get_row_data()
                    rec["debt_ratio"] = _sf(r[7]) * 100
            except Exception:
                pass

            try:
                rs = bs.query_cash_flow_data(code=bs_code, year=year, quarter=quarter)
                while (rs.error_code == '0') and rs.next():
                    r = rs.get_row_data()
                    rec["ocf_ratio"] = _sf(r[8])
            except Exception:
                pass

            for key in ["roe", "gross_margin", "net_margin", "net_profit", "eps",
                        "revenue_yoy", "profit_yoy", "debt_ratio", "ocf_ratio",
                        "goodwill_ratio", "inventory_turnover", "operating_leverage",
                        "accrual_ratio"]:
                rec.setdefault(key, 0.0)
            rec.setdefault("end_date", f"{year}-{quarter*3:02d}-01")

            records[code] = rec
            if (i + 1) % 50 == 0:
                logger.info(f"财务进度: {i+1}/{len(codes)}")
            time.sleep(0.03)

        df = pd.DataFrame(list(records.values()))
        # 保存缓存
        save_financial_cache(codes, df, year, quarter)
        logger.info(f"财务: {len(df)}只")
        return df
    finally:
        bs.logout()
