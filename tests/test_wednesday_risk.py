"""测试: 移动止盈 + Risk Parity + 相关性集中度 (2026-04-29)"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest


def test_trailing_take_profit_basic():
    """测试1: 移动止盈基本逻辑"""
    from src.risk_management.trailing_take_profit import TrailingTakeProfit
    
    ttp = TrailingTakeProfit()
    
    # 盈利5%: 不触发 (0-10%区间允许回撤到-2%)
    result = ttp.check("SH600000", 105.0, 100.0)
    assert not result["triggered"], f"盈利5%不应触发: {result}"
    
    # 盈利15%后回落到+4%: 触发 (10-20%区间锁定5%)
    result = ttp.check("SH600000", 115.0, 100.0)  # 先涨到15%
    assert not result["triggered"]
    result = ttp.check("SH600000", 104.0, 100.0)  # 回落到+4%
    assert result["triggered"], f"跌破锁定线应触发: {result}"
    assert "阶梯止盈" in result["reason"]
    
    # 清理
    ttp.remove("SH600000")
    print("✅ 测试1通过: 移动止盈基本逻辑")


def test_trailing_take_profit_high_profit():
    """测试2: 高盈利区间从峰值回撤止盈"""
    from src.risk_management.trailing_take_profit import TrailingTakeProfit
    
    ttp = TrailingTakeProfit()
    
    # 盈利35%: 峰值135
    ttp.check("SH600001", 135.0, 100.0)
    
    # 从峰值回撤8%到124.2: 应触发 (>30%区间)
    result = ttp.check("SH600001", 124.0, 100.0)
    assert result["triggered"], f"高盈利回撤应触发: {result}"
    assert "高盈利回撤" in result["reason"]
    assert result["sell_ratio"] == 1.0
    
    ttp.remove("SH600001")
    print("✅ 测试2通过: 高盈利回撤止盈")


def test_trailing_take_profit_rapid_gain():
    """测试3: 快速拉升保护"""
    from src.risk_management.trailing_take_profit import TrailingTakeProfit
    
    ttp = TrailingTakeProfit()
    
    # 近5日涨幅15%+ (快速拉升)
    recent_returns = [0.02, 0.03, 0.04, 0.02, 0.05]  # 总计16%
    
    # 先建仓，然后从高点回落
    ttp.check("SH600002", 118.0, 100.0)  # 峰值118
    result = ttp.check("SH600002", 112.0, 100.0, recent_returns)  # 回撤5.1%
    
    assert result["triggered"], f"快速拉升保护应触发: {result}"
    assert "快速拉升保护" in result["reason"]
    
    ttp.remove("SH600002")
    print("✅ 测试3通过: 快速拉升保护")


def test_risk_parity_converge():
    """测试4: Risk Parity权重收敛"""
    from src.risk_management.risk_parity import RiskParityAllocator
    
    allocator = RiskParityAllocator()
    
    # 3只股票: 低/中/高波动
    np.random.seed(42)
    low_vol = np.random.normal(0.001, 0.005, 100)    # 低波动
    mid_vol = np.random.normal(0.001, 0.015, 100)    # 中波动
    high_vol = np.random.normal(0.001, 0.03, 100)    # 高波动
    
    returns = np.array([low_vol, mid_vol, high_vol])
    codes = ["A", "B", "C"]
    
    weights = allocator.allocate(returns, codes)
    
    # 低波动应该有最高权重
    assert weights["A"] > weights["C"], f"低波动权重应>高波动: {weights}"
    # 所有权重之和应为1
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01, f"权重之和应≈1: {total}"
    # 每只股在下限以上
    for code, w in weights.items():
        assert w >= 0.04, f"{code}权重应≥5%: {w}"
    
    print(f"✅ 测试4通过: Risk Parity权重 = {weights}")


def test_risk_parity_simple():
    """测试5: 简化版Risk Parity"""
    from src.risk_management.risk_parity import RiskParityAllocator
    
    allocator = RiskParityAllocator()
    
    # 直接用波动率
    weights = allocator.allocate_simple(
        volatilities=[0.10, 0.20, 0.40],
        codes=["LOW", "MID", "HIGH"],
    )
    
    assert weights["LOW"] > weights["HIGH"]
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01, f"权重之和应≈1: {total}"
    
    print(f"✅ 测试5通过: 简化Risk Parity = {weights}")


def test_risk_parity_empty():
    """测试6: 空输入"""
    from src.risk_management.risk_parity import RiskParityAllocator
    
    allocator = RiskParityAllocator()
    result = allocator.allocate(np.array([]).reshape(0, 0))
    assert isinstance(result, np.ndarray) and len(result) == 0
    
    print("✅ 测试6通过: 空输入处理")


def test_correlation_cluster_alert():
    """测试7: 相关性集中度检查"""
    from src.simulator.risk_control import _check_correlation_clusters
    
    # Mock: 同行业4只股票，行业集中度>50%
    # 由于依赖get_industry，这里测试无行业数据时的graceful处理
    holdings = {
        "600000": {"shares": 1000, "cost_price": 10.0},
        "600001": {"shares": 1000, "cost_price": 10.0},
    }
    prices = {"600000": 10.0, "600001": 10.0}
    
    # 不应抛异常
    alerts = _check_correlation_clusters(holdings, prices)
    assert isinstance(alerts, list)
    
    print("✅ 测试7通过: 相关性集中度graceful处理")


def test_risk_control_with_trailing_tp():
    """测试8: 风控集成移动止盈"""
    from src.simulator.risk_control import check_risk
    
    # 盈利5%: 不应触发移动止盈
    holdings = {"600000": {"shares": 1000, "cost_price": 100.0}}
    prices = {"600000": 105.0}
    
    alerts = check_risk(holdings, prices, include_time_stop=False,
                        include_trailing_tp=True, include_correlation=False)
    
    # 盈利5%无风控触发
    tp_alerts = [a for a in alerts if "止盈" in a.get("reason", "")]
    assert len(tp_alerts) == 0, f"盈利5%不应触发止盈: {tp_alerts}"
    
    print("✅ 测试8通过: 风控集成移动止盈")


if __name__ == "__main__":
    test_trailing_take_profit_basic()
    test_trailing_take_profit_high_profit()
    test_trailing_take_profit_rapid_gain()
    test_risk_parity_converge()
    test_risk_parity_simple()
    test_risk_parity_empty()
    test_correlation_cluster_alert()
    test_risk_control_with_trailing_tp()
    print("\n🎉 全部8个测试通过!")
