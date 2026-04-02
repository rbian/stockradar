"""完整回测 — BaoStock + 36因子 + 风控

用法:
    python scripts/full_backtest.py --stocks 50 --start 20230101 --end 20240601
    python scripts/full_backtest.py --stocks 100 --start 20220101
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

from src.data.baostock_adapter import (
    fetch_stock_list_bs,
    fetch_daily_quote_batch_bs,
    fetch_financial_bs,
)
from src.factors.engine import FactorEngine
from src.infra.logger import setup_logger


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--stocks", type=int, default=50)
    p.add_argument("--start", type=str, default="20230101",
                   help="YYYYMMDD格式")
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--rebalance-days", type=int, default=10)
    p.add_argument("--capital", type=float, default=1000000)
    p.add_argument("--stop-loss", type=float, default=-0.15)
    return p.parse_args()


def run():
    args = parse_args()
    setup_logger()

    end_date = args.end or datetime.now().strftime("%Y%m%d")
    start_date = args.start

    # 确保日期格式正确 (YYYYMMDD)
    start_date = start_date.replace("-", "")
    end_date = end_date.replace("-", "")

    # 1. 股票池 — 沪深300成分股（优质池子）
    logger.info("获取沪深300成分股...")
    import baostock as _bs
    _bs.login()
    try:
        _rs = _bs.query_hs300_stocks()
        _rows = []
        while _rs.next():
            _rows.append(_rs.get_row_data())
        _idx_df = pd.DataFrame(_rows, columns=_rs.fields)
        all_codes = [c.split(".")[-1] for c in _idx_df["code"].tolist()]
    finally:
        _bs.logout()
    codes = all_codes[:args.stocks]

    logger.info(f"=== 完整回测（沪深300成分股） ===")
    logger.info(f"股票: {len(codes)}只 | 时间: {start_date}~{end_date}")
    logger.info(f"Top{args.top_n} | 每{args.rebalance_days}天调仓 | 止损{args.stop_loss:.0%}")

    # 2. 行情
    logger.info("拉取行情...")
    quote = fetch_daily_quote_batch_bs(codes, start_date, end_date, delay=0.05)
    if quote.empty:
        logger.error("无行情数据")
        return

    # 过滤掉没有足够数据的股票
    valid_codes = []
    for c in codes:
        if len(quote[quote["code"] == c]) >= 60:
            valid_codes.append(c)
    codes = valid_codes
    quote = quote[quote["code"].isin(codes)]
    logger.info(f"有效行情: {len(quote)}条, {len(codes)}只")

    # 3. 财务
    year = int(end_date[:4]) - 1
    logger.info(f"拉取财务 ({year}Q4)...")
    financial = fetch_financial_bs(codes, year=year, quarter=4)
    logger.info(f"财务: {len(financial)}只")

    # 4. 因子引擎
    engine = FactorEngine()

    # 5. 回测循环
    capital = args.capital
    holdings = {}  # code -> {"shares": int, "buy_price": float}
    nav_history = []
    trade_log = []
    peak_nav = args.capital

    dates = sorted(quote["date"].dt.date.unique())
    rebal_dates = dates[::args.rebalance_days]

    for idx, dt in enumerate(rebal_dates):
        dt_str = dt.strftime("%Y-%m-%d")

        # 截止当日的历史数据
        hist = quote[quote["date"].dt.date <= dt]
        day = quote[quote["date"].dt.date == dt]

        if hist.empty or day.empty:
            continue

        # 当日价格表
        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

        # ── 个股止损 ──
        for code in list(holdings.keys()):
            h = holdings[code]
            if code not in prices:
                continue
            pnl = prices[code] / h["buy_price"] - 1
            if pnl <= args.stop_loss:
                val = h["shares"] * prices[code]
                capital += val
                trade_log.append({
                    "date": dt_str, "code": code, "action": "sell",
                    "price": prices[code], "shares": h["shares"],
                    "pnl": val - h["shares"] * h["buy_price"],
                    "reason": "止损",
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
        # 卖出不在目标的
        for code in list(holdings.keys()):
            if code not in target:
                h = holdings.pop(code)
                if code in prices:
                    val = h["shares"] * prices[code]
                    capital += val
                    trade_log.append({
                        "date": dt_str, "code": code, "action": "sell",
                        "price": prices[code], "shares": h["shares"],
                        "pnl": val - h["shares"] * h["buy_price"],
                    })

        # 买入新进的
        need_buy = [c for c in target if c not in holdings and c in prices]
        if need_buy and capital > 0:
            per = capital / len(need_buy)
            for code in need_buy:
                price = prices[code]
                if price <= 0:
                    continue
                shares = int(per / price / 100) * 100
                if shares > 0:
                    capital -= shares * price
                    holdings[code] = {"shares": shares, "buy_price": price}
                    trade_log.append({
                        "date": dt_str, "code": code, "action": "buy",
                        "price": price, "shares": shares, "pnl": 0,
                    })

        # ── 净值 ──
        pv = capital
        for code, h in holdings.items():
            if code in prices:
                pv += h["shares"] * prices[code]

        peak_nav = max(peak_nav, pv)
        dd = (pv / peak_nav - 1) * 100

        nav_history.append({
            "date": dt_str, "nav": pv, "cash": capital,
            "holdings": len(holdings), "dd": dd,
        })

        if (idx + 1) % 20 == 0:
            logger.info(f"{dt_str} | 净值={pv:,.0f} | 回撤={dd:.1f}%")

    # 6. 报告
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
    stop_cnt = len(sells[sells.get("reason", "").str.contains("止损", na=False)]) if not sells.empty else 0

    print("\n" + "=" * 60)
    print(f"📊 完整回测 (BaoStock + {len(engine.factor_funcs)}因子)")
    print("=" * 60)
    print(f"股票: {len(codes)}只 | Top{args.top_n} | 每{args.rebalance_days}天")
    print(f"区间: {start_date} ~ {end_date}")
    print("-" * 60)
    print(f"最终净值: ¥{nav_df['nav'].iloc[-1]:,.0f}")
    print(f"总收益:   {total_ret:+.2f}%")
    print(f"最大回撤: {max_dd:.2f}%")
    print(f"Sharpe:   {sharpe:.2f}")
    print(f"Calmar:   {calmar:.2f}")
    print(f"交易:     {len(trade_df)}笔 | 胜率: {win:.0f}% | 止损: {stop_cnt}笔")
    if len(sells) > 0:
        best = sells.loc[sells["pnl"].idxmax()]
        worst = sells.loc[sells["pnl"].idxmin()]
        print(f"最佳: {int(best['code'])} +¥{best['pnl']:,.0f}")
        print(f"最差: {int(worst['code'])} ¥{worst['pnl']:,.0f}")
    print("=" * 60)

    out = PROJECT_ROOT / "output"
    out.mkdir(exist_ok=True)
    nav_df.to_csv(out / "full_backtest_nav.csv", index=False)
    if not trade_df.empty:
        trade_df.to_csv(out / "full_backtest_trades.csv", index=False)
    logger.info("结果已保存到 output/")


if __name__ == "__main__":
    run()
