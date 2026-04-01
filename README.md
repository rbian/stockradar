# 📡 StockRadar

> AI驱动的A股智能选股系统 — 300只沪深300 · 年化18.5% · 多Agent协作

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache_2.0-green)](LICENSE)

---

## 💡 为什么用多Agent？

传统量化系统是一个大脚本，所有逻辑耦合在一起。StockRadar把**决策链拆成专业Agent**，每个Agent只做一件事，做到最好：

| 对比 | 单体脚本 | StockRadar多Agent |
|------|---------|------------------|
| 新增功能 | 改主逻辑，怕引入bug | 加一个Agent，零耦合 |
| 出错定位 | 全链路排查 | 精确到单个Agent |
| LLM集成 | 所有逻辑共享一个prompt | 每个Agent有专属prompt |
| 扩展 | 越来越难维护 | 无限横向扩展 |
| 进化 | 手动调参 | Agent自我进化(D1-D5) |

**核心思路：把"选股→交易→风控→报告"拆成独立Agent，像团队一样协作。**

## 🏗️ 架构

```
         用户(Telegram)
              │
        ┌─────▼─────┐
        │  Router 🧭 │  意图识别，秒级路由
        └──┬──┬──┬──┘
           │  │  │
     ┌─────┘  │  └─────┐
     ▼        ▼        ▼
 Analyst📊 Trader💰 Reporter📰
  评分分析   交易决策   日报周报
     │        │        │
     └────┬───┘────────┘
          ▼
    ToolRegistry 🔧
    (工具注入所有Agent)
          │
          ▼
    FactorEngine ⚙️
    36因子评分(3秒/300只)
          │
          ▼
    数据层 📦
    QVeris(实时) + BaoStock(历史)
          │
          ▼
    EvolverAgent 🧬 (闭源)
    五维自进化 · 三级安全机制
```

### 三个设计决策

**1. 工具注入 > 继承**
Agent不继承任何基类方法，通过`ToolRegistry`动态注入能力。新增数据源？注册一个tool，所有Agent自动获得。

**2. LLM作为大脑，代码作为工具**
Agent的`think()`做决策（可接LLM），`act()`执行确定性代码。模糊决策用AI，精确执行用代码。

**3. 开源核心 + 闭源进化**
数据、因子、回测、Bot全部开源。EvolverAgent（因子发现/策略优化/架构演进）编译为.pyd，核心IP保护。

## 📊 实绩

### 300只沪深300 (2024.01-2026.03)

```
年化 18.5%  |  Sharpe 0.75  |  回撤 -21.7%
月度胜率 63%  |  909笔交易  |  含0.1%手续费
```

### Walk-Forward样本外验证

```
12月训练 → 3月测试 → 3月步进
胜率 75% (3/4季度正收益)
最佳季度 +23.7%  最差 -9.2%
```

## ⚙️ 36因子体系

```
基本面 35% ─── ROE·毛利率·PE分位·PEG 等12个
技术面 20% ─── RSI·MACD·布林带 等6个
资金流 20% ─── 北向·大单·主力净流入 等8个  
市场情绪 15% ── 换手异动·量比·涨停计数 等4个
LLM   10% ──── earnings情绪·新闻·研报 等6个
```

> BaoStock免费历史数据 + QVeris实时补充。无需付费数据源。

## 🧬 五维自进化

| 维度 | 自动化 | 说明 |
|------|--------|------|
| D1 信号 | 自动微调 | 因子权重±0.5，60天IC<0.01自动淘汰 |
| D2 策略 | 人工审批 | 止损/调仓规则变更 |
| D3 架构 | 人工审批 | 性能优化、缓存策略 |
| D4 能力 | 人工审批 | 新数据源、新工具接入 |
| D5 交互 | 全自动 | 用户偏好学习、推送个性化 |

**三个循环：** 日(IC追踪) → 周(LLM假设) → 月(策略复盘)

## 🚀 30秒上手

```bash
git clone https://github.com/rbian/stockradar.git
cd stockradar
pip install -r requirements.txt

# 配置
echo "QVERIS_API_KEY=your_key" >> .env
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env

# 初始化 + 运行
python scripts/init_data.py
python scripts/run_bot.py
```

Bot启动后，Telegram里发送 `帮助` 查看所有命令。

## 💬 Bot交互

```
/top       → 36因子评分Top10
/nav       → 净值+收益+回撤
/report    → 今日日报
分析茅台    → 个股深度分析
持仓建议    → 自动评分→建仓Top10
净值图     → 净值曲线图
回测       → 历史回测结果
```

每天 **15:30自动推送日报**（市况+持仓+净值+Top5推荐）。

## 📁 结构

```
src/agents/     ← 4个Agent (Router/Analyst/Trader/Reporter)
src/core/       ← 编排器 + 工具注册 + 共享上下文
src/factors/    ← 36因子引擎
src/data/       ← QVeris + BaoStock 适配器
src/simulator/  ← 净值追踪 (建仓/调仓/止损)
scripts/        ← Bot入口 + 回测 + 数据初始化
config/         ← YAML配置 (因子权重/策略参数)
```

## 📋 License

- **核心**: Apache 2.0 (本仓库)
- **EvolverAgent**: 商业许可 (`proprietary/`)

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/rbian">rbian</a> · 
  Powered by QVeris + BaoStock + python-telegram-bot</sub>
</p>
