"""A股交易约束模拟

模拟真实A股市场的交易约束：
- T+1：当天买入不能当天卖出
- 涨跌停：涨停买不到，跌停卖不出
- 停牌：不能交易
- 滑点：次日开盘价 ± 0.2%
- 手续费：买入万2.5 + 卖出万2.5 + 印花税千1
- 最低交易单位：100股
- ST股涨跌幅限制5%
- 非交易日跳过
"""

from dataclasses import dataclass, field

import pandas as pd
import numpy as np
from loguru import logger

from src.infra.config import get_settings


@dataclass
class Position:
    """持仓记录"""
    code: str
    shares: int
    buy_date: str
    buy_price: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl_pct(self) -> float:
        if self.buy_price == 0:
            return 0.0
        return (self.current_price - self.buy_price) / self.buy_price


@dataclass
class TradeRecord:
    """交易记录"""
    date: str
    code: str
    action: str  # buy / sell
    price: float
    shares: int
    amount: float  # 实际金额
    commission: float  # 手续费
    stamp_tax: float  # 印花税
    slippage_cost: float  # 滑点成本
    reason: str = ""
    pnl: float = 0.0  # 卖出时的盈亏


class AShareConstraints:
    """A股交易约束模拟器"""

    def __init__(self, settings: dict = None):
        if settings is None:
            settings = get_settings()

        sim_cfg = settings.get("simulator", {})
        self.commission_rate = sim_cfg.get("commission_rate", 0.00025)  # 万2.5
        self.stamp_tax_rate = sim_cfg.get("stamp_tax_rate", 0.001)  # 千1
        self.slippage = sim_cfg.get("slippage", 0.002)  # 0.2%
        self.min_lot = sim_cfg.get("min_lot", 100)

        # 涨跌停限制
        self.normal_limit_pct = 0.10  # 主板 ±10%
        self.st_limit_pct = 0.05  # ST ±5%
        self.gem_star_limit_pct = 0.20  # 创业板/科创板 ±20%

        # T+1追踪: {code: buy_date}
        self._today_buys: set = set()

        # 停牌信息缓存: {date: {code: is_suspended}}
        self._suspension_cache: dict = {}

    def reset_daily(self):
        """每日开盘前重置T+1追踪"""
        self._today_buys = set()

    def get_suspended_codes(self, daily_quote: pd.DataFrame,
                            date: str) -> set:
        """获取当日停牌股票

        通过当日无行情数据来判断停牌（简化处理）
        """
        date_ts = pd.Timestamp(date)
        if "date" in daily_quote.columns:
            daily_quote = daily_quote.copy()
            daily_quote["date"] = pd.to_datetime(daily_quote["date"])

        trading_codes = set(
            daily_quote[daily_quote["date"] == date_ts]["code"].unique()
        )
        # 所有已知代码中不在当日交易列表的即为停牌
        all_codes = set(daily_quote["code"].unique())
        return all_codes - trading_codes

    def check_limit_up(self, code: str, daily_quote: pd.DataFrame,
                       date: str, stock_info: pd.DataFrame = None) -> bool:
        """判断当日是否涨停（买不到）

        Args:
            code: 股票代码
            daily_quote: 日线行情
            date: 日期
            stock_info: 股票信息（判断ST等）

        Returns:
            True表示涨停，买不到
        """
        row = self._get_quote(daily_quote, code, date)
        if row is None:
            return True

        pre_close = row.get("pre_close", 0)
        close = row.get("close", 0)
        if pre_close == 0:
            return False

        change_pct = (close - pre_close) / pre_close
        limit_pct = self._get_limit_pct(code, stock_info)

        # 涨幅接近涨停（允许0.5%误差，因为四舍五入）
        return change_pct >= (limit_pct - 0.005)

    def check_limit_down(self, code: str, daily_quote: pd.DataFrame,
                         date: str, stock_info: pd.DataFrame = None) -> bool:
        """判断当日是否跌停（卖不出）"""
        row = self._get_quote(daily_quote, code, date)
        if row is None:
            return True

        pre_close = row.get("pre_close", 0)
        close = row.get("close", 0)
        if pre_close == 0:
            return False

        change_pct = (close - pre_close) / pre_close
        limit_pct = self._get_limit_pct(code, stock_info)

        return change_pct <= -(limit_pct - 0.005)

    def apply_slippage(self, price: float, action: str) -> float:
        """应用滑点

        买入价 = 目标价 × (1 + slippage)
        卖出价 = 目标价 × (1 - slippage)
        """
        if action == "buy":
            return price * (1 + self.slippage)
        else:
            return price * (1 - self.slippage)

    def calc_commission(self, amount: float) -> float:
        """计算手续费（双向万2.5，最低5元）"""
        comm = amount * self.commission_rate
        return max(comm, 5.0)

    def calc_stamp_tax(self, amount: float) -> float:
        """计算印花税（卖出千1）"""
        return amount * self.stamp_tax_rate

    def round_lot(self, shares: int) -> int:
        """按100股取整"""
        return (shares // self.min_lot) * self.min_lot

    def check_t_plus_1(self, code: str) -> bool:
        """检查T+1约束

        Returns:
            True表示可以卖出（非当日买入）
        """
        return code not in self._today_buys

    def execute_buy(self, code: str, target_amount: float,
                    daily_quote: pd.DataFrame, date: str,
                    stock_info: pd.DataFrame = None) -> TradeRecord | None:
        """执行买入

        Args:
            code: 股票代码
            target_amount: 目标买入金额
            daily_quote: 行情数据
            date: 日期
            stock_info: 股票信息

        Returns:
            交易记录，无法交易返回None
        """
        # 停牌检查
        suspended = self.get_suspended_codes(daily_quote, date)
        if code in suspended:
            logger.debug(f"[{date}] {code} 停牌，无法买入")
            return None

        # 涨停检查
        if self.check_limit_up(code, daily_quote, date, stock_info):
            logger.debug(f"[{date}] {code} 涨停，无法买入")
            return None

        row = self._get_quote(daily_quote, code, date)
        if row is None:
            return None

        # 使用次日开盘价作为买入价（回测中模拟盘后决策次日执行）
        price = row["open"]
        price = self.apply_slippage(price, "buy")

        # 计算可买股数（按手取整）
        shares = int(target_amount / price)
        shares = self.round_lot(shares)
        if shares <= 0:
            return None

        actual_amount = shares * price
        commission = self.calc_commission(actual_amount)
        stamp_tax = 0.0  # 买入无印花税

        # 记录T+1
        self._today_buys.add(code)

        return TradeRecord(
            date=date,
            code=code,
            action="buy",
            price=price,
            shares=shares,
            amount=actual_amount,
            commission=commission,
            stamp_tax=stamp_tax,
            slippage_cost=shares * price * self.slippage,
        )

    def execute_sell(self, position: Position, daily_quote: pd.DataFrame,
                     date: str, sell_shares: int = None,
                     stock_info: pd.DataFrame = None) -> TradeRecord | None:
        """执行卖出

        Args:
            position: 持仓
            daily_quote: 行情数据
            date: 日期
            sell_shares: 卖出数量（None表示全部卖出）
            stock_info: 股票信息

        Returns:
            交易记录，无法交易返回None
        """
        code = position.code

        # T+1检查
        if not self.check_t_plus_1(code):
            logger.debug(f"[{date}] {code} T+1限制，无法卖出")
            return None

        # 停牌检查
        suspended = self.get_suspended_codes(daily_quote, date)
        if code in suspended:
            logger.debug(f"[{date}] {code} 停牌，无法卖出")
            return None

        # 跌停检查
        if self.check_limit_down(code, daily_quote, date, stock_info):
            logger.debug(f"[{date}] {code} 跌停，无法卖出")
            return None

        row = self._get_quote(daily_quote, code, date)
        if row is None:
            return None

        price = row["open"]
        price = self.apply_slippage(price, "sell")

        if sell_shares is None:
            sell_shares = position.shares
        sell_shares = min(sell_shares, position.shares)
        sell_shares = self.round_lot(sell_shares)
        if sell_shares <= 0:
            return None

        actual_amount = sell_shares * price
        commission = self.calc_commission(actual_amount)
        stamp_tax = self.calc_stamp_tax(actual_amount)
        slippage_cost = sell_shares * row["open"] * self.slippage

        # 计算盈亏
        pnl = (price - position.buy_price) * sell_shares - commission - stamp_tax - slippage_cost

        return TradeRecord(
            date=date,
            code=code,
            action="sell",
            price=price,
            shares=sell_shares,
            amount=actual_amount,
            commission=commission,
            stamp_tax=stamp_tax,
            slippage_cost=slippage_cost,
            pnl=pnl,
        )

    def _get_quote(self, daily_quote: pd.DataFrame,
                   code: str, date: str) -> dict | None:
        """获取某只股票某日的行情"""
        date_ts = pd.Timestamp(date)
        if "date" in daily_quote.columns:
            daily_quote = daily_quote.copy()
            daily_quote["date"] = pd.to_datetime(daily_quote["date"])

        mask = (daily_quote["code"] == code) & (daily_quote["date"] == date_ts)
        rows = daily_quote[mask]
        if rows.empty:
            return None
        return rows.iloc[0].to_dict()

    def _get_limit_pct(self, code: str, stock_info: pd.DataFrame = None) -> float:
        """获取涨跌停限制比例"""
        # 创业板 300xxx / 科创板 688xxx → ±20%
        if code.startswith("300") or code.startswith("688"):
            return self.gem_star_limit_pct

        # ST判断
        if stock_info is not None and not stock_info.empty:
            if "is_st" in stock_info.columns and "code" in stock_info.columns:
                info = stock_info[stock_info["code"] == code]
                if not info.empty and info.iloc[0].get("is_st", False):
                    return self.st_limit_pct

        return self.normal_limit_pct
