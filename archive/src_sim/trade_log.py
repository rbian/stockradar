"""交易记录模块

记录所有模拟交易到 trade_log 表，
提供查询和统计功能。
"""

from datetime import date, datetime

import pandas as pd
from loguru import logger

from src.data.store import DataStore


class TradeLogger:
    """交易记录器"""

    def __init__(self, store: DataStore = None):
        self.store = store or DataStore()

    def log_trade(self, trade_record: dict):
        """记录一笔交易

        Args:
            trade_record: 交易记录dict，需含:
                code, action(buy/sell), price, shares, amount,
                reason, score_at_action, date
        """
        if not trade_record:
            return

        row = {
            "code": trade_record["code"],
            "action": trade_record["action"],
            "price": trade_record.get("price", 0.0),
            "shares": trade_record.get("shares", 0),
            "amount": trade_record.get("amount", 0.0),
            "reason": trade_record.get("reason", ""),
            "score_at_action": trade_record.get("score_at_action", 0.0),
            "date": trade_record.get("date", date.today()),
            "created_at": datetime.now(),
        }

        df = pd.DataFrame([row])
        self.store.upsert_df("trade_log", df, pk_cols=[])
        logger.info(f"交易记录: {row['action']} {row['code']} {row['shares']}股")

    def log_trades(self, trade_records: list):
        """批量记录交易"""
        for record in trade_records:
            self.log_trade(record)

    def get_trades(self, start_date=None, end_date=None,
                   code: str = None, action: str = None) -> pd.DataFrame:
        """查询交易记录

        Args:
            start_date: 起始日期
            end_date: 结束日期
            code: 股票代码过滤
            action: 动作过滤 (buy/sell)

        Returns:
            交易记录DataFrame
        """
        conditions = []
        if start_date:
            conditions.append(f"date >= '{start_date}'")
        if end_date:
            conditions.append(f"date <= '{end_date}'")
        if code:
            conditions.append(f"code = '{code}'")
        if action:
            conditions.append(f"action = '{action}'")

        where = " AND ".join(conditions) if conditions else None
        return self.store.get_table("trade_log", where=where)

    def get_today_trades(self, today=None) -> pd.DataFrame:
        """获取今日交易"""
        trade_date = today or date.today()
        return self.get_trades(start_date=trade_date, end_date=trade_date)

    def get_recent_trades(self, days: int = 7) -> pd.DataFrame:
        """获取最近N天的交易"""
        end = date.today()
        start = end - pd.Timedelta(days=days)
        return self.get_trades(start_date=start, end_date=end)

    def get_trade_stats(self, start_date=None, end_date=None) -> dict:
        """获取交易统计

        Returns:
            {
                total_trades: int,
                buy_count: int,
                sell_count: int,
                total_buy_amount: float,
                total_sell_amount: float,
                net_amount: float,
            }
        """
        trades = self.get_trades(start_date=start_date, end_date=end_date)

        if trades.empty:
            return {
                "total_trades": 0,
                "buy_count": 0,
                "sell_count": 0,
                "total_buy_amount": 0.0,
                "total_sell_amount": 0.0,
                "net_amount": 0.0,
            }

        buy_trades = trades[trades["action"] == "buy"]
        sell_trades = trades[trades["action"] == "sell"]

        total_buy = buy_trades["amount"].sum() if not buy_trades.empty else 0.0
        total_sell = sell_trades["amount"].sum() if not sell_trades.empty else 0.0

        return {
            "total_trades": len(trades),
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "total_buy_amount": round(total_buy, 2),
            "total_sell_amount": round(total_sell, 2),
            "net_amount": round(total_sell - total_buy, 2),
        }
