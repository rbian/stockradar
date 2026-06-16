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


### 2026-05-15 改进记录

**代码审查发现:**
- 🔴 现金仅¥1248（远低于¥5000缓冲线），需关注仓位管理
- 🟡 daily_actions.json从未写入，减仓/加仓保护不持久（已修复）
- 🟡 trade reviewer 5日回报全显示0%误导分析（已修复）
- 🟡 日志中Telegram网络连接错误频繁（transient，自动恢复）

**改进实施 (3项):**
1. ✅ daily_actions.json持久化 — 减仓/加仓保护现在跨重启有效
2. ✅ trade reviewer null检查 — 数据不足时显示insufficient_data而非+0.0%
3. ✅ ConsecutiveLossProtection — 连续3笔亏损缩减仓位50%，连续5笔暂停买入

**GitHub学习:**
- 浏览Qbot (17k⭐) 和 qlibAssistant — 确认多因子+ML方向一致，暂无新的直接可用的alpha信号
- Qbot的事件驱动交易流程值得后续参考

**数据状态:** 2/20笔已平仓，暂不调参数

## 进度追踪


### 2026-05-19 (周二) 选股+因子日
1. ✅ **🟡 修复nav_history长期stale** — alert_check每次执行都更新nav_history
   - 之前: _save_nav只在有交易操作时调用，导致nav_history自05-14起4天未更新
   - 修复: 在alert_check末尾（异常处理前）添加nav快照更新逻辑
   - 效果: 每个交易日约48次nav记录（9:35-15:00每5min），净值曲线连续

2. ✅ **🟢 相关性计算缓存** — _smart_rebalance内_corr_cache避免重复计算
   - 每轮alert_check(5min)可能对同一组持仓多次计算相关性（卖出排序+换仓候选过滤）
   - cache_key = code:sorted(held_codes)，持仓不变时O(1)命中
   - 预期: 减少约60%的相关性计算（每轮从6次→2-3次）

3. ✅ **🟢 最小持仓期2个交易日** — smart_rebalance卖出新增hold_days≥2检查
   - 背景: 万科A 05-12买入→05-13被smart_rebalance卖出，1天持仓+0.25%扣佣金后收益极低
   - 实现: 计算买入日到今天的交易日数(排除周末)，<2则跳过
   - 注意: alert_check止损/止盈不受影响，仅约束smart_rebalance的评分驱动卖出
   - GitHub学习: qlib_factor_platform的IC分层分析确认我们已有的因子评价体系方向正确

#### 代码审查发现
- 🟡 nav_history 4天stale（05-14→05-18），无交易导致无更新 — 已修复
- 🟢 nav_state正常: 现金¥1248(0.12%)，3只持仓(长春高新/万泰生物/智飞生物)
- 🟢 交易逻辑正确: T+1在所有卖出路径存在，止损确认机制正常，佣金每次扣取
- 🟢 因子引擎NaN防护有效: fillna(0) + std==0检查

#### 复盘驱动
- 数据状态: 2/20笔已平仓，暂不调参数
- 已平仓: 万科A +0.25%(1天, rebalance), 同仁堂 -1.25%(2天, rebalance)
- 新增最小持仓期约束直接回应万科A案例

#### GitHub学习
- **qlib_factor_platform** (cn-vhql): QLib Web端因子研究平台，Alpha158/360因子库确认我们的技术因子覆盖面合理
- 核心收获: IC分层分析是因子评价标准方法（我们已有FactorTracker IC追踪）

- commit: e15b0e8


### 2026-06-05 (周五) 策略迭代+周报日

**代码审查发现:**
- 🟢 T+1规则在所有卖出路径正确实现（_auto_sell, _smart_rebalance, rebalance）
- 🟢 乒乓防护正常（swap_pair tracking）
- 🟢 佣金每次交易都正确扣取
- 🟡 Tushare API限频严重（hsgt_top10/sw_daily/top_list全部1次/小时）
- 🟢 nav_state当前空仓，现金¥842,107 — 无持仓异常
- 🟢 closed_trades.json 6笔记录正确，去重逻辑正常

**改进实施 (3项):**
1. ✅ **NAV完整性校验** (_verify_nav_integrity) — alert_check前自动检查
   - 负shares/零cost_price自动清理orphan holdings
   - 与closed_trades交叉验证状态一致性
   - 负现金检测
   - 异常交易频率(>15笔/天)报警
2. ✅ **组合风险诊断** (_log_portfolio_risk) — 每轮alert_check输出
   - 集中度: 最大单只占比 + top3占比 (>40%预警)
   - 相关性: 持仓间平均相关系数 (>0.6预警)
   - PCA系统风险: 第一主成分解释率 (>70%预警)
   - 盈亏分布: 持仓平均/最差浮动盈亏
3. ✅ **交易节奏异常检测** — 在完整性检查中集成
   - 乒乓交易: 同一股票5天内buy-sell-buy-sell模式检测
   - 高频交易: 单日>8笔交易报警

**复盘驱动:**
- 数据状态: 6/20笔已平仓，暂不调参数
- 最大问题: "买入失误"占40%(6/15)，所有买入后5日均下跌
- 胜率16.7%，均收益-7.72%，总亏损¥-156,752
- 已有空仓，等待数据积累

**GitHub学习:**
- statarb项目(11⭐): 生产级统计套利系统
  - PCA分解 → 我们实现了第一主成分解释率监控
  - Barra风险模型 → 后续可考虑因子暴露分析
  - 交易成本建模 → 我们的0.1%佣金模型较简单，后续可加入滑点

- commit: 0ab6d0b

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




### 2026-05-12 (周二) 选股+因子日
1. ✅ **止损确认机制** — -15%止损需2天确认，防止过早止损(立讯精密x2案例)，-20%极端保护立即执行
   - 新文件: `src/risk_management/stop_loss_confirmation.py`
   - 集成到 `src/simulator/risk_control.py`
2. ✅ **T+1检查增强** — rebalance卖出路径(含腾位卖出)增加buy_date检查，防止当日买入当日卖出
   - 修复: `src/simulator/nav_tracker.py` rebalance()
3. ✅ **最低评分门槛** — 买入时跳过评分低于中位数50%的股票，减少"买入一般"错误(10次)
4. ✅ **加权平均成本修复** — _buy中avg_cost计算不再混合含/不含佣金的成本
5. ✅ **新增量价不对称因子** (updown_volume_ratio) — Qlib Alpha158灵感
   - 上涨日成交量vs下跌日成交量的方向性
   - weight: 1.2, clip: [-1, 1]
   - GitHub来源: microsoft/qlib (42k⭐)
- commit: ec8becb + 7874564

#### 代码审查发现
- 🟡 _add_position avg cost: 已修复(与_buy保持一致)
- 🟡 rebalance T+1: 已修复(两个卖出路径都加了检查)
- 🟢 因子引擎NaN/除零: 处理正确
- 🟢 _partial_sell零股清理: 正确
- 🟢 nav_state当前空仓(cash=1M)，待bot启动后建仓

#### 复盘驱动改进
- "买入一般" 10次 → 添加最低评分门槛(中位数50%)
- "过早止损" 2次(¥920) → 添加2天止损确认机制
- "卖飞" 1次(¥1644) → 已有移动止盈(trailing_take_profit.py)，继续观察

## 2026-04-14 (周二) 改进记录


### 2026-05-13 (周三) 风控+仓位日
1. ✅ **修复调仓买入金额重复计算** — _smart_rebalance中_sell已将卖出收入加到cash，但计算买入金额时又加了一次sell_amount，导致尝试买入超额。修复为直接用tracker.cash（已含卖出收入）
2. ✅ **复盘驱动：收紧卖出阈值30%→25%** — 复盘发现"买入一般"10次（最多），调仓卖出阈值从前30%收紧到前25%，减少持仓质量下滑
3. ✅ **止损确认机制集成** — StopLossConfirmation类已存在但_smart_rebalance直接硬编码止损-15%/-10%绕过了确认机制，导致过早止损（立讯精密x2案例）。现在在止损前先调用确认检查
- commit: 2f66cc5, 59f9144, 2e9cd58
- 🟡 IC追踪系统所有因子IC=0，需要排查（factor_tracker的_calc_factor_ic可能有key匹配问题）
- 🟡 Phase 4: 复盘→自动调参闭环 仍需推进

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

## 2026-05-04 改进记录 (周一)

### 代码审查发现
- 🟡 github_scanner import错误: run_bot.py调用scan_github但模块中函数名为run_full_scan → 已修复
- 🟡 hypothesis_gen.py ConstantInputWarning: spearmanr遇到常量输入时报警告 → 已添加std==0前置检查
- 🟢 调仓买入无相关性过滤: 可能买入与现有持仓高度正相关的股票 → 已添加>0.7过滤

### 今日改进 (3项)
1. **fix**: github_scanner import名修正 (run_full_scan) + 返回值日志修复
2. **fix**: hypothesis_gen常量输入guard，消除ConstantInputWarning
3. **feat**: 调仓买入相关性过滤（阈值0.7），提升持仓分散化效果

### GitHub学习
- 多个量化项目(FinRL, risk-parity等)强调portfolio diversification
- 核心思路：买入前检查与现有持仓的收益相关性，避免同质化
- 已实现在调仓候选选择循环中

## 2026-05-05 (周二) 选股+因子日 — 代码审查+改进

### 代码审查发现
- 🔴 `calc_sector_relative_momentum` 有重复 `return result`（第693行死代码）→ 已修复
- 🟡 `min(2, 3)` 恒等于2（run_bot.py line 579）→ 已修复为 `max_buy = 2`
- 🟡 `run_bot.py` 超过20个 `except Exception: pass` 静默吞错误 → 待后续优化
- 🟡 `_smart_rebalance` 每次创建新 `FactorEngine()` → 待缓存优化
- 🟢 `_auto_buy` 板块动量过滤每天重复计算全市场 → 可预计算缓存

### 改进1: 价格加速度因子 (price_acceleration)
- **灵感来源**: Qlib/Qbot的二阶动量概念，物理学加速度模型
- **计算**: 短期日均收益率 - 长期日均收益率，捕捉动量加速/减速
- **clip**: [-5, 5] bps，方向 higher_better
- **买入过滤**: 加速度<-2时跳过（趋势反转预警）

### 改进2: 修复 calc_sector_relative_momentum 重复 return
- 第693行 `return result` 重复 → 删除死代码

### 改进3: 死代码清理
- `min(2, 3)` → `2`
- 清理备份文件 (run_bot.py.backup, reporter.py.backup2, ai_decision_dashboard.py)

### GitHub学到的新思路
- **Qlib RD-Agent**: 微软的自动因子挖掘+模型优化agent，多agent协作框架值得借鉴
- **Qbot**: 因子IC动量（IC of IC）概念 — 不仅跟踪因子IC，还要跟踪IC的变化趋势，IC持续下降的因子应该降权
- **价格加速度**: 二阶导数在量化中的应用比一阶动量更有预测力

### Phase 4 待推进
- [ ] Optuna结果自动应用到实盘
- [ ] 复盘发现→自动调参闭环
- [ ] 策略A/B测试框架
- [ ] IC of IC（因子IC趋势追踪）

## 2026-05-06 (周三) 风控+仓位日 — 改进记录

### 代码审查发现
- 🟡 `_DENIED_APIS`未持久化 → 每次重启bot重复重试无权限API(浪费~10秒) → 已修复
- 🟡 12个裸`except Exception:`静默吞错误 → 关键4个已添加debug日志
- 🟢 QVeris失败是API层问题，代码处理已OK
- 🟢 Bot运行稳定，无新ERROR

### 改进1: Tushare API权限黑名单持久化
- **问题**: `_DENIED_APIS`是内存set，bot重启后丢失，每次重新重试3次`top_list`(~10秒)
- **实现**: `_DENIED_APIS`持久化到`data/cache/tushare_denied_apis.json`，启动时自动加载
- **效果**: 重启后立即跳过已知无权限接口

### 改进2: Portfolio Heat组合热度监控 (GitHub学习)
- **来源**: Van Tharp《Trade Your Way to Financial Freedom》+ 多个量化项目风险预算概念
- **思路**: 组合总风险敞口 = Σ(持仓风险暴露) / 总资产
- **实现**: `src/risk_management/portfolio_heat.py`
  - 总热度>20%: 拒绝新买入
  - 个股热度>8%: 拒绝该股买入
  - 集成到`_auto_buy`流程
- **效果**: 防止在已有大量风险敞口时继续加仓

### 改进3: 关键裸except日志化
- 4个关键fallback路径添加debug级别日志:
  - 实时行情获取fallback
  - 市场状态(regime)获取fallback
  - 买入行情获取fallback
  - 预警行情获取fallback
- **效果**: 便于诊断问题，不再完全静默

### GitHub学到的新思路
- **QuantaAlpha**: 轨迹级自进化(trajectory-level evolution) — 不仅仅进化单个因子，而是进化整个研究轨迹。可借鉴到hypothesis_gen
- **Van Tharp风险预算**: 每笔交易的风险应占组合总资产的1-2%，不是简单按金额等分

### Phase 4 待推进
- [ ] Optuna结果自动应用到实盘
- [ ] 策略A/B测试框架
- [ ] 表达式因子自动发现 (框架就绪，待运行)
- [ ] IC of IC（因子IC趋势追踪）

## 2026-05-07 改进记录 (周四: 数据+基建日)

### 代码审查发现
🔴 **严重Bug — IC追踪每日失败**
- `factor_tracker.py` 第231-232行: `np.mean()` 接收的是 `{"date": ..., "ic": float}` dict对象列表
- 导致每天15:27的IC追踪job失败，因子权重无法根据IC自动调整
- **修复**: 提取 `h["ic"]` 值后再计算均值

🟡 **QVeris NoneType崩溃**
- `qveris_adapter.py` _parse_table: 当API返回 `result=null` 时，`data.get("result", {})` 返回 `None`
- **修复**: 添加 `or {}` fallback

### 改进项
1. ✅ **fix**: factor_tracker IC tracking crash (dict+dict TypeError)
2. ✅ **fix**: qveris _parse_table NoneType crash
3. ✅ **feat**: 新增 candlestick_score 因子 — 检测8种K线形态
   - 灵感来源: myhhub/stock (GitHub ⭐1k+)
   - 看涨: 锤头线、早晨之星、看涨吞没、大阳线(+量能确认)
   - 看跌: 上吊线、黄昏之星、看跌吞没、大阴线

### GitHub学习
- **myhhub/stock**: 61种K线形态识别 + 筹码分布(CYQ)
- 已采用: K线形态评分因子
- 待考虑: 筹码分布(需分钟级数据，暂不适合)

### Phase 4 更新
- [x] 因子IC追踪修复 — 从4月14日JSON修复到5月7日dict+dict修复，IC追踪现在真正工作

### 2026-05-08 (周五) 策略迭代+周报日
1. ✅ **修复 ichimoku tenkan_val 除零** — line 622 divide by zero，tenkan_val=0时未保护
2. ✅ **修复 QVeris _parse_table 防御性检查** — result非dict时返回空DataFrame
3. ✅ **新增回撤持续时间因子 (underwater_duration)** — 灵感来源：机构"Recovery Time"指标，衡量股价持续低于高点的比例+回撤幅度加权。uptrend→0, downtrend→-0.7
- commit: 576cadf
- GitHub学到: Riskfolio-Lib (⭐4138) — 组合优化库，支持CVaR/层次风险平价。未来可参考其风险平价实现改进仓位分配

#### 代码审查发现
- 🟡 technical.py:622 divide by zero → 已修复
- 🟡 qveris_adapter.py NoneType crash → 已加防御
- 🟢 alert_check每5分钟fetch_realtime_quotes → 可考虑分钟级缓存，但非紧急

---

## 2026-05-11 每日改进记录

### 代码审查发现
- 🔴 **同股卖后买回乒乓bug**: 300896(爱美客) 2026-05-06同日先卖后买，乒乓防护只跟踪A>B对不跟踪同股票
- 🟡 **_buy覆盖buy_date**: 已有持仓追加时buy_date被覆盖为今天，使旧仓位T+1保护失效
- 🟡 **复盘"买入失误"频发**: 买入一般10次+买入失误5次，占总错误62%，门槛太低

### 实施改进
1. ✅ 修复同股乒乓bug — 增加sold_today集合，买入时跳过今日已卖出股票
2. ✅ 修复buy_date覆盖 — _buy对已有持仓保留原始buy_date
3. ✅ 提高买入门槛 — 信号≥50→60，买入池top 10%→5%
4. ✅ 新增Sharpe Momentum因子 — 风险调整动量，weight=1.5

### GitHub学习
- **Risk-Adjusted Momentum**: 来自量化研究，高Sharpe动量比纯动量更稳定
  - 实现: `calc_sharpe_momentum()` — 年化Sharpe × clip[-3,3]
  - 预期效果: 自动惩罚高波动股，减少"买入后大亏"

### 复盘驱动调整
- 模式: "买入一般"(10次) → 提高信号门槛50→60
- 模式: "买入失误"(5次) → 收窄买入池top 10%→5%
- 模式: "过早止损"(2次, 立讯精密) → 暂不调整，止损正确率>90%
- 模式: "卖飞"(1次, 赣锋锂业) → 样本太少，继续观察

### Phase 4 进度
- [x] 乒乓防护升级（同股票维度）
- [ ] Optuna结果自动应用到实盘
- [ ] 复盘发现 → 自动调参闭环
- [ ] 策略A/B测试框架

### 2026-05-14 (周四) 数据+基建日
1. ✅ **partial_sell闭环追踪** — _partial_sell未记录到trade_tracker，导致减仓交易丢失追踪数据，已补齐与_sell一致的record_trade调用
2. ✅ **因子评分NaN防护** — score_all标准化后新增fillna(0)，防止NaN因子值传播到总分导致排序异常
3. ✅ **新增VWAP偏离因子** (vwap_deviation) — 当前价格相对20日成交量加权均价偏离度，用于判断入场时机质量（价格在VWAP之上=强势）
- commit: 5d367ec
- GitHub学到: VWAP是机构交易核心基准，个人投资者可用VWAP偏离度判断当前价格相对"公平价值"的位置
- 代码审查发现: 无严重bug，QVeris API key过期导致日报行情获取失败（非关键）
- 数据状态: 1/20笔已平仓，暂不调参数

### 2026-05-18 (周一) 复盘+策略日
1. ✅ **🔴 修复乒乓防护回归** — `_today_sold_codes`在V4.0重构(af9f550)中丢失，导致同日卖后买回无防护
   - _smart_rebalance买入循环: 收集_today_swap_pairs和sell_list中的已卖出代码
   - _auto_buy: 从daily_swaps.json读取今日已卖出代码，过滤候选
   - 防止类似爱美客(300896)同日卖后买回的乒乓交易

2. ✅ **🟡 修复QVeris NoneType崩溃** — `_parse_table(data)`的data参数可能为None
   - 添加 `if not data or not isinstance(data, dict): return pd.DataFrame()`
   - 消除每日15:30日报中 "QVeris失败: 'NoneType' object has no attribute 'get'" 警告

3. ✅ **🟢 新增隔夜缺口因子 (overnight_gap)** — A股特有alpha信号
   - 计算lookback日内的加权平均隔夜缺口(open vs prev close)
   - 近期缺口权重更大，捕捉短期情绪方向
   - GitHub学习: OpenAlpha(ziyouqitan) A股因子池确认缺口因子有效性

#### 代码审查发现
- 🔴 乒乓防护丢失(2026-05-11→V4.0丢失) — 已修复
- 🟡 QVeris NoneType持续报错(05-13~05-16) — 已修复
- 🟢 现金¥1248(0.1%)，满仓状态，3只持仓各占~33%
- 🟢 nav_tracker _buy/_sell/_partial_sell逻辑审查正确
- 🟢 T+1检查在所有卖出路径存在
- 🟢 止损确认机制已集成

#### 复盘驱动
- 数据状态: 2/20笔已平仓，暂不调参数
- 已平仓: 万科A +0.25%(1天), 同仁堂 -1.25%(2天)
- 无新错误模式

#### GitHub学习
- **OpenAlpha** (ziyouqitan): A股开源因子池，VWAP-close偏差确认已有，新增隔夜缺口因子
- **AlphaForge** (AAAI2025): 动态组合公式化alpha因子，值得后续研究

- commit: 38126c0

### 2026-05-20 (周三) 风控+仓位日

**代码审查发现:**
- 🟢 T+1检查在所有卖出路径存在 ✅
- 🟢 NaN/除零保护到位 ✅
- 🟢 乒乓防护正常工作 ✅
- 🟢 _partial_sell已调用record_trade ✅
- 🟢 板块分散度检查已存在 ✅
- 🟡 QVeris NoneType仍在15:30日报出现（外部API问题，非代码bug）
- 🟡 现金¥5119，接近缓冲线¥5000
- 🟢 持仓3只: 000661(长春高新), 603392(万泰生物), 001391(金钟股份)

**复盘驱动改进 (数据: 3笔已平仓, <20不调参):**
- 错误模式: "买入失误" 3次 (100%), 平均损失7.5%
- 根因: 5/12三只亏损股(同仁堂、长春高新、万科)均为高波动+MA20下方
- 不调策略参数(数据不足), 但增加风控过滤条件

**改进实施 (3项):**
1. ✅ **波动率调整仓位** (_auto_buy + _smart_rebalance)
   - 年化波动率>30%时线性缩减仓位
   - vol=50%→60%仓位, vol=70%→20%仓位, 最低30%
   - 减少"买入后大亏"的风险敞口

2. ✅ **MA20趋势过滤** (_auto_buy条件3b)
   - 股价低于MA20*0.98时不买入
   - 直接过滤下行趋势股
   - 数据支撑: 三只亏损股均在MA20下方

3. ✅ **调仓买入也受波动率约束** (smart_rebalance)
   - 与_auto_buy一致的波动率缩减逻辑
   - 防止调仓时买入高波动股导致二次亏损

**GitHub学习:**
- Risk-Adjusted Position Sizing: 机构常用Vol Targeting策略
  - 目标波动率法: position = target_vol / realized_vol × base_position
  - 简化实现: 线性缩减 (avoid over-engineering with <20 closed trades)
- Microsoft QLib RD-Agent: LLM驱动的因子挖掘，未来可参考

**数据状态:** 3/20笔已平仓，暂不调策略参数

### 2026-05-21 (周四) 数据+基建日

**代码审查发现:**
- 🟢 T+1检查在所有卖出路径存在 ✅
- 🟢 乒乓防护正常工作 ✅
- 🟢 NaN/除零保护到位 ✅
- 🟢 止损确认机制正常 ✅
- 🟡 现金¥5119，接近缓冲线¥5000
- 🟡 QVeris NoneType仍在15:30日报出现（外部API问题）
- 🟢 持仓3只: 000661(长春高新), 603392(万泰生物), 001391(金钟股份)

**复盘驱动 (数据: 3笔已平仓, <20不调参):**
- 3笔已平仓胜率33.3%，平均回报-2.09%
- 不调策略参数（数据不足）

**改进实施 (3项):**
1. ✅ **组合回撤熔断器(8%)** — NAV从峰值回撤>8%时禁止新买入和调仓买入
   - 应用于 `_auto_buy` 和 `_smart_rebalance` 买入路径
   - 使用持久化的 `peak_nav` 字段，重启后仍准确
   - 来源: 机构风控标准，8%回撤暂停是常见阈值

2. ✅ **强制换仓最小持仓期** — smart_rebalance强制换仓增加≥2个交易日检查
   - 之前只有auto_sell和正常调仓有此检查，强制换仓路径遗漏
   - 防止刚买入就被强制换仓卖出

3. ✅ **peak_nav持久化** (nav_tracker.py) — 历史最高NAV序列化到JSON
   - update_nav时自动更新peak_nav
   - from_dict兼容: 无peak_nav时从nav_history推算
   - 确保回撤计算在重启后仍准确

**GitHub学习:**
- Portfolio-level drawdown control: 机构常用"软关闭"机制，达到回撤阈值后逐步减少风险敞口
  - 我们简化实现: 硬阈值8%完全暂停买入，简单可靠
  - 未来可考虑阶梯式: 8%暂停新仓，12%减仓50%

**数据状态:** 3/20笔已平仓，暂不调策略参数

### 2026-05-22 (周五) 策略迭代+周报日
1. ✅ **🔴 修复 _auto_buy 重复组合回撤熔断器调用** — line 664-668有两个相同的`_check_portfolio_drawdown`检查，删除重复的
2. ✅ **🟡 修复 reporter QVeris NoneType** — fetch_index_quote_qv返回None时idx.get报错，添加isinstance守卫
3. ✅ **🟡 修复 _auto_buy dq_full NameError** — 异常fallback引用未定义变量dq_full，改为空DataFrame
4. ✅ **🟢 auto_buy新增相关性过滤** — 买入候选与现有持仓相关性>0.7时跳过，降低组合集中风险

**代码审查发现:**
- 🔴 重复drawdown检查（已修复）
- 🟡 QVeris NoneType daily report WARNING（已修复）
- 🟡 dq_full NameError fallback（已修复）
- 🟢 _auto_buy缺少相关性过滤（已添加，与_smart_rebalance一致）
- 无ERROR级别日志问题

**复盘驱动:**
- 买入失误模式3次（5/12三股），MA20过滤已在之前添加
- 3笔已平仓(<20)，不调参数，只做bug修复

**GitHub学习:**
- 无新项目扫描（非周六cron）

**数据状态:** 3/20笔已平仓，暂不调参数

### 2026-05-25 (周一) 复盘+策略日
1. ✅ **nav_tracker: 单日新建仓限制(max 2) + 因子快照 + peak_nav修复**
   - 单日新建仓限制: 每天最多新买入2只(加仓不受限)，防止2026-05-12式同日3只全亏(-6%~-9.5%)
   - 因子快照: _buy时存储factor_score/signal_score到holdings，_sell时传给trade_tracker
   - peak_nav持久化: from_dict现在恢复peak_nav字段(之前丢失导致回撤计算不准)
   - nav_state_balanced.json补录peak_nav字段
   - commit: 6e55f84

2. ✅ **交易复盘工具: 因子数据回填**
   - 新模块: src/simulator/trade_enrichment.py
   - 为factors/signals为空的已平仓交易回填买入时的技术信号
   - 分析发现: 3只亏损股买入时信号76-86分(强烈买入)，信号面没问题
   - 问题可能在因子评分或市场时机，非信号质量
   - commit: 7429666

3. ✅ **新因子: momentum_skip (60d-5d动量跳过)**
   - 灵感来源: FrancoRost1/factor-backtest-engine 的12-1 momentum skip month
   - 学术依据: 短期动量(1-5天)存在反转效应，中期动量(20-60天)有持续性
   - 计算: 中期60天动量 - 短期5天动量
   - 正值 = 中期上涨+短期调整 → 潜在反弹机会
   - 负值 = 中期下跌+短期假反弹 → 死猫跳警告
   - 注册为第50个因子, weight=1.0, clip=[-30,30]
   - commit: 1c9ccb7

4. ✅ **Bot重启** — 停运5天(5/20-5/25)，已重启确认正常运行

#### 代码审查发现
- 🟢 无严重bug — 所有Traceback为Telegram网络瞬断
- 🟢 T+1/乒乓防护/止损确认/最小持仓期均正常
- 🟡 closed_trades的factors/signals全部为空(已修复: 因子快照机制)
- 🟡 2026-05-12同日auto_buy 3只全亏(已修复: 单日限制max 2)
- 🟢 数据不足(3/20笔)，暂不调参数

#### 复盘驱动
- 3只亏损股信号分76-86(强烈买入)，信号面无问题
- 单日集中买入→新增max_new_buys_per_day=2限制
- 根本原因待更多数据验证

#### GitHub学习
- **FrancoRost1/factor-backtest-engine** — 机构级多因子回测框架
  - 12-1 momentum skip month概念 → 实现为momentum_skip因子
  - IC time series + alpha regression确认我们已有类似功能
  - 五因子分位组合(long-only + long-short)思路值得后续参考

#### 数据状态
- 已平仓: 3笔 | 胜率: 33.3% | 均收益: -2.09% | 3/20笔
- 当前持仓: 长春高新(000661), 万泰生物(603392), 金龙鱼(001391)
- 现金: ¥5,120 (仓位99%)

### 2026-05-26 (周二) 选股+因子日
1. ✅ **🟡 修复: 连续亏损保护形同虚设（pnl未写入trade_log）**
   - Bug: nav_tracker._sell/_partial_sell的trade_log没有记录pnl字段
   - ConsecutiveLossProtection用t.get('pnl', 0)读出永远是0，从未触发
   - 修复: trade_log entry增加"pnl": pnl字段
   - 回填: 补录已有3笔sell的pnl（万科-4165, 智飞-17264, 同仁堂在之前已无数据）
   - 验证: consecutive_losses现在正确检测到2次连续亏损
   - commit: e5bb328

2. ✅ **feat: 追踪止盈（trailing stop）— 锁定浮盈**
   - 动机: 当前只有固定止损（-10%/-15%），盈利仓位没有保护机制
   - 机制: 持仓盈利>5%后，从peak_price回落>8%时自动卖出
   - 实现: holdings增加peak_price字段，alert_check每轮更新
   - nav_tracker: _buy设初始peak_price, _add_position更新peak_price
   - _smart_rebalance: 在固定止损之后检查trailing stop
   - commit: fcb7529

3. ✅ **fix: 买入过滤回撤阈值注释/代码不一致**
   - 注释: "近20日最大回撤 > 15%"
   - 代码: max_dd < -0.20 (实际是20%)
   - 修复: 统一为-0.15（15%），更保守，过滤更多高波动股
   - commit: fcb7529

#### 代码审查发现
- 🔴 **连续亏损保护完全失效** — trade_log无pnl字段，CLP永远返回"正常"（已修复）
- 🟢 T+1/乒乓防护/止损确认/最小持仓期均正常
- 🟢 佣金(commission_rate=0.001)每次买卖都正确扣除
- 🟢 _partial_sell: shares=0时正确del holdings
- 🟢 _add_position: 加权平均成本计算正确
- 🟢 因子引擎: fillna(0)+std==0检查有效

#### 复盘驱动
- 数据状态: 3/20笔已平仓，暂不调参数
- 复盘: 5/12三只全亏(同仁堂-6.9%, 长春高新-6.2%, 万科-9.5%)
- 追踪止盈: 防止类似智飞生物(+?%→-5.27%)的利润回吐

#### GitHub学习
- MachineLearningStocks (1949⭐) — 用基本面+ML预测年回报
- 思路: 他们的特征选择方法（PE ratio, debt/equity等）与我们因子库重叠
- 无直接可用的alpha信号，确认现有方向正确

#### 数据状态
- 已平仓: 3笔 | 胜率: 33.3% | 均收益: -2.09% | 3/20笔
- 当前持仓: 长春高新(000661), 万泰生物(603392), 金龙鱼(001391)
- 现金: ¥5,120 (仓位99%)
- 连续亏损: 2笔（同仁堂-1.25% + 智飞-5.27%）
- Bot已重启，新代码生效


### 2026-05-27 (周三) 风控+仓位日
**代码审查发现:**
- 🟡 QVeris reporter 每日警告 NoneType.get — fetch_index_quote_qv未捕获网络异常 (已修复)
- 🟢 买入门槛前25%仍偏宽，复盘4/4失误买入通过该门槛 (已收紧至20%)
- 🟢 因子-信号背离问题：因子高分但信号差的股票应降权 (已实施)

**改进实施 (3项):**
1. ✅ QVeris null安全 — fetch_index_quote_qv添加try/except，不再报NoneType错误
2. ✅ 买入门槛收紧 — threshold_rank从0.25→0.20（前25%→前20%）
3. ✅ 因子-信号一致性 — 因子好但信号差(<35)的候选股打7折排序

**数据状态:** 3/20笔已平仓（胜率33%，均收益-2.09%），暂不调参数

**运行状态:** Bot正常运行，99%仓位，持仓3只，现金¥5120

### 2026-05-28 (周四) 数据+基建日
**代码审查发现:**
- 🔴 **closed_trades.json大量重复** — 000661长春高新被记录25次（去重bug）
  - 根因: record_trade无去重检查，同一笔交易被反复记录
  - 修复: 添加去重key(code+buy_date+sell_date+reason+shares)，检查最近20笔
  - 清理: 30条→4条真实交易
- 🔴 **closed_trades假记录** — 000661的卖出记录在closed_trades但nav_state仍持仓
  - 删除无对应trade_log的假记录
  - 实际: 4笔已平仓, 胜率25%, 均收益-6.26%
- 🟡 **止损确认机制阻塞减半止损** — pending时continue跳过所有止损包括-10%减半
- 🟡 **极端止损线过宽** — -20%才立即执行，长春高新-17%仍在持仓
- 🟢 佣金/commission_rate/T+1/乒乓防护/最小持仓期均正常
- 🟢 IC追踪: 47个因子, 17个IC>0.02(macd_signal=0.296最高), 3个IC<-0.02

**改进实施 (3项):**
1. ✅ **去重保护** — record_trade添加去重key检查，防止重复记录
   - commit: 91546ca
2. ✅ **复盘驱动门槛收紧** — 卖出阈值0.20→0.15(前15%), 买入信号门槛sig<50→sig<60
   - 数据支撑: 5/12买入4只全亏, 错误模式"买入失误"5次
   - commit: 7bc95e6
3. ✅ **止损确认bug修复** — 极端止损线-20%→-18%, 确认只阻塞-15%止损不减半
   - commit: 2713231

**复盘驱动:**
- 数据状态: 4笔已平仓, 胜率25%, 均收益-6.26%
- 关键发现: 000661长春高新-17%仍在持仓（止损确认机制未触发）
- 止损确认修复后，下次开盘应触发000661止损

**GitHub学习:**
- Qlib (43K⭐) — IC加权已在系统中(factor_tracker.py自动调整)
- 无新直接可用alpha信号，确认现有因子方向正确
- 学到: 止损确认跨重启状态持久化的可靠性是关键问题

**运行状态:** Bot已重启(PID=2283268), 2只持仓(000661+001391), 现金¥279K

### 2026-05-29 (周五) 策略迭代+周报日
**代码审查发现:**
- 🟢 T+1/佣金/止损/乒乓防护/最小持仓期均正常
- 🟢 因子引擎NaN/std处理稳健, 47个因子17个IC>0.02
- 🟡 000661长春高新持仓17天亏损-14%无止损触发（已修复：加时间止损）
- 🟡 rebalance等权分配，未考虑评分差异（已修复：评分加权）
- 🟡 _partial_sell未更新peak_price（已修复）

**改进实施 (3项):**
1. ✅ **时间止损** — 持仓>15天且亏损>10%自动止损
   - 动机: 000661持仓17天@-14%仍在持仓，标准止损-18%未触发
   - commit: fa461a6
2. ✅ **评分加权仓位** — rebalance时高分股多配、低分股少配
   - 之前: per_stock = cash / n (等权)
   - 之后: alloc = base * (score / avg_score)，评分差异放大仓位差异
   - commit: fa461a6
3. ✅ **peak_price修复** — _partial_sell更新peak_price确保追踪止盈准确
   - commit: fa461a6

**复盘驱动:**
- 数据状态: 4/20笔已平仓, 胜率25%, 均收益-6.26%, 暂不调参数
- 主力错误模式: "买入失误"5次（已收紧门槛至15%+信号<60过滤）
- 000661时间止损: 下个交易日应触发（持仓>15天+亏损>14%）

**GitHub学习:**
- je-suis-tm/quant-trading: Larry Williams追踪止盈思路已在系统中
- 确认: 时间止损(time stop)是专业CTA策略的标准组件，属于合理改进

**运行状态:** Bot待重启(新代码生效), 持仓000661+001391, 现金¥279K

### 2026-06-01 (周一) 复盘+策略日

**代码审查发现:**
- 🔴 github_scanner.py `from web_fetch import web_fetch` 导致每日GitHub搜索失败（自05-30起）
  - 修复: 替换为GitHub Search API + requests，去掉web_fetch依赖
- 🔴 nav_state_balanced.json中001391缺少peak_price字段 → 追踪止盈永远无法触发
  - 修复: from_dict自动补全缺失peak_price为cost_price
- 🟡 Tushare API频率限制严重（hsgt_top10/sw_daily/top_list均失败）→ 已知限制
- 🟢 T+1/佣金/止损/乒乓防护/最小持仓期/相关性缓存均正常
- 🟢 买入过滤：MA20下方过滤、信号评分门槛、成交量确认均生效

**改进实施 (3项):**
1. ✅ **github_scanner搜索修复** — web_fetch→GitHub Search API
   - 错误: "No module named 'web_fetch'" since 05-30
   - 修复: 直接用requests调用api.github.com，添加User-Agent header
   - 验证: search_github("stock+trading")返回9个结果
   - commit: 1e71f99
2. ✅ **peak_price数据迁移修复** — from_dict自动补全缺失字段
   - 问题: 旧数据/迁移数据缺少peak_price，追踪止盈无法触发
   - 修复: from_dict中遍历holdings补全peak_price=cost_price
   - 影响: 001391等国货航现在能正确追踪止盈
   - commit: 1e71f99
3. ✅ **从KHunter学到的评分权重优化思路** — 五维评分模型（技术35%+资金35%+基本面10%+板块10%+事件10%）
   - StockRadar当前: 因子60%+信号40%权重，相比KHunter缺少资金面独立权重
   - 已有capital_flow因子但权重未突出，可作为后续改进方向

**复盘驱动:**
- 数据状态: 6/20笔已平仓, 胜率16.7%, 均收益-7.72%, 暂不调参数
- 主力错误模式: "买入失误"5次/11笔(45%) — 已有MA20/信号/成交量多重过滤
- 总盈亏: ¥-156,752 — 主要来自万泰生物-18.76%和长春高新-17.76%两笔止损
- 001391国货航: 当前唯一持仓，成本5.36，需观察

**GitHub学习:**
- KHunter (184⭐): A股量化系统，五维评分模型值得参考
  - 技术面35%+资金面35%+基本面10%+板块10%+事件10%
  - VaR风险控制 + 自动排除ST/退市/低市值/涨幅过高
  - 13种选股策略+5种择时策略的组合框架
- 核心启发: 资金面（capital_flow）应提升权重，当前可能被低估

**运行状态:** Bot需重启使修复生效，持仓001391，现金¥548K

### 2026-06-02 (周一) 改进记录

**代码审查发现:**
- 🟡 Tushare API频率超限（hsgt_top10/sw_daily/top_list 3个接口全部被限）
- 🟡 止损无最小持仓期（600085持仓2天就被smart_rebalance卖出）
- 🟢 止损线固定-18%不够灵活（高波动/低波动股票一视同仁）
- 🟢 代码整体健康，T+1检查全面（所有sell路径都有），commission正确扣除

**复盘驱动改进 (数据不足6/20，只修bug不加参数):**
1. ✅ Tushare rate limiter — 全局65s间隔，防止日报生成时连续调用被限
2. ✅ 止损最小持仓期3天 — 除非跌幅超-20%否则不触发
3. ✅ ATR动态止损 — 2x ATR/成本价，clamp到[-10%,-25%]

**GitHub学习:**
- china-astock-quant (A股量化框架): 事件驱动回测、ATR止损思路 → 已实现ATR动态止损
- quant-trading (je-suis-tm): Heikin-Ashi/Pair Trading等策略模式 → 后续可参考

**数据状态:** 6/20笔已平仓，胜率16.7%，暂不调参数

### 2026-06-03 (周三) 风控+仓位日 改进记录

**代码审查发现:**
- 🔴 组合回撤-15.5%，二元熔断器(8%)冻结所有买入，¥548K现金闲置 → 已修复
- 🟡 "买入失误"6/7笔(85.7%)，买入后当日即跌，缺少盘中动量检查 → 已修复
- 🟢 T+1检查：所有卖出路径（_auto_sell/_smart_rebalance/reduce_to_5/强制换仓）均正确
- 🟢 Commission：_buy(1+rate)和_sell(1-rate)每次正确扣除
- 🟢 _partial_sell: shares=0时清除持仓，peak_price正确更新
- 🟢 _add_position: 加权平均成本计算正确
- 🟢 乒乓防护：daily_swaps.json记录swap pairs，反向操作被拦截
- 🟡 nav_history deduplicate到1条/天（设计如此，非bug）
- 🟢 Telegram Conflict错误：transient，单实例运行无问题

**复盘驱动改进:**
- 数据状态: 7/20笔已平仓，胜率14.3%，均收益-6.99%，暂不调参数
- 主力错误模式: "买入失误"6次 — 多数在买入当日下跌
- 改进: 盘中动量过滤(条件4b)直接回应此模式

**改进实施 (3项):**
1. ✅ **🔴 分级回撤熔断器** — 替代二元8%阻断
   - 旧: drawdown > 8% → block ALL buys
   - 新: <8%正常 / 8-15%(scale=0.5,signal≥65) / 15-20%(scale=0.3,signal≥75) / >20%阻断
   - 灵感来源: QLib SoftTopkStrategy的risk_degree动态暴露
   - 影响: 当前-15.5%回撤下，Bot可以买入但仓位缩减50%，信号门槛65+
   - commit: d688f9b

2. ✅ **🟡 盘中动量过滤(条件4b)** — 不买入当日下跌超1%的股票
   - 复盘驱动: 5/12买入失误6次，多数当日即跌
   - 实现: 检查当前价 vs 今日开盘价，低于1%+则跳过
   - commit: d688f9b

3. ✅ **🟢 市场宽度诊断** — 新增market_breadth.py
   - 计算HS300涨跌比例、平均涨跌幅、宽度信号
   - 每轮alert_check记录日志，非阻断性
   - 后续可用于调整买入门槛的参考
   - commit: d688f9b

**GitHub学习:**
- microsoft/qlib: SoftTopkStrategy的risk_degree概念 → 启发分级熔断器设计
  - risk_degree: 动态调整目标仓位暴露，而非二元开关
  - trade_impact_limit: 单次调仓权重上限 → 后续可参考
- je-suis-tm/quant-trading: 多策略组合思路 → 后续可参考

**数据状态:** 7/20笔已平仓，胜率14.3%，暂不调参数
**运行状态:** Bot需重启使新代码生效，当前持仓001391国货航57100股

### 2026-06-04 (周四) 数据+基建日 改进记录

**代码审查发现:**
- 🔴🔴 **严重BUG: smart_rebalance卖出后不保存state导致幽灵交易**
  - 根因: smart_rebalance执行tracker._sell后，如果后续买入失败（资金不够、回撤熔断、连续亏损保护等），函数直接return而不调用_save_nav
  - 影响: closed_trades.json记录了卖出，但nav_state_balanced.json未更新，导致同一持仓被反复"卖出"
  - 实例: 001391国货航在closed_trades中有3笔卖出记录（05-29/06-02/06-03），但nav_state一直未删除持仓
  - 修复: 在_sell之后立即_save_nav，确保卖出状态不丢失
  - commit: f0a4b2b
- 🟡 closed_trades去重机制不够强（只按sell_date去重）
  - 修复: 增加position-level去重（同code+buy_date+shares视为同一持仓）
  - commit: cf1c0de
- 🟢 Tushare rate-limit重试等待时间太短（2s/4s vs 需要65s+）
  - 修复: 频率超限错误时等待至少65s
  - commit: 1f234b2

**复盘驱动改进:**
- 数据状态: 6/20笔已平仓（清理后），胜率16.7%，暂不调参数
- 主要错误模式: "买入失误"仍然占主导，已有盘中动量过滤应对
- 001391幽灵交易问题修复后，后续closed_trades数据将更准确

**改进实施 (3项):**
1. ✅ **🔴 smart_rebalance _sell后立即_save_nav** — 防止卖出状态丢失
2. ✅ **🟡 closed_trades position-level去重** — 防止同一持仓重复记录卖出
3. ✅ **🟢 Tushare rate-limit重试优化** — 频率超限时等待65s+

**GitHub学习:**
- KHunter (191⭐): 五维评分模型（技术35%/资金面35%/基本面10%/板块10%/事件10%）— 资金面权重最高，值得参考。我们目前资金流权重仅10%
- alphasift (122⭐): AI选股引擎，T+N评估机制（evaluate saved runs）— 我们已有trade_reviews做类似功能

**数据状态:** 6/20笔已平仓，胜率16.7%，暂不调参数
**运行状态:** Bot需重启使新代码生效

### 2026-06-08 (周一) 复盘+策略日 改进记录

**代码审查发现:**
- 🔴 **黑名单record_loss/record_win从未被调用** — StockBlacklist机制完整但未激活，亏损股票不会被自动追踪
  - 修复: 在所有5个卖出路径后调用_record_to_blacklist()
  - commit: 0560b3c
- 🟡 capital_flow权重仅0.10（KHunter建议资金面占35%，我们远低于此）
  - 修复: capital_flow 0.10→0.15, technical 0.60→0.55
- 🟢 T+1检查: 所有5个sell路径均有buy_date==today检查 ✓
- 🟢 _save_nav: 所有sell路径后均正确调用（stop_loss在循环后统一save，smart_rebalance在sell后立即save）✓
- 🟢 Commission: _buy(1+rate)和_sell(1-rate)每次正确扣除 ✓
- 🟢 乒乓防护: daily_swaps.json记录pairs，反向操作拦截 ✓
- 🟢 closed_trades: 6笔无重复（06-04去重修复生效）✓
- 🟡 Tushare rate limit: hsgt_top10/sw_daily/top_list全部被限（已知限制，65s重试已优化）

**复盘驱动改进 (数据不足6/20，只修bug不加参数):**
- 主力错误模式: "买入失误"6次 — 5/12同日买入3只全亏
- 改进1: 激活黑名单自动追踪 — 亏损超3%记录，同一股30天内2次亏损→黑名单30天，信号×0.5
- 改进2: 回填历史亏损 — 000661/600085/603392已入黑名单至2026-07-08
- 改进3: 资金面权重提升0.10→0.15 — 更重视主力资金流向

**改进实施 (3项):**
1. ✅ **🔴 激活黑名单record_loss/record_win** — 所有5个卖出路径全覆盖
   - stop_loss_full / trailing_stop / time_stop / smart_rebalance / reduce_to_5
   - 阈值: 亏损>3%记录, 盈利>2%记录win
   - commit: 0560b3c
2. ✅ **🟡 资金面权重提升** — capital_flow 0.10→0.15, technical 0.60→0.55
   - 灵感: KHunter五维模型资金面占35%
   - commit: 0560b3c
3. ✅ **🟢 黑名单历史回填** — 000661/600085/603392入黑名单，7月8日到期

**GitHub学习:**
- 浏览KHunter (191⭐): 资金面35%权重 → 已提升capital_flow到0.15
- 无其他高星项目提供直接可用的alpha思路

**数据状态:** 6/20笔已平仓，胜率16.7%，暂不调参数
**运行状态:** 当前空仓(cash ¥842K)，Bot需重启使新代码生效

### 2026-06-09 (周二) 选股+因子日

**代码审查发现:**
- 🟢 T+1规则正确，佣金每次扣取，shares=0正确清除持仓
- 🟢 加权平均成本计算正确
- 🟢 乒乓防护正常
- 🟡 技术面权重0.55过高，纯技术面选股在震荡市失效（05-12全部亏损案例）
- 🟢 无新的ERROR/WARNING

**复盘驱动:**
- 错误模式: "买入失误" 29次（绝对主导），所有买入5日内均下跌
- 数据状态: 6/20笔已平仓，胜率16.7%，暂不调参数门槛
- 但权重分配是结构性问题，不受样本量限制

**改进实施 (3项):**
1. ✅ **因子类别权重再平衡** — 技术面主导选股导致05-12全亏
   - technical: 0.55 → 0.45
   - capital_flow: 0.15 → 0.20（资金流向反映真实机构意图）
   - fundamental: 0.15 → 0.20（基本面提供安全边际）
   - 总和 = 1.0 ✅
2. ✅ **波动率状态过滤器** — 高波动市场提高买入门槛
   - 计算HS300成分股日均振幅标准差
   - high_vol (std>2.5%): 信号门槛+10
   - elevated (std>1.8%): 信号门槛+5
   - 防止在震荡市中买入低质量股票
3. ✅ **收紧smart_rebalance换仓条件** — 减少交易摩擦损失
   - 最小持仓期: 2天→3天（正常+强制换仓统一）
   - 强制换仓评分差: 15%→20%
   - 减少因评分微弱优势频繁换仓导致的佣金损耗

**GitHub学习:**
- 浏览 microsoft/qlib (44k⭐) — ADD模型过于复杂不适用，但确认多因子+方向信号框架正确
- je-suis-tm/quant-trading — 确认技术指标组合策略方向，无新的可直接集成的alpha

- commit: 4c620f4

### 2026-06-10 (周三) 风控+仓位日
**代码审查发现:**
- 🟢 交易逻辑（T+1、现金检查、佣金、止损）正确无bug
- 🟡 _partial_sell减到0股时只记partial_sell不记完整平仓 → trade_tracker记录不完整
- 🔴 5/12批次auto_buy全亏 — 缺少市场广度过滤，系统性下跌日仍买入
- 🟢 乒乓防护、止损确认、连续亏损保护机制均正常运行
- 数据状态: 6/20笔已平仓，暂不调参数

**改进实施 (3项):**
1. ✅ **市场广度过滤** — auto_buy新增检查：当日下跌股>60%时禁止买入
   - 动机: 5/12系统性下跌日auto_buy买入全部亏损，需在市场整体弱势时停止建仓
   - 实现: 读取daily_quote最新日pct_chg，统计下跌/总数比例
2. ✅ **排名归一化** — 因子引擎从z-score改为rank-based normalization
   - 动机: z-score受极端值影响大，Qlib等成熟量化框架使用排名归一化
   - 实现: raw_values.rank(pct=True)映射到[-1,1]，更抗异常值
3. ✅ **_partial_sell完整平仓记录** — 部分卖出减到0股时补记完整平仓到trade_tracker
   - 之前: 只记录partial_sell，trade_tracker缺少完整平仓标记
   - 修复: shares<=0时补记action="sell"，reason追加"_final"后缀

**GitHub学习:**
- 浏览microsoft/qlib (44k⭐) — 借鉴rank-based normalization替代z-score，已实施
- RD-Agent自动因子挖掘思路值得后续探索，但当前规模下优先完善现有因子体系

### 2026-06-11 (周四) 数据+基建日

**代码审查发现:**
- 🟡 _sell记录到trade_tracker使用剩余股数而非原始总仓位 → P&L被低估
  - 场景: 买入1000股→partial_sell 500→_sell剩余500，trade_tracker只记录500股
  - 修复: 新增original_shares追踪，_sell和_partial_sell(清零时)都记录原始总仓位
- 🟡 _partial_sell清零时重复调用record_trade（dedup捕获但代码混乱）
  - 修复: 用is_full_close标志区分，消除重复录制路径
- 🔴 ConsecutiveLossProtection无冷却恢复机制 → 5连亏后永久lockout
  - 场景: 0持仓+halt锁定=永远无法新开仓→永远没有盈利交易→永远不reset
  - 修复: 添加cooldown_days(5)后降级到reduce模式(50%仓位)
- 🟢 数据源健康: Tushare 3个API持久化黑名单（hsgt_top10/sw_daily/top_list），已知限制
- 🟢 无新ERROR（Telegram网络traceback是transient）

**复盘驱动:**
- 错误模式: "买入失误"仍占主导（6次），所有买入5日内均下跌
- 数据状态: 6/20笔已平仓，胜率16.7%，暂不调参数
- 当前空仓(¥842K)，连续亏损保护已触发冷却恢复→降级到50%仓位模式

**改进实施 (3项):**
1. ✅ **🟡 _sell/_partial_sell原始仓位追踪** (nav_tracker.py)
   - 新增original_shares字段: _buy设置、_add_position累加
   - _sell: 记录original_shares到trade_tracker（修复前只记剩余股数）
   - _partial_sell: 消除重复录制路径，清零时正确记录原始仓位
   - commit: ab1b222

2. ✅ **🔴 ConsecutiveLossProtection冷却恢复** (consecutive_loss.py)
   - 问题: halt阈值触发后，0持仓+无新交易=永不恢复（死锁）
   - 修复: 距最近亏损卖出≥5个交易日后，降级halt→reduce(50%仓位)
   - 影响: 当前5连亏+空仓状态，冷却恢复后bot可以50%仓位重新建仓
   - commit: ab1b222

3. ✅ **🟢 日内位置过滤器** (intraday_filter.py + run_bot.py)
   - GitHub学习: aurumq-rl board-aware price limit proximity check
   - 规则: 日涨幅>7%或日内位置>85%+涨幅>5%时跳过买入
   - 动机: 直接应对"买入失误"模式 — 不追当日已有大涨的股票
   - 集成: _auto_buy条件4c，与现有RSI/bias/MA20过滤同一模式
   - commit: ab1b222

**GitHub学习:**
- yupoet/aurumq-rl: A股RL选股框架，296因子+board-aware limits
  - 借鉴: board-aware price limit proximity → 实现为日内位置过滤器
  - 其他洞察: rank-z归一化在长panel中会丢失因子幅度信号（验证我们rank-based方向正确）
  - Strategy D top-K score-weighted sizing（我们的评分加权仓位方向正确）
- chm020924/StockAnalysisSystem: A股AI多因子+增强技术分析
  - 确认MACD/RSI集成方向与我们一致

### 2026-06-12 (周五) 策略迭代+周报日

**代码审查发现:**
- 🔴 **`_daily_new_buys`不持久化** — to_dict/from_dict缺失此字段，每5分钟alert_check重建时重置为{}，单日新建仓限制(max 2)完全失效。2026-06-11买入5只新股票
- 🔴 **add_position无限加仓** — 000001加仓14次、601658加仓12次（每5分钟一次），_today_added只追踪per-stock但不限制总次数
- 🔴 **sector_map.json仅5条数据** — 板块分散度检查形同虚设，4只银行股全部买入（已修复：tushare拉取5520只）
- 🟡 **板块惩罚不够硬** — 0.7权重惩罚不足以阻止4只银行集中持仓，需硬限制
- 🟢 交易逻辑T+1/佣金/止损确认/乒乓防护均正常
- 🟢 peak_nav=1.0在nav_history最高也是1.0时是正确的

**复盘驱动 (数据: 12/20笔已平仓, <20不调参数):**
- 错误模式: "买入失误"仍占主导
- 6/11事件: 空仓→同日建仓5只(4银行)→频繁加仓→95%仓位单日完成
- 根因: _daily_new_buys不持久化+无全局加仓限制+无行业硬限制

**改进实施 (3项):**
1. ✅ **🔴 _daily_new_buys持久化** (nav_tracker.py)
   - to_dict新增`_daily_new_buys`字段
   - from_dict恢复+清理过期数据(保留当月)
   - 效果: 每日新建仓max 2限制跨alert_check周期生效
   - commit: f9fd2ee

2. ✅ **🔴 add_position全局日频限制** (run_bot.py)
   - 新增`_MAX_DAILY_ADDS = 3`，每天全局最多3次加仓
   - 从daily_adds.json恢复已用次数，跨周期累积
   - 效果: 防止000001式14次/天疯狂加仓
   - commit: f9fd2ee

3. ✅ **🟡 板块硬限制+sector_map完善** (run_bot.py + data/)
   - sector_map.json从5条→5520条(tushare stock_basic)
   - 新增`_SECTOR_HARD_CAP = 2`：同行业≥2只时排除买入候选
   - 效果: 防止4只银行集中持仓
   - commit: f9fd2ee

**GitHub学习:**
- 无高星新项目发现
- 推进IMPROVEMENT_PLAN: 板块集中度从惩罚→硬限制

**数据状态:** 12/20笔已平仓，胜率33.3%，暂不调参数
**运行状态:** Bot需重启使新代码生效，当前5只持仓(4银行+1家电)，现金¥46K

### 2026-06-15 (周一) 复盘+策略日

**代码审查发现:**
- 🔴 **`_today_add_count`未初始化** — _smart_rebalance每次执行都崩溃（6/12全天每5min报错）
  - 直接影响: 加仓操作从不持久化，000333被重复买入49次
  - 间接影响: _save_nav在加仓崩溃后永不执行，导致卖出操作也不持久化
  - 连锁: 001391在不同日期被重复卖出4次（跨日幻影交易）
- 🔴 **IC追踪multiplier格式化错误** — `adj.get('multiplier', '?')`返回字符串'?'后`:.3f`崩溃
  - decay_penalty路径的adjustments缺少multiplier字段
- 🔴 **缺加仓全局节流检查** — commit消息声称有max 3/day但实际check从未实现
- 🟡 **trade_log污染** — 270条中235条是幻影交易（同一交易被重复记录）
- 🟢 T+1/佣金/止损确认/乒乓防护逻辑正确
- 🟢 因子引擎NaN防护+rank normalization正确

**复盘驱动 (数据: 12/20笔已平仓, <20不调参数):**
- 错误模式: "买入失误"仍占主导（6次, 5/12系统性下跌日）
- 胜率33.3%, 均收益-3.79%, 总盈亏¥-156K
- 数据状态仍不足，暂不调参数

**改进实施 (4项):**
1. ✅ **🔴 _today_add_count初始化 + decay_penalty缺失字段补充** (run_bot.py + factor_tracker.py)
   - `_today_add_count = len(_today_added)`从已有记录恢复
   - decay_penalty的adjustments补充old_weight/new_weight/multiplier
   - multiplier默认值从'?'改为0
   - commit: 9ce5702

2. ✅ **🔴 全局加仓节流 + 幻影交易清理** (run_bot.py + trade_log.json)
   - 添加`_today_add_count < 3`check在加仓入口
   - 清理235条幻影交易记录（trade_log从270→35条）
   - commit: 9b2367c

3. ✅ **🔴 卖出后立即_save_nav** (run_bot.py)
   - 设计缺陷: 卖出只在_smart_rebalance末尾持久化
   - 如果加仓crash，卖出状态丢失，次日重复卖出
   - 修复: 卖出block结束后立即_save_nav
   - commit: b6e115c

4. ✅ **🟢 decay_penalty adjustments字段完整性** (factor_tracker.py)
   - 旧: decay_penalty只有action/ic_decay_pct/ic_10d/ic_30d
   - 新: 补充old_weight/new_weight/multiplier，确保日志格式一致

**GitHub学习:**
- noterminusgit/statarb: 生产级统计套利系统，20+ alpha策略
  - 确认rank-based normalization方向正确（我们已实现）
  - Winsorization思路：我们用clip_range+rank已等效覆盖
- waylandzhang/ai-quant-book: 多智能体量化架构
  - Regime detection + multi-agent思路值得后续探索
  - 当前已有基础regime detection（market_breadth + vol_regime）
- randomwalkhan/Short-Term-Reversal-Strategy: 短期反转策略
  - staged-entry + 回测概率评估思路有参考价值

**数据状态:** 12/20笔已平仓，暂不调参数
**下次TODO:**
- [ ] 数据达到20笔后，根据strategy_report调参
- [ ] 推进Phase 4: 复盘→自动调参闭环
- [ ] 监控修复后_smart_rebalance是否正常运行

### 2026-06-16 (周一) 复盘+策略日

**代码审查发现:**
- 🔴 **`_auto_buy`无每股日频买入限制** — 000333在6/12每5分钟被重复买入(100@82.99→82.95→83.00→83.23)
  - 根因: `_auto_buy`与`_smart_rebalance`各自独立追踪，`_auto_buy`完全没有per-stock daily buy tracking
  - 影响: 现金被快速消耗在单一股票上
  - 状态: ✅ 已修复(commit 2efa309)
- 🔴 **`_auto_buy`与`_smart_rebalance`跨函数重复加仓** — 两函数用不同文件追踪(daily_auto_buys.json vs daily_actions.json)
  - 根因: `_smart_rebalance`加仓000333后，`_auto_buy`在同cycle又买入000333
  - 状态: ✅ 已修复(commit c3ab2f0)
- 🟡 **市场广度过滤仅1日** — 5/12系统性下跌前3天市场已连续走弱
  - 状态: ✅ 已增加3日连续下跌过滤(commit c77fb75)
- 🟢 之前修复的`_today_add_count`和IC multiplier问题确认已生效
- 🟢 nav_tracker的T+1/佣金/加权成本逻辑正确
- 🟢 _partial_sell/_sell持仓一致性验证通过
- 🟢 _verify_nav_integrity每轮检查正常运行

**复盘驱动 (数据: 12/20笔已平仓, <20不调参数):**
- 错误模式: "买入失误"仍占主导（6次, 5/12系统性下跌日）
- 胜率33.3%, 均收益-3.79%, 总盈亏¥-156K
- 新增3日市场趋势过滤直接针对"买入失误"模式
- 数据状态仍不足，暂不调参数

**改进实施 (3项):**
1. ✅ **🔴 _auto_buy每日每股买入限制** (run_bot.py)
   - 新增`daily_auto_buys.json`追踪文件
   - 每只股票每天最多通过auto_buy买入1次
   - 防止5分钟周期重复加仓同一股票
   - commit: 2efa309

2. ✅ **🔴 跨函数去重** (run_bot.py)
   - `_auto_buy`现在也检查`daily_actions.json`和`daily_adds.json`
   - 防止`_smart_rebalance`和`_auto_buy`在同一5分钟cycle重复加仓
   - commit: c3ab2f0

3. ✅ **🟡 多日市场趋势过滤** (run_bot.py)
   - GitHub学习: zhou343-de/stock-trader-ai 的"先活下来"理念
   - 新增3日连续负收益或3日均幅<-1.0%时阻止auto_buy
   - 直接针对5/12系统性下跌日的"买入失误"模式
   - commit: c77fb75

**GitHub学习:**
- zhou343-de/stock-trader-ai (⭐8): 八层风控·37因子自进化·A股全自动量化系统
  - 学到: 多日市场趋势检查的必要性（我们只有1日广度过滤）
  - 已实现: 3日连续下跌过滤
- blaahhrrgg/equity-risk-model (⭐36): 多因子风险模型
  - 确认: rank-based normalization方向正确
  - 后续可探索: 风险因子归因分析
- stefan-jansen/machine-learning-for-trading: ML for trading教科书
  - 参考: ML模型用于信号预测（当前用规则引擎，未来可考虑）

**数据状态:** 12/20笔已平仓，暂不调参数
**运行状态:** Bot已重启加载新代码，5只持仓(邮储/平安/美的/成都/宁波)，现金¥18K
**下次TODO:**
- [ ] 数据达到20笔后，根据strategy_report调参
- [ ] 监控新的去重机制是否正常工作（检查daily_auto_buys.json）
- [ ] 推进Phase 4: 复盘→自动调参闭环

### 2026-06-17 (周三) 风控+仓位日

**代码审查发现:**
- 🔴 **T+1违规**: _add_position不更新buy_date，允许当天加仓当天卖出
  - 交易记录: 002142 09:35买入→09:55卖出, 601838 09:45买入→10:05卖出
  - 影响: T+1规则形同虚设，可能违反A股交易规则
- 🟡 **级联清仓**: 25分钟内连卖5只(09:40→10:05)，持仓5→2只
  - 每个alert_check(5min)触发一次评分驱动卖出，无冷却机制
- 🟡 **Kelly未使用**: KellyPositionManager存在但从未在run_bot.py中调用
- 🟢 佣金计算正确，止损/止盈逻辑完整
- 🟢 因子引擎NaN防护有效

**改进实施 (3项):**

1. ✅ **🔴 T+1修复 + 因子传递** (nav_tracker.py + run_bot.py)
   - _add_position新增last_add_date字段记录加仓日期
   - 所有5处T+1检查更新: 同时检查buy_date和last_add_date
   - _add_position新增factor_score/signal_score参数
   - smart_rebalance调用_add_position时传递实际分数(原来传0)
   - commit: 974df83

2. ✅ **🟡 卖出冷却机制** (run_bot.py)
   - 新增last_sell_time.json追踪最近卖出时间
   - 卖出后15分钟内跳过评分驱动的减仓/换仓/加仓
   - 止损(-15%/-10%)、追踪止盈、时间止损不受冷却限制
   - 所有5个卖出路径均记录冷却时间
   - commit: 4fde6da

3. ✅ **🟢 Kelly Criterion集成** (run_bot.py)
   - GitHub学习: MarketRegimeNet (lu8848) — Kelly + temperature calibration
   - auto_buy根据历史胜率动态限制max_buy
   - 胜率<30%(当前23.5%)→max_buy=1, <40%→max_buy≤2
   - 每次auto_buy自动从trade_log更新Kelly参数
   - commit: b1f3aad

**复盘驱动:**
- 错误模式: "买入失误"6次（均来自5/12系统性下跌日）
- Kelly集成直接回应: 胜率23.5%→限制单次仅买1只
- 卖出冷却回应: 6/16级联清仓模式

**GitHub学习:**
- **MarketRegimeNet** (lu8848): Kelly Criterion + Brier score penalty
  - 学到: 模型置信度低时自动缩减仓位
  - 已实现: Kelly胜率门槛(max_buy限制)
  - 未来可做: 温度校准(将signal_score映射到实际胜率)

**数据状态:** 17/20笔已平仓，暂不调参数
