"""D1自进化回测 — 因子权重自适应

每N天计算一次因子IC，动态调整权重：
- IC高 → 加权
- IC低 → 减权
- 连续低IC → 暂停

对比：有进化 vs 无进化
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
from src.evolution.factor_tracker import FactorTracker
from src.infra.logger import setup_logger


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--stocks", type=int, default=50)
    p.add_argument("--start", type=str, default="20230101")
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--rebalance-days", type=int, default=10)
    p.add_argument("--evolve-days", type=int, default=20,
                   help="每N天做一次因子权重进化")
    p.add_argument("--capital", type=float, default=1000000)
    p.add_argument("--stop-loss", type=float, default=-0.18)
    p.add_argument("--commission", type=float, default=0.001)
    return p.parse_args()


def run():
    args = parse_args()
    setup_logger()

    start_date = args.start.replace("-", "")
    end_date = (args.end or datetime.now().strftime("%Y%m%d")).replace("-", "")

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

    logger.info(f"=== D1自进化回测（沪深300 {len(codes)}只） ===")

    # 2. 行情
    quote = fetch_daily_quote_batch_bs(codes, start_date, end_date, delay=0.05)
    if quote.empty:
        return
    valid = [c for c in codes if len(quote[quote["code"] == c]) >= 60]
    codes = valid
    quote = quote[quote["code"].isin(codes)]
    logger.info(f"行情: {len(quote)}条, {len(codes)}只")

    # 3. 财务
    end_year = int(end_date[:4])
    fin_list = []
    for y in [end_year - 1, end_year - 2]:
        f = fetch_financial_bs(codes, year=y, quarter=4)
        if not f.empty:
            fin_list.append(f)
    financial = pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()

    # 4. 引擎 + 进化器
    engine = FactorEngine()
    tracker = FactorTracker()

    logger.info(f"因子: {len(engine.factor_funcs)}个 | 进化周期: 每{args.evolve_days}天")

    # 5. 跑两个回测：有进化 vs 无进化
    results = {}
    for mode in ["evolved", "static"]:
        capital = args.capital
        holdings = {}
        nav_history = []
        trade_log = []
        peak_nav = args.capital

        # 进化版用新tracker，静态版不调整权重
        if mode == "evolved":
            tracker_evo = FactorTracker()
        else:
            tracker_evo = None

        dates = sorted(quote["date"].dt.date.unique())
        rebal_dates = dates[::args.rebalance_days]
        evolve_counter = 0

        for idx, dt in enumerate(rebal_dates):
            dt_str = dt.strftime("%Y-%m-%d")
            hist = quote[quote["date"].dt.date <= dt]
            day = quote[quote["date"].dt.date == dt]
            if hist.empty or day.empty:
                continue

            prices = dict(zip(day["code"].tolist(), day["close"].tolist()))

            # ── D1进化：每evolve_days天调整权重 ──
            if mode == "evolved" and tracker_evo and idx > 0 and idx % (args.evolve_days // args.rebalance_days) == 0:
                data = {
                    "daily_quote": hist, "codes": codes,
                    "financial": financial, "northbound": pd.DataFrame(),
                }
                adjustments = tracker_evo.daily_update(
                    data, dt_str, factor_engine=engine, daily_quote=quote
                )
                # 应用权重到引擎
                for fname, status in tracker_evo.factor_statuses.items():
                    if status.is_suspended:
                        engine.adjust_factor_weight(fname, 0.0)
                    else:
                        # 归一化到因子级别权重
                        engine.adjust_factor_weight(fname, status.current_weight / max(status.original_weight, 0.01))

            # ── 个股止损 ──
            for code in list(holdings.keys()):
                h = holdings[code]
                if code not in prices:
                    continue
                if prices[code] / h["buy_price"] - 1 <= args.stop_loss:
                    val = h["shares"] * prices[code]
                    fee = val * args.commission
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
                "daily_quote": hist, "codes": codes,
                "financial": financial, "northbound": pd.DataFrame(),
            }
            try:
                scores = engine.score_all(data, dt_str)
            except Exception:
                continue

            target = list(scores.head(args.top_n).index)

            # ── 调仓 ──
            for code in list(holdings.keys()):
                if code not in target:
                    h = holdings.pop(code)
                    if code in prices:
                        val = h["shares"] * prices[code]
                        fee = val * args.commission
                        capital += val - fee
                        trade_log.append({
                            "date": dt_str, "code": code, "action": "sell",
                            "price": prices[code], "shares": h["shares"],
                            "pnl": val - fee - h["shares"] * h["buy_price"],
                            "fee": fee,
                        })

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
                        fee = cost * args.commission
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

            nav_history.append({"date": dt_str, "nav": pv, "dd": dd})

        results[mode] = {
            "nav": pd.DataFrame(nav_history),
            "trades": pd.DataFrame(trade_log) if trade_log else pd.DataFrame(),
        }

        if mode == "evolved" and tracker_evo:
            results["factor_status"] = tracker_evo.get_status()

        logger.info(f"{mode} 完成: {len(nav_history)}个调仓日")

    # 6. 对比报告
    print()
    print("=" * 60)
    print("📊 D1自进化 vs 静态 对比报告")
    print("=" * 60)
    print(f"区间: {start_date} ~ {end_date} | {len(codes)}只 | Top{args.top_n}")
    print(f"进化周期: 每{args.evolve_days}天 | 手续费{args.commission:.1%}")
    print("-" * 60)

    for mode in ["static", "evolved"]:
        r = results[mode]
        nav = r["nav"]
        trades = r["trades"]
        total_ret = (nav["nav"].iloc[-1] / args.capital - 1) * 100
        max_dd = nav["dd"].min()
        rets = nav["nav"].pct_change().dropna()
        sharpe = rets.mean() / rets.std() * (252 / args.rebalance_days) ** 0.5 if rets.std() > 0 else 0
        calmar = abs(total_ret / max_dd) if max_dd != 0 else 0
        sells = trades[trades["action"] == "sell"] if not trades.empty else pd.DataFrame()
        win = (sells["pnl"] > 0).mean() * 100 if len(sells) > 0 else 0
        total_fee = trades["fee"].sum() if not trades.empty and "fee" in trades.columns else 0
        n_days = (pd.Timestamp(nav["date"].iloc[-1]) - pd.Timestamp(nav["date"].iloc[0])).days
        annual = ((nav["nav"].iloc[-1] / args.capital) ** (365 / max(n_days, 1)) - 1) * 100

        label = "🤖 进化版" if mode == "evolved" else "📊 静态版"
        print(f"\n{label}")
        print(f"  总收益: {total_ret:+.2f}%  |  年化: {annual:.2f}%")
        print(f"  最大回撤: {max_dd:.2f}%  |  Calmar: {calmar:.2f}")
        print(f"  Sharpe: {sharpe:.2f}  |  胜率: {win:.0f}%")
        print(f"  交易: {len(trades)}笔  |  手续费: ¥{total_fee:,.0f}")

    # 进化效果
    s_ret = (results["static"]["nav"]["nav"].iloc[-1] / args.capital - 1) * 100
    e_ret = (results["evolved"]["nav"]["nav"].iloc[-1] / args.capital - 1) * 100
    s_dd = results["static"]["nav"]["dd"].min()
    e_dd = results["evolved"]["nav"]["dd"].min()

    print()
    print("-" * 60)
    print(f"进化提升: 收益 {e_ret - s_ret:+.2f}% | 回撤 {e_dd - s_dd:+.2f}%")
    print("-" * 60)

    # 因子状态
    if "factor_status" in results:
        fs = results["factor_status"]
        suspended = fs[fs["is_suspended"]]
        boosted = fs[fs["current_weight"] > fs["original_weight"]]
        print(f"\n因子进化结果:")
        print(f"  活跃: {len(fs[~fs['is_suspended']])}/{len(fs)}")
        print(f"  暂停: {len(suspended)}个")
        print(f"  增权: {len(boosted)}个")
        if len(suspended) > 0:
            print(f"  暂停因子: {', '.join(suspended['factor'].tolist()[:10])}")
        if len(boosted) > 0:
            top3 = boosted.nlargest(3, "current_weight")
            for _, r in top3.iterrows():
                print(f"  最强: {r['factor']} (权重{r['current_weight']:.2f})")

    print("=" * 60)

    # 保存
    out = PROJECT_ROOT / "output"
    out.mkdir(exist_ok=True)
    for mode in ["static", "evolved"]:
        results[mode]["nav"].to_csv(out / f"d1_{mode}_nav.csv", index=False)
    logger.info("结果保存到 output/")


if __name__ == "__main__":
    run()
