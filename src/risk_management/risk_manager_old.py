"""风险管理模块

实现先进的风险控制策略：
- ATR-based Trailing Stop Loss
- Portfolio-level Max Drawdown Protection  
- Volatility-adjusted Position Sizing
"""

import pandas as pd
import numpy as np
from loguru import logger

from src.backtest.a_share_constraints import Position


class RiskManager:
    """风险管理器"""
    
    def __init__(self, config=None):
        if config is None:
            config = self._get_default_config()
        
        # Trailing Stop Loss 配置
        self.atr_multiplier = config.get("atr_multiplier", 2.5)
        self.atr_period = config.get("atr_period", 20)
        self.trailing_protection = config.get("trailing_protection", 0.5)  # 保护性止损距离
        
        # Portfolio-level 配置  
        self.max_drawdown_threshold = config.get("max_drawdown_threshold", 0.15)  # 15%
        self.portfolio_cash_ratio = config.get("portfolio_cash_ratio", 0.2)  # 最低现金比例
        
        # Volatility Position Sizing 配置
        self.base_position_size = config.get("base_position_size", 0.1)  # 基础仓位 10%
        self.volatility_scaling = config.get("volatility_scaling", 0.5)  # 波动率缩放系数
        
        # 当前状态追踪
        self.trailing_stops = {}  # {code: stop_price}
        self.peak_nav = 1.0  # 净值峰值
        self.highest_atr = {}  # {code: highest_atr}
        
    def _get_default_config(self):
        """默认配置"""
        return {
            # ATR Trailing Stop
            "atr_multiplier": 2.5,
            "atr_period": 20,
            "trailing_protection": 0.5,  # 0.5x ATR保护距离
            
            # Portfolio Protection
            "max_drawdown_threshold": 0.15,  # 15%
            "portfolio_cash_ratio": 0.2,  # 最低20%现金
            
            # Position Sizing
            "base_position_size": 0.1,  # 基础10%
            "volatility_scaling": 0.5,  # 波动率缩放系数
        }
        
    def calculate_trailing_stops(self, positions: dict, daily_quote: pd.DataFrame, 
                                date: str) -> dict:
        """计算ATR-based移动止损价
        
        Args:
            positions: 当前持仓 {code: Position}
            daily_quote: 行情数据  
            date: 当前日期
            
        Returns:
            {code: stop_price}
        """
        stop_signals = {}
        
        for code, position in positions.items():
            if code not in daily_quote.columns:
                continue
                
            # 计算当前ATR
            atr = self._calculate_atr(daily_quote[code], self.atr_period, date)
            if atr is None or atr <= 0:
                continue
                
            # 更新最高ATR记录
            current_high = self.highest_atr.get(code, 0)
            if atr > current_high:
                self.highest_atr[code] = atr
                
            # 计算移动止损价
            atr_based_stop = position.current_price - (atr * self.atr_multiplier)
            
            # 保护性止损：如果有止损记录，不能向上调整
            existing_stop = self.trailing_stops.get(code, 0)
            if existing_stop > 0:
                # 只保留更低的止损价（防止止损价上调）
                stop_price = min(atr_based_stop, existing_stop)
            else:
                stop_price = atr_based_stop
                
            # 保护性距离：确保止损价不会太接近当前价格
            protection_distance = atr * self.trailing_protection
            if position.current_price - stop_price > protection_distance:
                stop_signals[code] = stop_price
                
        return stop_signals
        
    def should_trail_stop(self, position: Position, daily_quote: pd.DataFrame,
                          date: str, stop_signals: dict) -> bool:
        """判断是否触发移动止损
        
        Args:
            position: 单个持仓
            daily_quote: 行情数据
            date: 当前日期
            stop_signals: 计算出的止损信号
            
        Returns:
            True表示需要止损
        """
        code = position.code
        if code not in stop_signals:
            return False
            
        stop_price = stop_signals[code]
        
        # 触发条件：当前价格≤移动止损价
        current_price = daily_quote[code].iloc[-1] if hasattr(daily_quote[code], 'iloc') else position.current_price
        return current_price <= stop_price
        
    def check_portfolio_drawdown(self, current_nav: float, all_trades: list) -> dict:
        """检查组合回撤，决定是否需要减仓
        
        Args:
            current_nav: 当前净值
            all_trades: 所有交易记录
            
        Returns:
            {"drawdown": float, "reduce_positions": dict, "reduce_ratio": float}
        """
        # 更新净值峰值
        if current_nav > self.peak_nav:
            self.peak_nav = current_nav
            
        # 计算当前回撤
        if self.peak_nav <= 1.0:
            drawdown = 0.0
        else:
            drawdown = (self.peak_nav - current_nav) / self.peak_nav
            
        # 检查是否触发回撤保护
        reduce_positions = {}
        reduce_ratio = 0.0
        
        if drawdown > self.max_drawdown_threshold:
            # 超过最大回撤，需要减仓
            excess_drawdown = drawdown - self.max_drawdown_threshold
            reduce_ratio = min(excess_drawdown * 2, 0.3)  # 最多减仓30%
            
            logger.warning(
                f"组合回撤{drawdown:.1%}超过阈值{self.max_drawdown_threshold:.1%}, "
                f"建议整体减仓{reduce_ratio:.1%}"
            )
            
        return {
            "drawdown": drawdown,
            "reduce_positions": reduce_positions,
            "reduce_ratio": reduce_ratio,
        }
        
    def calculate_volatility_adjusted_size(self, code: str, daily_quote: pd.DataFrame,
                                         date: str, available_cash: float) -> float:
        """根据波动率计算调整后的仓位大小
        
        Args:
            code: 股票代码
            daily_quote: 行情数据
            date: 当前日期
            available_cash: 可用资金
            
        Returns:
            目标买入金额
        """
        # 计算ATR作为波动率指标
        atr = self._calculate_atr(daily_quote[code], self.atr_period, date)
        if atr is None or atr <= 0:
            # 如果无法计算ATR，使用基础仓位
            return available_cash * self.base_position_size
            
        current_price = daily_quote[code].iloc[-1] if hasattr(daily_quote[code], 'iloc') else 1.0
        atr_pct = atr / current_price
        
        # 波动率越大，仓位越小（反比关系）
        volatility_factor = 1.0 / (1.0 + atr_pct / self.volatility_scaling)
        
        # 计算调整后仓位
        target_size = available_cash * self.base_position_size * volatility_factor
        
        logger.debug(
            f"代码{code}: ATR={atr:.4f} ({atr_pct:.1%}), "
            f"波动率因子={volatility_factor:.2f}, "
            f"目标仓位{target_size:,.0f}元"
        )
        
        return target_size
        
    def _calculate_atr(self, series: pd.Series, period: int, date: str) -> float:
        """计算ATR (Average True Range)
        
        Args:
            series: 价格序列（日线数据）
            period: 计算周期
            date: 当前日期（用于取数据截止点）
            
        Returns:
            ATR值
        """
        if len(series) < period + 1:
            return None
            
        # 取最近N+1天的数据（需要前一日计算真实波幅）
        subset = series.tail(period + 1)
        if isinstance(subset, pd.Series):
            subset = subset.iloc[-(period + 1):]
        else:
            subset = subset[-(period + 1):]
            
        if len(subset) < period + 1:
            return None
            
        # 计算真实波幅 (True Range)
        tr_values = []
        for i in range(1, len(subset)):
            high = subset.iloc[i] if hasattr(subset.iloc[i], 'max') else subset.iloc[i]
            low = subset.iloc[i] if hasattr(subset.iloc[i], 'min') else subset.iloc[i]
            prev_close = subset.iloc[i-1]
            
            # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
            
        if not tr_values:
            return None
            
        # ATR = 真实波幅的移动平均
        atr = np.mean(tr_values)
        return atr
        
    def generate_risk_actions(self, positions: dict, daily_quote: pd.DataFrame,
                            date: str, all_trades: list, current_nav: float,
                            available_cash: float) -> list:
        """生成风控相关的交易动作
        
        Args:
            positions: 当前持仓
            daily_quote: 行情数据
            date: 当前日期
            all_trades: 所有交易记录
            current_nav: 当前净值
            available_cash: 可用资金
            
        Returns:
            交易动作列表 [{"action": "sell", "code": str, "reason": str}]
        """
        risk_actions = []
        
        # 1. 移动止损检查
        stop_signals = self.calculate_trailing_stops(positions, daily_quote, date)
        for code, position in positions.items():
            if self.should_trail_stop(position, daily_quote, date, stop_signals):
                risk_actions.append({
                    "action": "sell",
                    "code": code,
                    "reason": f"ATR移动止损触发（止损价{stop_signals[code]:.3f}）",
                    "urgency": "high",
                    "risk_type": "trailing_stop",
                })
                
        # 2. 组合回撤检查
        drawdown_info = self.check_portfolio_drawdown(current_nav, all_trades)
        if drawdown_info["reduce_ratio"] > 0:
            # 按比例减仓所有持仓
            for code, position in positions.items():
                reduce_shares = int(position.shares * drawdown_info["reduce_ratio"])
                if reduce_shares > 0:
                    risk_actions.append({
                        "action": "reduce",
                        "code": code,
                        "ratio": drawdown_info["reduce_ratio"],
                        "reason": f"组合回撤风控（当前回撤{drawdown_info['drawdown']:.1%}）",
                        "urgency": "high",
                        "risk_type": "portfolio_drawdown",
                    })
                    
        # 3. 生成买入动作时使用波动率调整仓位
        buy_actions = []
        for code in daily_quote.columns:
            if code not in positions:  # 不持有才买入
                target_size = self.calculate_volatility_adjusted_size(
                    code, daily_quote, date, available_cash
                )
                if target_size > 0:
                    buy_actions.append({
                        "code": code,
                        "action": "buy",
                        "target_amount": target_size,
                        "reason": "基于ATR波动率的仓位调整",
                        "risk_type": "volatility_positioning",
                    })
                    
        return risk_actions + buy_actions
        
    def update_position_status(self, executed_trades: list):
        """更新持仓状态（成交后调用）"""
        # 更新移动止损记录
        for trade in executed_trades:
            if trade.action == "sell":
                # 卖出的股票移除止损记录
                self.trailing_stops.pop(trade.code, None)
                self.highest_atr.pop(trade.code, None)
            elif trade.action == "buy":
                # 新买入的股票重置最高ATR记录
                self.highest_atr[trade.code] = 0.0
                # 初始止损设为买入价 - 2倍ATR（会在下次计算时更新）
                # TODO: 需要在下次计算时获取实际ATR值