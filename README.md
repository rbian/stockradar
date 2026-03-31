# 📡 StockRadar

> AI驱动的A股智能选股系统 — 多Agent架构，36因子评分，实时数据

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache_2.0-green)](LICENSE)

## 🎯 核心功能

- **36因子评分体系** — 基本面(35%) + 技术面(20%) + 资金流(20%) + 市场情绪(15%) + LLM(10%)
- **多Agent架构** — Router → Analyst → Trader → Reporter，各司其职
- **实时数据** — QVeris(海外可用) + BaoStock(免费备份)，A股实时行情
- **Telegram Bot** — 主交互界面，随时查询
- **Walk-Forward验证** — 样本外胜率75%，无过拟合
- **自进化框架** — 五维进化(D1信号/D2策略/D3架构/D4能力/D5交互)

## 📊 回测表现

```
99只沪深300成分股 | 36因子 | 2023.01-2025.02 | 0.1%手续费

总收益:    +67.67%    年化:  27.5%
最大回撤:  -20.5%     Sharpe: 1.24
Calmar:    3.31       交易:  810笔
```

### Walk-Forward (样本外)

| 区间 | 收益 | 回撤 | Sharpe |
|------|------|------|--------|
| 23Q4 | +8.1% 🟢 | -5.1% | 1.74 |
| 24Q1 | +0.9% 🟢 | -2.5% | 0.63 |
| 24Q2 | -9.2% 🔴 | -9.2% | -4.73 |
| 24Q3 | +23.7% 🟢 | -8.0% | 2.47 |

## 🏗️ 架构

```
┌─────────────────────────────────────────┐
│            Telegram Bot                  │
│         (主交互界面)                      │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│           RouterAgent                    │
│       (意图识别 → 任务分发)               │
├──────────┬──────────┬───────────────────┤
│Analyst   │Trader    │Reporter           │
│评分/分析  │持仓/交易  │日报/周报           │
├──────────┴──────────┴───────────────────┤
│         ToolRegistry                     │
│  score_all │ fetch_quote │ QVeris       │
├─────────────────────────────────────────┤
│         FactorEngine (36因子)            │
│  基本面12 │ 技术6 │ 资金8 │ 情绪4 │ LLM │
├─────────────────────────────────────────┤
│         数据层                            │
│  QVeris (实时) │ BaoStock (历史缓存)      │
│  DuckDB + Parquet                       │
└─────────────────────────────────────────┘
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
```

### 运行

```bash
# Telegram Bot
python scripts/run_bot.py

# 端到端测试
python scripts/e2e_test.py

# 正式回测
python scripts/enhanced_backtest_v2.py
```

## 💬 Bot命令

| 命令 | 功能 | 示例 |
|------|------|------|
| `分析600519` | 个股分析(行情+技术+基本面) | 分析茅台 |
| `市场怎么样` | 市场概况(沪深300实时) | 大盘行情 |
| `评分排名` | 36因子评分Top10 | 选股推荐 |
| `当前持仓` | 持仓查看 | 持仓组合 |
| `净值` | 净值追踪 | 收益盈亏 |
| `回测` | 回测结果 | 策略效果 |
| `日报` | 今日日报 | 市场总结 |
| `帮助` | 功能列表 | 怎么用 |

## 📁 项目结构

```
stockradar/
├── src/
│   ├── agents/          # 多Agent系统
│   │   ├── router.py    # 路由Agent
│   │   ├── analyst.py   # 分析Agent
│   │   ├── trader.py    # 交易Agent
│   │   └── reporter.py  # 报告Agent
│   ├── core/            # 核心框架
│   │   ├── orchestrator.py   # Agent编排
│   │   ├── agent_base.py     # Agent基类
│   │   ├── tool_registry.py  # 工具注册
│   │   └── shared_context.py # 共享上下文
│   ├── factors/         # 36因子引擎
│   │   ├── engine.py    # 评分引擎
│   │   ├── fundamental.py  # 基本面(12)
│   │   ├── technical.py    # 技术面(6)
│   │   ├── capital_flow.py # 资金流(8)
│   │   └── market_sentiment.py # 情绪(4)
│   ├── data/            # 数据层
│   │   ├── qveris_adapter.py  # QVeris实时
│   │   ├── baostock_adapter.py # BaoStock缓存
│   │   ├── cache.py           # Parquet缓存
│   │   └── store.py           # DuckDB存储
│   ├── backtest/        # 回测引擎
│   ├── evolution/       # 自进化框架
│   ├── llm/             # LLM集成
│   ├── bot/             # Telegram Bot
│   └── infra/           # 基础设施
├── config/              # 配置文件
│   ├── settings.yaml
│   ├── factors.yaml
│   └── strategies.yaml
├── scripts/             # 运行脚本
├── data/                # 数据目录(DuckDB + Parquet)
├── docs/                # 文档
└── tests/               # 测试
```

## 📈 36因子列表

### 基本面 (权重35%)
ROE、毛利率、净利率、营收增速、利润增速、现金流比率、负债率、商誉比、PE分位、PB分位、PEG、经营杠杆

### 技术面 (权重20%)
RSI、MACD信号、布林带宽度、量价背离、换手率变化、振幅

### 资金流 (权重20%)
北向资金、大单净买入、主力净流入、资金流向变化、特大单比、大单比、北向持股变化、北向增持

### 市场情绪 (权重15%)
换手率异动、涨停计数、高低位置、量比

### LLM (权重10%)
 earnings情绪、新闻情绪7日、研报共识、LLM深度分析

## 🧬 五维自进化

| 维度 | 内容 | 安全等级 |
|------|------|---------|
| D1 信号 | 因子发现/淘汰/权重调整 | L1 通知 |
| D2 策略 | 参数优化、止损调仓 | L2 审批 |
| D3 架构 | 性能优化、缓存策略 | L2 审批 |
| D4 能力 | 新工具/新数据源接入 | L2 审批 |
| D5 交互 | 用户画像、个性化推送 | L0 自动 |

## 📋 License

- **核心模块**: Apache 2.0 (开源)
- **进化模块** (`proprietary/`): 商业许可 (编译为.pyd)

## 🙏 致谢

- [QVeris](https://qveris.ai) — AI Agent工具网关，实时A股数据
- [BaoStock](http://baostock.com) — 免费A股历史数据
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot框架
- [DuckDB](https://duckdb.org) — 列式分析数据库
