"""Walk-Forward验证 — 只用行情数据，不走财务

核心思路：36因子中大部分是技术因子，用行情就能算。
财务因子用已有缓存或跳过。重点是验证不同时期的稳定性。
"""

import sys
from datetime import timedelta
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from loguru import logger
import baostock as bs
from src.data.baostock_adapter import fetch_daily_quote_batch_bs
from src.factors.engine import FactorEngine
from src.infra.logger import setup_logger

CAPITAL = 1_000_000
TOP_N = 10
REBAL_DAYS = 10
STOP_LOSS = -0.18
COMM = 0.001


def backtest_period(quote, codes, engine, financial, start, end):
    sd, ed = pd.Timestamp(start), pd.Timestamp(end)
    pq = quote[(quote["date"] >= sd) & (quote["date"] <= ed)]
    if pq.empty: return None

    capital, holdings, navs, peak = CAPITAL, {}, [], CAPITAL
    for dt in sorted(pq["date"].dt.date.unique())[::REBAL_DAYS]:
        ds = dt.strftime("%Y-%m-%d")
        day = pq[pq["date"].dt.date == dt]
        if day.empty: continue
        prices = dict(zip(day["code"].tolist(), day["close"].tolist()))
        hist = quote[quote["date"].dt.date <= dt]

        # 止损
        for c in list(holdings):
            if c in prices and prices[c] > 0 and prices[c]/holdings[c]["bp"]-1 <= STOP_LOSS:
                capital += holdings.pop(c)["sh"] * prices[c] * (1-COMM)

        data = {"daily_quote": hist, "codes": codes, "financial": financial, "northbound": pd.DataFrame()}
        try: scores = engine.score_all(data, ds)
        except: continue
        target = scores.index[:TOP_N].tolist()

        for c in list(holdings):
            if c not in target:
                h = holdings.pop(c)
                if c in prices and prices[c] > 0: capital += h["sh"] * prices[c] * (1-COMM)

        need = [c for c in target if c not in holdings and c in prices and prices[c] > 0]
        if need and capital > 0:
            per = capital / len(need)
            for c in need:
                sh = int(per / prices[c] / 100) * 100
                if sh > 0:
                    cost = sh * prices[c]
                    if capital >= cost * (1+COMM):
                        capital -= cost * (1+COMM)
                        holdings[c] = {"sh": sh, "bp": prices[c]}

        pv = capital + sum(h["sh"]*prices.get(c,h["bp"]) for c,h in holdings.items() if c in prices)
        peak = max(peak, pv)
        navs.append({"date": ds, "nav": pv, "dd": pv/peak-1})
    return navs


def main():
    setup_logger()
    # 股票池
    bs.login()
    try:
        rs = bs.query_hs300_stocks()
        rows = []
        while rs.next(): rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        codes = [c.split(".")[-1] for c in df["code"].tolist()][:100]
    finally: bs.logout()

    # 行情（缓存）
    quote = fetch_daily_quote_batch_bs(codes, "20200101", "20250301", delay=0.05)
    codes = [c for c in codes if len(quote[quote["code"]==c]) >= 60]
    quote = quote[quote["code"].isin(codes)]
    logger.info(f"行情: {len(quote)}条, {len(codes)}只")

    # 财务：只用已缓存的，不主动拉
    from src.data.cache import load_financial_cache
    fin_list = []
    for y in range(2020, 2026):
        for q in [1,2,3,4]:
            f = load_financial_cache(y, q, max_age_days=9999)
            if not f.empty: fin_list.append(f)
    financial = pd.concat(fin_list, ignore_index=True) if fin_list else pd.DataFrame()
    logger.info(f"财务缓存: {len(financial)}条")

    engine = FactorEngine()
    all_dates = sorted(quote["date"].dt.date.unique())

    # 滚动窗口：12月训练 → 3月测试，步长3月
    results = []
    train_start = all_dates[0]
    while True:
        test_start = train_start + timedelta(days=360)
        test_end = test_start + timedelta(days=90)
        if test_end > all_dates[-1]: break

        ts, te = test_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")
        navs = backtest_period(quote, codes, engine, financial, ts, te)
        if navs and len(navs) > 1:
            df_n = pd.DataFrame(navs)
            ret = (df_n["nav"].iloc[-1]/CAPITAL-1)*100
            mdd = df_n["dd"].min()*100
            r = df_n["nav"].pct_change().dropna()
            sharpe = r.mean()/r.std()*(252/REBAL_DAYS)**0.5 if r.std()>0 else 0
            results.append({"period": f"{ts[:7]}~{te[:7]}", "return": ret, "mdd": mdd, "sharpe": sharpe})
            logger.info(f"{ts[:7]}~{te[:7]}: {ret:+.1f}% dd{mdd:.1f}%")

        train_start += timedelta(days=90)

    if not results:
        print("无结果"); return

    rdf = pd.DataFrame(results)
    print("\n" + "="*65)
    print("📊 Walk-Forward 验证（99只沪深300 | 12月→3月滚动）")
    print("="*65)
    for _, r in rdf.iterrows():
        flag = "🟢" if r["return"]>0 else "🔴"
        print(f"  {r['period']} {flag} {r['return']:+6.1f}% | 回撤{r['mdd']:5.1f}% | Sharpe{r['sharpe']:.2f}")
    print("-"*65)
    wins = (rdf["return"]>0).sum()
    print(f"  正收益窗口: {wins}/{len(rdf)} ({wins/len(rdf)*100:.0f}%)")
    print(f"  平均收益:   {rdf['return'].mean():+.1f}%")
    print(f"  中位收益:   {rdf['return'].median():+.1f}%")
    print(f"  最佳:       {rdf['return'].max():+.1f}%")
    print(f"  最差:       {rdf['return'].min():+.1f}%")
    print(f"  收益标准差: {rdf['return'].std():.1f}%")
    print(f"  平均Sharpe: {rdf['sharpe'].mean():.2f}")
    print("-"*65)
    wr = wins/len(rdf)*100
    if wr>=70 and rdf['return'].mean()>5:
        print("  ✅ 策略稳定性: 优秀 — 样本外表现一致")
    elif wr>=60 and rdf['return'].mean()>0:
        print("  ⚠️ 策略稳定性: 中等 — 部分窗口表现不佳")
    else:
        print("  ❌ 策略稳定性: 较差 — 可能存在过拟合")
    print("="*65)

    out = Path(PROJECT_ROOT / "output"); out.mkdir(exist_ok=True)
    rdf.to_csv(out/"walk_forward_results.csv", index=False)

if __name__ == "__main__":
    main()
