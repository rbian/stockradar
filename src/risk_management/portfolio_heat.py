"""Portfolio Heat — 组合热度监控

来源: Van Tharp《Trade Your Way to Financial Freedom》
思路: 组合总风险 = Σ(每只持仓的风险暴露)，即 (入场价 - 止损价) × 持仓数量
Portfolio Heat = 组合总风险 / 总资产

规则:
- Heat > 20%: 过度风险 → 优先减仓最高风险的持仓
- Heat > 30%: 紧急 → 减仓至Heat < 20%
- 每只股票的Individual Heat = 风险暴露 / 总资产 > 8% → 该股过度集中

用于:
1. 调仓前检查: 新买入会使Heat超过阈值则拒绝
2. 每日风险扫描: 自动识别过度集中的持仓
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class HeatResult:
    """组合热度分析结果"""
    total_heat: float  # 总热度 (0-1)
    individual_heat: Dict[str, float]  # 个股热度 {code: heat}
    max_heat_stock: str  # 最高热度股票
    overheat_stocks: List[str]  # 超过个股阈值的股票
    action: str  # "ok" / "warning" / "danger"
    message: str


class PortfolioHeat:
    """组合热度监控器"""

    def __init__(self, config=None):
        cfg = config or {}
        self.max_total_heat = cfg.get("max_total_heat", 0.20)  # 总热度上限20%
        self.danger_total_heat = cfg.get("danger_total_heat", 0.30)  # 危险阈值30%
        self.max_individual_heat = cfg.get("max_individual_heat", 0.08)  # 个股上限8%

    def calculate(
        self,
        holdings: Dict[str, dict],  # {code: {"shares": int, "entry_price": float}}
        current_prices: Dict[str, float],  # {code: current_price}
        stop_prices: Dict[str, float],  # {code: stop_price}
        total_assets: float,
    ) -> HeatResult:
        """计算组合热度

        Args:
            holdings: 持仓字典
            current_prices: 当前价格
            stop_prices: 止损价格
            total_assets: 总资产
        """
        if total_assets <= 0 or not holdings:
            return HeatResult(
                total_heat=0, individual_heat={},
                max_heat_stock="", overheat_stocks=[],
                action="ok", message="无持仓或无资产"
            )

        individual_heat = {}
        total_risk = 0.0

        for code, holding in holdings.items():
            price = current_prices.get(code, 0)
            stop = stop_prices.get(code, 0)
            shares = holding.get("shares", 0)

            if price <= 0 or shares <= 0:
                individual_heat[code] = 0.0
                continue

            # 如果没有止损价，用5%作为默认风险距离
            if stop <= 0 or stop >= price:
                risk_per_share = price * 0.05
            else:
                risk_per_share = price - stop

            risk_exposure = risk_per_share * shares
            heat = risk_exposure / total_assets
            individual_heat[code] = heat
            total_risk += risk_exposure

        total_heat = total_risk / total_assets

        # 排名
        sorted_heat = sorted(individual_heat.items(), key=lambda x: x[1], reverse=True)
        max_heat_stock = sorted_heat[0][0] if sorted_heat else ""
        overheat = [code for code, h in individual_heat.items() if h > self.max_individual_heat]

        # 判断状态
        if total_heat >= self.danger_total_heat:
            action = "danger"
            msg = f"⚠️ 组合热度{total_heat:.1%}超过危险线{self.danger_total_heat:.0%}，建议立即减仓"
        elif total_heat >= self.max_total_heat:
            action = "warning"
            msg = f"⚡ 组合热度{total_heat:.1%}接近上限{self.max_total_heat:.0%}"
        else:
            action = "ok"
            msg = f"✅ 组合热度{total_heat:.1%}，风险可控"

        if overheat:
            msg += f" | 个股过热: {len(overheat)}只"

        return HeatResult(
            total_heat=total_heat,
            individual_heat=individual_heat,
            max_heat_stock=max_heat_stock,
            overheat_stocks=overheat,
            action=action,
            message=msg,
        )

    def check_buy_allowed(
        self,
        code: str,
        buy_shares: int,
        buy_price: float,
        stop_price: float,
        holdings: Dict[str, dict],
        current_prices: Dict[str, float],
        stop_prices: Dict[str, float],
        total_assets: float,
    ) -> tuple:
        """检查买入是否会使组合热度超标

        Returns:
            (allowed: bool, reason: str)
        """
        # 计算当前热度
        result = self.calculate(holdings, current_prices, stop_prices, total_assets)

        # 计算新增热度
        if stop_price > 0 and stop_price < buy_price:
            new_risk = (buy_price - stop_price) * buy_shares
        else:
            new_risk = buy_price * 0.05 * buy_shares

        new_heat = new_risk / total_assets if total_assets > 0 else 0
        projected_heat = result.total_heat + new_heat

        # 个股热度检查
        individual_new = new_heat
        if individual_new > self.max_individual_heat:
            return False, f"个股热度{individual_new:.1%}超过上限{self.max_individual_heat:.0%}"

        # 总热度检查
        if projected_heat > self.danger_total_heat:
            return False, f"买入后组合热度{projected_heat:.1%}将超过危险线"
        if projected_heat > self.max_total_heat:
            return False, f"买入后组合热度{projected_heat:.1%}将超过上限{self.max_total_heat:.0%}"

        return True, f"买入OK，热度{result.total_heat:.1%}→{projected_heat:.1%}"
