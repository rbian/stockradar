"""测试双动量策略 + 自动调参"""

import sys
import os
import pandas as pd
import numpy as np
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_dual_momentum():
    """测试双动量策略核心逻辑"""
    from src.strategy.dual_momentum import DualMomentumStrategy
    
    strategy = DualMomentumStrategy(portfolio_size=5)
    
    # Test absolute momentum - bull
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    prices_bull = pd.DataFrame({
        "date": dates,
        "close": np.linspace(3000, 4000, 300),  # 上升趋势
    })
    result = strategy.calculate_absolute_momentum(prices_bull)
    assert result["signal"] == "bull", f"Expected bull, got {result['signal']}"
    assert result["momentum_pct"] > 0
    print(f"✅ Bull momentum: {result}")
    
    # Test absolute momentum - bear
    prices_bear = pd.DataFrame({
        "date": dates,
        "close": np.linspace(4000, 3000, 300),  # 下降趋势
    })
    result = strategy.calculate_absolute_momentum(prices_bear)
    assert result["signal"] == "bear", f"Expected bear, got {result['signal']}"
    print(f"✅ Bear momentum: {result}")
    
    # Test empty data
    result = strategy.calculate_absolute_momentum(pd.DataFrame())
    assert result["signal"] == "neutral"
    print("✅ Empty data → neutral")


def test_auto_tuner():
    """测试自动调参"""
    from src.evolution.auto_tuner import AutoTuner
    
    tuner = AutoTuner()
    
    # Test parse_suggestions
    review = {
        "date": "2026-04-20",
        "suggestions": [
            {"text": "信号门槛 75→80 (胜率太低)"},
            {"text": "止损 10%→5% (盈亏比极差)"},
            {"text": "单只上限 15%→10% (亏损集中度高)"},
            {"text": "切换防御模式"},
        ],
    }
    
    adjustments = tuner.parse_suggestions(review)
    assert len(adjustments) >= 3, f"Expected >=3 adjustments, got {len(adjustments)}"
    print(f"✅ Parsed {len(adjustments)} adjustments: {[a['param'] for a in adjustments]}")
    
    # Test validate_and_apply
    result = tuner.validate_and_apply(adjustments)
    assert len(result["applied"]) >= 3
    print(f"✅ Applied {len(result['applied'])}, Rejected {len(result['rejected'])}")
    
    # Test bounds checking - reject out of range
    bad_adj = [{"param": "signal_threshold", "value": 5, "reason": "test"}]
    result = tuner.validate_and_apply(bad_adj)
    assert len(result["rejected"]) == 1
    print("✅ Out-of-bounds rejected correctly")


if __name__ == "__main__":
    test_dual_momentum()
    test_auto_tuner()
    print("\n✅ All tests passed!")
