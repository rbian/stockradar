"""测试Inverse Volatility Portfolio权重分配"""
import numpy as np
import pytest
from src.risk_management.risk_manager import RiskManager


def _gbm(price, mu, sigma, n):
    """Generate GBM price series"""
    prices = [price]
    for _ in range(n):
        prices.append(prices[-1] * np.exp(np.random.normal(mu, sigma)))
    return np.array(prices)


def test_inverse_volatility_weights():
    """测试Inverse Volatility权重分配 - 低波动应获得更高权重"""
    rm = RiskManager()
    np.random.seed(42)

    daily_quote = {
        "low_vol": _gbm(100, 0.0001, 0.005, 30),
        "mid_vol": _gbm(50, 0.0001, 0.02, 30),
        "high_vol": _gbm(200, 0.0001, 0.05, 30),
    }

    weights = rm.inverse_volatility_weights(
        ["low_vol", "mid_vol", "high_vol"], daily_quote
    )

    assert len(weights) == 3
    assert abs(sum(weights.values()) - 1.0) < 0.01
    assert weights["low_vol"] > weights["high_vol"], \
        f"低波动应获得更高权重: {weights}"


def test_inverse_volatility_empty():
    rm = RiskManager()
    assert rm.inverse_volatility_weights([], {}) == {}


def test_inverse_volatility_insufficient_data():
    rm = RiskManager()
    short_prices = np.array([100.0, 101.0, 102.0])
    daily_quote = {"code1": short_prices, "code2": short_prices}
    weights = rm.inverse_volatility_weights(["code1", "code2"], daily_quote)
    assert abs(weights["code1"] - 0.5) < 0.01
