"""模拟持仓管理 - 买入、卖出、持仓状态维护

A股交易约束：
- T+1（当天买入不能当天卖出）
- 涨跌停（涨停买不到，跌停卖不出）
- 手续费（买入万2.5 + 卖出万2.5 + 印花税千1）
- 滑点（次日开盘价 ± 0.2%）
- 最低交易单位（100股 = 1手）
"""

from datetime import date, datetime

import pandas as pd
from loguru import logger

from src.data.store import DataStore
from src.infra.config import get_settings


class PortfolioManager:
    """模拟持仓管理器

    维护 portfolio 表，提供买入/卖出/查询操作。
    """

    def __init__(self, store: DataStore = None):
        settings = get_settings()
        sim_cfg = settings.get("simulator", {})
        portfolio_cfg = settings.get("portfolio", {})

        self.store = store or DataStore()
        self.initial_capital = sim_cfg.get("initial_capital", 1_000_000.0)
        self.commission_rate = sim_cfg.get("commission_rate", 0.00025)
        self.stamp_tax_rate = sim_cfg.get("stamp_tax_rate", 0.001)
        self.slippage = sim_cfg.get("slippage", 0.002)
        self.min_lot = sim_cfg.get("min_lot", 100)
        self.portfolio_size = portfolio_cfg.get("size", 10)

        # 内存缓存: {code: {buy_date, buy_price, shares, current_price, ...}}
        self._positions = None

    # ============ 持仓加载/保存 ============

    def load_portfolio(self) -> dict:
        """从DuckDB加载当前持仓，返回 {code: row_dict}"""
        df = self.store.get_table("portfolio", where="status = 'holding'")
        self._positions = {}
        if not df.empty:
            for _, row in df.iterrows():
                self._positions[row["code"]] = row.to_dict()
        logger.info(f"加载持仓: {len(self._positions)} 只")
        return self._positions

    def save_portfolio(self):
        """将内存持仓写入DuckDB"""
        if not self._positions:
            return
        rows = []
        for code, pos in self._positions.items():
            rows.append({
                "code": code,
                "buy_date": pos.get("buy_date"),
                "buy_price": pos.get("buy_price", 0.0),
                "shares": pos.get("shares", 0),
                "current_price": pos.get("current_price", 0.0),
                "pnl_pct": pos.get("pnl_pct", 0.0),
                "target_weight": pos.get("target_weight", 1.0),
                "status": pos.get("status", "holding"),
                "updated_at": datetime.now(),
            })
        df = pd.DataFrame(rows)
        self.store.upsert_df("portfolio", df, pk_cols=["code"])

    def get_positions(self) -> dict:
        """获取当前持仓（懒加载）"""
        if self._positions is None:
            self.load_portfolio()
        return self._positions

    def get_portfolio_codes(self) -> list:
        """获取当前持仓代码列表"""
        positions = self.get_positions()
        return [code for code, pos in positions.items()
                if pos.get("status") == "holding"]

    # ============ 交易执行 ============

    def buy(self, code: str, price: float, capital_per_stock: float,
            trade_date=None, reason: str = "", score_at_action: float = 0.0) -> dict | None:
        """买入股票

        Args:
            code: 股票代码
            price: 买入价格（含滑点）
            capital_per_stock: 分配给该股票的资金
            trade_date: 交易日期
            reason: 买入原因
            score_at_action: 操作时的评分

        Returns:
            交易记录dict，或None（买入失败）
        """
        positions = self.get_positions()

        # 已持有则跳过
        if code in positions and positions[code].get("status") == "holding":
            logger.info(f"已持有 {code}，跳过买入")
            return None

        # 滑点调整（买入价格上浮）
        exec_price = price * (1 + self.slippage)

        # 计算可买股数（向下取整到100股）
        commission = capital_per_stock * self.commission_rate
        usable = capital_per_stock - commission
        shares = int(usable / exec_price) // self.min_lot * self.min_lot

        if shares <= 0:
            logger.warning(f"{code} 资金不足，无法买入（资金{capital_per_stock:.0f}，价格{exec_price:.2f}）")
            return None

        amount = shares * exec_price
        total_commission = amount * self.commission_rate

        # 记录持仓
        self._positions[code] = {
            "buy_date": trade_date or date.today(),
            "buy_price": exec_price,
            "shares": shares,
            "current_price": exec_price,
            "pnl_pct": 0.0,
            "target_weight": 1.0,
            "status": "holding",
            "updated_at": datetime.now(),
        }

        # 生成交易记录
        trade_record = {
            "code": code,
            "action": "buy",
            "price": round(exec_price, 3),
            "shares": shares,
            "amount": round(amount + total_commission, 2),
            "reason": reason,
            "score_at_action": round(score_at_action, 4),
            "date": trade_date or date.today(),
            "created_at": datetime.now(),
        }

        logger.info(
            f"买入 {code}: {shares}股 @ {exec_price:.3f}, "
            f"金额{amount + total_commission:.2f}, 原因: {reason}"
        )

        self.save_portfolio()
        return trade_record

    def sell(self, code: str, price: float, shares: int = None,
             trade_date=None, reason: str = "", score_at_action: float = 0.0) -> dict | None:
        """卖出股票

        Args:
            code: 股票代码
            price: 卖出价格（含滑点）
            shares: 卖出数量（None=全部卖出）
            trade_date: 交易日期
            reason: 卖出原因
            score_at_action: 操作时的评分

        Returns:
            交易记录dict，或None（卖出失败）
        """
        positions = self.get_positions()

        if code not in positions or positions[code].get("status") != "holding":
            logger.warning(f"未持有 {code}，无法卖出")
            return None

        pos = positions[code]
        sell_shares = shares if shares else pos["shares"]
        sell_shares = min(sell_shares, pos["shares"])

        # 滑点调整（卖出价格下浮）
        exec_price = price * (1 - self.slippage)

        amount = sell_shares * exec_price
        commission = amount * self.commission_rate
        stamp_tax = amount * self.stamp_tax_rate

        # 计算盈亏
        buy_amount = sell_shares * pos["buy_price"]
        pnl = amount - buy_amount - commission - stamp_tax
        pnl_pct = (exec_price - pos["buy_price"]) / pos["buy_price"]

        # 更新持仓
        if sell_shares >= pos["shares"]:
            # 全部卖出
            self._positions[code]["status"] = "sold"
            self._positions[code]["shares"] = 0
            self._positions[code]["current_price"] = exec_price
            self._positions[code]["pnl_pct"] = round(pnl_pct, 4)
            self._positions[code]["updated_at"] = datetime.now()
        else:
            # 部分卖出（减仓）
            self._positions[code]["shares"] -= sell_shares
            self._positions[code]["current_price"] = exec_price
            self._positions[code]["pnl_pct"] = round(pnl_pct, 4)
            self._positions[code]["updated_at"] = datetime.now()

        trade_record = {
            "code": code,
            "action": "sell",
            "price": round(exec_price, 3),
            "shares": sell_shares,
            "amount": round(amount - commission - stamp_tax, 2),
            "reason": reason,
            "score_at_action": round(score_at_action, 4),
            "date": trade_date or date.today(),
            "created_at": datetime.now(),
        }

        logger.info(
            f"卖出 {code}: {sell_shares}股 @ {exec_price:.3f}, "
            f"盈亏{pnl:+.2f}({pnl_pct*100:+.2f}%), 原因: {reason}"
        )

        self.save_portfolio()
        return trade_record

    # ============ 持仓更新 ============

    def update_prices(self, daily_quote_df: pd.DataFrame, trade_date=None):
        """用最新行情更新持仓价格和盈亏

        Args:
            daily_quote_df: 日线行情数据（含code, date, close列）
            trade_date: 交易日
        """
        positions = self.get_positions()
        if not positions:
            return

        date_ts = pd.Timestamp(trade_date) if trade_date else pd.Timestamp.now()

        for code, pos in positions.items():
            if pos.get("status") != "holding":
                continue

            code_data = daily_quote_df[
                (daily_quote_df["code"] == code) &
                (daily_quote_df["date"] == date_ts)
            ]

            if code_data.empty:
                # 尝试取最新一天
                code_data = daily_quote_df[
                    daily_quote_df["code"] == code
                ].sort_values("date")

            if not code_data.empty:
                current_price = float(code_data.iloc[-1]["close"])
                buy_price = pos["buy_price"]
                pnl_pct = (current_price - buy_price) / buy_price if buy_price > 0 else 0.0

                self._positions[code]["current_price"] = current_price
                self._positions[code]["pnl_pct"] = round(pnl_pct, 4)
                self._positions[code]["updated_at"] = datetime.now()

        self.save_portfolio()

    # ============ 统计 ============

    def get_total_market_value(self) -> float:
        """获取持仓总市值"""
        positions = self.get_positions()
        total = 0.0
        for pos in positions.values():
            if pos.get("status") == "holding":
                total += pos.get("shares", 0) * pos.get("current_price", 0.0)
        return total

    def get_portfolio_summary(self) -> dict:
        """获取持仓汇总

        Returns:
            {
                positions: [{code, name, shares, buy_price, current_price, pnl_pct, market_value}],
                total_market_value: float,
                total_pnl: float,
                total_pnl_pct: float,
                position_count: int,
            }
        """
        positions = self.get_positions()

        pos_list = []
        total_mv = 0.0
        total_cost = 0.0

        for code, pos in positions.items():
            if pos.get("status") != "holding":
                continue

            shares = pos.get("shares", 0)
            buy_price = pos.get("buy_price", 0.0)
            current_price = pos.get("current_price", 0.0)
            pnl_pct = pos.get("pnl_pct", 0.0)
            mv = shares * current_price
            cost = shares * buy_price

            pos_list.append({
                "code": code,
                "shares": shares,
                "buy_date": pos.get("buy_date"),
                "buy_price": buy_price,
                "current_price": current_price,
                "pnl_pct": pnl_pct,
                "market_value": mv,
                "cost": cost,
            })
            total_mv += mv
            total_cost += cost

        # 按市值排序
        pos_list.sort(key=lambda x: x["market_value"], reverse=True)

        total_pnl = total_mv - total_cost
        total_pnl_pct = total_pnl / total_cost if total_cost > 0 else 0.0

        return {
            "positions": pos_list,
            "total_market_value": total_mv,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "position_count": len(pos_list),
        }

    def calc_buy_amount(self, cash: float, target_count: int) -> float:
        """计算每只股票可分配的买入资金

        Args:
            cash: 可用现金
            target_count: 目标持仓总数（用于等权分配）

        Returns:
            每只股票的分配资金
        """
        if target_count <= 0:
            return 0.0
        return cash / target_count
