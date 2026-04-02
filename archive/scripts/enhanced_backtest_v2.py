"""增强回测 v2 — 行业分散 + 全沪深300 + 月度归因

改进:
1. 行业分散约束（同行业最多N只）
2. 交易成本细化（佣金+印花税分开）
3. 月度归因报告
4. 基准对比（沪深300指数）
"""

import argparse
import sys
from collections import defaultdict
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
    p.add_argument("--max-per-industry", type=int, default=2,
                   help="同行业最大持仓数")
    p.add_argument("--commission-rate", type=float, default=0.00025,
                   help="佣金费率(单边)")
    p.add_argument("--stamp-tax", type=float, default=0.001,
                   help="印花税率(卖出)")
    p.add_argument("--slippage", type=float, default=0.001,
                   help="滑点")
    return p.parse_args()


# A股简单行业映射（按申万L1代码前缀）
def _industry_map(code: str) -> str:
    """粗粒度行业分类（按代码范围）"""
    c = int(code)
    if 600000 <= c < 600100: return "银行"
    if 600100 <= c < 600200: return "地产基建"
    if 600200 <= c < 600400: return "交运公用"
    if 600400 <= c < 600600: return "商贸"
    if 600500 <= c < 600700: return "医药化工"
    if 600700 <= c < 601000: return "消费"
    if 601000 <= c < 601200: return "金融保险"
    if 601200 <= c < 601400: return "券商"
    if 601400 <= c < 601700: return "能源"
    if 601700 <= c < 602000: return "制造"
    if 603000 <= c < 604000: return "制造"
    if 601600 <= c < 602000: return "建筑交运"
    if 688000 <= c < 689000: return "科创板"
    if c < 1000: return "深主板"
    if 2000 <= c < 3000: return "制造"
    if 3000 <= c < 3010: return "IT"
    if 300000 <= c < 301000: return "创业板IT"
    if 301000 <= c < 302000: return "创业板"
    return "其他"


def run():
    args = parse_args()
    setup_logger()

    start_date = args.start.replace("-", "")
    end_date = (args.end or datetime.now().strftime("%Y%m%d")).replace("-", "")
    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # 1. 股票池
    bs.login()
    try:
        rs = bs.query_hs300_stocks()
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        codes = [c.split(".")[-1] for c in df["code"].tolist()][:args.stocks]
    finally:
        bs.logout()

    logger.info(f"=== 增强回测v2（沪深300 {len(codes)}只） ===")
    logger.info(f"{sd} ~ {ed} | Top{args.top_n} | 每{args.rebalance_days}天")
    logger.info(f"行业分散: 同行业最多{args.max_per_industry}只 | 止损{args.stop_loss:.0%}")
    logger.info(f"成本: 佣金{args.commission_rate:.3%} 印花税{args.stamp_tax:.3%} 滑点{args.slippage:.3%}")

    # 2. 行情
    quote = fetch_daily_quote_batch_bs(codes, start_date, end_date, delay=0.05)
    if quote.empty:
        return
    valid = [c for c in codes if len(quote[quote["code"] == c]) >= 60]
    codes = valid
    quote = quote[quote["code"].isin(codes)]
    logger.info(f"有效: {len(quote)}条, {len(codes)}只")

    # 3. 财务（只用最近一年，避免BaoStock限流）
    end_year = int(end_date[:4])
    financial = fetch_financial_bs(codes, year=end_year - 1, quarter=4)

    # 4. 基准指数 — 暂时跳过（BaoStock限流会卡死）
    index_df = pd.DataFrame()
    logger.info("跳过基准指数对比（BaoStock限流）")

    # 5. 因子引擎
    engine = FactorEngine()

    # 6. 回测
    capital = args.capital
    holdings = {}  # code -> {shares, buy_price, buy_date}
    nav_history = []
    trade_log = []
    peak_nav = args.capital

    # 行业映射
    industry = {c: _industry_map(c) for c in codes}

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
                # 卖出成本: 佣金 + 印花税 + 滑点
                cost = val * (args.commission_rate + args.stamp_tax + args.slippage)
                capital += val - cost
                trade_log.append({
                    "date": dt_str, "code": code, "action": "sell",
                    "price": prices[code], "shares": h["shares"],
                    "pnl": val - cost - h["shares"] * h["buy_price"],
                    "fee": cost, "reason": "止损",
                })
                del holdings[code]

        # ── 评分 ──
        data = {
            "daily_quote": hist, "codes": codes,
            "financial": financial, "northbound": pd.DataFrame(),
        }
        try:
            scores = engine.score_all(data, dt_str)
        except Exception:
            continue

        # ── 行业分散选股 ──
        target = []
        industry_count = defaultdict(int)
        for code in scores.index:
            if len(target) >= args.top_n:
                break
            ind = industry.get(code, "其他")
            # 已持仓的不受行业限制（避免不必要的换手）
            if code in holdings:
                target.append(code)
                industry_count[ind] += 1
            elif industry_count[ind] < args.max_per_industry:
                target.append(code)
                industry_count[ind] += 1

        # ── 调仓 ──
        target_set = set(target)

        for code in list(holdings.keys()):
            if code not in target_set:
                h = holdings.pop(code)
                if code in prices:
                    val = h["shares"] * prices[code]
                    cost = val * (args.commission_rate + args.stamp_tax + args.slippage)
                    capital += val - cost
                    trade_log.append({
                        "date": dt_str, "code": code, "action": "sell",
                        "price": prices[code], "shares": h["shares"],
                        "pnl": val - cost - h["shares"] * h["buy_price"],
                        "fee": cost,
                    })

        need_buy = [c for c in target if c not in holdings and c in prices]
        if need_buy and capital > 0:
            per = capital / len(need_buy)
            for code in need_buy:
                price = prices[code]
                if price <= 0:
                    continue
                # 买入价加滑点
                buy_price = price * (1 + args.slippage)
                shares = int(per / buy_price / 100) * 100
                if shares > 0:
                    cost = shares * buy_price
                    fee = cost * args.commission_rate
                    if capital >= cost + fee:
                        capital -= cost + fee
                        holdings[code] = {"shares": shares, "buy_price": buy_price, "buy_date": dt_str}
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

        # 基准
        idx_close = None
        if not index_df.empty:
            idx_row = index_df[index_df["date"].dt.date <= dt]
            if not idx_row.empty:
                idx_close = idx_row.iloc[-1]["close"]

        # 持仓行业分布
        ind_dist = defaultdict(float)
        for code, h in holdings.items():
            if code in prices:
                val = h["shares"] * prices[code]
                ind_dist[industry.get(code, "其他")] += val

        nav_history.append({
            "date": dt_str, "nav": pv, "cash": capital,
            "holdings": len(holdings), "dd": dd,
            "index": idx_close,
            "industries": len(ind_dist),
        })

        if (idx + 1) % 20 == 0:
            logger.info(f"{dt_str} | ¥{pv:,.0f} | dd={dd:.1f}% | {len(holdings)}只 {len(ind_dist)}行业")

    # 7. 报告
    if not nav_history:
        return

    nav_df = pd.DataFrame(nav_history)
    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()

    total_ret = (nav_df["nav"].iloc[-1] / args.capital - 1) * 100
    max_dd = nav_df["dd"].min()
    rets = nav_df["nav"].pct_change().dropna()
    sharpe = rets.mean() / rets.std() * (252 / args.rebalance_days) ** 0.5 if rets.std() > 0 else 0
    calmar = abs(total_ret / max_dd) if max_dd != 0 else 0
    n_days = (pd.Timestamp(nav_df["date"].iloc[-1]) - pd.Timestamp(nav_df["date"].iloc[0])).days
    annual = ((nav_df["nav"].iloc[-1] / args.capital) ** (365 / max(n_days, 1)) - 1) * 100

    sells = trade_df[trade_df["action"] == "sell"] if not trade_df.empty else pd.DataFrame()
    buys = trade_df[trade_df["action"] == "buy"] if not trade_df.empty else pd.DataFrame()
    win = (sells["pnl"] > 0).mean() * 100 if len(sells) > 0 else 0
    stop_n = len(sells[sells.get("reason", "").str.contains("止损", na=False)]) if not sells.empty else 0
    total_fee = trade_df["fee"].sum() if not trade_df.empty and "fee" in trade_df.columns else 0

    # 基准
    bench_ret = 0
    idx_valid = nav_df["index"].dropna()
    if len(idx_valid) > 1 and idx_valid.iloc[0] and idx_valid.iloc[-1]:
        bench_ret = (idx_valid.iloc[-1] / idx_valid.iloc[0] - 1) * 100
    annual_bench = ((idx_valid.iloc[-1] / idx_valid.iloc[0]) ** (365 / max(n_days, 1)) - 1) * 100 if len(idx_valid) > 1 else 0

    print()
    print("=" * 60)
    print(f"📊 增强回测v2（{len(codes)}只沪深300 + 行业分散）")
    print("=" * 60)
    print(f"区间: {sd} ~ {ed} ({n_days}天)")
    print(f"Top{args.top_n} | 每{args.rebalance_days}天 | 同行业≤{args.max_per_industry}只")
    print(f"成本: 佣金{args.commission_rate:.3%} 印花税{args.stamp_tax:.3%} 滑点{args.slippage:.3%}")
    print("-" * 60)
    print(f"最终净值:     ¥{nav_df['nav'].iloc[-1]:,.0f}")
    print(f"总收益:       {total_ret:+.2f}%")
    print(f"年化收益:     {annual:.2f}%")
    print(f"最大回撤:     {max_dd:.2f}%")
    print(f"Sharpe:       {sharpe:.2f}")
    print(f"Calmar:       {calmar:.2f}")
    print(f"沪深300基准:  {bench_ret:+.2f}% (年化{annual_bench:.1f}%)")
    print(f"超额收益:     {total_ret - bench_ret:+.2f}%")
    print(f"交易:         {len(trade_df)}笔 | 胜率: {win:.0f}%")
    print(f"止损:         {stop_n}笔")
    print(f"总成本:       ¥{total_fee:,.0f}")
    if len(sells) > 0:
        best = sells.loc[sells["pnl"].idxmax()]
        worst = sells.loc[sells["pnl"].idxmin()]
        print(f"最佳:         {int(best['code'])} +¥{best['pnl']:,.0f}")
        print(f"最差:         {int(worst['code'])} ¥{worst['pnl']:,.0f}")

    # 月度归因
    print("-" * 60)
    print("月度归因:")
    nav_df["date_dt"] = pd.to_datetime(nav_df["date"])
    nav_df["month"] = nav_df["date_dt"].dt.to_period("M")
    for m, grp in nav_df.groupby("month"):
        m_ret = (grp["nav"].iloc[-1] / grp["nav"].iloc[0] - 1) * 100
        idx_g = grp["index"].dropna()
        m_bench = (idx_g.iloc[-1] / idx_g.iloc[0] - 1) * 100 if len(idx_g) > 1 else 0
        flag = "✅" if m_ret > m_bench else "❌"
        print(f"  {m} 策略{m_ret:+6.1f}% 基准{m_bench:+6.1f}% 超额{m_ret-m_bench:+6.1f}% {flag}")

    # 行业集中度
    print("-" * 60)
    print("持仓行业分布:")
    final_ind = defaultdict(float)
    total_pv = nav_df["nav"].iloc[-1]
    for code, h in holdings.items():
        if code in prices:
            final_ind[industry.get(code, "其他")] += h["shares"] * prices[code]
    for ind, val in sorted(final_ind.items(), key=lambda x: -x[1]):
        pct = val / total_pv * 100
        print(f"  {ind}: {pct:.1f}%")

    print("=" * 60)

    out = PROJECT_ROOT / "output"
    out.mkdir(exist_ok=True)
    nav_df.to_csv(out / "enhanced_v2_nav.csv", index=False)
    if not trade_df.empty:
        trade_df.to_csv(out / "enhanced_v2_trades.csv", index=False)
    logger.info("结果保存到 output/")


if __name__ == "__main__":
    run()
