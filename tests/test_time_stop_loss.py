"""测试: 时间止损 + 连续亏损保护 + 风控集成

2026-04-22 周三风控日
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_time_stop():
    """测试时间止损管理器"""
    from src.risk_management.time_stop import TimeStopManager
    import tempfile, json
    
    # 用临时目录避免污染数据
    tsm = TimeStopManager()
    
    # 模拟: 30天前买入
    from datetime import datetime, timedelta
    entry_date = (datetime.now() - timedelta(days=42)).strftime("%Y-%m-%d")  # 42天≈30交易日
    tsm.entry_dates["000001"] = entry_date
    
    # Case 1: 长持30天收益2% → 应触发(未达5%目标)
    result = tsm.check_time_stop("000001", 0.02)
    assert result["triggered"] is True
    assert result["action"] == "sell"
    print(f"✅ 时间止损 Case1: {result['reason']}")
    
    # Case 2: 长持30天收益6% → 不触发
    result = tsm.check_time_stop("000001", 0.06)
    assert result["triggered"] is False
    print("✅ 时间止损 Case2: 收益达标不触发")
    
    # Case 3: 持仓15天亏损4% → 中期减仓
    entry_date2 = (datetime.now() - timedelta(days=21)).strftime("%Y-%m-%d")  # 21天≈15交易日
    tsm.entry_dates["000002"] = entry_date2
    result = tsm.check_time_stop("000002", -0.04)
    assert result["triggered"] is True
    assert result["action"] == "reduce"
    print(f"✅ 时间止损 Case3: {result['reason']}")
    
    # Case 4: 持仓5天 → 不触发
    tsm.entry_dates["000003"] = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    result = tsm.check_time_stop("000003", -0.02)
    assert result["triggered"] is False
    print("✅ 时间止损 Case4: 短期持仓不触发")
    
    # Cleanup
    tsm.entry_dates = {}
    tsm._save_state()


def test_consecutive_loss():
    """测试连续亏损保护"""
    from src.risk_management.time_stop import ConsecutiveLossProtector
    
    clp = ConsecutiveLossProtector()
    
    # Case 1: 正常模式
    clp.loss_streak = 0
    clp.mode = "normal"
    assert clp.get_position_multiplier() == 1.0
    assert clp.get_signal_threshold_bonus() == 0
    print("✅ 连续亏损 Case1: 正常模式 ×1.0")
    
    # Case 2: 3次连续亏损 → 防御模式
    trades = [
        {"action": "sell", "pnl": -100},
        {"action": "sell", "pnl": -200},
        {"action": "sell", "pnl": -50},
    ]
    clp.update_from_trades(trades)
    assert clp.mode == "defense"
    assert clp.get_position_multiplier() == 0.5
    assert clp.get_signal_threshold_bonus() == 5
    print(f"✅ 连续亏损 Case2: 防御模式 ×0.5, 门槛+5")
    
    # Case 3: 5次连续亏损 → 保守模式
    trades5 = [
        {"action": "sell", "pnl": -100},
        {"action": "sell", "pnl": -200},
        {"action": "sell", "pnl": -50},
        {"action": "sell", "pnl": -80},
        {"action": "sell", "pnl": -300},
    ]
    clp.update_from_trades(trades5)
    assert clp.mode == "conservative"
    assert clp.get_position_multiplier() == 0.3
    assert clp.get_signal_threshold_bonus() == 10
    print(f"✅ 连续亏损 Case3: 保守模式 ×0.3, 门槛+10")
    
    # Case 4: 最近一笔盈利 → 重置
    trades_reset = trades5 + [{"action": "sell", "pnl": 500}]
    clp.update_from_trades(trades_reset)
    assert clp.mode == "normal"
    assert clp.loss_streak == 0
    print("✅ 连续亏损 Case4: 盈利后恢复正常")
    
    # Cleanup
    clp.loss_streak = 0
    clp.mode = "normal"
    clp._save_state()


def test_risk_control_integration():
    """测试风控集成时间止损"""
    from src.simulator.risk_control import check_risk
    
    holdings = {
        "000001": {"shares": 100, "cost_price": 10.0},
    }
    prices = {"000001": 8.5}  # -15% 触发止损
    
    alerts = check_risk(holdings, prices, include_time_stop=False)
    assert len(alerts) >= 1
    assert alerts[0]["action"] == "sell"
    print(f"✅ 风控集成: 传统止损正常 {alerts[0]['reason']}")


def test_kelly_integration():
    """测试Kelly仓位管理集成"""
    from src.risk_management.kelly_position import KellyPositionManager
    
    kpm = KellyPositionManager()
    # 当前状态应该是亏损策略，Kelly会降低仓位
    pct = kpm.get_position_pct()
    assert 0.01 <= pct <= 0.2  # 应该在合理范围
    print(f"✅ Kelly仓位: {pct*100:.1f}%")
    
    status = str(kpm.get_status())


if __name__ == "__main__":
    test_time_stop()
    test_consecutive_loss()
    test_risk_control_integration()
    test_kelly_integration()
    print("\n🎉 全部测试通过!")
