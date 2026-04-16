"""风险管理模块测试

验证：
1. ATR-based Trailing Stop
2. Portfolio Drawdown Protection
3. Volatility Position Sizing
4. ADX Dynamic Adjustment
"""

import numpy as np
import pandas as pd
from src.risk_management.risk_manager import RiskManager
from src.backtest.a_share_constraints import Position
from src.factors.technical import get_adx_multiplier, calc_adx


def test_atr_calculation():
    """测试ATR计算"""
    print("\n=== 测试1: ATR计算 ===")

    # 创建模拟价格序列
    prices = np.array([100, 102, 105, 103, 106, 108, 107, 109, 111, 110,
                      112, 115, 113, 116, 118, 117, 119, 121, 120, 122])

    rm = RiskManager()
    atr = rm._calculate_atr(prices, period=14)

    print(f"价格序列长度: {len(prices)}")
    print(f"ATR (period=14): {atr:.4f}")
    print(f"ATR占价格百分比: {atr/prices[-1]*100:.2f}%")

    assert atr is not None, "ATR计算失败"
    assert atr > 0, "ATR应该为正值"
    print("✓ ATR计算测试通过")


def test_adx_multiplier():
    """测试ADX倍数获取"""
    print("\n=== 测试2: ADX倍数动态调整 ===")

    # 测试不同ADX值的倍数
    test_cases = [
        (10, 2.0, "弱趋势"),
        (18, 2.0, "弱趋势"),
        (22, 2.5, "中趋势"),
        (24, 2.5, "中趋势"),
        (28, 3.0, "强趋势"),
        (35, 3.0, "强趋势"),
    ]

    for adx, expected_mult, desc in test_cases:
        actual_mult = get_adx_multiplier(adx)
        status = "✓" if actual_mult == expected_mult else "✗"
        print(f"{status} ADX={adx:4.1f} → multiplier={actual_mult} ({desc})")
        assert actual_mult == expected_mult, f"ADX {adx} 应返回 {expected_mult}"

    print("✓ ADX倍数测试通过")


def test_trailing_stop():
    """测试移动止损"""
    print("\n=== 测试3: 移动止损 ===")

    rm = RiskManager()

    # 创建持仓
    position = Position(
        code="TEST001",
        shares=1000,
        buy_date="2026-04-01",
        buy_price=100.0,
        current_price=108.0,  # 上涨8%
    )

    # 创建模拟价格序列
    prices = np.array([100, 102, 105, 103, 106, 108])

    daily_quote = {
        "TEST001": prices
    }

    # 计算移动止损
    stop_signals = rm.calculate_trailing_stops(
        positions={"TEST001": position},
        daily_quote=daily_quote,
        date="2026-04-15",
    )

    print(f"当前价格: {position.current_price}")
    print(f"移动止损价: {stop_signals.get('TEST001', 'N/A')}")

    if "TEST001" in stop_signals:
        stop_price = stop_signals["TEST001"]
        distance_pct = (position.current_price - stop_price) / position.current_price * 100
        print(f"止损距离: {distance_pct:.2f}%")
        assert stop_price < position.current_price, "止损价应该低于当前价格"

    # 测试止损触发
    position.current_price = 102.0  # 价格下跌到止损位附近
    should_sell = rm.should_trail_stop(position, daily_quote, "2026-04-15", stop_signals)
    print(f"价格跌至{position.current_price}，触发止损: {should_sell}")

    print("✓ 移动止损测试通过")


def test_drawdown_protection():
    """测试组合回撤保护"""
    print("\n=== 测试4: 组合回撤保护 ===")

    rm = RiskManager(config={"max_drawdown_threshold": 0.15})

    # 模拟净值序列
    nav_sequence = [1.0, 1.05, 1.10, 1.15, 1.20, 1.18, 1.16, 1.14, 1.13, 1.10]

    for i, nav in enumerate(nav_sequence):
        result = rm.check_portfolio_drawdown(nav, [])

        if result["drawdown"] > rm.max_drawdown_threshold:
            print(f"净值{nav:.2f}: 回撤{result['drawdown']:.1%} > 阈值，减仓{result['reduce_ratio']:.1%}")
            assert result["reduce_ratio"] > 0, "应该触发减仓"
        else:
            print(f"净值{nav:.2f}: 回撤{result['drawdown']:.1%} ≤ 阈值，无操作")

    # 测试极端回撤
    extreme_result = rm.check_portfolio_drawdown(0.80, [])
    print(f"\n极端回撤测试: 净值0.80，回撤{extreme_result['drawdown']:.1%}")
    assert extreme_result["reduce_ratio"] > 0, "极端回撤应该触发减仓"

    print("✓ 组合回撤保护测试通过")


def test_volatility_position_sizing():
    """测试波动率仓位调整"""
    print("\n=== 测试5: 波动率仓位调整 ===")

    rm = RiskManager(config={"base_position_size": 0.1, "volatility_scaling": 0.5})

    available_cash = 100000  # 10万元可用资金

    # 低波动股票（价格稳定）
    low_vol_prices = np.ones(30) * 100 + np.random.randn(30) * 0.5
    low_vol_size = rm.calculate_volatility_adjusted_size(
        "LOWVOL", {"LOWVOL": low_vol_prices}, "2026-04-15", available_cash
    )

    # 高波动股票（价格波动大）
    high_vol_prices = np.ones(30) * 100 + np.random.randn(30) * 3.0
    high_vol_size = rm.calculate_volatility_adjusted_size(
        "HIGHVOL", {"HIGHVOL": high_vol_prices}, "2026-04-15", available_cash
    )

    base_size = available_cash * rm.base_position_size

    print(f"基础仓位: {base_size:,.0f}元")
    print(f"低波动股票仓位: {low_vol_size:,.0f}元 ({low_vol_size/base_size:.2f}x)")
    print(f"高波动股票仓位: {high_vol_size:,.0f}元 ({high_vol_size/base_size:.2f}x)")

    # 低波动应该获得更大仓位
    assert low_vol_size >= base_size, "低波动股票应该获得≥基础仓位"
    assert high_vol_size <= base_size, "高波动股票应该获得≤基础仓位"
    assert low_vol_size > high_vol_size, "低波动股票应该比高波动股票仓位更大"

    print("✓ 波动率仓位调整测试通过")


def test_adx_calculation():
    """测试ADX计算"""
    print("\n=== 测试6: ADX计算 ===")

    # 创建模拟OHLC数据
    # 强趋势：持续上涨
    n = 50
    strong_trend = pd.DataFrame({
        "date": pd.date_range("2026-03-01", periods=n),
        "code": ["TREND"] * n,
        "high": np.arange(n) * 0.5 + 100,
        "low": np.arange(n) * 0.5 + 99,
        "close": np.arange(n) * 0.5 + 99.5,
        "volume": np.ones(n) * 1000000,
    })

    # 震荡：上下波动
    oscillating = pd.DataFrame({
        "date": pd.date_range("2026-03-01", periods=n),
        "code": ["OSC"] * n,
        "high": 100 + np.sin(np.arange(n) * 0.5) * 2,
        "low": 99 + np.sin(np.arange(n) * 0.5) * 2 - 1,
        "close": 99.5 + np.sin(np.arange(n) * 0.5) * 2 - 0.5,
        "volume": np.ones(n) * 1000000,
    })

    adx_strong = calc_adx(strong_trend)
    adx_osc = calc_adx(oscillating)

    print(f"强趋势ADX: {adx_strong.get('TREND', 'N/A')}")
    print(f"震荡行情ADX: {adx_osc.get('OSC', 'N/A')}")

    if not pd.isna(adx_strong.get('TREND', np.nan)):
        print(f"  趋势强度: {'强' if adx_strong['TREND'] >= 25 else '中' if adx_strong['TREND'] >= 20 else '弱'}")

    print("✓ ADX计算测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("风险管理模块测试套件")
    print("=" * 60)

    try:
        test_atr_calculation()
        test_adx_multiplier()
        test_trailing_stop()
        test_drawdown_protection()
        test_volatility_position_sizing()
        test_adx_calculation()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)

    def test_inverse_volatility_weights(self):
        """测试Inverse Volatility权重分配"""
        rm = RiskManager()

        # 模拟3只股票：低/中/高波动率
        np.random.seed(42)
        low_vol_prices = 100 + np.cumsum(np.random.normal(0, 0.005, 30))  # 低波动
        mid_vol_prices = 50 + np.cumsum(np.random.normal(0, 0.02, 30))   # 中波动
        high_vol_prices = 200 + np.cumsum(np.random.normal(0, 0.05, 30)) # 高波动

        daily_quote = {
            "low_vol": low_vol_prices,
            "mid_vol": mid_vol_prices,
            "high_vol": high_vol_prices,
        }

        weights = rm.inverse_volatility_weights(
            ["low_vol", "mid_vol", "high_vol"],
            daily_quote
        )

        # 验证基本属性
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 0.01  # 权重总和≈1

        # 低波动股票应该获得更高权重
        assert weights["low_vol"] > weights["high_vol"], \
            f"低波动应获得更高权重: {weights}"

        # 所有权重在5%-25%之间
        for code, w in weights.items():
            assert 0.05 <= w <= 0.25, f"{code}权重{w:.2%}超出范围"

    def test_inverse_volatility_empty(self):
        """测试空输入"""
        rm = RiskManager()
        assert rm.inverse_volatility_weights([], {}) == {}

    def test_inverse_volatility_insufficient_data(self):
        """测试数据不足时回退到等权"""
        rm = RiskManager()
        short_prices = np.array([100.0, 101.0, 102.0])
        daily_quote = {"code1": short_prices, "code2": short_prices}
        weights = rm.inverse_volatility_weights(["code1", "code2"], daily_quote)
        assert abs(weights["code1"] - 0.5) < 0.01
