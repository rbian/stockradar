"""Tests for Kelly Position Manager, Agreement Filter, and Weekly Reviewer"""

import json
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import pytest


class TestKellyPositionManager:
    def test_kelly_basic(self):
        from src.risk_management.kelly_position import KellyPositionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            km = KellyPositionManager(config={
                "fractional_kelly": 0.25,
                "min_trades": 5,
                "data_dir": tmpdir,
            })
            km.state_file = Path(tmpdir) / "kelly_state.json"
            km.data_dir = Path(tmpdir)

            # 模拟交易: 3胜2负, 胜率60%
            sells = [
                {"pnl": 500}, {"pnl": -200}, {"pnl": 300},
                {"pnl": -100}, {"pnl": 800},
            ]
            km.update_from_trades(sells)

            assert km.win_rate == pytest.approx(0.6, abs=0.01)
            assert km.kelly_fraction > 0

            # Kelly仓位应该合理
            pos = km.get_position_pct()
            assert 0.01 <= pos <= 0.20

    def test_kelly_losing_strategy(self):
        from src.risk_management.kelly_position import KellyPositionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            km = KellyPositionManager(config={"min_trades": 3, "data_dir": tmpdir})
            km.state_file = Path(tmpdir) / "kelly_state.json"
            km.data_dir = Path(tmpdir)

            # 全亏策略
            sells = [{"pnl": -100}, {"pnl": -200}, {"pnl": -150}]
            km.update_from_trades(sells)

            # Kelly应该为0或负(策略不可行)
            assert km.kelly_fraction <= 0

    def test_kelly_insufficient_data(self):
        from src.risk_management.kelly_position import KellyPositionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            km = KellyPositionManager(config={"min_trades": 100, "data_dir": tmpdir})
            km.state_file = Path(tmpdir) / "kelly_state.json"
            km.data_dir = Path(tmpdir)

            sells = [{"pnl": 100}, {"pnl": -50}]
            km.update_from_trades(sells)

            # 数据不足，使用默认
            pos = km.get_position_pct()
            assert pos == km.default_position_pct * 0.5

    def test_kelly_persistence(self):
        from src.risk_management.kelly_position import KellyPositionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            # 写入
            km1 = KellyPositionManager(config={"min_trades": 3, "data_dir": tmpdir})
            km1.state_file = Path(tmpdir) / "kelly_state.json"
            km1.data_dir = Path(tmpdir)
            km1.update_from_trades([{"pnl": 300}, {"pnl": -100}, {"pnl": 200}])
            saved_wr = km1.win_rate

            # 读取
            km2 = KellyPositionManager(config={"data_dir": tmpdir})
            km2.state_file = Path(tmpdir) / "kelly_state.json"
            km2._load_state()
            assert km2.win_rate == pytest.approx(saved_wr, abs=0.01)


class TestAgreementFilter:
    def _make_daily(self, code="000001", n=60, trend="up"):
        """生成模拟日线数据"""
        dates = pd.date_range("2026-03-01", periods=n, freq="D")
        if trend == "up":
            prices = np.cumsum(np.random.randn(n) * 0.5 + 0.3) + 20
        elif trend == "down":
            prices = np.cumsum(np.random.randn(n) * 0.5 - 0.3) + 30
        else:
            prices = np.cumsum(np.random.randn(n) * 0.5) + 25

        return pd.DataFrame({
            "code": code,
            "date": dates,
            "close": prices,
            "open": prices - np.random.rand(n) * 0.5,
            "high": prices + np.random.rand(n) * 0.5,
            "low": prices - np.random.rand(n) * 0.5,
            "volume": np.random.randint(100000, 500000, n),
            "amount": np.random.randint(5e6, 5e7, n),
            "change_pct": np.random.randn(n) * 2,
        })

    def test_trending_stock_passes(self):
        from src.factors.agreement_filter import check_factor_agreement

        daily = self._make_daily(trend="up")
        result = check_factor_agreement("000001", daily)
        assert result["agree_count"] >= 1  # 上涨股至少趋势维度通过
        assert result["total_dimensions"] == 5

    def test_declining_stock_rejected(self):
        from src.factors.agreement_filter import check_factor_agreement

        daily = self._make_daily(trend="down")
        result = check_factor_agreement("000001", daily)
        # 下跌股不应该strong_buy
        assert result["signal"] != "strong_buy"

    def test_filter_batch(self):
        from src.factors.agreement_filter import filter_by_agreement

        # 创建评分和行情
        scores = pd.DataFrame(
            {"score_total": [90, 85, 80, 75, 70]},
            index=["000001", "000002", "000003", "000004", "000005"]
        )

        daily_frames = []
        for code in scores.index:
            daily_frames.append(self._make_daily(code=code, trend="up"))
        daily = pd.concat(daily_frames, ignore_index=True)

        filtered = filter_by_agreement(scores, daily)
        # 至少应该保留一些
        assert len(filtered) >= 1


class TestWeeklyReviewer:
    def test_basic_analysis(self):
        from src.evolution.weekly_reviewer import WeeklyReviewer

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建模拟交易记录
            trades = []
            for i in range(15):
                trades.append({
                    "action": "buy",
                    "code": f"00000{i%5}",
                    "date": f"2026-04-{10+i:02d}",
                    "price": 20 + i,
                    "shares": 100,
                })
            for i in range(10):
                pnl = 500 if i < 4 else -300  # 40% win rate
                trades.append({
                    "action": "sell",
                    "code": f"00000{i%5}",
                    "date": f"2026-04-{15+i:02d}",
                    "price": 22 + i,
                    "shares": 100,
                    "pnl": pnl,
                })

            data_dir = Path(tmpdir)
            (data_dir / "trade_log.json").write_text(json.dumps(trades))

            reviewer = WeeklyReviewer(data_dir=str(data_dir))
            result = reviewer.analyze()

            assert result["status"] == "ok"
            assert result["basic_stats"]["win_rate"] == pytest.approx(0.4, abs=0.01)
            assert len(result["adjustments"]) > 0

            # 格式化报告
            report = reviewer.format_report(result)
            assert "周度复盘" in report

    def test_no_data(self):
        from src.evolution.weekly_reviewer import WeeklyReviewer

        with tempfile.TemporaryDirectory() as tmpdir:
            reviewer = WeeklyReviewer(data_dir=tmpdir)
            result = reviewer.analyze()
            assert result["status"] == "no_data"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
