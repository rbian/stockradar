"""快速回测 — 使用Yahoo Finance数据

在海外服务器上用Yahoo Finance拉取A股数据，跑一个简化版回测。
验证策略是否有效。

用法:
    python scripts/quick_backtest.py
    python scripts/quick_backtest.py --stocks 600519 000858 300750 --start 2023-01-01
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

from src.data.yahoo_adapter import fetch_daily_quote_batch_yf, fetch_stock_list_yf
from src.factors.engine import FactorEngine
from src.infra.logger import setup_logger


def parse_args():
    parser = argparse.ArgumentParser(description="快速回测")
    parser.add_argument("--stocks", nargs="+", default=None,
                        help="指定股票代码列表")
    parser.add_argument("--start", type=str, default="2024-01-01",
                        help="回测开始日期")
    parser.add_argument("--end", type=str, default=None,
                        help="回测结束日期")
    parser.add_argument("--top-n", type=int, default=5,
                        help="持仓数量")
    parser.add_argument("--rebalance-days", type=int, default=5,
                        help="调仓间隔天数")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="初始资金")
    return parser.parse_args()


def run_quick_backtest(args):
    """简化回测：每N天按评分调仓"""
    setup_logger()
    end_date = args.end or datetime.now().strftime("%Y-%m-%d")

    # 1. 确定股票池
    if args.stocks:
        codes = args.stocks
    else:
        stock_list = fetch_stock_list_yf()
        codes = stock_list["code"].tolist()

    logger.info(f"=== 快速回测 ===")
    logger.info(f"股票池: {len(codes)}只")
    logger.info(f"时间: {args.start} ~ {end_date}")
    logger.info(f"持仓: Top{args.top_n}, 每{args.rebalance_days}天调仓")
    logger.info(f"初始资金: ¥{args.capital:,.0f}")

    # 2. 拉取数据
    logger.info("正在拉取行情数据...")
    all_data = fetch_daily_quote_batch_yf(codes, args.start, end_date, delay=0.3)

    if all_data.empty:
        logger.error("没有获取到任何数据")
        return

    logger.info(f"获取到 {len(all_data)} 条行情数据")

    # 3. 计算因子（简化版 — 只用技术因子，不需要财务数据）
    engine = FactorEngine()
    dates = sorted(all_data["date"].dt.date.unique())

    # 4. 回测循环
    capital = args.capital
    holdings = {}  # code -> {shares, buy_price, buy_date}
    nav_history = []
    trade_log = []

    rebalance_dates = dates[::args.rebalance_days]

    # 风控参数（个股止损为主，不干预组合级别）
    STOP_LOSS = -0.20          # 个股止损线 -20%（硬止损，保命用）
    REDUCE_LOSS = -0.12        # 减仓线 -12%
    REDUCE_RATIO = 0.5         # 减仓比例
    CRISIS_DROP = -0.09        # 单日暴跌阈值
    CRISIS_REDUCE = 0.6        # 危机减仓比例
    MAX_DRAWDOWN_LIMIT = -0.99 # 组合级风控关闭（设极大值，不用组合级干预）

    # 追踪历史最高净值
    peak_nav = args.capital

    for i, date in enumerate(rebalance_dates):
        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")

        # 截止当日的历史数据
        hist = all_data[all_data["date"].dt.date <= date]
        if hist.empty:
            continue

        # 当日价格
        current_prices = {}
        day_data = hist[hist["date"].dt.date == date]
        for _, row in day_data.iterrows():
            current_prices[row["code"]] = row["close"]

        # ──── 风控检查（调仓前） ────

        # 1. 个股止损/减仓
        risk_sell_codes = set()
        for code, h in list(holdings.items()):
            if code not in current_prices:
                continue
            current_price = current_prices[code]
            pnl_pct = (current_price / h["buy_price"]) - 1

            if pnl_pct <= STOP_LOSS:
                # 止损清仓
                sell_value = h["shares"] * current_price
                pnl = sell_value - h["shares"] * h["buy_price"]
                capital += sell_value
                trade_log.append({
                    "date": date_str, "code": code, "action": "sell",
                    "price": current_price, "shares": h["shares"],
                    "pnl": pnl, "reason": "止损",
                })
                del holdings[code]
                logger.debug(f"⚠️ 止损: {code} {pnl_pct:.1%}")

            elif pnl_pct <= REDUCE_LOSS:
                # 减仓50%
                reduce_shares = int(h["shares"] * REDUCE_RATIO / 100) * 100
                if reduce_shares > 0:
                    sell_value = reduce_shares * current_price
                    cost_basis = reduce_shares * h["buy_price"]
                    capital += sell_value
                    h["shares"] -= reduce_shares
                    trade_log.append({
                        "date": date_str, "code": code, "action": "sell",
                        "price": current_price, "shares": reduce_shares,
                        "pnl": sell_value - cost_basis, "reason": "减仓",
                    })

        # 2. 组合回撤检查
        portfolio_value = capital
        for code, h in holdings.items():
            if code in current_prices:
                portfolio_value += h["shares"] * current_prices[code]

        peak_nav = max(peak_nav, portfolio_value)
        drawdown = (portfolio_value / peak_nav) - 1

        if drawdown <= MAX_DRAWDOWN_LIMIT:
            # 组合回撤超限，按比例减仓
            logger.warning(f"⚠️ 组合回撤 {drawdown:.1%} 超限，触发减仓")
            for code, h in list(holdings.items()):
                if code not in current_prices:
                    continue
                reduce_shares = int(h["shares"] * 0.5 / 100) * 100
                if reduce_shares > 0:
                    sell_value = reduce_shares * current_prices[code]
                    cost_basis = reduce_shares * h["buy_price"]
                    capital += sell_value
                    h["shares"] -= reduce_shares
                    trade_log.append({
                        "date": date_str, "code": code, "action": "sell",
                        "price": current_prices[code], "shares": reduce_shares,
                        "pnl": sell_value - cost_basis, "reason": "回撤减仓",
                    })

        # 3. 单日暴跌检查
        for code, h in list(holdings.items()):
            if code not in current_prices:
                continue
            prev_data = hist[(hist["code"] == code) & (hist["date"].dt.date < date)]
            if prev_data.empty:
                continue
            prev_close = prev_data.iloc[-1]["close"]
            day_drop = (current_prices[code] / prev_close) - 1
            if day_drop <= CRISIS_DROP:
                reduce_shares = int(h["shares"] * CRISIS_REDUCE / 100) * 100
                if reduce_shares > 0:
                    sell_value = reduce_shares * current_prices[code]
                    cost_basis = reduce_shares * h["buy_price"]
                    capital += sell_value
                    h["shares"] -= reduce_shares
                    trade_log.append({
                        "date": date_str, "code": code, "action": "sell",
                        "price": current_prices[code], "shares": reduce_shares,
                        "pnl": sell_value - cost_basis, "reason": "暴跌减仓",
                    })
                    logger.warning(f"⚠️ 暴跌减仓: {code} {day_drop:.1%}")

        # ──── 正常评分调仓 ────

        data_dict = {
            "daily_quote": hist,
            "codes": codes,
            "financial": pd.DataFrame(),
            "northbound": pd.DataFrame(),
        }

        try:
            scores = engine.score_all(data_dict, date_str)
            top_n = scores.head(args.top_n)
            target_codes = set(top_n.index.tolist())
        except Exception as e:
            logger.warning(f"{date_str} 评分失败: {e}")
            continue

        # 重新计算市值
        portfolio_value = capital
        for code, h in holdings.items():
            if code in current_prices:
                portfolio_value += h["shares"] * current_prices[code]

        # 调仓
        current_holdings = set(holdings.keys())
        sell_codes = current_holdings - target_codes
        buy_codes = target_codes - current_holdings

        # 卖出
        for code in sell_codes:
            if code not in holdings:
                continue
            h = holdings.pop(code)
            if code in current_prices:
                sell_value = h["shares"] * current_prices[code]
                pnl = sell_value - h["shares"] * h["buy_price"]
                capital += sell_value
                trade_log.append({
                    "date": date_str, "code": code, "action": "sell",
                    "price": current_prices[code], "shares": h["shares"],
                    "pnl": pnl,
                })

        # 买入
        if buy_codes and capital > 0:
            per_stock = capital / max(len(buy_codes), 1)
            for code in buy_codes:
                if code in current_prices and current_prices[code] > 0:
                    shares = int(per_stock / current_prices[code] / 100) * 100
                    if shares > 0:
                        cost = shares * current_prices[code]
                        capital -= cost
                        holdings[code] = {
                            "shares": shares,
                            "buy_price": current_prices[code],
                            "buy_date": date_str,
                        }
                        trade_log.append({
                            "date": date_str, "code": code, "action": "buy",
                            "price": current_prices[code], "shares": shares,
                            "pnl": 0,
                        })

        # 最终净值
        portfolio_value = capital
        for code, h in holdings.items():
            if code in current_prices:
                portfolio_value += h["shares"] * current_prices[code]

        # 记录净值
        nav_history.append({
            "date": date_str,
            "nav": portfolio_value,
            "cash": capital,
            "holdings": len(holdings),
        })

    # 5. 计算绩效
    if not nav_history:
        logger.error("没有产生任何净值记录")
        return

    nav_df = pd.DataFrame(nav_history)
    nav_df["return"] = nav_df["nav"].pct_change()
    trade_df = pd.DataFrame(trade_log)

    # 统计
    total_return = (nav_df["nav"].iloc[-1] / args.capital - 1) * 100
    max_nav = nav_df["nav"].cummax()
    drawdown = (nav_df["nav"] - max_nav) / max_nav
    max_drawdown = drawdown.min() * 100
    sharpe = nav_df["return"].mean() / nav_df["return"].std() * np.sqrt(252 / args.rebalance_days) if nav_df["return"].std() > 0 else 0

    winning_trades = trade_df[trade_df["action"] == "sell"]
    win_rate = (winning_trades["pnl"] > 0).mean() * 100 if len(winning_trades) > 0 else 0

    print("\n" + "=" * 60)
    print("📊 快速回测报告")
    print("=" * 60)
    print(f"回测区间: {args.start} ~ {end_date}")
    print(f"股票池: {len(codes)}只")
    print(f"调仓频率: 每{args.rebalance_days}天, Top{args.top_n}")
    print(f"初始资金: ¥{args.capital:,.0f}")
    print("-" * 60)
    print(f"最终净值: ¥{nav_df['nav'].iloc[-1]:,.0f}")
    print(f"总收益率: {total_return:+.2f}%")
    print(f"最大回撤: {max_drawdown:.2f}%")
    print(f"Sharpe比率: {sharpe:.2f}")
    print(f"交易次数: {len(trade_df)}笔 (买{len(trade_df[trade_df['action']=='buy'])} 卖{len(trade_df[trade_df['action']=='sell'])})")
    print(f"胜率: {win_rate:.1f}%")
    print("-" * 60)

    if not trade_df.empty:
        sells = trade_df[trade_df["action"] == "sell"].sort_values("pnl")
        if len(sells) > 0:
            best = sells.iloc[-1]
            worst = sells.iloc[0]
            print(f"最佳交易: {best['code']} +¥{best['pnl']:,.0f}")
            print(f"最差交易: {worst['code']} ¥{worst['pnl']:,.0f}")

    print("=" * 60)

    # 保存结果
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    nav_df.to_csv(output_dir / "quick_backtest_nav.csv", index=False)
    trade_df.to_csv(output_dir / "quick_backtest_trades.csv", index=False)
    logger.info(f"结果已保存到 output/")


if __name__ == "__main__":
    args = parse_args()
    run_quick_backtest(args)
