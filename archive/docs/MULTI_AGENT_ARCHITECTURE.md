# StockRadar 多Agent架构设计

## 1. 整体架构

### Agent角色定义

| Agent | 职责 | 类型 | 开源 |
|---|---|---|---|
| RouterAgent | 意图识别、任务分发、上下文管理 | 主控 | ✅ |
| AnalystAgent | 市场分析、个股研究、财报解读 | 工作 | ✅ |
| TraderAgent | 交易决策、风控、持仓管理 | 工作 | ✅ |
| EvolverAgent | 因子进化、策略优化、知识沉淀 | 工作 | ❌ 闭源 |
| ReporterAgent | 报告生成、可视化、通知 | 工作 | ✅ |

### 通信方式

Agent间通过 **Message Bus** 通信，消息格式统一：

```python
@dataclass
class AgentMessage:
    sender: str        # "analyst", "evolver", "trader"
    receiver: str      # "router", "trader", "all"
    msg_type: str      # "analysis", "signal", "decision", "alert"
    priority: int      # 1=critical, 2=high, 3=normal, 4=low
    content: dict      # 具体内容
    timestamp: str
    correlation_id: str  # 关联ID，追踪一个任务流
```

## 2. 目录结构

```
stockradar/
├── src/
│   ├── core/                    # 📖 开源 - 核心框架
│   │   ├── agent_base.py        # Agent基类
│   │   ├── message_bus.py       # Agent间消息总线
│   │   ├── context.py           # 共享上下文（黑板模式）
│   │   ├── tool_registry.py     # 工具注册中心
│   │   └── scheduler.py         # 任务调度
│   │
│   ├── agents/                  # 📖 开源 - Agent实现
│   │   ├── router.py            # 路由Agent（意图识别+分发）
│   │   ├── analyst.py           # 分析师Agent
│   │   ├── trader.py            # 交易Agent
│   │   └── reporter.py          # 报告Agent
│   │
│   ├── tools/                   # 📖 开源 - 工具集（Agent可调用的能力）
│   │   ├── data_tools.py        # 数据获取工具
│   │   ├── factor_tools.py      # 因子计算工具
│   │   ├── backtest_tools.py    # 回测工具
│   │   ├── portfolio_tools.py   # 持仓管理工具
│   │   └── notify_tools.py      # 通知推送工具
│   │
│   ├── data/                    # 📖 开源 - 数据层（保留现有）
│   ├── factors/                 # 📖 开源 - 基础因子（保留现有36个）
│   ├── backtest/                # 📖 开源 - 回测引擎（保留现有）
│   ├── simulator/               # 📖 开源 - 模拟交易（保留现有）
│   ├── app/                     # 📖 开源 - Bot（保留现有）
│   ├── infra/                   # 📖 开源 - 基础设施（保留现有）
│   │
│   └── proprietary/             # 🔒 闭源 - 核心商业模块
│       ├── __init__.py
│       ├── evolver_agent.py     # 进化Agent（因子发现+策略自愈）
│       ├── factor_lab.py        # 因子实验室（LLM生成+验证新因子）
│       ├── strategy_brain.py    # 策略大脑（动态策略切换）
│       ├── knowledge_graph.py   # 知识图谱（进阶版knowledge store）
│       └── secret_sauce.py      # 核心alpha（权重优化+因子组合）
│
├── config/
│   ├── settings.yaml            # 基础配置
│   ├── factors.yaml             # 因子配置
│   ├── agents.yaml              # Agent配置（模型选择、工具权限）
│   └── proprietary/             # 🔒 闭源配置
│       ├── evolution.yaml
│       └── factor_lab.yaml
│
├── tests/
├── scripts/
├── docs/
├── pyproject.toml               # 替代 requirements.txt
└── README.md
```

## 3. Agent基类设计

每个Agent有统一的生命周期：感知 → 思考 → 行动 → 反思

```python
class BaseAgent:
    name: str                    # Agent名称
    tools: list[Tool]            # 可用工具列表
    llm_client: LLMClient        # LLM客户端（可选）
    
    async def perceive(self, context) -> Observation
    async def think(self, observation) -> Plan  
    async def act(self, plan) -> Result
    async def reflect(self, result) -> Lesson
    
    async def run(self, context):
        obs = await self.perceive(context)
        plan = await self.think(obs)
        result = await self.act(plan)
        lesson = await self.reflect(result)
        return result
```

## 4. RouterAgent 工作流

```
用户消息 → RouterAgent
  │
  ├─ "分析一下宁德时代" → AnalystAgent.analyze("300750")
  │     → data_tools.get_quote("300750")
  │     → factor_tools.calc_factors("300750")  
  │     → LLM分析 → 返回分析报告
  │
  ├─ "今天持仓怎么样" → TraderAgent.status()
  │     → portfolio_tools.get_portfolio()
  │     → 返回持仓+盈亏
  │
  ├─ "跑一下回测" → TraderAgent.backtest(...)
  │     → backtest_tools.run(...)
  │     → 返回回测报告
  │
  ├─ "最近因子表现" → EvolverAgent.report()  # 闭源
  │     → 返回因子IC+权重变化
  │
  └─ "市场感觉不对" → AnalystAgent.scan()
        → data_tools.get_market_sentiment()
        → factor_tools.calc_regime()
        → LLM综合判断 → 返回风险提示
```

## 5. EvolverAgent（闭源核心）

这是商业化核心，独立打包为proprietary模块：

```python
# proprietary/evolver_agent.py

class EvolverAgent(BaseAgent):
    """进化Agent — 核心商业模块
    
    三个进化循环：
    1. 日循环：因子IC监控 → 权重微调 → 暂停/恢复
    2. 周循环：LLM提出新因子假设 → 自动验证 → 上线/淘汰
    3. 月循环：策略全面体检 → 失败复盘 → 策略改进
    
    闭源但接口开放：
    - 开源用户可以用基础因子（36个），但不自动进化
    - 付费用户解锁EvolverAgent，因子持续进化优化
    """
    
    async def perceive(self, context):
        # 收集：因子IC、市场结构、持仓表现、LLM准确率
        pass
    
    async def think(self, observation):
        # LLM推理：哪些因子失效？市场在变化？需要什么新因子？
        pass
    
    async def act(self, plan):
        # 执行：调整权重、注册新因子、修改策略参数
        pass
    
    async def reflect(self, result):
        # 反思：调整效果如何？记录教训到知识图谱
        pass
```

## 6. 开源/闭源边界设计

### 接口层（开源）

```python
# src/core/evolution_interface.py — 开源侧接口

class EvolutionInterface:
    """进化模块的开放接口
    
    开源版：返回基础统计（IC历史、因子列表）
    闭源版：通过插件机制加载EvolverAgent，获得完整进化能力
    """
    
    def get_factor_status(self) -> pd.DataFrame:
        """获取因子状态（开源版：静态；闭源版：动态进化）"""
        ...
    
    def get_evolution_log(self) -> list:
        """获取进化日志（开源版：空；闭源版：完整记录）"""
        ...
```

### 插件加载

```python
# src/core/plugin.py

def load_proprietary():
    """尝试加载闭源模块，失败则降级为开源版"""
    try:
        from proprietary.evolver_agent import EvolverAgent
        from proprietary.factor_lab import FactorLab
        return EvolverAgent(), FactorLab()
    except ImportError:
        logger.info("闭源模块未安装，使用开源基础版")
        return None, None
```

## 7. 商业模式

```
                    开源版（免费）          Pro版（付费）
                    ────────────          ────────────
因子数量            36个基础因子            36+LLM自动发现
因子进化            ❌ 手动调整             ✅ 自动进化
策略               连续评分（固定）         动态策略切换
知识积累            本地markdown           知识图谱+语义检索
回测               基础回测               Walk-forward+蒙特卡洛
报告               文本报告               可视化仪表盘
社区               GitHub Issues          私有Discord频道

定价参考：
  开源版：免费，吸引社区
  Pro版：¥99/月 或 ¥899/年（个人），¥299/月（机构）
```

## 8. 迁移路径（从当前代码到多Agent）

### Phase 1：框架搭建（1周）
- 实现BaseAgent + MessageBus + Context
- RouterAgent实现意图识别
- 现有代码重构为Tools

### Phase 2：Agent实现（2周）
- AnalystAgent（包装现有因子+LLM分析）
- TraderAgent（包装现有策略+模拟交易）
- ReporterAgent（包装现有Bot+报告）

### Phase 3：闭源模块（2周）
- EvolverAgent（从现有evolution模块升级）
- FactorLab（LLM因子实验室）
- StrategyBrain（动态策略）

### Phase 4：开源发布（1周）
- 代码清理、文档、示例
- GitHub公开
- pip install stockradar

## 9. 技术选型

| 组件 | 选择 | 理由 |
|---|---|---|
| Agent框架 | 自研（轻量） | 不需要LangGraph/CrewAI的复杂度 |
| LLM | OpenAI/国产API | 通过接口抽象，用户自选 |
| 消息总线 | asyncio.Queue | 进程内通信，够用 |
| 工具调用 | Function Calling | LLM原生工具调用 |
| 包管理 | pyproject.toml | 现代Python标准 |
| 闭源分发 | .pyd编译/wheel | 二进制分发，保护源码 |
