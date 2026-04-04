# 📡 StockRadar

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[English](README.md)** | **[在线持仓](https://rbian.github.io/stockradar)**

---

## 💡 这是什么

StockRadar 是一个**个人A股模拟交易系统**，每天自动给沪深300成分股打分，维护模拟持仓，通过Telegram Bot推送日报。
### 核心特点

- **多Agent架构** — Router + Analyst + Trader + Reporter + Evolver，每个Agent拥有独立的推理能力和工具集
- **36因子评分** — 基本面+技术面+资金流+市场情绪，3秒完成300只评分
- **模拟交易** — 自动建仓、调仓、净值追踪、风控止损
- **LLM增强** — 个股估值研判、新闻情绪分析、因子假设生成
- **自进化** — 因子IC追踪，权重自动调整，动态因子发现与注册
- **Telegram Bot** — 随时查看评分/持仓/分析

📊 **在线持仓跟踪**: [https://rbian.github.io/stockradar](https://rbian.github.io/stockradar)
## 📊 回测结果
| 年份 | 收益 | 年化 | Sharpe | 最大回撤 | 交易笔数 |
|------|------|------|--------|---------|---------|
| 2024 | +46.2% | 18.5% | 0.75 | -21.7% | 909 |
| 2025 | +37.3% | 29.1% | 1.24 | -18.9% | 476 |
> 回测基于等权Top10持仓，含0.1%手续费。过去表现不代表未来收益。
## ⚙️ 评分因子
```
基本面 35% ─── ROE · 毛利率 · PE分位 · 营收增速 · 利润增速
技术面 20% ─── RSI · MACD · 均线趋势 · 动量
资金流 20% ─── 北向 · 大单 · 主力净流入
市场情绪 15% ─── 换手异动 · 量比 · 涨停计数
LLM   10% ─── 新闻情绪 · 估值研判
```
因子权重由IC追踪系统自动调整（IC高的因子权重增加，IC持续低的因子降权)。
## 🧬 自进化系统
| 维度 | 功能 | 频率 |
|------|------|------|
| D1 因子IC追踪 | 计算因子预测力，自动调整权重 | 每日 |
| D2 策略医生 | 持仓诊断，异常预警 | 每日 |
| D3 市场状态 | 检测趋势/震荡市，辅助策略选择 | 实时 |
| D4 假设生成 | LLM生成新因子假设，IC验证 | 每周 |
**IC实证发现（20日基线）：**
- 趋势因子最强：ma20_slope IC=+0.22
- 反转因子失效：max_drawdown_60d IC=-0.20
- 技术面 >> 基本面（当前市场特征）
## 🏗️ 架构
```
        Telegram Bot
             │
       ┌─────▼─────┐
       │  Router    │  意图识别，路由到对应Agent
       └──┬──┬──┬──┘
          │  │  │
    ┌─────┘  │  └─────┐
    ▼        ▼        ▼
 Analyst  Trader  Reporter
  评分分析  交易决策   日报周报
    │        │        │
    └────┬───┘────────┘
         ▼
   FactorEngine (36因子)
         ▼
   数据层 (新浪 + mootdx + BaoStock)
```
## 💬 Bot命令
```
/top        → 评分Top10 (含持仓标记📦)
/nav        → 净值+收益
/report     → 日报 (行情+持仓+新闻+诊断)
分析600519  → 个股9层深度分析
持仓建议   → 评分→建仓Top10
诊断        → 持仓5日涨跌+风控预警
因子        → IC排行Top/Bottom
市场状态    → 趋势/震荡市判断
风控        → 止损/减仓检查
周报/月报    → 周期报告
回测        → 历史回测结果
```
每天自动：15:10数据更新 → 15:25调仓 → 15:27 IC追踪 → 15:30日报推送 → 15:35 Pages更新
## 📁 项目结构
```
src/agents/      ← 5个Agent (Router / Analyst / Trader / Reporter / Evolver)
src/core/        ← 编排器 + 工具注册 + 共享上下文
src/factors/     ← 36因子评分引擎
src/data/        ← 新浪 + mootdx + BaoStock 数据适配
src/simulator/   ← 净值追踪 + 风控 + 交易记录
src/evolution/   ← IC追踪 + 策略医生 + 假设生成 + 市场状态检测
scripts/         ← Bot入口 + 数据初始化 + 每日更新
config/          ← YAML配置 (因子权重/策略参数)
```
## 🚀 快速开始
```bash
git clone https://github.com/rbian/stockradar.git
cd stockradar
pip install -r requirements.txt
# 配置
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env
echo "TELEGRAM_ALLOWED_USERS=your_id" >> .env
# 运行
python scripts/run_bot.py
```
## 📋 License
MIT
