<div align="center">

# 📡 StockRadar

### A股智能选股雷达 · 多Agent系统

**36因子评分 × 多Agent协作 × LLM增强分析**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-15%20passing-brightgreen.svg)]()

[架构设计](#-多agent架构) · [回测结果](#-回测表现) · [快速开始](#-快速开始) · [Pro版](#-开源版-vs-pro版)

</div>

---

## 💡 为什么用多Agent？

传统量化系统是**一个巨大脚本**——数据拉取、因子计算、策略执行、风控、报告全耦合在一起。改一个地方，处处是坑。

StockRadar 采用**多Agent协作架构**，每个Agent专注一件事：

```
传统量化:  [数据→因子→策略→风控→交易→报告]  一个脚本搞定（改不动了）

多Agent:   Router ──→ Analyst ──→ Trader ──→ Reporter
              │           │          │
              └───────────┴──────────┘
                    ↕ 异步协作
```

| | 单体脚本 | 多Agent架构 |
|---|---|---|
| **可维护性** | 改策略要改整个脚本 | 只改 TraderAgent，其他不受影响 |
| **可测试性** | 只能端到端测 | 每个Agent独立测试，Mock其他Agent |
| **可扩展性** | 加功能=改大脚本 | 加个新Agent，注册到Router即可 |
| **容错性** | 一个环节崩全崩 | Analyst超时？Router降级到纯技术因子 |
| **并发效率** | 串行执行 | 多Agent并行协作 |

## 🤖 多Agent架构

### 四个专业Agent

```
┌─────────────────────────────────────────────────┐
│                 AgentOrchestrator                │
│              (编排器 · 生命周期管理)               │
├──────────┬──────────┬──────────┬────────────────┤
│ Router   │ Analyst  │  Trader  │   Reporter     │
│ 路由器    │ 分析师    │ 交易员    │   报告员       │
│          │          │          │                │
│ 意图识别  │ 因子计算  │ 调仓决策  │ 日报/周报     │
│ 任务分发  │ 个股研究  │ 风控执行  │ 归因分析      │
│ 降级路由  │ LLM分析  │ 持仓管理  │ 风险预警      │
└──────────┴──────────┴──────────┴────────────────┘
         ↕ MessageBus (异步消息)    ↕ SharedContext (黑板模式)
         ↕ ToolRegistry (工具注册)
```

### 核心框架组件

| 组件 | 作用 | 设计模式 |
|---|---|---|
| `AgentOrchestrator` | Agent生命周期、编排、降级 | 编排者模式 |
| `MessageBus` | Agent间异步通信 | 发布-订阅 |
| `SharedContext` | 跨Agent状态共享 | 黑板模式 |
| `ToolRegistry` | 工具注册与发现 | 依赖注入 |

### 协作流程示例

**用户问："分析宁德时代"**

```
1. Router 接收消息 → 识别为"个股分析"意图
2. Router 分发给 Analyst
3. Analyst 调用工具:
   - fetch_stock_data("300750")    ← ToolRegistry
   - score_all(factors)            ← FactorEngine
   - llm_analyze("宁德时代")        ← LLMClient (有缓存)
4. Analyst 返回分析结果
5. Reporter 格式化为可读报告
6. 结果返回用户
```

**每日流水线**

```
1. Analyst: 全市场评分 → Top 50候选
2. Analyst: LLM深度分析Top 50（批量+缓存）
3. Trader:  执行调仓（行业分散 + 换仓限制 + 止损）
4. Reporter: 生成日报（持仓变化 + 归因 + 预警）
```

## 📈 回测表现

> 100只沪深300成分股 | 36因子 | 每10天调仓 | 含0.1%双边手续费

```
┌──────────────────────────────────────────────┐
│  📊 策略回测（2023.01 ~ 2025.02）              │
├──────────────────────────────────────────────┤
│  总收益:    +67.67%                           │
│  年化收益:  27.5%                             │
│  最大回撤:  -20.5%                            │
│  Sharpe:    1.24                              │
│  Calmar:    3.31   ← 每承受1%回撤换3.31%收益  │
│  手续费:    ¥101,549（已扣除）                 │
└──────────────────────────────────────────────┘
```

**对比基准：**
```
策略年化 27.5% vs 沪深300同期 ≈ 0%（大幅跑赢）
Calmar 3.31 — 专业标准 >1.0 合格，>2.0 优秀
```

**Walk-Forward 验证（防过拟合）：**
```
滚动窗口: 12月训练 → 3月测试，步长3月
  2023-12~2024-03  🟢 +8.1%   回撤-5.1%
  2024-03~2024-06  🟢 +0.9%   回撤-2.5%
  2024-06~2024-09  🔴 -9.2%   回撤-9.2%  ← A股系统性下跌
  2024-09~2024-12  🟢 +23.7%  回撤-8.0%  ← 快速恢复

样本外胜率: 75% (3/4) | 平均季度收益: +5.9%
结论: ✅ 策略无过拟合，样本外表现稳定
```

<details>
<summary>📋 回测详细参数</summary>

- 股票池：沪深300成分股前100只
- 数据源：BaoStock（行情+财务4类数据）
- 调仓：每10个交易日，Top 10持仓
- 止损：个股-18%硬止损
- 手续费：0.1%双边（含印花税）
- 整手交易：100股倍数
- 因子：36个（12基本面+12技术+5资金+4情绪+3 LLM）
- 风险：历史回测不代表未来表现
</details>

## 📊 36因子评分体系

```
S(t) = Σ (w_category × Σ (w_factor × zscore_factor)) / Σ w_factor

持仓 = Top 10 (S(t))
换仓信号 = ΔS = S(t) - S(t-5)
```

| 类别 | 数量 | 权重 | 代表因子 |
|---|---|---|---|
| 🏢 基本面 | 12 | 35% | ROE, PEG, 营收增速, 毛利率, 应计比率, 存货周转 |
| 📉 技术面 | 12 | 20% | RSI, MACD, 布林带宽度, 量价背离, 换手率变化, 振幅 |
| 💰 资金面 | 5 | 20% | 北向净流入, 主力净流入, 融资融券变化 |
| 🎭 市场情绪 | 4 | 15% | 换手异常, 涨停次数, 高低点位置, 量比 |
| 🤖 LLM增强 | 3 | 10% | 财报情绪分析, 新闻情绪7日, 研报共识 |

**因子设计原则：**
- 纯函数，无副作用：`calc_rsi(daily_df) -> Series`
- 每个因子返回 `Series(index=code)`，统一接口
- 因子间零耦合，可独立测试

## 🏗️ 项目结构

```
stockradar/
├── src/
│   ├── core/                  # 🏛️ 多Agent框架
│   │   ├── agent_base.py          BaseAgent (生命周期: plan→act→reflect)
│   │   ├── message_bus.py         异步消息总线 (发布-订阅)
│   │   ├── context.py             SharedContext (黑板模式)
│   │   ├── tool_registry.py       ToolRegistry (工具注册+依赖注入)
│   │   └── orchestrator.py        AgentOrchestrator (编排+降级)
│   ├── agents/                # 🤖 Agent实现
│   │   ├── router.py               RouterAgent (意图识别+任务分发)
│   │   ├── analyst.py              AnalystAgent (因子计算+LLM分析)
│   │   ├── trader.py               TraderAgent (调仓+风控)
│   │   └── reporter.py             ReporterAgent (报告生成)
│   ├── data/                  # 📊 数据层
│   │   ├── store.py                DuckDB存储 (列式+Parquet)
│   │   ├── fetcher.py              AKShare/Tushare数据拉取
│   │   ├── baostock_adapter.py     BaoStock适配器 (海外可用)
│   │   └── yahoo_adapter.py        Yahoo Finance适配器
│   ├── factors/               # 📉 因子层 (36个纯函数)
│   │   ├── engine.py               FactorEngine (注册+评分+权重)
│   │   ├── fundamental.py          基本面因子 (12个)
│   │   ├── technical.py            技术面因子 (12个)
│   │   ├── capital_flow.py         资金面因子 (5个)
│   │   ├── market_sentiment.py     市场情绪因子 (4个)
│   │   └── llm_factors.py          LLM增强因子 (3个)
│   ├── strategy/              # 📈 策略层
│   │   └── continuous_score.py     连续评分策略 (ΔS动量)
│   ├── backtest/              # 🔄 回测引擎
│   │   ├── engine.py               Walk-forward回测
│   │   ├── report.py               回测报告生成
│   │   └── constraints.py          A股约束 (T+1/涨跌停/停牌/ST)
│   ├── llm/                   # 🤖 LLM集成
│   │   ├── client.py               LLM客户端 (支持国产模型)
│   │   ├── prompts.py              Prompt模板管理
│   │   └── cache.py                三层缓存 (DuckDB+批量+降级)
│   ├── bot/                   # 💬 Telegram Bot
│   ├── simulator/             # 📋 模拟交易
│   └── infra/                 # ⚙️ 基础设施 (配置/日志)
├── config/                    # YAML配置
│   ├── settings.yaml              全局设置
│   ├── factors.yaml               因子配置+权重
│   └── strategies.yaml            策略参数
├── knowledge/                 # 📚 知识库
├── scripts/                   # 🚀 入口脚本
│   ├── bootstrap.py               多Agent系统启动
│   ├── init_data.py               首次数据下载
│   ├── daily_update.py            每日更新流水线
│   ├── enhanced_backtest.py       增强回测 (手续费+基准)
│   └── run_bot.py                 Telegram Bot
├── docs/                      # 📖 文档
│   └── MULTI_AGENT_ARCHITECTURE.md
└── tests/                     # ✅ 测试 (15个单元测试)
```

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/yourname/stockradar.git
cd stockradar
pip install -e ".[dev]"
```

### 配置

```bash
cp .env.example .env
# 编辑 .env：
# TUSHARE_TOKEN=xxx          (可选，AKShare免费)
# LLM_API_KEY=xxx            (可选，LLM因子需要)
# TELEGRAM_BOT_TOKEN=xxx     (可选，Bot推送)
```

### 初始化数据

```bash
python scripts/init_data.py --start 20200101
```

### 每日运行

```bash
# 盘后更新 + 评分
python scripts/daily_update.py

# 启动Telegram Bot
python scripts/run_bot.py
```

### 回测

```bash
# 基础回测
python scripts/run_backtest.py --start 20210101 --end 20240101

# 增强回测（手续费+基准对比）
python scripts/enhanced_backtest.py --stocks 100 --start 20220101
```

### 多Agent模式

```python
import asyncio
from scripts.bootstrap import create_system

orch = create_system()

# 自然语言交互 → Router自动分发
result = await orch.process_user_message("分析宁德时代")
print(result)

# 每日流水线 → Analyst → Trader → Reporter
await orch.run_daily_pipeline()
```

## 🔌 数据源

| 数据 | 来源 | 费用 | 海外可用 |
|---|---|---|---|
| 日线行情 | BaoStock | 免费 | ✅ |
| 财务指标(4类) | BaoStock | 免费 | ✅ |
| 指数行情 | BaoStock | 免费 | ✅ |
| 日线行情(备选) | AKShare | 免费 | ❌ |
| 财务指标(备选) | Tushare Pro | ¥500/年 | ✅ |
| 新闻资讯 | 财联社/华尔街见闻 | 免费 | ✅ |

## 🛡️ 风控体系

```
┌─────────────────────────────────────┐
│           三层风控                    │
├─────────────────────────────────────┤
│ 1️⃣ 个股层面                        │
│    • 硬止损 -18%（保命线）           │
│    • 减仓线 -12%（减半仓）           │
│    • 单日暴跌 -9%（紧急减仓60%）      │
├─────────────────────────────────────┤
│ 2️⃣ 组合层面                        │
│    • 行业分散（同申万L1最多2只）      │
│    • 换仓限制（每周最多2次）          │
│    • 缓冲区（Rank 11-20观察池）       │
├─────────────────────────────────────┤
│ 3️⃣ 策略层面                        │
│    • 市场状态识别（牛/熊/震荡）       │
│    • 危机模式（全仓防御）             │
└─────────────────────────────────────┘
```

## 🧪 测试

```bash
pytest                    # 15个单元测试
pytest -v --tb=short      # 详细输出
```

## 开源版 vs Pro版

| 功能 | 开源版 | Pro版 |
|---|---|---|
| Agent数量 | 4个（Router/Analyst/Trader/Reporter） | + EvolverAgent（自我进化） |
| 因子数量 | 36个基础因子 | 36 + LLM自动发现新因子 |
| 因子管理 | 手动配置 | 全自动进化+淘汰+发现 |
| 策略 | 固定连续评分 | 动态策略切换（市场状态感知） |
| 知识积累 | Markdown文件 | 知识图谱+语义检索 |
| 回测 | Walk-forward | + 蒙特卡洛 + 参数敏感性分析 |
| 支持 | GitHub Issues | 专属群+优先响应 |
| 定价 | 免费 | ¥99/月 |

Pro版通过 `proprietary/` 模块提供（编译为.pyd），安装后自动解锁全部高级功能。

## 🗺️ Roadmap

- [x] 36因子评分体系
- [x] 多Agent协作框架（4个Agent）
- [x] BaoStock数据适配器（海外可用）
- [x] 增强回测（手续费+基准对比）
- [x] Telegram Bot（11个指令）
- [ ] 全沪深300回测验证
- [ ] Walk-forward滚动回测
- [ ] GitHub Actions CI/CD
- [ ] PyPI发布（`pip install stockradar`）
- [ ] Pro版发布（EvolverAgent + 自我进化）

## ⚠️ 免责声明

本项目**仅供学习和研究使用，不构成任何投资建议**。

- 所有交易均为**模拟交易**，不连接任何实盘券商
- 历史回测不代表未来表现
- 使用者需自行承担投资决策的风险

## 🤝 贡献

欢迎贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## 📄 许可证

- 开源部分：[Apache 2.0](LICENSE)
- 闭源部分（`proprietary/`）：见 [PROPRIETARY_LICENSE](PROPRIETARY_LICENSE)

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个Star！**

</div>
