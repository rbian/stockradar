"""Risk Parity仓位分配 (风险平价)

GitHub学习: convexfi/riskparity.py (320 stars) + PyPortfolioOpt (5678 stars)
- Spinu (2013) 凸优化公式
- 核心思想: 每只股票对组合总风险的贡献相等
- 实现: 使用Iterative Marginal Risk Contribution调整法 (比Spinu更稳定)

简化公式 (当相关性适中时近似等价):
  w_i ∝ 1 / σ_i  (inverse volatility)
  用协方差矩阵迭代修正: w_i = 1 / (Σ·w)_i
"""

import numpy as np
from loguru import logger


class RiskParityAllocator:
    """风险平价仓位分配器"""

    def __init__(self, config=None):
        config = config or {}
        self.max_weight = config.get("max_weight", 0.40)
        self.min_weight = config.get("min_weight", 0.05)
        self.max_iterations = config.get("max_iterations", 50)
        self.tolerance = config.get("tolerance", 1e-4)

    def allocate(self, returns_matrix: np.ndarray, codes: list = None) -> dict:
        """计算风险平价权重

        Args:
            returns_matrix: shape (n_stocks, n_periods)
            codes: 股票代码列表

        Returns:
            dict {code: weight} 或 np.array
        """
        if returns_matrix.ndim == 1:
            returns_matrix = returns_matrix.reshape(1, -1)
        
        n = returns_matrix.shape[0]
        if n == 0:
            return {} if codes else np.array([])
        if n == 1:
            return {codes[0]: 1.0} if codes else np.array([1.0])

        cov_matrix = np.cov(returns_matrix)
        if cov_matrix.ndim == 0:
            return {codes[0]: 1.0} if codes else np.array([1.0])
        
        # 确保协方差矩阵正定
        cov_matrix = self._ensure_positive_definite(cov_matrix)
        
        weights = self._solve_risk_parity(cov_matrix, n)
        weights = self._apply_constraints(weights)
        
        total = weights.sum()
        if total > 0:
            weights = weights / total
        
        if codes and len(codes) == n:
            return {code: float(w) for code, w in zip(codes, weights)}
        return weights

    def _solve_risk_parity(self, cov_matrix: np.ndarray, n: int) -> np.ndarray:
        """迭代MRC法求解风险平价
        
        每轮: w_i_new ∝ 1 / (Σ·w)_i
        比Spinu更稳定，收敛更快
        """
        # 初始化: inverse volatility
        vols = np.sqrt(np.diag(cov_matrix))
        inv_vols = np.where(vols > 0, 1.0 / vols, 1.0)
        weights = inv_vols / inv_vols.sum()
        
        for iteration in range(self.max_iterations):
            old_weights = weights.copy()
            
            # 边际风险: (Σ·w)
            marginal_risk = cov_matrix @ weights
            
            # 新权重 ∝ 1/marginal_risk (确保正值)
            inv_mr = np.where(marginal_risk > 1e-12, 1.0 / marginal_risk, 0)
            if inv_mr.sum() > 0:
                weights = inv_mr / inv_mr.sum()
            
            # 只保留正值
            weights = np.maximum(weights, 1e-10)
            weights = weights / weights.sum()
            
            if np.max(np.abs(weights - old_weights)) < self.tolerance:
                logger.debug(f"Risk Parity收敛于第{iteration+1}次迭代")
                break
        
        return weights

    def _ensure_positive_definite(self, cov: np.ndarray) -> np.ndarray:
        """确保协方差矩阵正定"""
        # 添加小对角线项
        min_eig = np.min(np.linalg.eigvalsh(cov))
        if min_eig < 1e-10:
            cov = cov + (1e-10 - min_eig) * np.eye(len(cov))
        return cov

    def _apply_constraints(self, weights: np.ndarray) -> np.ndarray:
        """应用权重上下限 (自适应)"""
        n = len(weights)
        effective_max = max(self.max_weight, 1.0 / n)
        effective_min = min(self.min_weight, 1.0 / (n * 3))
        for _ in range(20):
            clipped = np.clip(weights, effective_min, effective_max)
            total = clipped.sum()
            if total > 0:
                clipped = clipped / total
            if np.allclose(clipped, weights, atol=1e-6):
                break
            weights = clipped
        return weights

    def allocate_simple(self, volatilities: list, codes: list) -> dict:
        """简化版: 只需波动率 (inverse volatility)"""
        n = len(volatilities)
        if n == 0:
            return {}
        
        vols = np.array(volatilities)
        inv_vols = np.where(vols > 0, 1.0 / vols, 0)
        total = inv_vols.sum()
        if total <= 0:
            return {code: 1.0 / n for code in codes}
        
        weights = inv_vols / total
        weights = self._apply_constraints(weights)
        return {code: float(w) for code, w in zip(codes, weights)}


def risk_parity_allocate(holdings: dict, returns_data: dict = None) -> dict:
    """便捷接口"""
    allocator = RiskParityAllocator()
    codes = list(holdings.keys())
    n = len(codes)
    if n == 0:
        return {}
    
    if returns_data and len(returns_data) == n:
        try:
            returns_matrix = np.array([returns_data[c] for c in codes])
            if returns_matrix.shape[1] >= 10:
                return allocator.allocate(returns_matrix, codes)
        except Exception:
            pass
    
    return {code: 1.0 / n for code in codes}
