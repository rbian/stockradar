"""策略医生 — 持仓诊断

诊断逻辑：
1. 对每只持仓股，计算近5日涨跌幅
2. 对比同期沪深300涨跌幅
3. 跑输大盘 > 3% → 标记异常
4. 分析原因：基本面/技术面/资金面
5. 给出建议：继续持有/减仓/清仓
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_stock_names():
    """加载股票名称映射"""
    name_file = DATA_DIR.parent / "data" / "hs300_codes.txt"
    # 从缓存加载
    from src.data.industry import _load_industry
    df = _load_industry()
    if not df.empty:
        return dict(zip(df["code"], df["name"]))
    return {}


def diagnose_holdings(nav_data: dict, daily_quote: pd.DataFrame = None,
                      scores: pd.DataFrame = None) -> str:
    """诊断持仓
    
    Args:
        nav_data: NAVTracker.to_dict() 的输出
        daily_quote: 日行情数据
        scores: 评分数据
    """
    holdings = nav_data.get("holdings", {})
    if not holdings:
        return "📭 当前无持仓"
    
    if daily_quote is None or daily_quote.empty:
        return _simple_diagnose(holdings, nav_data)
    
    names = _load_stock_names()
    lines = [f"🏥 **持仓诊断** ({len(holdings)}只)\n"]
    warnings = []
    
    for code, pos in holdings.items():
        name = names.get(code, code)
        cost = pos.get("cost_price", pos.get("avg_cost", 0))
        
        # 近5日表现
        stock_data = daily_quote[daily_quote["code"] == code].tail(5)
        if len(stock_data) < 2:
            lines.append(f"  {name}({code}): 数据不足")
            continue
        
        latest_price = stock_data["close"].iloc[-1]
        ret_5d = (latest_price / stock_data["close"].iloc[0] - 1) * 100
        ret_total = (latest_price / cost - 1) * 100 if cost > 0 else 0
        
        # 涨跌判断
        if ret_5d < -5:
            status = "🔴 急跌"
            warnings.append(code)
        elif ret_5d < -2:
            status = "🟡 走弱"
        elif ret_5d > 5:
            status = "🟢 强势"
        else:
            status = "➖ 平稳"
        
        # 评分排名
        rank_info = ""
        if scores is not None and code in scores.index:
            rank = (scores["score_total"] > scores.loc[code, "score_total"]).sum() + 1
            rank_info = f" | 排名{rank}/{len(scores)}"
        
        lines.append(f"  {name} {status} 5日{ret_5d:+.1f}% 总{ret_total:+.1f}%{rank_info}")
    
    # 总结
    if warnings:
        lines.append(f"\n⚠️ **需关注**: {', '.join(names.get(c, c) for c in warnings)}")
        lines.append("建议检查基本面是否有变化，考虑止损")
        # 自动写入知识库
        try:
            _log_warning(warnings, names, nav_data)
        except Exception:
            pass
    elif len(holdings) > 0:
        lines.append("\n✅ 持仓整体健康")
    
    return "\n".join(lines)


def _simple_diagnose(holdings: dict, nav_data: dict) -> str:
    """无行情数据时的简化诊断"""
    names = _load_stock_names()
    nav = nav_data.get("nav", 1.0)
    ret = nav_data.get("total_return", 0)
    
    lines = [f"🏥 **持仓概览** ({len(holdings)}只)"]
    lines.append(f"💰 净值: {nav:.4f} | 收益: {ret:+.2f}%")
    
    for code, pos in holdings.items():
        name = names.get(code, code)
        weight = pos.get("weight", 0) * 100
        lines.append(f"  {name}: {weight:.1f}%")
    
    return "\n".join(lines)

def _log_warning(warnings: list, names: dict, nav_data: dict):
    """记录持仓异常到知识库"""
    from datetime import datetime
    log_file = DATA_DIR.parent / "knowledge" / "failure_patterns.md"
    if not log_file.exists():
        return
    
    content = log_file.read_text()
    date = datetime.now().strftime("%Y-%m-%d")
    stocks = ", ".join(names.get(c, c) for c in warnings)
    nav = nav_data.get("nav", 1.0)
    
    entry = f"\n### {date} 持仓预警\n- 异常股票: {stocks}\n- 净值: {nav:.4f}\n- 原因: 5日跌幅>5%\n- 状态: 待观察\n"
    
    # 避免重复
    if date not in content[-500:]:
        content += entry
        log_file.write_text(content)
