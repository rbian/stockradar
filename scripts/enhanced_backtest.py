"""增强回测 — 全沪深300 + 交易成本 + 基准对比

用法:
    python scripts/enhanced_backtest.py --stocks 100 --start 20220101
    python scripts/full_backtest.py --stocks 300 --start 20210101
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from loguru import logger

import baostock as bs
from src.data.baostock_adapter import (
    fetch_daily_quote_batch_bs,
    fetch_financial_bs,
)
from src.factors.engine import FactorEngine
from src.infra.logger import setup_logger


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--stocks", type=int, default=100)
    p.add_argument("--start", type=str, default="20220101")
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--rebalance-days", type=int, default=10)
    p.add_argument("--capital", type=float, default=1000000)
    p.add_argument("--stop-loss", type=float, default=-0.18)
    p.add_argument("--commission", type=float, default=0.001,
                   help="单边交易费率(含印花税)，默认0.1%")
    return p.parse_args()


def fetch_hs300_codes(limit: int) -> list:
    bs.login()
    try:
        rs = bs.query_hs300_stocks()
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        return [c.split(".")[-1] for c in df["code"].tolist()][:limit]
    finally:
        bs.logout()


def fetch_index_data(start: str, end: str) -> pd.DataFrame:
    """拉沪深300指数作为基准"""
    bs.login()
    try:
        # 指数用query_history_k_data_plus，不带复权
        sd = start.replace("-", "")
        ed = end.replace("-", "")
        # 确保YYYYMMDD格式（如果已经是YYYY-MM-DD就转换）
        if "-" in sd:
            sd = sd.replace("-", "")
        if "-" in ed:
            ed = ed.replace("-", "")
        rs = bs.query_history_k_data_plus(
            "sh.000300",
            "date,close",
            start_date=sd, end_date=ed,
            frequency="d",
        )
        if rs is None or rs.error_code != '0':
            logger.warning(f"指数拉取失败: {rs.error_msg if rs else 'None'}")
            return pd.DataFrame()
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=rs.fields)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        return df
    finally:
        bs.logout()


def run():
    args = parse_args()
    setup_logger()

    start_date = args.start.replace("-", "")
    end_date = (args.end or datetime.now().strftime("%Y%m%d")).replace("-", "")

    # 格式化为 YYYY-MM-DD
    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # 1. 股票池
    codes = fetch_hs300_codes(args.stocks)
    logger.info(f"=== 增强回测（沪深300成分股 {len(codes)}只） ===")
    logger.info(f"{sd} ~ {ed} | Top{args.top_n} | 每{args.rebalance_days}天 | 手续费{args.commission:.1%}")

    # 2. 行情
    logger.info("拉取行情...")
    quote = fetch_daily_quote_batch_bs(codes, start_date, end_date, delay=0.05)
    if quote.empty:
        logger.error("无行情")
        return

    valid = [c for c in codes if len(quote[quote["code"] == c]) >= 60]
    codes = valid
    quote = quote[quote["code"].isin(codes)]
    logger.info(f"有效: {len(quote)}条, {len(codes)}只")

    # 3. 财务（拉最近2年Q4，取最新的）
    end_year = int(end_date[:4])
    logger.info("拉取财务数据...")
    fin_list = []
    for y in [end_year - 1, end_year - 2]:
        f = fetch_financial_bs(codes, year=y, quarter=4)
        if not f.empty:
            fin_list.append(f)
    financial = pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()
    logger.info(f"财务: {len(financial)}条")

    # 基准指数
    logger.info("拉取沪深300指数...")
    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            "sh.000300", "date,close",
            start_date=start_date, end_date=end_date,
            frequency="d",
        )
        if rs and rs.error_code == '0':
            idx_rows = []
            while rs.next():
                idx_rows.append(rs.get_row_data())
            index_df = pd.DataFrame(idx_rows, columns=rs.fields) if idx_rows else pd.DataFrame()
            if not index_df.empty:
                index_df["close"] = pd.to_numeric(index_df["close"], errors="coerce")
                index_df["date"] = pd.to_datetime(index_df["date"])
            logger.info(f"指数: {len(index_df)}天")
        else:
            index_df = pd.DataFrame()
            logger.warning("指数拉取失败")
    finally:
        bs.logout()

    # 5. 因子引擎
    engine = FactorEngine()

    # 6. 回测
    capital = args.capital
    holdings = {}
    nav_history = []
    trade_log = []
    peak_nav = args.capital
    commission_rate = args.commission

    dates = sorted(quote["date"].dt.date.unique())
    rebal_dates = dates[::args.rebalance_days]

    for idx, dt in enumerate(rebal_dates):
        dt_str = dt.strftime("%Y-%m-%d")

        hist = quote[quote["date"].dt.date <= dt]
        day = quote[quote["date"].dt.date == dt]
        if hist.empty or day.empty:
            continue

        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

        # ── 个股止损 ──
        for code in list(holdings.keys()):
            h = holdings[code]
            if code not in prices:
                continue
            pnl_pct = prices[code] / h["buy_price"] - 1
            if pnl_pct <= args.stop_loss:
                val = h["shares"] * prices[code]
                fee = val * commission_rate
                capital += val - fee
                trade_log.append({
                    "date": dt_str, "code": code, "action": "sell",
                    "price": prices[code], "shares": h["shares"],
                    "pnl": val - fee - h["shares"] * h["buy_price"],
                    "fee": fee, "reason": "止损",
                })
                del holdings[code]

        # ── 评分 ──
        data = {
            "daily_quote": hist,
            "codes": codes,
            "financial": financial,
            "northbound": pd.DataFrame(),
        }

        try:
            scores = engine.score_all(data, dt_str)
        except Exception as e:
            logger.warning(f"{dt_str} 评分失败: {e}")
            continue

        target = list(scores.head(args.top_n).index)

        # ── 调仓 ──
        # 卖出
        for code in list(holdings.keys()):
            if code not in target:
                h = holdings.pop(code)
                if code in prices:
                    val = h["shares"] * prices[code]
                    fee = val * commission_rate
                    capital += val - fee
                    trade_log.append({
                        "date": dt_str, "code": code, "action": "sell",
                        "price": prices[code], "shares": h["shares"],
                        "pnl": val - fee - h["shares"] * h["buy_price"],
                        "fee": fee,
                    })

        # 买入
        need_buy = [c for c in target if c not in holdings and c in prices]
        if need_buy and capital > 0:
            per = capital / len(need_buy)
            for code in need_buy:
                price = prices[code]
                if price <= 0:
                    continue
                shares = int(per / price / 100) * 100
                if shares > 0:
                    cost = shares * price
                    fee = cost * commission_rate
                    if capital >= cost + fee:
                        capital -= cost + fee
                        holdings[code] = {"shares": shares, "buy_price": price}
                        trade_log.append({
                            "date": dt_str, "code": code, "action": "buy",
                            "price": price, "shares": shares, "pnl": 0, "fee": fee,
                        })

        # ── 净值 ──
        pv = capital
        for code, h in holdings.items():
            if code in prices:
                pv += h["shares"] * prices[code]

        peak_nav = max(peak_nav, pv)
        dd = (pv / peak_nav - 1) * 100

        # 基准指数
        idx_close = None
        if not index_df.empty:
            idx_row = index_df[index_df["date"].dt.date <= dt]
            if not idx_row.empty:
                idx_close = idx_row.iloc[-1]["close"]

        nav_history.append({
            "date": dt_str, "nav": pv, "cash": capital,
            "holdings": len(holdings), "dd": dd,
            "index": idx_close,
        })

        if (idx + 1) % 20 == 0:
            logger.info(f"{dt_str} | 净值={pv:,.0f} | 回撤={dd:.1f}%")

    # 7. 报告
    if not nav_history:
        logger.error("无结果")
        return

    nav_df = pd.DataFrame(nav_history)
    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()

    total_ret = (nav_df["nav"].iloc[-1] / args.capital - 1) * 100
    max_dd = nav_df["dd"].min()
    rets = nav_df["nav"].pct_change().dropna()
    sharpe = rets.mean() / rets.std() * (252 / args.rebalance_days) ** 0.5 if rets.std() > 0 else 0
    calmar = abs(total_ret / max_dd) if max_dd != 0 else 0

    sells = trade_df[trade_df["action"] == "sell"] if not trade_df.empty else pd.DataFrame()
    win = (sells["pnl"] > 0).mean() * 100 if len(sells) > 0 else 0
    stop_n = len(sells[sells.get("reason", "").str.contains("止损", na=False)]) if not sells.empty else 0
    total_fee = trade_df["fee"].sum() if not trade_df.empty and "fee" in trade_df.columns else 0

    # 基准对比
    bench_ret = "N/A"
    excess_ret = "N/A"
    if not nav_df.empty and nav_df["index"].iloc[0] and nav_df["index"].iloc[-1]:
        idx_start = nav_df["index"].iloc[0]
        idx_end = nav_df["index"].dropna().iloc[-1] if not nav_df["index"].dropna().empty else None
        if idx_start and idx_end:
            bench_ret_val = (idx_end / idx_start - 1) * 100
            bench_ret = f"{bench_ret_val:+.2f}%"
            excess_ret = f"{total_ret - bench_ret_val:+.2f}%"

    # 年化
    n_days = (pd.Timestamp(nav_df["date"].iloc[-1]) - pd.Timestamp(nav_df["date"].iloc[0])).days
    annual_ret = ((nav_df["nav"].iloc[-1] / args.capital) ** (365 / max(n_days, 1)) - 1) * 100

    print()
    print("=" * 60)
    print(f"📊 增强回测报告 ({len(codes)}只沪深300成分股 + {len(engine.factor_funcs)}因子)")
    print("=" * 60)
    print(f"区间: {sd} ~ {ed} ({n_days}天)")
    print(f"Top{args.top_n} | 每{args.rebalance_days}天 | 手续费{commission_rate:.1%} | 止损{args.stop_loss:.0%}")
    print("-" * 60)
    print(f"最终净值:     ¥{nav_df['nav'].iloc[-1]:,.0f}")
    print(f"总收益:       {total_ret:+.2f}%")
    print(f"年化收益:     {annual_ret:.2f}%")
    print(f"最大回撤:     {max_dd:.2f}%")
    print(f"Sharpe:       {sharpe:.2f}")
    print(f"Calmar:       {calmar:.2f}")
    print(f"沪深300基准:  {bench_ret}")
    print(f"超额收益:     {excess_ret}")
    print(f"交易:         {len(trade_df)}笔 | 胜率: {win:.0f}%")
    print(f"止损:         {stop_n}笔")
    print(f"总手续费:     ¥{total_fee:,.0f}")
    if len(sells) > 0:
        best = sells.loc[sells["pnl"].idxmax()]
        worst = sells.loc[sells["pnl"].idxmin()]
        print(f"最佳交易:     {int(best['code'])} +¥{best['pnl']:,.0f}")
        print(f"最差交易:     {int(worst['code'])} ¥{worst['pnl']:,.0f}")
    print("=" * 60)

    # 保存
    out = PROJECT_ROOT / "output"
    out.mkdir(exist_ok=True)
    nav_df.to_csv(out / "enhanced_backtest_nav.csv", index=False)
    if not trade_df.empty:
        trade_df.to_csv(out / "enhanced_backtest_trades.csv", index=False)
    logger.info("结果保存到 output/")


if __name__ == "__main__":
    run()
