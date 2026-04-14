# StockRadar 每日改进计划

## 每日（00:00 自动执行，1小时，至少3个改进）

### 周一: 复盘+策略日
1. 分析上周全部交易，统计胜率/盈亏比/最大回撤
2. 复盘模式→自动调整参数（止损/信号门槛）
3. 回测验证上周改进的效果
4. 从Phase待办推进1项

### 周二: 选股+因子日
1. 分析被过滤候选股，微调过滤条件减少误杀
2. 检查各因子IC值，淘汰持续为负的因子
3. 尝试1个新因子或新条件（用回测验证）
4. 从Phase待办推进1项

### 周三: 风控+仓位日
1. 回顾止损触发，统计过早止损率
2. 评估板块/相关性集中度是否改善
3. 模拟不同仓位分配方案的回测对比
4. 从Phase待办推进1项

### 周四: 数据+基建日
1. 更新BaoStock数据，检查数据质量
2. 检查API稳定性，有备用方案就加上
3. 优化代码性能（缓存/预计算/减少API调用）
4. 从Phase待办推进1项

### 周五: 策略迭代+周报日
1. 快速回测2-3个策略变体，对比收益
2. 生成周报（15:45 cron自动）
3. 提交本周所有改进，更新README
4. 制定下周改进TODO

## 自动Cron时间表

| 任务 | 时间 | 频率 |
|------|------|------|
| 盯盘监控 | 9:35-15:00 每5min | 工作日 |
| 交易复盘 | 15:40 | 工作日 |
| 周报 | 15:45 | 周五 |
| **每日改进** | **00:00** | **周一-周五 (3+改进/天)** |
| Optuna优化 | 09:00 | 周六 (50 trials) |
| GitHub Pages | 15:30 | 工作日 |

## 进度追踪

### Phase 1: 稳定性 ✅
- [x] Bot崩溃自动重启
- [x] pidfile锁机制
- [x] T+1规则
- [x] 交易成本回测

### Phase 2: 风控 ✅
- [x] 分批止损 (-10%/-15%)
- [x] 仓位上限 (80%股票/20%现金)
- [x] 大盘择时 (HS300 MA5/MA20)
- [x] 板块分散度 (同板块降权)
- [x] 相关性检查 (卖出优先)

### Phase 3: 选股质量 ✅
- [x] 6条件买入过滤
- [x] 个股风险过滤 (回撤/连跌/流动性)
- [x] 信号驱动加仓 (90+/80+/75-)
- [x] 动态仓位分配 (0.7x-1.5x)
- [x] 减仓冷却 (每只每天1次)

### Phase 4: 自进化 🔧 (进行中)
- [x] Optuna优化器 (预计算缓存)
- [x] 周末自动优化cron
- [x] 复盘模式检测
- [ ] Optuna结果自动应用到实盘
- [x] 因子IC追踪 → 淘汰无效因子 (JSON持久化已修复 2026-04-14)
- [ ] 复盘发现 → 自动调参闭环
- [ ] 策略A/B测试框架

### Phase 5: 规模化 📋 (待推进)
- [ ] HS300 → 中证500扩展
- [ ] 多策略组合 (趋势+反转+价值)
- [ ] 自动板块轮动信号
- [ ] 新闻情绪实时因子
- [ ] Page Agent信息采集（东方财富新闻/研报/北向资金/龙虎榜/雪球舆情）
- [ ] 可转债/ETF轮动


## 2026-04-14 (周二) 改进记录

### 改进1: ATR + Volume Trend 新因子
- **GitHub学习**: 经典量化框架(Qlib/聚宽)中ATR是核心波动率因子，用于波动率调仓
- **实现**: `calc_atr()` 和 `calc_volume_trend()` 添加到 technical.py
- **效果**: ATR归一化为收盘价百分比，直接可用于仓位调整；Volume Trend结合量价方向
- **回测**: mock数据测试通过，ATR值约1-15%范围合理

### 改进2: FactorTracker IC数据持久化
- **问题**: FactorTracker无store时不保存IC历史，重启丢失全部数据
- **实现**: 新增 `_save_to_json()` 和 JSON备份恢复逻辑
- **效果**: 每次daily_update后自动保存到 `data/cache/factor_ic_state.json`

### 改进3: 连续涨停追高过滤
- **学习**: 追涨停是A股散户常见亏损原因，连续涨停后回调概率高
- **实现**: hard_filter新增规则：近5日涨停≥2次排除
- **效果**: 减少追高风险，保护组合

### Phase 4.5: 自验证交易决策 (从Dexter项目学习)
- [ ] 魔鬼代言人机制：买入/卖出前自动生成反对理由
- [ ] 反对理由包括：板块集中度、相关性、大盘逆势、近期利空等
- [ ] 只有通过质疑（反对理由不成立）才执行交易
- [ ] 质疑记录保存到trade_log供复盘分析


## 2026-04-15 (周三) 改进记录 - 风控+仓位日

### 改进1: ATR-based Trailing Stop Loss (移动止损)
- **GitHub学习**: Qlib(微软18.5k星)和聚宽中ATR是核心风控工具
- **实现**: 
  - 新增 `src/risk_management/` 模块
  - `RiskManager.calculate_trailing_stops()` 基于ATR计算动态止损价
  - 保护性止损：止损价只降不升，保护已实现利润
  - 支持ADX动态调整倍数（见改进4）
- **效果**: 止损距离随波动率动态调整，避免在强趋势中被震荡洗出
- **回测**: 单元测试验证ATR计算和止损触发逻辑

### 改进2: Portfolio Max Drawdown Protection (组合回撤保护)
- **GitHub学习**: Zipline(Quantopian 16.5k星)的系统性风控思想
- **实现**: 
  - `RiskManager.check_portfolio_drawdown()` 监控组合净值
  - 回撤超过15%触发系统性减仓
  - 减仓比例 = (当前回撤 - 15%) * 2，上限30%
- **效果**: 防止系统性风险失控，避免单次大幅亏损
- **回测**: 单元测试验证不同回撤水平下的减仓逻辑

### 改进3: Volatility-adjusted Position Sizing (波动率仓位调整)
- **GitHub学习**: Qlib/聚宽的仓位管理实践
- **实现**: 
  - `RiskManager.calculate_volatility_adjusted_size()` 基于ATR计算波动率
  - 低波动股票 → 更大仓位（波动率因子 > 1.0）
  - 高波动股票 → 更小仓位（波动率因子 < 1.0）
  - 公式: `position = base_size * (1 / (1 + ATR_pct / scaling))`
- **效果**: 优化风险收益比，降低组合整体波动
- **回测**: 单元测试验证高/低波动股票的仓位差异

### 改进4 (GitHub学习): ADX Dynamic Stop-Loss Adjustment
- **来源**: Backtrader/QuantConnect实战策略
- **思路**: 根据趋势强度(ADX)动态调整止损距离
  - ADX < 20: 弱趋势，收紧止损(multiplier=2.0)
  - 20 <= ADX < 25: 中趋势，标准止损(multiplier=2.5)
  - ADX >= 25: 强趋势，放宽止损(multiplier=3.0)
- **实现**: 
  - 新增 `calc_adx()` 函数计算趋势强度指标
  - 新增 `get_adx_multiplier()` 动态调整倍数
  - 集成到 `RiskManager.calculate_trailing_stops()`
- **效果**: 强趋势中避免过早止损，弱趋势中快速止损
- **回测**: 单元测试验证ADX计算和倍数映射

### Phase 4.5: 自验证交易决策
- [x] ✅ GitHub学习记录: ideas/github_ideas.md
- [ ] 魔鬼代言人机制：买入/卖出前自动生成反对理由
- [ ] 反对理由包括：板块集中度、相关性、大盘逆势、近期利空等
- [ ] 只有通过质疑（反对理由不成立）才执行交易
- [ ] 质疑记录保存到trade_log供复盘分析

### 代码变更
- 新增 `src/risk_management/risk_manager.py` - 风控核心模块
- 新增 `src/strategy/continuous_score.py` - 策略文件归位
- 扩展 `src/factors/technical.py` - 新增ADX因子
- 修改 `src/backtest/engine.py` - 集成RiskManager
- 新增 `src/backtest/engine_risk_integration.py` - 风控集成补丁
- 新增 `tests/test_risk_management.py` - 风控模块单元测试
- 新增 `ideas/github_ideas.md` - GitHub学习记录

### Git提交
- Commit: `feat: 风控改进 - ATR移动止损+组合回撤保护+波动率仓位+ADX动态调整`
- 推送至: origin/master
- 变更: 8 files, 1350+ insertions

---

## 待改进项 (从GitHub学习)

### Kelly Criterion仓位管理
- **来源**: 多个量化项目
- **思路**: 根据历史胜率和盈亏比计算最优仓位
- **优先级**: 高

### Regime-based Risk Parameters
- **来源**: Backtrader / QuantConnect
- **思路**: 市场状态相关风控参数
- **优先级**: 中

### Correlation-based Position Limits
- **来源**: PyPortfolioOpt (3.5k stars)
- **思路**: 相关性仓位限制
- **优先级**: 中
