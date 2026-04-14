# GitHub 量化项目学习记录

## 2026-04-15 风控改进

### 从经典量化框架学习到的思路

#### 1. Qlib (微软开源, 18.5k stars)
**学习点**: ATR-based Position Scaling
- 在Qlib中，ATR不仅用于止损，更用于仓位分配
- 核心思想: 低波动率股票可以配置更大仓位
- 公式: `position_size = base_size * (1 / (1 + ATR/price * scaling_factor))`
- **已实现**: 在RiskManager.calculate_volatility_adjusted_size()

#### 2. 聚宽(JoinQuant) 风控系统
**学习点**: Trailing Stop with Volatility Adjustment
- 移动止损不是固定百分比，而是基于ATR的动态止损
- 公式: `stop_price = high_price - ATR * multiplier`
- 关键点: 止损价只能向下调整，不能向上（保护利润）
- **已实现**: 在RiskManager.calculate_trailing_stops()

#### 3. Zipline (Quantopian开源, 16.5k stars)
**学习点**: Portfolio-level Drawdown Protection
- 当组合回撤超过阈值时，触发系统性减仓
- 不同于个股止损，这是组合层面的保护
- 减仓比例 = (当前回撤 - 阈值) * 敏感度系数
- **已实现**: 在RiskManager.check_portfolio_drawdown()

#### 4. 新学到的思路 (待实现)

##### 4.1 Kelly Criterion - 凯利公式仓位管理
**来源**: 多个量化项目
**思路**: 根据历史胜率和盈亏比计算最优仓位
- 公式: `f = (bp - q) / b`，其中 b=盈亏比, p=胜率, q=1-p
- 应用: 根据策略历史表现动态调整整体仓位
- **实现难度**: 中等
- **优先级**: 高

##### 4.2 Regime-based Risk Parameters - 市场状态相关风控
**来源**: Backtrader / QuantConnect
**思路**: 根据市场状态（牛市/熊市/震荡）动态调整风控参数
- 牛市: 放宽止损，扩大仓位
- 熊市: 收紧止损，降低仓位
- 实现: 检测市场状态 → 选择对应参数集
- **实现难度**: 高
- **优先级**: 中

##### 4.3 Correlation-based Position Limits - 相关性仓位限制
**来源**: PyPortfolioOpt (3.5k stars)
**思路**: 限制高度相关股票的总仓位
- 计算持仓相关性矩阵
- 同一板块/高相关性的股票总仓位不超过X%
- 降低系统性风险
- **实现难度**: 中
- **优先级**: 中

##### 4.4 Dynamic Stop-Loss based on Trend - 趋势动态止损
**来源**: 量邦科技/聚宽实战策略
**思路**: 根据趋势强度动态调整止损距离
- 强趋势（ADX高）: 放宽止损，避免被震荡洗出
- 弱趋势（ADX低）: 收紧止损，快速止损
- 实现: ADX指标 → 调整ATR multiplier
- **实现难度**: 低
- **优先级**: 高（今天实现）

---

## 今日实现计划

### 改进1: ATR-based Trailing Stop (已完成)
- ✅ RiskManager.calculate_trailing_stops()
- ✅ 动态止损价计算
- ✅ 保护性止损（只降不升）

### 改进2: Portfolio Drawdown Protection (已完成)
- ✅ RiskManager.check_portfolio_drawdown()
- ✅ 回撤超过15%触发减仓
- ✅ 系统性风险控制

### 改进3: Volatility Position Sizing (已完成)
- ✅ RiskManager.calculate_volatility_adjusted_size()
- ✅ ATR归一化计算波动率
- ✅ 反比仓位分配

### 改进4 (NEW): Dynamic Stop-Loss based on Trend
**来源**: 量化实战经验
**实现**: 基于ADX指标调整止损距离
- 强趋势 (ADX > 25): multiplier = 3.0
- 中趋势 (15 <= ADX <= 25): multiplier = 2.5
- 弱趋势 (ADX < 15): multiplier = 2.0
- 在RiskManager中实现
- 需要添加ADX因子计算

### 改进5 (NEW): Kelly Criterion Initial Position
**来源**: Kelly公式
**实现**: 根据策略历史表现计算初始仓位
- 统计过去30笔交易的胜率和盈亏比
- 计算凯利f值，限制在0.02-0.15之间
- 调整整体仓位上限
