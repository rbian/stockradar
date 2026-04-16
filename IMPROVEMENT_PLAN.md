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

---

## 2026-04-16 (周四) 改进记录 - 数据+基建日

### 改进1: 修复交易复盘verdict KeyError (关键BUG)
- **问题**: trade_reviewer.py中_judge_buy/_judge_sell返回`{"outcome": ...}`，但_review_single_trade读取`outcome["verdict"]`
- **影响**: 每日15:40交易复盘持续失败，报错`'verdict'` KeyError
- **修复**: 改为`outcome.get("outcome", "unknown")`安全访问
- **验证**: 单元测试通过，buy/sell各场景返回正确outcome

### 改进2: Tushare API重试+缓存机制
- **GitHub学习**: 量化数据系统中resilience pattern是标配（Qlib有完整的DataFetcher+Cache体系）
- **实现**:
  - `_retry_api_call()`: 指数退避重试，3次(2s/4s/8s延迟)
  - Tushare专用Parquet缓存层: `_save_tushare_cache()` / `_load_tushare_cache()`
  - 缓存策略: northbound/sector/dragon_tiger 1天TTL, macro 30天TTL
  - API失败时自动回退到7天内缓存
- **效果**: 解决ConnectionResetError导致的数据丢失，减少API调用次数
- **验证**: 单元测试确认缓存读写和重试逻辑

### 改进3: Tushare缓存 + graceful degradation
- 上述缓存机制中已包含: API不可用时回退到7天内旧缓存
- 确保即使Tushare完全不可用，报告生成不会中断

### Phase 4进度更新
- [x] 因子IC追踪 → 淘汰无效因子
- [x] 风控模块(RiskManager)已完成
- [ ] Optuna结果自动应用到实盘
- [ ] 复盘发现 → 自动调参闭环
- [ ] 策略A/B测试框架

### Git提交
- Commit: `fix: 交易复盘verdict KeyError + Tushare重试+缓存`
- 推送至: origin/master
- 变更: 2 files, 233 insertions

## 2026-04-17 (周五) 改进记录 - 策略迭代+周报日

### 改进1: 修复reporter.py stock_name UnboundLocalError (关键BUG)
- **问题**: `_daily_report()` 内line 116有 `from src.data.stock_names import stock_name` 局部导入
- **影响**: Python将方法内所有 `stock_name` 引用视为local变量，导致15:30日报持续失败
- **修复**: 删除冗余局部导入，使用模块级导入（line 14）
- **日志证据**: `2026-04-16 15:30:05 | ERROR | src.agents.reporter:act:49 - 报告生成失败: cannot access local variable 'stock_name'`

### 改进2: 修复trade_reviewer.py analysis key安全访问
- **问题**: `_review_single_trade()` 中 `outcome["analysis"]` 无安全访问
- **修复**: 改为 `outcome.get("analysis", "")` 防止KeyError
- **关联**: 配合04-16的verdict修复，完整解决15:40复盘失败链

### 改进3: Inverse Volatility Portfolio权重分配 (GitHub学习: skfolio)
- **来源**: skfolio (skfolio.org, 500+ stars) + PyPortfolioOpt + DeMiguel 2007论文
- **思路**: 组合权重与波动率成反比，低波动高权重，降低组合波动
- **实现**:
  - `RiskManager.inverse_volatility_weights()` 新方法
  - 年化波动率 = 20日收益率标准差 × √252
  - weight_i = (1/vol_i) / Σ(1/vol_j)，限制5%-25%
  - 数据不足时回退等权
- **测试**: 3个场景全部通过（正常分配、空输入、数据不足）
- **下一步**: 集成到每日选股流程，替代等权分配

### 修复4: backtest/engine.py语法错误
- **问题**: if strategy is None 块后跟独立 else，导致SyntaxError
- **影响**: 阻止所有单元测试运行（import chain: risk_manager → backtest → engine）
- **修复**: 重构if/else结构，同时解决circular import（lazy import Position）

### Git提交
- Commit: `fix: reporter stock_name scoping bug + trade_reviewer safety + Inverse Volatility Portfolio weights + backtest engine syntax fix`
- 推送至: origin/master
- 变更: 6 files, 169 insertions(+), 7 deletions(-)
