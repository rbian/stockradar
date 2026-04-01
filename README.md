# 📡 StockRadar

> AI驱动的A股智能选股系统 — 多Agent协作架构 · 36因子评分 · 模拟交易 · 自进化

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache_2.0-green)](LICENSE)
[![Stocks](https://img.shields.io/badge/沪深300-300只-orange)](https://csiindex.com.cn)

## 🎯 核心功能

- **36因子评分体系** — 基本面(35%) + 技术面(20%) + 资金流(20%) + 市场情绪(15%) + LLM(10%)
- **多Agent协作架构** — Router → Analyst → Trader → Reporter + Evolver，各司其职，LLM驱动决策
- **模拟交易系统** — 自动建仓/调仓/止损，净值追踪，交易日志，每日15:30自动推送日报
- **实时数据** — QVeris(实时补充) + BaoStock(历史缓存)，海外可用
- **Telegram Bot** — 主交互界面，/top /nav /report 快捷命令
- **Walk-Forward验证** — 12月训练→3月测试滚动窗口，样本外胜率75%
- **五维自进化** — D1信号/D2策略/D3架构/D4能力/D5交互，三级安全机制
- **开源核心** — 数据、因子、回测、Bot全开源；EvolverAgent编译为.pyd

## 📊 回测表现

### 300只沪深300全量回测 (2024.01-2026.03)

```
300只 | 36因子 | 每10天调仓 | 含0.1%手续费 | 止损-18%

总收益:    +46.23%    年化:    18.5%
最大回撤:  -21.7%     Sharpe:  0.75
Calmar:    0.85       交易:    909笔
月度胜率:  63%        调仓:    54次
```

### 99只Walk-Forward验证 (样本外)

```
12月训练 → 3月测试 → 3月步进 | 样本外胜率75%

23Q4:  +8.1% 🟢  Sharpe 1.74
24Q1:  +0.9% 🟢  Sharpe 0.63
24Q2:  -9.2% 🔴  Sharpe -4.73
24Q3:  +23.7% 🟢 Sharpe 2.47
```

### 月度收益热力图 (300只)

```
2024:  +10.9%  +2.8%  -5.7%  -3.5%  +1.9%  -1.8%  -7.0%  +26.3%  -1.6%  -2.7%  +6.4%  +4.7%
2025:  +15.4%  -1.2%  -2.6%  -0.0%  +8.7%  +7.3%  +11.8% +4.4%   -6.8%  -4.1%  +3.4%  +1.2%
2026:  -2.3%   -7.3%
```

## 🏗️ 多Agent架构

StockRadar采用**多Agent协作架构**，每个Agent有独立的职责、工具和决策逻辑：

```
┌──────────────────────────────────────────────────┐
│                   Telegram Bot                     │
│              (主交互界面 · 用户API)                 │
│  APScheduler: 15:10数据更新 · 15:25调仓 · 15:30日报 │
└───────────────────┬──────────────────────────────┘
                    │ 用户消息
┌───────────────────▼──────────────────────────────┐
│                RouterAgent 🧭                      │
│           意图识别 → 任务路由                        │
│  正则匹配 + 关键词分类 → 分发到专业Agent             │
├─────────┬──────────┬──────────┬──────────────────┤
│         │          │          │                    │
│  AnalystAgent 📊  │  TraderAgent 💰  │  ReporterAgent 📰  │
│  ─────────────── │  ────────────── │  ──────────────── │
│  • 36因子评分     │  • 持仓管理     │  • 日报(大盘+持仓) │
│  • 个股深度分析   │  • 调仓决策     │  • 周报(收益+交易) │
│  • 技术面诊断     │  • 净值追踪     │  • 月报(净值曲线) │
│  • Top10排名      │  • 止损-18%    │  • 市场概况       │
│                  │  • 交易日志     │                   │
├──────────────────┴──────────┴──────────────────────┤
│              ToolRegistry 🔧                        │
│  score_all() · fetch_quote() · get_portfolio()     │
│  register_tool() 注入所有Agent                      │
├────────────────────────────────────────────────────┤
│            FactorEngine ⚙️ (36因子)                  │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│
│  │基本面(12)│ │技术面(6) │ │资金流(8) │ │情绪(4) ││
│  │权重 35%  │ │权重 20%  │ │权重 20%  │ │权重15% ││
│  │ROE/PE/..│ │RSI/MACD  │ │北向/大单 │ │换手/量比││
│  └──────────┘ └──────────┘ └──────────┘ └────────┘│
│  + LLM因子(10%): earnings情绪·新闻·研报·深度分析     │
├────────────────────────────────────────────────────┤
│                  数据层 📦                           │
│                                                     │
│  QVeris API ──→ 实时行情(1000 credits/天)           │
│  BaoStock   ──→ 历史数据(免费,33.8万条Parquet缓存)   │
│  DuckDB + Parquet ───→ 列式存储,10年滚动窗口         │
├────────────────────────────────────────────────────┤
│              EvolverAgent 🧬 (闭源)                  │
│                                                     │
│  D1 信号发现 → D2 策略优化 → D3 架构演进             │
│  D4 能力扩展 → D5 交互进化                           │
│  三级安全: L0自动 → L1通知 → L2审批 → L3建议        │
└────────────────────────────────────────────────────┘
```

### Agent通信机制

```python
# 消息总线 + 共享上下文
MessageBus → 异步消息传递
SharedContext → 全局状态读写(行情/评分/持仓)
ToolRegistry → 工具注册,注入所有Agent

# 工作流
用户消息 → Router路由 → 目标Agent.think() → Plan → Agent.act() → ActionResult
                                                                 ↓
                                                           Telegram回复
```

### Agent生命周期

```python
class BaseAgent:
    async def think(observation) → Plan      # 感知+规划
    async def act(plan, context) → ActionResult  # 执行
    async def run(context) → ActionResult    # think → act
    def register_tool(name, fn)              # 工具注入
```

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/rbian/stockradar.git
cd stockradar
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入:
#   QVERIS_API_KEY=your_key       # https://qveris.ai 注册获取
#   TELEGRAM_BOT_TOKEN=your_token  # @BotFather 获取
```

### 初始化数据

```bash
python scripts/init_data.py        # 拉取沪深300数据 (首次~10分钟)
python scripts/fetch_hs300.py      # 更新沪深300成分股
```

### 运行

```bash
# Telegram Bot (主入口)
python scripts/run_bot.py

# 300只历史回测
python scripts/nav_backtest.py

# Walk-Forward验证
python scripts/walk_forward.py

# 端到端测试
python scripts/e2e_test.py
```

## 💬 Bot命令

| 命令 | 快捷键 | 功能 | 示例 |
|------|--------|------|------|
| `评分排名` | /top | 36因子评分Top10 | `选股推荐` |
| `分析600519` | — | 个股深度分析 | `分析茅台` |
| `市场怎么样` | — | 市场概况(沪深300) | `大盘行情` |
| `持仓建议` | — | 评分→建仓Top10 | `调仓` |
| `净值` | /nav | 净值追踪+收益 | `盈亏` |
| `净值图` | — | 净值曲线图 | `走势图` |
| `日报` | /report | 每日总结 | `今天怎么样` |
| `回测` | — | 历史回测结果 | `策略效果` |
| `周报` | — | 本周收益+交易 | `这周表现` |
| `帮助` | /help | 功能列表 | `怎么用` |

### 定时任务 (自动)

| 时间 | 任务 | 说明 |
|------|------|------|
| 15:10 | 数据更新 | QVeris增量拉取最新行情 |
| 15:25 | 自动调仓 | 评分Top10调仓 + 止损检查 |
| 15:30 | 日报推送 | 市况+持仓+净值+Top5 |

## 📁 项目结构

```
stockradar/
├── src/
│   ├── agents/              # 🤖 多Agent系统
│   │   ├── agent_base.py    #   Agent基类(think/act/run)
│   │   ├── router.py        #   RouterAgent 路由分发
│   │   ├── analyst.py       #   AnalystAgent 评分分析
│   │   ├── trader.py        #   TraderAgent 交易决策
│   │   └── reporter.py      #   ReporterAgent 日报周报
│   ├── core/                # 🏗️ 核心框架
│   │   ├── orchestrator.py  #   Agent编排+生命周期
│   │   ├── tool_registry.py #   工具注册+注入
│   │   └── shared_context.py#   共享上下文(行情/评分)
│   ├── factors/             # ⚙️ 36因子引擎
│   │   ├── engine.py        #   评分引擎(批量300只)
│   │   ├── fundamental.py   #   基本面因子(12个)
│   │   ├── technical.py     #   技术面因子(6个)
│   │   ├── capital_flow.py  #   资金流因子(8个)
│   │   └── market_sentiment.py # 市场情绪因子(4个)
│   ├── data/                # 📦 数据层
│   │   ├── qveris_adapter.py  # QVeris实时接口
│   │   ├── baostock_adapter.py# BaoStock历史接口
│   │   ├── cache.py           # Parquet财务缓存
│   │   └── stock_names.py     # 股票名称映射(5509只)
│   ├── simulator/           # 💰 模拟交易
│   │   └── nav_tracker.py   #   净值追踪(建仓/调仓/止损)
│   ├── backtest/            # 📊 回测引擎
│   ├── evolution/           # 🧬 自进化框架
│   ├── llm/                 # 🧠 LLM集成
│   └── infra/               # 🔧 基础设施
├── config/                  # ⚙️ 配置
│   ├── settings.yaml        #   全局设置
│   ├── factors.yaml         #   因子权重配置
│   └── strategies.yaml      #   策略参数
├── scripts/                 # 📜 运行脚本
│   ├── run_bot.py           #   Telegram Bot入口
│   ├── nav_backtest.py      #   300只历史回测
│   ├── walk_forward.py      #   Walk-Forward验证
│   ├── e2e_test.py          #   端到端测试
│   └── incremental_update.py#   QVeris增量更新
├── data/                    # 📊 数据目录
│   ├── parquet/             #   行情Parquet(33.8万条)
│   ├── cache/financial/     #   财务缓存(300只)
│   └── nav_state.json       #   模拟持仓状态
├── output/                  # 📈 输出
│   ├── nav_chart.png        #   净值曲线图
│   └── nav_history.csv      #   净值历史
└── docs/                    # 📚 文档
    ├── ARCHITECTURE.md
    ├── MULTI_AGENT_ARCHITECTURE.md
    └── EVOLVER_FIVE_DIMENSIONS.md
```

## 📈 36因子详细列表

### 基本面 (12因子, 权重35%)
| 因子 | 说明 | 数据源 |
|------|------|--------|
| ROE | 净资产收益率 | BaoStock季报 |
| 毛利率 | gross_profit_margin | BaoStock |
| 净利率 | net_profit_margin | BaoStock |
| 营收增速 | revenue_yoy | BaoStock |
| 利润增速 | profit_yoy | BaoStock |
| 现金流比率 | operating_cash/revenue | BaoStock |
| 负债率 | debt_to_assets | BaoStock |
| 商誉比 | goodwill/assets | BaoStock |
| PE分位 | historical percentile | 计算衍生 |
| PB分位 | historical percentile | 计算衍生 |
| PEG | PE / earnings_growth | 计算衍生 |
| 经营杠杆 | revenue_growth / profit_growth | 计算衍生 |

### 技术面 (6因子, 权重20%)
RSI(14) · MACD信号 · 布林带宽度 · 量价背离 · 换手率变化 · 振幅

### 资金流 (8因子, 权重20%)
北向资金 · 大单净买入 · 主力净流入 · 资金流向变化 · 特大单比 · 大单比 · 北向持股变化 · 北向增持

### 市场情绪 (4因子, 权重15%)
换手率异动 · 涨停计数 · 高低位置(52周) · 量比

### LLM (6因子, 权重10%)
earnings情绪 · 新闻情绪7日 · 研报共识 · LLM深度分析 (通过API调用，三层缓存)

## 🧬 五维自进化系统

### 进化维度

| 维度 | 代号 | 内容 | 安全等级 |
|------|------|------|---------|
| D1 信号 | Signal | 因子发现/淘汰/权重微调 | L1 通知 |
| D2 策略 | Strategy | 参数优化、止损调仓规则 | L2 审批 |
| D3 架构 | Architecture | 性能优化、缓存策略 | L2 审批 |
| D4 能力 | Ability | 新工具/新数据源接入 | L2 审批 |
| D5 交互 | Interaction | 用户画像、个性化推送 | L0 自动 |

### 安全机制

```
L0 自动执行 → 因子权重微调(±0.5)、用户偏好学习
L1 通知确认 → 新因子上线、因子淘汰
L2 人工审批 → 策略逻辑变更、代码补丁
L3 仅建议   → 基础设施变更、数据源切换
```

### 三个进化循环

```
日循环: IC追踪 + 权重微调 (自动)
周循环: LLM假设生成 → 新因子验证 (通知)
月循环: 策略诊断 + 失败交易复盘 (审批)
```

## 📋 License

- **核心模块** (`src/`, `scripts/`, `config/`): [Apache 2.0](LICENSE)
- **进化模块** (`proprietary/`): 商业许可 (编译为.pyd)

## 🙏 致谢

- [QVeris](https://qveris.ai) — AI Agent工具网关，实时A股数据
- [BaoStock](http://baostock.com) — 免费A股历史数据
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot框架
- [DuckDB](https://duckdb.org) — 列式分析数据库
- [PyArrow](https://arrow.apache.org) — Parquet列式存储
