# EvolverAgent 五维进化系统设计

## 概述

EvolverAgent是StockRadar的闭源核心，负责系统在五个维度上的持续进化。
从"因子优化器"升级为"系统自进化引擎"。

```
进化 = 感知瓶颈 + LLM推理 + 受限执行 + 反馈闭环
安全性 = 危险程度越高，审批层级越高
```

## 五维进化体系

```
┌─────────────────────────────────────────────────────────┐
│                  EvolverAgent                            │
│                                                         │
│  D1:Signal    D2:Strategy   D3:Architecture             │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐       │
│  │因子权重  │  │持仓参数   │  │算法优化   [auto]  │       │
│  │新因子发现 │  │风控阈值   │  │代码补丁 [review]  │       │
│  │因子淘汰  │  │换仓逻辑   │  │系统建议 [advisory]│       │
│  └─────────┘  └──────────┘  └──────────────────┘       │
│                                                         │
│  D4:Ability              D5:Interaction                 │
│  ┌─────────────────┐    ┌──────────────────────┐       │
│  │工具自动发现       │    │用户画像学习            │       │
│  │数据源自动管理     │    │推送节奏校准            │       │
│  │新技能习得        │    │沟通风格适应            │       │
│  │Agent自我分裂     │    │主动性调节              │       │
│  └─────────────────┘    └──────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## 维度1: 信号进化 (Signal Evolution)

### 频率: 每日
### 权限: 全自动
### 已实现: ✅

```python
class SignalEvolver:
    """因子级进化"""
    
    # 每日执行
    def daily_ic_track(self, date):
        """追踪每个因子IC，自动调整权重"""
        # IC < 0.01 连续30天 → 暂停
        # IC > 0.02 连续10天 → 恢复
        # 权重调整幅度: ±0.2×original/天
        
    # 每周执行  
    async def weekly_factor_discovery(self, date):
        """LLM提出新因子假设 → 自动验证"""
        # 1. LLM分析近期失效因子 + 市场变化
        # 2. 提出3个新因子假设（含pandas表达式）
        # 3. 沙箱执行 → 计算IC
        # 4. IC > 0.03 → 注册为新因子
        # 5. IC < 0.01 → 记录失败到知识库
    
    # 每月执行
    def monthly_factor_review(self):
        """因子体系全面review"""
        # - 暂停因子数 > 30%? → 触发策略级告警
        # - 同类因子相关性 > 0.9? → 建议合并
        # - 新因子上线30天回顾
```

## 维度2: 策略进化 (Strategy Evolution)

### 频率: 每周+每月
### 权限: 全自动(参数) / 需审批(逻辑)
### 已实现: ✅

```python
class StrategyEvolver:
    """策略级进化"""
    
    # 每周
    def weekly_param_tune(self):
        """策略参数自动微调"""
        tunable_params = {
            "delta_lookback": (3, 10),      # ΔS回看天数
            "buffer_rank_end": (15, 25),     # 缓冲区上界
            "max_weekly_change": (1, 3),     # 每周最大换仓
            "stop_loss": (-0.20, -0.08),     # 止损线
        }
        # 基于近期表现做grid search微调
        
    # 每月
    async def monthly_diagnosis(self, date):
        """策略全面体检"""
        # 1. 健康度评分(0-100)
        # 2. 失败交易模式提取
        # 3. LLM生成改进建议
        # 4. 市场regime适配性评估
        
    # 按需
    async def failure_postmortem(self, trade_id):
        """单笔失败交易复盘"""
        # 为什么买入? 什么信号触发了卖出?
        # 哪个因子判断错误? 如何避免?
```

## 维度3: 架构进化 (Architecture Evolution)

### 频率: 持续监控 + 月度review
### 权限: 分层
### 已实现: ❌ (新增)

```python
class ArchitectureEvolver:
    """系统架构自进化 — 核心创新"""
    
    # ──── Level 1: 全自动 (算法层) ────
    
    def profile_performance(self):
        """运行时性能profiling"""
        metrics = {
            "score_all_duration": ...,      # 评分计算耗时
            "data_fetch_duration": ...,     # 数据拉取耗时  
            "memory_usage_mb": ...,         # 内存使用
            "duckdb_size_gb": ...,          # 数据库大小
            "daily_total_duration": ...,    # 每日任务总耗时
        }
        return self._detect_anomalies(metrics)
    
    def auto_optimize_algorithm(self, bottleneck):
        """自动算法优化（仅限纯函数）"""
        
        # 示例: score_all() 慢了
        if bottleneck.type == "score_all_slow":
            # 生成向量化版本
            patch = self._generate_vectorized_patch()
            # 沙箱测试: 确保结果一致
            if self._sandbox_test(patch, tolerance=1e-6):
                self._apply_patch(patch)
                self._log("自动优化: score_all向量化, 耗时 15s→3s")
        
        # 示例: 数据膨胀
        elif bottleneck.type == "data_bloat":
            # 自动归档旧数据到parquet
            self._archive_old_data(years=10)
            self._log("自动归档: 10年前数据已压缩")
    
    # ──── Level 2: 代码补丁 (需用户审批) ────
    
    async def suggest_code_improvement(self):
        """LLM发现代码改进机会"""
        improvements = []
        
        # 1. 错误模式分析
        error_log = self._get_recent_errors()
        if error_log:
            fix = await self._llm_analyze_errors(error_log)
            improvements.append({
                "type": "bug_fix",
                "risk": "medium",
                "description": fix.description,
                "patch": fix.code,
                "test": fix.test_code,
            })
        
        # 2. 接口失效检测
        failed_apis = self._get_api_failure_rates()
        for api, fail_rate in failed_apis.items():
            if fail_rate > 0.3:  # 30%失败率
                alt = await self._llm_find_alternative_api(api)
                improvements.append({
                    "type": "api_migration",
                    "risk": "low",
                    "description": f"{api} 失败率{fail_rate:.0%}, 建议迁移到 {alt}",
                    "patch": alt.code,
                })
        
        # 3. 数据质量退化
        quality_issues = self._detect_data_quality_issues()
        for issue in quality_issues:
            improvements.append({
                "type": "data_quality",
                "risk": "low",
                "description": issue.description,
                "patch": issue.fix_code,
            })
        
        return improvements
    
    # ──── Level 3: 系统建议 (仅供参考) ────
    
    async def generate_system_report(self):
        """月度系统健康报告 + 升级建议"""
        report = {
            "performance": self._performance_summary(),
            "data_stats": self._data_statistics(),
            "degradation": self._detect_degradation(),
            "recommendations": [],
        }
        
        # 数据量建议
        db_size = self._get_db_size()
        if db_size > 5:  # GB
            report["recommendations"].append(
                "数据库已超5GB，建议启用分区存储或迁移到ClickHouse"
            )
        
        # 版本建议
        versions = self._check_dependencies()
        for pkg, (current, latest) in versions.items():
            if current < latest:
                report["recommendations"].append(
                    f"{pkg} {current} → {latest} 可能有性能改进"
                )
        
        return report
```

## 维度4: 能力进化 (Ability Evolution)

### 频率: 按需 + 每周扫描
### 权限: 工具注册全自动 / 数据源切换需审批
### 已实现: ❌ (新增)

```python
class AbilityEvolver:
    """系统能力自我扩展"""
    
    # ──── 工具自动发现 ────
    
    async def discover_new_tools(self):
        """发现并注册新工具"""
        
        # 1. 分析能力缺口
        gaps = self._detect_ability_gaps()
        # 例: "可转债数据分析" "期权PCR指标" "龙虎榜数据"
        
        for gap in gaps:
            # 2. 搜索可用数据源
            sources = await self._search_data_sources(gap)
            
            for source in sources:
                # 3. 验证数据可用性
                test_result = await self._test_data_source(source)
                if not test_result.available:
                    continue
                
                # 4. 自动生成工具函数
                tool_func = await self._generate_tool(source)
                
                # 5. 沙箱测试
                if self._sandbox_test_tool(tool_func):
                    # 6. 注册为正式工具
                    self._register_tool(gap.name, tool_func)
                    self._log(f"新工具注册: {gap.name} from {source}")
    
    def _detect_ability_gaps(self) -> list:
        """检测能力缺口"""
        gaps = []
        
        # 从进化日志中发现
        # 例: 多个因子因"缺少XX数据"而失效
        failed_needs = self.knowledge.query("factor_failures", 
                                             reason="data_unavailable")
        gaps.extend(failed_needs)
        
        # 从用户问题中发现
        # 例: 用户问过"可转债"但系统没有这个能力
        unanswered = self.knowledge.query("unanswered_questions")
        gaps.extend(unanswered)
        
        # 从市场变化中发现
        # 例: 新板块出现但系统没有对应因子
        new_sectors = self._detect_new_market_sectors()
        gaps.extend(new_sectors)
        
        return gaps
    
    # ──── 数据源自动管理 ────
    
    def audit_data_sources(self):
        """数据源健康审计"""
        for source in self.data_sources:
            stats = {
                "success_rate": self._get_success_rate(source),
                "avg_latency": self._get_latency(source),
                "data_freshness": self._get_freshness(source),
                "cost_per_call": self._get_cost(source),
            }
            
            if stats["success_rate"] < 0.8:
                self._find_backup_source(source)
            
            if stats["data_freshness"] > 2:  # 2天没更新
                self._alert_stale_data(source)
    
    # ──── Agent技能学习 ────
    
    async def learn_skill(self, skill_description: str):
        """学习新技能"""
        
        # 1. LLM理解技能需求
        spec = await self._llm_parse_skill_requirement(skill_description)
        
        # 2. 搜索现有工具能否组合实现
        combo = self._search_tool_combination(spec)
        if combo:
            self._register_skill(spec.name, combo)
            return
        
        # 3. 不能组合 → 生成新工具
        tool_code = await self._llm_generate_tool(spec)
        
        # 4. 测试
        if self._sandbox_test_tool(tool_code):
            self._register_tool(spec.name, tool_code)
            self._log(f"新技能习得: {spec.name}")
    
    # ──── Agent自我分裂 ────
    
    async def evaluate_agent_split(self):
        """评估是否需要创建新的子Agent"""
        
        # 如果某个工具组合被高频使用，可能需要独立Agent
        usage_patterns = self._analyze_tool_usage()
        
        for pattern in usage_patterns:
            if pattern.frequency > 10 and pattern.is_coherent:
                proposal = {
                    "name": f"{pattern.domain}_agent",
                    "tools": pattern.tools,
                    "trigger": pattern.trigger_conditions,
                    "reason": f"工具组合 {pattern.tools} 近30天使用{pattern.frequency}次",
                }
                self._propose_agent_creation(proposal)
```

## 维度5: 交互进化 (Interaction Evolution)

### 频率: 每次交互持续更新
### 权限: 全自动
### 已实现: ❌ (新增)

```python
class InteractionEvolver:
    """用户交互持续进化"""
    
    # ──── 用户画像 ────
    
    def __init__(self):
        self.user_profile = {
            "risk_tolerance": "medium",      # 保守/中等/激进
            "attention_style": "summary",    # summary/detail/visual
            "interested_sectors": [],        # 关注行业
            "active_hours": [],              # 活跃时段
            "response_patterns": {},         # 对不同消息的响应模式
            "correction_history": [],        # 用户纠正记录
        }
    
    def update_profile(self, interaction):
        """每次交互后更新画像"""
        
        # 从提问内容学习关注领域
        if interaction.type == "question":
            sectors = self._extract_sectors(interaction.content)
            self._update_sectors(sectors)
        
        # 从交易确认速度学习决策风格
        if interaction.type == "trade_confirm":
            response_time = interaction.response_time
            if response_time < 60:  # 1分钟内确认
                self.user_profile["decision_style"] = "decisive"
            elif response_time > 3600:  # 1小时以上
                self.user_profile["decision_style"] = "deliberate"
        
        # 从忽略的消息学习推送偏好
        if interaction.type == "message_ignored":
            self._decrease_topic_priority(interaction.topic)
        
        # 从纠正中学习
        if interaction.type == "correction":
            self.user_profile["correction_history"].append({
                "what": interaction.content,
                "when": interaction.timestamp,
            })
            self._immediate_learn(interaction.content)
    
    # ──── 推送节奏校准 ────
    
    def calibrate_proactivity(self):
        """校准主动推送节奏"""
        
        # 统计最近7天的推送效果
        stats = {
            "messages_sent": self._count_recent_messages(),
            "messages_read": self._count_read_messages(),
            "messages_acted_on": self._count_acted_messages(),
            "messages_ignored": self._count_ignored_messages(),
            "explicit_complaints": self._count_complaints(),
        }
        
        read_rate = stats["messages_read"] / max(stats["messages_sent"], 1)
        act_rate = stats["messages_acted_on"] / max(stats["messages_read"], 1)
        
        # 调整推送频率
        if read_rate > 0.8 and act_rate > 0.3:
            self._increase_frequency()     # 用户在看也在用 → 可以多推
        elif read_rate < 0.3:
            self._decrease_frequency()     # 用户不看 → 少推
        elif stats["explicit_complaints"] > 2:
            self._pause_proactive(24h)     # 被抱怨 → 暂停24小时
        
        # 调整推送时段
        active_hours = self._detect_active_hours()
        self.user_profile["active_hours"] = active_hours
    
    # ──── 沟通风格适应 ────
    
    def adapt_communication_style(self):
        """适应用户的沟通偏好"""
        
        # 用户偏好简短? → 输出摘要模式
        if self.user_profile.get("attention_style") == "summary":
            self._set_output_mode("brief")  # 3句话+关键数字
        
        # 用户爱看图表? → 生成更多可视化
        if self.user_profile.get("prefers_visual"):
            self._enable_chart_generation()
        
        # 用户是技术背景? → 用专业术语
        if self.user_profile.get("technical_level") == "high":
            self._set_technical_depth("expert")
        
        # 用户纠正过某些表述? → 永久学习
        for correction in self.user_profile["correction_history"]:
            self._apply_correction(correction)
    
    # ──── 主动性调节 ────
    
    def get_proactivity_level(self) -> dict:
        """获取当前主动性配置"""
        level = self._calculate_proactivity_level()
        
        return {
            "market_scan_frequency": "2h" if level > 0.7 else "4h",
            "alert_threshold": "medium" if level > 0.5 else "high",
            "proactive_suggestions": level > 0.6,
            "weekly_deep_analysis": True,  # 始终开启
            "off_hours_notifications": level > 0.8,  # 默认关闭
        }
```

## 进化安全等级

```
┌──────────────────────────────────────────────────────────┐
│                    安全等级金字塔                          │
│                                                          │
│              Level 0: 全自动                              │
│              ┌──────────────────┐                        │
│              │ 因子权重微调      │                        │
│              │ 策略参数优化      │                        │
│              │ 用户画像更新      │                        │
│              │ 推送节奏调节      │                        │
│              │ 算法自动优化      │                        │
│              │ 工具自动注册      │                        │
│              └──────────────────┘                        │
│                                                          │
│          Level 1: 需通知确认                               │
│          ┌────────────────────────────┐                  │
│          │ 新因子上线（IC验证通过）     │                  │
│          │ 风控参数变更               │                  │
│          │ 数据源切换                │                  │
│          │ Agent创建提案              │                  │
│          └────────────────────────────┘                  │
│                                                          │
│      Level 2: 需用户审批                                  │
│      ┌──────────────────────────────────────┐            │
│      │ 代码补丁应用                          │            │
│      │ 策略逻辑变更                          │            │
│      │ 新依赖引入                           │            │
│      │ 配置文件修改                          │            │
│      └──────────────────────────────────────┘            │
│                                                          │
│  Level 3: 仅建议不执行                                    │
│  ┌──────────────────────────────────────────────┐        │
│  │ 基础设施变更（数据库迁移等）                     │        │
│  │ 版本升级建议                                   │        │
│  │ 架构重构建议                                   │        │
│  │ 新Agent架构提案                                │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## 进化日志格式

所有进化动作记录到 `evolution_log` DuckDB表，用于审计和回滚：

```sql
CREATE TABLE evolution_log (
    id          INTEGER PRIMARY KEY,
    timestamp   DATETIME,
    dimension   VARCHAR,    -- signal/strategy/architecture/ability/interaction
    action      VARCHAR,    -- adjust_weight/register_factor/optimize_algorithm/...
    target      VARCHAR,    -- 具体对象名
    before_value  JSON,     -- 变更前
    after_value   JSON,     -- 变更后
    trigger     VARCHAR,    -- 触发原因
    approval_level INTEGER, -- 0=auto, 1=notify, 2=approved, 3=advisory
    result      VARCHAR,    -- success/failed/rolled_back
    ic_before   FLOAT,      -- 动作前IC（如适用）
    ic_after    FLOAT,      -- 动作后IC（如适用）
    notes       TEXT
);
```

## 进化调度

```python
# 统一调度时间表

DAILY:
  09:00  data_fetch()           # 拉数据
  09:30  signal.daily_ic()      # D1: IC追踪+权重调整
  09:35  strategy.param_check() # D2: 参数微调
  20:00  interaction.update()   # D5: 用户画像更新
  20:30  interaction.calibrate()# D5: 推送节奏校准

WEEKLY (周日):
  10:00  signal.factor_discovery()    # D1: 新因子假设
  14:00  ability.discover_tools()     # D4: 工具发现
  16:00  ability.audit_sources()      # D4: 数据源审计
  18:00  architecture.profile()       # D3: 性能profiling

MONTHLY (1号):
  10:00  strategy.monthly_diagnosis() # D2: 策略体检
  14:00  signal.factor_review()       # D1: 因子体系review
  16:00  architecture.suggest()       # D3: 代码改进建议
  18:00  ability.evaluate_split()     # D4: Agent分裂评估
  20:00  evolution_report()           # 月度进化报告
```

## 闭源模块文件结构

```
proprietary/
├── __init__.py
├── evolver_agent.py           # 总调度，串联5个进化器
├── signal_evolver.py          # D1: 信号进化
├── strategy_evolver.py        # D2: 策略进化  
├── architecture_evolver.py    # D3: 架构进化
├── ability_evolver.py         # D4: 能力进化
├── interaction_evolver.py     # D5: 交互进化
├── sandbox.py                 # 沙箱执行环境
├── knowledge_graph.py         # 进阶知识图谱
├── factor_lab.py              # 因子实验室
├── secret_sauce.py            # 核心alpha
└── config/
    ├── evolution.yaml         # 进化参数配置
    ├── safety_rules.yaml      # 安全规则
    └── user_profile.yaml      # 用户画像持久化
```
