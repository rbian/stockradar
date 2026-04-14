"""回测引擎与风险管理集成补丁

在回测循环中插入风险管理检查，实现：
1. 组合回撤保护
2. 移动止损
3. 波动率仓位调整
"""

import numpy as np
import pandas as pd
from loguru import logger

from src.backtest.a_share_constraints import Position


def _prepare_quote_for_risk(daily_quote: pd.DataFrame, date: str) -> dict:
    """准备风险管理所需的数据格式

    将长格式的日线数据转换为 {code: Series} 格式
    """
    if daily_quote.empty or "date" not in daily_quote.columns:
        return {}

    dq = daily_quote.copy()
    dq["date"] = pd.to_datetime(dq["date"])
    date_ts = pd.Timestamp(date)

    # 获取截止当日的所有数据
    historical_data = dq[dq["date"] <= date_ts]

    if historical_data.empty:
        return {}

    # 按代码分组，构建 {code: Series}
    result = {}
    for code in historical_data["code"].unique():
        code_data = historical_data[historical_data["code"] == code].sort_values("date")
        if not code_data.empty:
            # 使用收盘价作为价格序列
            result[code] = code_data["close"].values

    return result


def _apply_risk_checks(self, positions: dict, data: dict, date: str,
                       current_quote: dict, all_trades: list, current_nav: float,
                       strategy_actions: list, cash: float) -> list:
    """应用风险管理检查，返回修改后的交易动作

    Args:
        positions: 当前持仓 {code: Position}
        data: 截止当日的数据
        date: 当前日期
        current_quote: 当日收盘价 {code: close}
        all_trades: 所有交易记录
        current_nav: 当前净值
        strategy_actions: 策略生成的交易动作
        cash: 可用现金

    Returns:
        合并后的交易动作列表（策略+风控）
    """
    if not hasattr(self, 'risk_manager'):
        # 如果没有初始化风险管理器，直接返回策略动作
        return strategy_actions

    # 准备数据格式
    quote_by_code = _prepare_quote_for_risk(data["daily_quote"], date)

    if not quote_by_code:
        # 无法准备数据，直接返回策略动作
        return strategy_actions

    # 生成风控动作
    risk_actions = self.risk_manager.generate_risk_actions(
        positions=positions,
        daily_quote=quote_by_code,
        date=date,
        all_trades=all_trades,
        current_nav=current_nav,
        available_cash=cash
    )

    if not risk_actions:
        return strategy_actions

    # 合并策略动作和风控动作
    # 风控动作优先级更高，需要处理冲突
    final_actions = []
    codes_to_sell = set()

    # 优先处理风控卖出/减仓动作
    for action in risk_actions:
        if action.get("action") in ["sell", "reduce"]:
            final_actions.append(action)
            codes_to_sell.add(action["code"])

    # 处理策略动作（排除已被风控卖出的代码）
    for action in strategy_actions:
        code = action.get("code")
        if code and code in codes_to_sell:
            # 该股票已被风控卖出，跳过策略动作
            logger.debug(f"[{date}] {code} 被风控卖出，跳过策略动作")
            continue
        final_actions.append(action)

    # 处理风控买入动作（使用波动率调整的仓位）
    for action in risk_actions:
        if action.get("action") == "buy":
            # 找到对应的策略买入动作，替换金额
            for i, strat_act in enumerate(final_actions):
                if (strat_act.get("action") == "buy" and
                    strat_act.get("code") == action["code"]):
                    # 用风控计算的目标金额替换策略动作
                    strat_act["target_amount"] = action.get("target_amount", strat_act.get("target_amount"))
                    strat_act["reason"] = f"{strat_act.get('reason', '')} (风控调整)"
                    break
            else:
                # 如果策略没有该买入动作，添加风控买入动作
                final_actions.append(action)

    if risk_actions:
        logger.info(
            f"[{date}] 风控检查完成: "
            f"策略动作{len(strategy_actions)}个 + 风控动作{len(risk_actions)}个 "
            f"= 最终动作{len(final_actions)}个"
        )

    return final_actions


# Monkey patch - 将函数注入到BacktestEngine类
import sys
if 'src.backtest.engine' not in sys.modules:
    # 模块还未导入，等待后续导入
    pass
else:
    # 模块已导入，直接注入
    from src.backtest import engine as engine_module
    engine_module.BacktestEngine._apply_risk_checks = _apply_risk_checks
    logger.info("Risk management integration patched into BacktestEngine")
