# 📡 StockRadar

> AI-driven A-share stock scoring & simulated trading — Multi-Agent Architecture · 36 Factors · Self-Evolving

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[中文文档](README_CN.md)** | **[Live Portfolio](https://rbian.github.io/stockradar)**

---

## What is this

StockRadar is a personal A-share simulated trading system that automatically scores HS300 stocks daily, manages a simulated portfolio, and delivers reports via Telegram Bot.

### Key Features

- **Multi-Agent Architecture** — Router + Analyst + Trader + Reporter + Evolver, each with specialized reasoning and tools
- **36-factor scoring** — fundamentals + technicals + capital flow + sentiment, 300 stocks in 3 seconds
- **Simulated trading** — auto rebalance, NAV tracking, stop-loss
- **LLM-enhanced** — valuation analysis, news sentiment, factor hypothesis generation
- **Self-evolving** — IC-based factor weight adjustment, automatic factor discovery and registration
- **Telegram Bot** — real-time scoring / portfolio / analysis

📊 **Live Portfolio Dashboard**: [https://rbian.github.io/stockradar](https://rbian.github.io/stockradar)

## Backtest Results

| Year | Return | Ann. | Sharpe | Max DD | Trades |
|------|--------|------|--------|--------|--------|
| 2024 | +46.2% | 18.5% | 0.75 | -21.7% | 909 |
| 2025 | +37.3% | 29.1% | 1.24 | -18.9% | 476 |

> Equal-weighted Top 10 portfolio, 0.1% commission. Past performance does not guarantee future results.

## Scoring Factors

```
Fundamentals  35% ─── ROE · Gross Margin · PE Percentile · Revenue Growth · Profit Growth
Technicals    20% ─── RSI · MACD · MA Trend · Momentum
Capital Flow  20% ─── Northbound · Large Orders · Net Inflow
Sentiment     15% ─── Turnover Anomaly · Volume Ratio · Limit-Up Count
LLM           10% ─── News Sentiment · Valuation Judgment
```

Factor weights are auto-adjusted by IC tracking (high-IC factors gain weight, persistently low-IC factors are penalized).

## Self-Evolving System

| Dimension | Function | Frequency |
|-----------|----------|-----------|
| D1 Factor IC Tracking | Measure predictive power, auto-adjust weights | Daily |
| D2 Strategy Doctor | Portfolio diagnostics, anomaly alerts | Daily |
| D3 Market Regime | Detect trending/ranging market | Real-time |
| D4 Hypothesis Generation | LLM generates new factor hypotheses, IC validation | Weekly |

**Empirical IC Findings (20-day baseline):**
- Strongest: ma20_slope IC=+0.22 (trend)
- Weakest: max_drawdown_60d IC=-0.20 (reversal)
- Technicals >> Fundamentals (current market regime)

## Architecture

```
        Telegram Bot
             │
       ┌─────▼─────┐
       │  Router    │  intent routing
       └──┬──┬──┬──┘
          │  │  │
    ┌─────┘  │  └─────┐
    ▼        ▼        ▼
 Analyst  Trader  Reporter
 scoring  trading   reports
    │        │        │
    └────┬───┘────────┘
         ▼
   FactorEngine (36 factors)
         ▼
   Data (Sina + mootdx + BaoStock)
```

## Bot Commands

```
/top        → Top 10 scored stocks (with holding markers 📦)
/nav        → NAV + returns
/report     → Daily report (market + portfolio + news + diagnostics)
分析600519  → Deep stock analysis (9 dimensions)
持仓建议     → Score → build Top 10 portfolio
诊断        → 5-day P&L + risk alerts
因子        → IC ranking Top/Bottom
市场状态     → Trend/range detection
风控        → Stop-loss / position reduction check
周报/月报    → Weekly/monthly reports
回测        → Historical backtest results
```

Daily schedule: 15:10 data update → 15:25 rebalance → 15:27 IC tracking → 15:30 report → 15:35 pages update

## Project Structure

```
src/agents/      ← 5 Agents (Router / Analyst / Trader / Reporter / Evolver)
src/core/        ← Orchestrator + Tool Registry + Shared Context
src/factors/     ← 36-factor scoring engine
src/data/        ← Sina + mootdx + BaoStock data adapters
src/simulator/   ← NAV tracking + risk control + trade logging
src/evolution/   ← IC tracking + strategy doctor + hypothesis generation + regime detection
scripts/         ← Bot entry + data init + daily update
config/          ← YAML config (factor weights / strategy params)
```

## Quick Start

```bash
git clone https://github.com/rbian/stockradar.git
cd stockradar
pip install -r requirements.txt

# Configure
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env
echo "TELEGRAM_ALLOWED_USERS=your_id" >> .env

# Run
python scripts/run_bot.py
```

## License

MIT
