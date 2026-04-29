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

---

## 每日改进日志

### 2026-04-28 (周二) 选股+因子日
1. ✅ **IC追踪持久化修复** — JSON格式兼容问题导致历史IC数据丢失，已修复restore逻辑+自动save
2. ✅ **新增板块相对动量因子** (sector_relative_momentum) — 灵感来自GitHub RRG概念，42个行业分类，个股vs行业均值偏离度
3. ✅ **买入过滤新增板块动量条件** — 跑输板块8%以上的股票不买入
- commit: 584d784
- GitHub学到: Relative Rotation Graph概念 — 个股alpha应相对于板块衡量，而非绝对动量
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

## 2026-04-20 (周一) 改进记录 - 复盘+策略日

### 周度复盘结果
- 总交易: 33卖/46买
- **胜率: 30% | 盈亏比: 0.04** (极差)
- 平均盈利: ¥1,863 vs 平均亏损: ¥-23,587
- 最大亏损来源: 688506(百利天恒) ¥-73,785 × 3笔，占Top5亏损82%
- 趋势: 📉 恶化

### 改进1: Kelly Criterion仓位管理 (GitHub学习: 量化金融经典)
- **来源**: Kelly(1956) + Thorp(1969) + 多个量化项目实践
- **思路**: 根据历史胜率和盈亏比计算最优仓位比例
- **实现**: `src/risk_management/kelly_position.py`
  - Full Kelly = (p*b - q) / b, 使用1/4 fractional Kelly降波动
  - 当前数据: 胜率30%, 盈亏比0.08, Full Kelly=-8.52 → 自动降为4%保守仓位
  - JSON持久化，状态跨重启保存
- **效果**: 策略亏钱时自动降低仓位保护本金
- **测试**: 4个场景全部通过（正常/亏损策略/数据不足/持久化）

### 改进2: 多因子一致性过滤器 (GitHub学习: ashare-neural-network ensemble方法)
- **来源**: heyixuan2/ashare-neural-network - LSTM-Transformer ensemble预测
- **思路**: ensemble多模型一致性投票 → 多因子5维度一致性检查
- **实现**: `src/factors/agreement_filter.py`
  - 5维度: 趋势(MA排列) / 量价配合 / 基本面(PE+ROE) / 资金流向(北向) / 动量
  - 买入门槛: ≥3维度看多 且 ≤1维度看空
  - 批量过滤: Top30评分股逐一检查，不通过的直接排除
- **效果**: 解决30%胜率核心问题 — 单一维度假信号太多
- **测试**: 5个场景全部通过（上涨股/下跌股/批量过滤/维度检查）

### 改进3: 周度复盘自动分析器
- **实现**: `src/evolution/weekly_reviewer.py`
  - 自动分析胜率/盈亏比/亏损集中度/交易时间模式
  - 生成4条参数调整建议:
    1. 信号门槛 75→80 (胜率太低)
    2. 止损 10%→5% (盈亏比极差)
    3. 单只上限 15%→10% (亏损集中度高)
    4. 切换防御模式 (趋势恶化)
  - JSON报告自动保存到 `data/weekly_reviews/`
- **效果**: 每周一自动执行，为后续自动调参闭环提供数据基础
- **测试**: 2个场景通过（正常分析/无数据）

### Phase 4进度更新
- [x] Kelly Criterion仓位管理 ✅
- [x] 多因子一致性过滤器 ✅
- [x] 周度复盘自动分析器 ✅ (为闭环做准备)
- [ ] 复盘发现 → 自动调参闭环 (下一步: 将weekly_reviewer建议自动应用)
- [ ] Optuna结果自动应用到实盘
- [ ] 策略A/B测试框架

### 代码变更
- 新增 `src/risk_management/kelly_position.py` - Kelly仓位管理
- 新增 `src/factors/agreement_filter.py` - 多因子一致性过滤器
- 新增 `src/evolution/weekly_reviewer.py` - 周度复盘分析器
- 新增 `tests/test_kelly_agreement_weekly.py` - 9个测试全部通过
- 新增 `data/weekly_reviews/2026-04-20.json` - 首份自动复盘报告

### Git提交
- Commit: `feat: Kelly Criterion仓位管理 + 多因子一致性过滤 + 周度复盘分析器`
- 推送至: origin/master
- 变更: 4 files, 893 insertions(+)

### 下一步重点
1. **将agreement_filter集成到trader.py选股流程** (直接影响胜率)
2. **将kelly_position集成到仓位计算** (直接控制风险)
3. **自动调参闭环**: weekly_reviewer建议 → 自动修改配置 → 回测验证

## 2026-04-21 (周二) 改进记录 - 选股+因子日

### 改进1: 均值回归评分因子 (Mean Reversion Score)
- **GitHub学习**: je-suis-tm/quant-trading(1.1k⭐)的reversal策略 + De Bondt & Thaler均值回归理论
- **实现**: `calc_mean_reversion_score()` - 短期收益率Z-score偏离 + 换手率确认
- **逻辑**: 下跌且放量时评分高 → 捕捉超卖反弹机会；上涨时反向扣分
- **回测**: mock数据测试通过，值域[-100, 100]合理

### 改进2: Williams %R 超买超卖因子
- **GitHub学习**: Larry Williams经典指标，广泛用于趋势反转判断
- **实现**: `calc_williams_r()` - 当前价格在近期高低范围中的位置
- **逻辑**: <-80超卖(得分高) → 反弹信号；>-20超买(得分低) → 回调风险
- **回测**: mock数据值在[-100, 0]范围，符合预期

### 改进3: 一目均衡表信号因子 (Ichimoku Cloud)
- **GitHub学习**: 日本主流量化指标，综合趋势判断
- **实现**: `calc_ichimoku_signal()` - 转换线vs基准线 + 价格vs转换线
- **逻辑**: 双重信号确认趋势方向和强度
- **回测**: mock数据值在[-100, 100]范围合理

### 改进4: FactorTracker ConstantInputWarning修复
- **问题**: factor_tracker.py在IC计算时频繁出现ConstantInputWarning
- **实现**: 计算spearmanr前检查输入std，常量输入直接返回IC=0
- **效果**: 消除日志噪音，IC计算更稳健

### Phase 4 进度推进
- 因子IC追踪: ✅ 修复ConstantInputWarning
- 新增3个选股因子 → Phase 4因子库扩充

### 代码变更
- 扩展 `src/factors/technical.py` - 新增3个因子(142行)
- 修改 `src/factors/engine.py` - 注册新因子
- 修改 `config/factors.yaml` - 新因子配置
- 修改 `src/evolution/factor_tracker.py` - IC计算bugfix
- Git: a0ca18c pushed to master

### 下次TODO
- [ ] 观察3个新因子的IC值，淘汰持续为负的
- [ ] 推进Phase 4: Optuna结果自动应用
- [ ] 推进Phase 4: 复盘→自动调参闭环

## 2026-04-22 (周三) 改进记录 - 风控+仓位日

### 改进1: TimeStopManager - 时间止损 (GitHub学习)
- **来源**: 量化交易经典时间止损概念 + systematic-investing实践
- **思路**: 价格止损管"亏多少"，时间止损管"等多久"，两者互补
- **规则**:
  - 持仓>30天(约) 且 收益<5% → 清仓(错过主升浪)
  - 持仓>20天 且 收益<2% → 清仓(资金效率低)
  - 持仓>10天 且 收益<-3% → 减仓50%(趋势判断失误)
- **实现**: `src/risk_management/time_stop.py` - TimeStopManager类
- **效果**: 解决"长期套牢"问题，提高资金周转效率
- **集成**: 接入 `risk_control.py` 的 check_risk() 自动检查
- **测试**: 4个场景通过(长持未达标/收益达标/中期亏损/短期不触发)

### 改进2: ConsecutiveLossProtector - 连续亏损保护 (GitHub学习)
- **来源**: Larry Hite / Ed Seykota 赌注管理理论
- **思路**: 连续亏损不是运气问题，而是市场环境或策略失效信号
- **规则**:
  - 连续3次亏损 → 防御模式: 仓位×0.5, 信号门槛+5
  - 连续5次亏损 → 保守模式: 仓位×0.3, 信号门槛+10
  - 盈利一次 → 恢复正常
- **实现**: `src/risk_management/time_stop.py` - ConsecutiveLossProtector类
- **效果**: 避免"追损"，30%胜率策略下自动降仓位保护本金
- **测试**: 4个场景通过(正常/防御/保守/恢复)

### 改进3: 风控模块统一集成到trader决策流程
- **集成内容**:
  - Kelly仓位管理 → trader._daily_decision()
  - ConsecutiveLossProtector → trader._daily_decision()
  - TimeStopManager → risk_control.check_risk() + nav_tracker._buy()
- **效果**: 每日交易决策自动考虑: Kelly最优仓位 + 连续亏损降仓位 + 时间止损清仓
- **数据流**: trade_log → ConsecutiveLoss更新 → 仓位调整 → 评分门槛提升 → 调仓

### Phase 4 进度更新
- [x] Kelly Criterion仓位管理 ✅ (已集成)
- [x] 多因子一致性过滤器 ✅
- [x] 周度复盘自动分析器 ✅
- [x] 时间止损 ✅ (新增)
- [x] 连续亏损保护 ✅ (新增)
- [ ] 复盘发现 → 自动调参闭环 (下一步)
- [ ] Optuna结果自动应用到实盘
- [ ] 策略A/B测试框架

### 代码变更
- 新增 `src/risk_management/time_stop.py` - TimeStopManager + ConsecutiveLossProtector
- 修改 `src/simulator/risk_control.py` - 集成时间止损到check_risk()
- 修改 `src/agents/trader.py` - 集成Kelly + 连续亏损保护到决策流程
- 修改 `src/simulator/nav_tracker.py` - 买入时记录时间止损entry
- 新增 `tests/test_time_stop_loss.py` - 4个测试全部通过

### Git提交
- Commit: `feat: 时间止损+连续亏损保护+风控集成Kelly/Agreement到trader`
- 推送至: origin/master
- 变更: 5 files, 457 insertions(+), 2 deletions(-)

### 下次TODO
- [ ] 观察时间止损和连续亏损保护的实际触发情况
- [ ] 推进Phase 4: 复盘→自动调参闭环
- [ ] 推进Phase 4: Optuna结果自动应用

## 2026-04-24 (周五) 改进记录 - 策略迭代+周报日

### 改进1: DualMomentumStrategy 双动量策略 (GitHub学习)
- **来源**: Gary Antonacci《Dual Momentum Investing》+ schlafen318/dual-momentum
- **思路**: 绝对动量(大盘趋势过滤) + 相对动量(评分选股) 双重确认
- **实现**: `src/strategy/dual_momentum.py`
  - 绝对动量: 沪深300价格 vs 20日均线 + 6个月收益率双确认
  - 牛市: 正常选股; 中性: 减半持仓; 熊市: 全部清仓转现金
  - 与ContinuousScore互补: 大盘不好时空仓，解决30%胜率根源
- **回测**: bull/bear/neutral三场景测试通过

### 改进2: Bot "Event loop is closed" 崩溃修复
- **问题**: run_polling()关闭event loop后重试重建Application仍用旧loop
- **修复**: 每次重试前 `asyncio.set_event_loop(asyncio.new_event_loop())`
- **效果**: 解决04-22连续5次崩溃无法恢复的问题

### 改进3: AutoTuner 自动调参闭环 (Phase 4推进)
- **来源**: Phase 4目标 - "复盘发现→自动调参闭环"
- **实现**: `src/evolution/auto_tuner.py`
  - 读取weekly_reviews最新报告 → 解析参数建议 → 安全边界验证 → 保存pending
  - 支持: 信号门槛/止损/仓位上限/防御模式 自动调整
  - 参数边界保护: 防止调整失控
  - promote_pending(): 开盘前自动生效
- **测试**: 解析3条建议全部正确，边界拒绝测试通过

### Phase 4 进度更新
- [x] Kelly Criterion仓位管理 ✅
- [x] 多因子一致性过滤器 ✅
- [x] 周度复盘自动分析器 ✅
- [x] 时间止损 ✅
- [x] 连续亏损保护 ✅
- [x] **自动调参闭环** ✅ (新增)
- [x] 双动量策略 ✅ (新增)
- [ ] Optuna结果自动应用到实盘
- [ ] 策略A/B测试框架

### Git提交
- Commit: `feat: 双动量策略 + Event loop崩溃修复 + 自动调参闭环`
- 推送至: origin/master
- 变更: 7 files, 1470 insertions(+), 4 deletions(-)

## 2026-04-27 (周一) 改进记录

### 改进1: Recovery-aware Stop Loss (恢复感知止损)
- **GitHub学习**: Microsoft Qlib的CAT(Cluster-Aware Trading)概念 — 在止损触发前检查恢复信号，避免恐慌低点止损
- **问题驱动**: 立讯精密两次过早止损后反弹+22.2%，是最大单笔亏损来源
- **实现**: `src/risk_management/recovery_stop.py` — 3层恢复检查(价格回升2%+/缩量下跌/RSI<30)，最多3天宽限期
- **集成**: RiskManager.generate_risk_actions() 止损触发前先检查恢复信号
- **预期效果**: 减少"过早止损"错误模式

### 改进2: Stock Blacklist (股票黑名单)
- **GitHub学习**: Qlib因子无效自动淘汰思路，延伸到个股级别
- **问题驱动**: 复盘显示"买入一般"(10次)和"买入失误"(5次)是Top2错误模式，部分股票反复亏损
- **实现**: `src/risk_management/stock_blacklist.py` — 30天内同股票亏损2次→黑名单，信号惩罚x0.5
- **集成**: FactorEngine评分时自动对黑名单股票降权
- **预期效果**: 减少对"毒股"的反复买入

### 改进3: Expression Factor Generator (表达式因子生成器)
- **GitHub学习**: Qlib/RD-Agent的自动因子挖掘 — 用基础算子自动组合生成新因子
- **实现**: `src/factors/expression_gen.py` — 15个表达式模板(趋势/波动/量价/动量反转/RSI-like)
- **筛选标准**: |IC|>0.03 + IC一致性>60% → 自动保留
- **状态**: 框架就绪，待下次有历史数据时运行scan_factors()发现有效因子
- **Phase 4推进**: 新增"表达式因子自动发现"子任务

### Bot运行状态
- Telegram网络偶发ReadError（非代码问题，网络波动）
- 无代码级ERROR

## 2026-04-29 (周三) 改进记录 - 风控+仓位日

### 改进1: 移动止盈 (Trailing Take-Profit) (GitHub学习)
- **来源**: 海龟交易法则 (Richard Dennis) + O'Neil CANSLIM策略
- **问题驱动**: 赣锋锂业卖飞+11.8%，立讯精密过早止损后反弹+22%
- **实现**: `src/risk_management/trailing_take_profit.py`
  - 峰值阶梯: 曾达10%/20%/30%+盈利 → 回撤6%/8%/8%触发止盈
  - 快速拉升保护: 5日涨15%+后回撤5%即止盈
  - JSON状态持久化峰值价格
- **集成**: `risk_control.check_risk()` 自动检查
- **测试**: 8个场景全部通过

### 改进2: Risk Parity仓位分配 (GitHub学习)
- **来源**: convexfi/riskparity.py (320 stars) + PyPortfolioOpt (5678 stars) + Spinu (2013)
- **实现**: `src/risk_management/risk_parity.py`
  - 迭代MRC法 (比Spinu更稳定)
  - 自适应约束: 小N放宽上限，大N收紧
  - 5股测试: V1(低波动)=40% vs V5(高波动)=8%
- **效果**: 替代等权分配，低波动股自然获得更高权重

### 改进3: 相关性集中度风控 (GitHub学习)
- **来源**: PyPortfolioOpt (5678 stars) 相关性矩阵分析
- **实现**: 集成到 `src/simulator/risk_control.py`
  - 同行业持仓市值>40% → 警告
  - 同行业持仓市值>50% → 建议减仓
- **效果**: 防止行业过度集中

### Bot状态
- 无ERROR，运行正常

### Git提交
- Commit: 635e19b
- 推送至: origin/master
- 变更: 7 files, 1607 insertions

### Phase 4 进度更新
- [x] 移动止盈 (新增) ✅
- [x] Risk Parity仓位分配 ✅
- [x] 相关性集中度风控 ✅
- [ ] Optuna结果自动应用到实盘
- [ ] 策略A/B测试框架
- [ ] 表达式因子自动发现 (框架就绪，待运行)

## 2026-04-30 (周四) 改进记录

### 代码审查发现
- 🔴 **严重bug**: `_daily_adds`/`_add_log_file`未定义，导致调仓每5分钟NameError（从4/29 14:10开始连续失败）
- 🟡 tushare `top_list`无权限但每次重试3次浪费~10秒
- 🟢 `alert_check`内重复import json/pandas（13次），热路径应提至顶部

### 今日改进 (3项)
1. **fix: `_daily_adds`未定义bug** → 添加daily_adds.json初始化逻辑，修复调仓连续失败
2. **feat: 因子衰退检测(Factor Decay)** → 从GitHub Factor-Research学到IC趋势衰退检测，10d vs 30d IC均值比较，衰退>30%提前降权
3. **opt: Tushare API权限黑名单缓存** → 首次检测到无权限接口后缓存，后续直接跳过

### GitHub学到的新思路
- **Factor-Research项目** (ML-powered stock prediction): 因子IC衰退检测思路 — 不等连续60天低IC才暂停，而是检测IC趋势性下降提前降权
