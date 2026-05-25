#!/usr/bin/env python3
"""因子IC分析 — 找出哪些因子有效，哪些有害

对每个因子单独计算IC（信息系数）和分位收益
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from loguru import logger
from src.factors.engine import FactorEngine

def analyze_factor_ic(daily_quote: pd.DataFrame, start_date: str = "2025-10-01", end_date: str = "2026-03-31"):
    """分析每个因子的IC和分位收益"""
    
    # 过滤日期范围
    df = daily_quote.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))]
    
    trading_dates = sorted(df["date"].unique())
    codes = sorted(df["code"].unique())
    logger.info(f"分析区间: {start_date} ~ {end_date}, {len(trading_dates)}交易日, {len(codes)}股票")
    
    # 创建因子引擎
    engine = FactorEngine()
    
    # 因子列表
    all_factors = []
    for cat_name, cat_config in engine.config["categories"].items():
        for factor_name in cat_config.get("factors", {}).keys():
            all_factors.append((cat_name, factor_name))
    
    logger.info(f"共 {len(all_factors)} 个因子待分析")
    
    # 按rebalance_days分组日期
    rebalance_days = 10
    rebalance_dates = trading_dates[::rebalance_days]
    
    # 存储因子值和未来收益
    factor_values = {fn: [] for _, fn in all_factors}
    future_returns = []
    factor_dates = []
    
    # 构建价格表
    price_pivot = df.pivot_table(index="date", columns="code", values="close")
    
    # 加载财务数据（循环外，只需加载一次）
    from src.data.cache import load_financial_cache, load_growth_cache
    financial_data = pd.DataFrame()
    for y, q in [(2024,4),(2024,3),(2024,2),(2024,1),(2023,4),(2023,3)]:
        f = load_financial_cache(y, q, max_age_days=9999)
        if not f.empty:
            financial_data = pd.concat([financial_data, f], ignore_index=True)
    growth = load_growth_cache(2024, 4, max_age_days=9999)
    if not growth.empty and not financial_data.empty:
        g_map = dict(zip(growth["code"], growth["YOYNI"]))
        financial_data["profit_yoy"] = financial_data["code"].map(g_map).mul(100).fillna(financial_data["profit_yoy"])
    logger.info(f"财务数据: {len(financial_data)}条")

    for i, date in enumerate(rebalance_dates):
        date_str = str(date.date()) if hasattr(date, "date") else str(date)
        date_idx = trading_dates.index(date)
        
        # 计算未来5日/10日收益
        if date_idx + 10 >= len(trading_dates):
            continue
        
        future_date_5 = trading_dates[date_idx + 5] if date_idx + 5 < len(trading_dates) else trading_dates[-1]
        future_date_10 = trading_dates[date_idx + 10] if date_idx + 10 < len(trading_dates) else trading_dates[-1]
        
        # 截取历史数据
        hist_data = df[df["date"] <= date]
        data = {"daily_quote": hist_data, "codes": codes, "financial": financial_data}
        
        # 逐因子计算
        try:
            # 先计算所有因子
            raw_values = {}
            for cat_name, factor_name in all_factors:
                factor_config = engine.config["categories"][cat_name]["factors"][factor_name]
                if factor_config.get("_suspended", False):
                    factor_values[factor_name].append(np.nan)
                    continue
                
                func = engine.factor_funcs.get(factor_name)
                if func is None:
                    factor_values[factor_name].append(np.nan)
                    continue
                
                try:
                    vals = func(data)
                    if vals is None or vals.empty:
                        factor_values[factor_name].append(np.nan)
                        continue
                    
                    # 标准化（和引擎一样）
                    clip_range = factor_config.get("clip")
                    if clip_range and clip_range[0] is not None:
                        vals = vals.clip(*clip_range)
                    
                    std = vals.std()
                    if std == 0 or pd.isna(std):
                        normalized = pd.Series(0.0, index=vals.index)
                    else:
                        normalized = (vals - vals.mean()) / std
                    
                    invert = factor_config.get("invert", False)
                    if invert or factor_config.get("direction") == "lower_better":
                        normalized = -normalized
                    
                    # 存储每只股票的因子值
                    factor_values[factor_name].append(normalized)
                except:
                    factor_values[factor_name].append(np.nan)
            
            # 计算未来收益
            today_prices = price_pivot.loc[date]
            future5_prices = price_pivot.loc[future_date_5] if future_date_5 in price_pivot.index else today_prices
            future10_prices = price_pivot.loc[future_date_10] if future_date_10 in price_pivot.index else today_prices
            
            ret5 = (future5_prices / today_prices - 1).fillna(0)
            ret10 = (future10_prices / today_prices - 1).fillna(0)
            
            future_returns.append({"ret5": ret5, "ret10": ret10})
            factor_dates.append(date_str)
            
        except Exception as e:
            logger.warning(f"因子计算失败 {date_str}: {e}")
            continue
        
        if (i + 1) % 5 == 0:
            logger.info(f"  进度 {i+1}/{len(rebalance_dates)}")
    
    # 计算IC
    logger.info("计算IC...")
    results = []
    
    for cat_name, factor_name in all_factors:
        vals_list = factor_values[factor_name]
        ic5_list = []
        ic10_list = []
        ir_list = []  # 信息比率
        
        for j in range(len(vals_list)):
            vals = vals_list[j]
            if vals is None or isinstance(vals, float) and np.isnan(vals):
                continue
            
            ret5 = future_returns[j]["ret5"]
            ret10 = future_returns[j]["ret10"]
            
            # 对齐
            common = vals.index.intersection(ret5.index)
            if len(common) < 20:
                continue
            
            v = vals.loc[common].fillna(0).values
            r5 = ret5.loc[common].values
            r10 = ret10.loc[common].values
            
            ic5 = np.corrcoef(v, r5)[0, 1] if np.std(v) > 0 and np.std(r5) > 0 else 0
            ic10 = np.corrcoef(v, r10)[0, 1] if np.std(v) > 0 and np.std(r10) > 0 else 0
            
            if not np.isnan(ic5):
                ic5_list.append(ic5)
            if not np.isnan(ic10):
                ic10_list.append(ic10)
        
        avg_ic5 = np.mean(ic5_list) if ic5_list else 0
        avg_ic10 = np.mean(ic10_list) if ic10_list else 0
        ic_std5 = np.std(ic5_list) if ic5_list else 1
        ic_std10 = np.std(ic10_list) if ic10_list else 1
        ir5 = avg_ic5 / ic_std5 if ic_std5 > 0 else 0
        ir10 = avg_ic10 / ic_std10 if ic_std10 > 0 else 0
        
        results.append({
            "category": cat_name,
            "factor": factor_name,
            "ic5": avg_ic5,
            "ic10": avg_ic10,
            "ir5": ir5,
            "ir10": ir10,
            "samples": len(ic5_list),
            "positive_pct_5": sum(1 for x in ic5_list if x > 0) / len(ic5_list) * 100 if ic5_list else 0,
        })
    
    return pd.DataFrame(results)


def main():
    print("=" * 70)
    print("StockRadar 因子IC分析")
    print("=" * 70)
    
    # 加载数据
    parquet_path = Path(__file__).parent.parent / "data" / "parquet" / "hs300_daily.parquet"
    daily_quote = pd.read_parquet(parquet_path)
    daily_quote["date"] = pd.to_datetime(daily_quote["date"])
    
    # 分析2025-10后的因子IC
    results = analyze_factor_ic(daily_quote, "2025-10-01", "2026-03-31")
    
    if results.empty:
        print("无分析结果")
        return
    
    # 排序
    results = results.sort_values("ic10", ascending=True)
    
    # 输出
    print(f"\n{'='*70}")
    print(f"因子IC排名 (2025-10 ~ 2026-03, {results['samples'].iloc[0]}期)")
    print(f"{'='*70}")
    
    print(f"\n{'排名':>4} {'类别':<16} {'因子名':<28} {'IC5':>7} {'IC10':>7} {'IR5':>7} {'IR10':>7} {'正IC%':>6} {'评价':>6}")
    print("-" * 95)
    
    rank = 1
    for _, row in results.iterrows():
        ic10 = row["ic10"]
        ic5 = row["ic5"]
        
        if ic10 > 0.03:
            verdict = "✅强"
        elif ic10 > 0.01:
            verdict = "✅弱"
        elif ic10 > -0.01:
            verdict = "⚠️无"
        elif ic10 > -0.03:
            verdict = "❌弱"
        else:
            verdict = "❌强"
        
        print(f"{rank:>4} {row['category']:<16} {row['factor']:<28} {ic5:>+7.4f} {ic10:>+7.4f} {row['ir5']:>+7.3f} {row['ir10']:>+7.3f} {row['positive_pct_5']:>5.1f}% {verdict:>6}")
        rank += 1
    
    # 分类汇总
    print(f"\n{'='*70}")
    print(f"类别汇总")
    print(f"{'='*70}")
    
    for cat in results["category"].unique():
        cat_data = results[results["category"] == cat]
        avg_ic10 = cat_data["ic10"].mean()
        avg_ir10 = cat_data["ir10"].mean()
        good = len(cat_data[cat_data["ic10"] > 0.01])
        bad = len(cat_data[cat_data["ic10"] < -0.01])
        total = len(cat_data)
        
        print(f"\n{cat} (平均IC10={avg_ic10:+.4f}, IR10={avg_ir10:+.3f})")
        print(f"  有效(✅): {good}/{total}, 有害(❌): {bad}/{total}")
        
        # 列出有害因子
        harmful = cat_data[cat_data["ic10"] < -0.01].sort_values("ic10")
        if not harmful.empty:
            print(f"  建议暂停的因子:")
            for _, row in harmful.iterrows():
                print(f"    ❌ {row['factor']}: IC10={row['ic10']:+.4f}")
        
        # 列出有效因子
        useful = cat_data[cat_data["ic10"] > 0.01].sort_values("ic10", ascending=False)
        if not useful.empty:
            print(f"  保留的有效因子:")
            for _, row in useful.iterrows():
                print(f"    ✅ {row['factor']}: IC10={row['ic10']:+.4f}")
    
    # 推荐操作
    print(f"\n{'='*70}")
    print(f"🎯 推荐操作")
    print(f"{'='*70}")
    
    harmful_factors = results[results["ic10"] < -0.02]
    if not harmful_factors.empty:
        print(f"\n建议暂停的因子 ({len(harmful_factors)}个, IC10 < -0.02):")
        for _, row in harmful_factors.iterrows():
            print(f"  ❌ {row['category']}/{row['factor']}: IC10={row['ic10']:+.4f}")
    
    neutral_factors = results[(results["ic10"] >= -0.02) & (results["ic10"] <= 0.01)]
    if not neutral_factors.empty:
        print(f"\n建议降权的因子 ({len(neutral_factors)}个, -0.02 ≤ IC10 ≤ 0.01):")
        for _, row in neutral_factors.iterrows():
            print(f"  ⚠️ {row['category']}/{row['factor']}: IC10={row['ic10']:+.4f}")


if __name__ == "__main__":
    main()
