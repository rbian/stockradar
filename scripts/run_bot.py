"""Telegram Bot — StockRadar多Agent系统"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from src.infra.logger import setup_logger
from scripts.system_init import create_system

orch = None
ALLOWED_USERS = set()

# 按钮文字 → Agent消息映射
BUTTON_MAP = {
    "📊 市场概况": "市场怎么样",
    "🏆 评分排名": "评分排名",
    "📈 持仓建议": "持仓",
    "📰 日报": "日报",
    "📉 回测": "回测",
    "📈 净值图": "净值图",
    "📝 周报": "周报",
    "📊 月报": "月报",
    "❓ 帮助": "帮助",
}


def load_env():
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🏆 评分排名", "📈 持仓建议"],
            ["📊 市场概况", "📰 日报"],
            ["📉 回测", "📈 净值图"],
            ["📝 周报", "📊 月报"],
        ],
        resize_keyboard=True,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ 未授权")
        return
    await update.message.reply_text(
        "📡 **StockRadar 已上线！**\n\n"
        "功能:\n"
        "• 实时沪深300行情\n"
        "• 36因子智能评分\n"
        "• 个股分析（输入代码或名称）\n"
        "• 持仓建议和回测\n\n"
        "点击按钮或直接输入 👇",
        reply_markup=get_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 **StockRadar**\n\n"
        "📊 市场 — 实时沪深300\n"
        "🏆 评分 — 36因子排名\n"
        "📈 持仓 — Top10建议\n"
        "📰 日报 — 每日总结\n"
        "📉 回测 — 历史表现\n"
        "🔍 个股 — 600519 或 茅台\n\n"
        "命令: /top /nav /report\n\n"
        "数据: QVeris(实时) + BaoStock(历史)",
        reply_markup=get_keyboard(),
    )


async def _quick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, msg: str):
    """快捷命令 — 直接处理，不修改不可变的message.text"""
    await _process_text(update, msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _process_text(update, update.message.text.strip())


async def _process_text(update: Update, text: str):
    """统一消息处理"""
    global orch
    user_id = str(update.effective_user.id)
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        return

    if not text:
        return

    # 按钮映射
    text = BUTTON_MAP.get(text, text)

    logger.info(f"[{user_id}] {text}")

    try:
        # 净值图请求 → 发送图片
        if any(kw in text for kw in ["净值图", "曲线", "走势图"]):
            chart = PROJECT_ROOT / "output" / "nav_chart.png"
            if chart.exists():
                await update.message.reply_photo(photo=open(chart, "rb"),
                    caption="📊 StockRadar 300只净值曲线 (2024-2026)\n年化18.5% | 回撤-21.7%",
                    reply_markup=get_keyboard())
                return

        result = await asyncio.wait_for(
            orch.process_user_message(text, user_id=user_id),
            timeout=90,
        )
        if len(result) > 4000:
            result = result[:4000] + "\n..."
        await update.message.reply_text(result, reply_markup=get_keyboard())
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ 分析超时（90秒），LLM或数据源响应慢，请稍后重试", reply_markup=get_keyboard())
    except ConnectionError:
        await update.message.reply_text("📡 网络连接失败，请检查网络后重试", reply_markup=get_keyboard())
    except Exception as e:
        logger.error(f"处理失败: {e}")
        await update.message.reply_text(f"❌ 处理失败，请重试或输入'帮助'", reply_markup=get_keyboard())


def main():
    global orch, ALLOWED_USERS
    setup_logger()
    load_env()

    # Pidfile锁 — 防止多实例
    PIDFILE = Path(__file__).resolve().parent.parent / "data" / "bot.pid"
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)

    # 检查旧进程是否存活
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            if old_pid > 0:
                try:
                    os.kill(old_pid, 0)  # 检查进程是否存在
                    # 如果没抛异常，说明进程还活着
                    logger.error(f"❌ Bot已在运行(PID:{old_pid})，退出")
                    return
                except ProcessLookupError:
                    logger.warning(f"旧Bot进程(PID:{old_pid})已死，启动新实例")
                except PermissionError:
                    pass
        except (ValueError, OSError):
            pass

    # 写入新PID
    PIDFILE.write_text(str(os.getpid()))

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set")
        return

    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    if allowed:
        ALLOWED_USERS = set(allowed.split(","))

    logger.info("Starting StockRadar Bot...")

    orch = create_system()
    logger.info(f"System ready: {len(orch.agents)} agents")

    app = Application.builder().token(token).build()
    
    # 注册Telegram命令菜单
    async def set_commands(app):
        from telegram import BotCommand
        await app.bot.set_my_commands([
            BotCommand("top", "📊 评分Top10"),
            BotCommand("nav", "💰 净值+收益"),
            BotCommand("report", "📰 今日日报"),
            BotCommand("help", "❓ 功能列表"),
            BotCommand("factors", "🧬 因子状态"),
        ])
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("top", lambda u, c: _quick_cmd(u, c, "评分排名")))
    app.add_handler(CommandHandler("nav", lambda u, c: _quick_cmd(u, c, "净值")))
    app.add_handler(CommandHandler("report", lambda u, c: _quick_cmd(u, c, "日报")))
    app.add_handler(CommandHandler("factors", lambda u, c: _quick_cmd(u, c, "因子状态")))

    # 定时任务
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import asyncio

    async def daily_push():
        """15:30 日报推送"""
        for uid in ALLOWED_USERS:
            try:
                result = await asyncio.wait_for(
                    orch.process_user_message("日报", user_id=uid), timeout=60
                )
                await app.bot.send_message(chat_id=uid, text=result, reply_markup=get_keyboard())
                logger.info(f"日报推送: {uid}")
            except Exception as e:
                logger.error(f"日报推送失败 {uid}: {e}")

    async def post_init(app):
        await set_commands(app)
        scheduler = AsyncIOScheduler()
        # 数据更新: 15:10 新浪实时行情（优先）+ mootdx备用
        async def data_update():
            if not _is_trading_day():
                logger.info("今日休市，跳过数据更新")
                return
            logger.info("定时数据更新...")
            try:
                import pandas as pd
                from src.data.sina_adapter import update_daily_from_sina
                dq = orch.context.read("data.daily_quote")
                codes = pd.read_csv("data/hs300_codes.txt", header=None)[0].tolist()
                parquet = str(PROJECT_ROOT / "data" / "parquet" / "hs300_daily.parquet")
                updated = update_daily_from_sina(dq, codes, parquet)
                orch.context.write("data.daily_quote", updated, writer="system")
                logger.info(f"新浪更新: {len(updated)}条, 最新={updated['date'].max()}")
            except Exception as e:
                logger.warning(f"新浪更新失败，尝试mootdx: {e}")
                try:
                    from src.data.mootdx_adapter import daily_update_mootdx
                    daily_update_mootdx()
                except Exception as e2:
                    logger.warning(f"mootdx也失败，尝试Tushare日线: {e2}")
                    try:
                        import tushare as ts
                        token = os.environ.get('TUSHARE_TOKEN', '')
                        if token:
                            ts.set_token(token)
                            pro = ts.pro_api()
                            codes = pd.read_csv("data/hs300_codes.txt", header=None)[0].tolist()
                            rows = []
                            for c in codes[:50]:  # Free tier limit
                                df = pro.daily(ts_code=f"{c}.SH" if c.startswith('6') else f"{c}.SZ",
                                               start_date=datetime.now().strftime('%Y%m%d'))
                                if not df.empty:
                                    df['code'] = c
                                    rows.append(df)
                                import time; time.sleep(0.3)
                            if rows:
                                new = pd.concat(rows)
                                new = new.rename(columns={'trade_date':'date','open':'open','high':'high','low':'low','close':'close','vol':'volume'})
                                new['date'] = pd.to_datetime(new['date'])
                                new['change_pct'] = new['pct_chg']
                                dq = orch.context.read("data.daily_quote")
                                updated = pd.concat([dq, new], ignore_index=True).drop_duplicates(subset=['code','date'], keep='last')
                                orch.context.write("data.daily_quote", updated, writer="system")
                                logger.info(f"Tushare兜底更新: {len(new)}条")
                    except Exception as e3:
                        logger.error(f"数据更新全部失败: {e3}")
        scheduler.add_job(data_update, "cron", hour=15, minute=10,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # 调仓已移除 — 完全由盘中预警驱动(每5min)
        # IC追踪: 15:27
        async def ic_track():
            if not _is_trading_day(): return
            logger.info("因子IC追踪...")
            try:
                from src.evolution.factor_tracker import FactorTracker
                from src.factors.engine import FactorEngine
                tracker = FactorTracker()
                engine = FactorEngine()
                dq = orch.context.read("data.daily_quote")
                data = {
                    "daily_quote": dq,
                    "codes": orch.context.read("codes", []),
                    "financial": orch.context.read("financial_data"),
                    "northbound": None,
                }
                from datetime import datetime as _dt
                # 用T-5日期确保有未来收益数据
                import pandas as pd
                dq_dates = sorted(pd.to_datetime(dq["date"]).unique())
                if len(dq_dates) >= 6:
                    calc_date = pd.Timestamp(dq_dates[-6]).strftime("%Y-%m-%d")
                else:
                    calc_date = _dt.now().strftime("%Y-%m-%d")
                
                result = tracker.daily_update(data, date=calc_date, factor_engine=engine, daily_quote=dq)
                n_adjusted = len(result)
                
                # 保存IC状态（使用tracker内置持久化，保证格式一致）
                tracker._save_to_json()
                
                logger.info(f"IC追踪完成: {calc_date}, {n_adjusted}个因子调整")
            except Exception as e:
                logger.error(f"IC追踪失败: {e}")
        scheduler.add_job(ic_track, "cron", hour=15, minute=27,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # 日报: 15:30
        scheduler.add_job(daily_push, "cron", hour=15, minute=30,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # Pages更新: 15:35
        async def pages_update():
            logger.info("更新GitHub Pages...")
            try:
                # Use export_pages.py which handles master commit + gh-pages deploy
                import subprocess
                result = subprocess.run(
                    ["python3", "scripts/export_pages.py"],
                    cwd=str(PROJECT_ROOT), timeout=60,
                    capture_output=True, text=True
                )
                # Ensure we're back on master after export_pages.py checkout
                subprocess.run(["git", "checkout", "master"],
                              cwd=str(PROJECT_ROOT), timeout=10,
                              capture_output=True)
                logger.info("GitHub Pages 已更新")
            except Exception as e:
                logger.warning(f"Pages更新失败(不影响主功能): {e}")
        scheduler.add_job(pages_update, "cron", hour=15, minute=35,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")

        # 交易复盘: 15:40 (调仓+日报之后)
        async def trade_review():
            if not _is_trading_day(): return
            logger.info("交易复盘...")
            try:
                import json, pandas as pd
                from src.evolution.trade_reviewer import review_trades, save_review_to_knowledge
                from src.evolution.error_patterns import update_patterns_from_review
                dq = orch.context.read("data.daily_quote")
                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                trade_log = []
                if nav_file.exists():
                    nav_data = json.loads(nav_file.read_text())
                    trade_log = nav_data.get('trade_log', [])
                tl_file = PROJECT_ROOT / 'data' / 'trade_log.json'
                if tl_file.exists():
                    trade_log.extend(json.loads(tl_file.read_text()))
                if dq is not None and trade_log:
                    result = review_trades(dq, trade_log)
                    save_review_to_knowledge(result['reviews'], result['patterns'])
                    update_patterns_from_review(result)
                    n = len(result['reviews'])
                    p = len(result['patterns'])
                    logger.info(f"交易复盘完成: {n}条, {p}个模式")
                    # 推送复盘摘要
                    good = sum(1 for r in result['reviews'] if r.get('outcome') in ('excellent', 'good', 'correct_stop'))
                    bad = sum(1 for r in result['reviews'] if r.get('outcome') in ('bad', 'bad_stop'))
                    early = sum(1 for r in result['reviews'] if r.get('outcome') == 'early_sell')
                    msg = f"📋 **交易复盘** ({n}笔)\n  ✅ 正确: {good} | ⚠️ 提前卖出: {early} | ❌ 错误: {bad}"
                    if result.get('patterns'):
                        msg += f"\n  🔍 发现{p}个错误模式"
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
            except Exception as e:
                logger.warning(f"交易复盘失败: {e}")
        scheduler.add_job(trade_review, "cron", hour=15, minute=40,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # A股休市日历 (节假日 + 周末补班但休市)
        HOLIDAYS_2026 = {
            # 元旦
            "2026-01-01", "2026-01-02", "2026-01-03",
            # 春节
            "2026-02-14", "2026-02-15", "2026-02-16", "2026-02-17",
            "2026-02-18", "2026-02-19", "2026-02-20",
            # 清明
            "2026-04-04", "2026-04-05", "2026-04-06",
            # 劳动节
            "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
            # 端午
            "2026-05-30", "2026-05-31", "2026-06-01",
            # 中秋+国庆
            "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
            "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
        }

        def _save_nav(tracker, dq):
            """保存nav状态并更新nav_history"""
            try:
                from datetime import date as _date
                prices = {}
                if dq is not None and 'code' in dq.columns:
                    latest_d = dq['date'].max()
                    today_dq = dq[dq['date'] == latest_d]
                    prices = dict(zip(today_dq['code'].astype(str), today_dq['close']))
                tracker.update_nav(_date.today().isoformat(), prices)
                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                import json as _json2
                nav_file.write_text(_json2.dumps(tracker.to_dict(), ensure_ascii=False, indent=2))
            except Exception as e:
                logger.error(f"save_nav失败: {e}")

        def _is_trading_day() -> bool:
            """判断今天是否为交易日"""
            from datetime import date
            today = date.today().isoformat()
            if today in HOLIDAYS_2026:
                return False
            return date.today().weekday() < 5  # Mon-Fri

        async def alert_check():
            if not _is_trading_day():
                return
            try:
                import json, pandas as pd
                from src.simulator.alert_system import check_alerts, format_alerts
                from src.data.stock_names import stock_name as _sn
                from src.data.sina_adapter import fetch_realtime_quotes
                nav_data = json.load(open(PROJECT_ROOT / 'data' / 'nav_state_balanced.json'))
                holdings = nav_data.get('holdings', {})
                if not holdings:
                    return
                # 获取实时行情（非缓存的日线数据）
                codes = list(holdings.keys())
                try:
                    dq = fetch_realtime_quotes(codes)
                    if dq is None or dq.empty:
                        logger.debug("实时行情获取失败，回退到缓存数据")
                        dq = orch.context.read("data.daily_quote")
                except Exception as e:
                    logger.debug(f"实时行情异常，回退缓存: {e}")
                    dq = orch.context.read("data.daily_quote")
                if dq is None:
                    return
                alerts = check_alerts(holdings, dq)
                if alerts:
                    names = {c: _sn(c) for c in holdings}
                    msg = format_alerts(alerts, names)
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
                    logger.info(f"预警推送: {len(alerts)}条")

                    # 被动卖出: 止损/止盈
                    from src.simulator.alert_system import get_auto_sell_codes
                    sell_codes = get_auto_sell_codes(alerts)
                    if sell_codes:
                        sold_count = await _auto_sell(sell_codes, dq)
                        if sold_count > 0:
                            await _auto_buy(dq)
                            await pages_update()

                # 主动调仓: 评分驱动 + 技术面恶化
                if _is_trading_day():
                    await _smart_rebalance(dq)

                # 主动建仓: 每轮都检查是否有机会用现金买入（不限于卖出后）
                if _is_trading_day():
                    try:
                        nav_data_now = json.load(open(PROJECT_ROOT / 'data' / 'nav_state_balanced.json'))
                        holdings_now = nav_data_now.get('holdings', {})
                        cash_now = nav_data_now.get('cash', 0)
                        # 用实时行情计算持仓市值
                        def _get_price_now(code):
                            row = dq[dq['code'] == code] if 'code' in dq.columns else None
                            if row is not None and len(row) > 0:
                                return float(row.iloc[0]['close'])
                            return None
                        held_value = sum(
                            h['shares'] * p for c, h in holdings_now.items()
                            if (p := _get_price_now(c)) is not None
                        )
                        total_assets_now = cash_now + held_value
                        pos_pct = held_value / total_assets_now if total_assets_now > 0 else 0
                        # 仓位<80%且有现金>5万时，尝试主动买入（新建仓或加仓已有持仓）
                        if cash_now >= 50000 and pos_pct < 0.80:
                            logger.info(f'主动建仓检查: 仓位{pos_pct*100:.0f}% 现金¥{cash_now:.0f} 持仓{len(holdings_now)}只 → 触发买入')
                            await _auto_buy(dq)
                        else:
                            logger.info(f'主动建仓跳过: 仓位{pos_pct*100:.0f}% 现金¥{cash_now:.0f} 持仓{len(holdings_now)}只')
                    except Exception as e:
                        logger.warning(f'主动建仓检查失败: {e}')
            except Exception as e:
                logger.debug(f"预警检查失败: {e}")

        async def _auto_sell(codes: list[str], dq) -> int:
            """Auto-sell triggered by stop-loss / take-profit alerts. Returns count sold."""
            try:
                from src.simulator.nav_tracker import NAVTracker
                from src.data.stock_names import stock_name as _sn
                import json
                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                nav_data = json.loads(nav_file.read_text())
                tracker = NAVTracker.from_dict(nav_data)

                sold = []
                from datetime import date as _date
                today_str = _date.today().isoformat()
                for code in codes:
                    if code not in tracker.holdings:
                        continue
                    # T+1: 当天买入的不能卖
                    h = tracker.holdings[code]
                    if h.get('buy_date', '') == today_str:
                        logger.info(f"T+1限制: {code}今天买入，不能卖出")
                        continue
                    price_row = dq[dq['code'] == code] if 'code' in dq.columns else None
                    if price_row is not None and len(price_row) > 0:
                        price = float(price_row.iloc[0]['close'])
                    else:
                        continue

                    h = tracker.holdings[code]
                    pnl = (price - h['cost_price']) * h['shares']
                    tracker._sell(code, price, datetime.now().strftime('%Y-%m-%d %H:%M'), 'auto_stop')
                    sold.append(f"{_sn(code)} ¥{price:.2f} 盈亏{pnl:+.0f}")

                if sold:
                    _save_nav(tracker, dq)
                    msg = f"🔴 **自动卖出执行**\n" + "\n".join(f"  • {s}" for s in sold)
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
                    logger.info(f"自动卖出: {', '.join(codes)}")
                return len(sold)
            except Exception as e:
                logger.error(f"自动卖出失败: {e}")
                return 0

        async def _auto_buy(dq):
            """Auto-buy with multi-condition entry filter

            Filters: factor score + technical signal + not chasing highs + volume confirm
            """
            try:
                from src.simulator.nav_tracker import NAVTracker
                from src.factors.engine import FactorEngine
                from src.factors.technical_signals import score_stock
                from src.data.sina_adapter import fetch_realtime_quotes
                from src.data.stock_names import stock_name as _sn
                import json
                import pandas as pd
                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                nav_data = json.loads(nav_file.read_text())
                tracker = NAVTracker.from_dict(nav_data)

                if tracker.cash < 10000:
                    return
                # 持仓已满5只时，仍然允许加仓已有持仓（用闲置现金）
                # 不再硬性return
                # 仓位上限: 股票市值占总资产>=80%时停止买入
                # 获取实时行情用于价格计算
                try:
                    rt_codes = list(tracker.holdings.keys())
                    rt_data = fetch_realtime_quotes(rt_codes)
                except Exception:
                    rt_data = dq_full
                def _auto_buy_price(code):
                    row = rt_data[rt_data['code'] == code] if 'code' in rt_data.columns else None
                    if row is not None and len(row) > 0:
                        return float(row.iloc[0]['close'])
                    return None
                total_assets = tracker.cash + sum(
                    h['shares'] * _auto_buy_price(c)
                    for c, h in tracker.holdings.items()
                    if _auto_buy_price(c)
                )
                position_pct = (total_assets - tracker.cash) / total_assets if total_assets > 0 else 0
                if position_pct >= 0.90:
                    logger.info(f"仓位已达{position_pct*100:.1f}%，保留现金，跳过买入")
                    return

                # Step 1: 因子评分排名
                engine = FactorEngine()
                dq_full = orch.context.read("data.daily_quote")
                if dq_full is None:
                    return
                codes_list = orch.context.read("codes", [])
                data = {"daily_quote": dq_full, "codes": codes_list}
                scores = engine.score_all(data)
                if scores.empty:
                    return

                held = set(tracker.holdings.keys())
                full_holdings = len(held) >= 5  # 持仓已满标志
                
                # 获取大盘趋势（DualMomentum判断）
                try:
                    market_regime, regime_conf = orch.context.get_market_regime()
                except Exception:
                    market_regime = "neutral"  # 默认中性

                # Step 2: 多条件过滤候选股
                candidates = []
                filter_stats = {"total": 0, "no_data": 0, "signal": 0, "rsi": 0, "bias": 0, "vol": 0, "trend": 0, "risk": 0}
                for code in scores.index:
                    if code in held and not full_holdings:
                        continue  # 未满时跳过已持仓
                    if code in held and full_holdings:
                        pass  # 已满时不跳过，允许加仓已有持仓
                    if len(candidates) >= 10:
                        break
                    filter_stats["total"] += 1

                    # 获取该股历史数据
                    stock_data = dq_full[dq_full['code'] == code].tail(60)
                    if len(stock_data) < 30:
                        filter_stats["no_data"] += 1
                        continue

                    # 条件1: 技术信号评分 (大盘择时调整)
                    tech = score_stock(stock_data)
                    min_signal = 30
                    if market_regime == "bearish":
                        min_signal = 40  # bearish: moderate
                    elif market_regime == "bullish":
                        min_signal = 25  # bullish: low
                    if tech.get('signal_score', 0) < min_signal:
                        filter_stats["signal"] += 1
                        continue

                    # 条件2: RSI未超买 (< 70)
                    rsi_val = tech.get('details', {}).get('rsi', {})
                    rsi = rsi_val.get('value', 50) if isinstance(rsi_val, dict) else rsi_val
                    if isinstance(rsi, (int, float)) and rsi > 70:
                        continue

                    # 条件3: 不在近期高点 (乖离率 < 5%)
                    close = stock_data['close']
                    ma20 = close.rolling(20).mean().iloc[-1]
                    latest_price = close.iloc[-1]
                    if ma20 > 0 and (latest_price / ma20 - 1) > 0.05:
                        continue  # 偏离MA20超5%，追高风险

                    # 条件4: 成交量确认 (> 5日均量)
                    vol = stock_data.get('volume', pd.Series(dtype=float))
                    if len(vol) >= 2:
                        vol_ma5 = vol.tail(6).iloc[:-1].mean()
                        if vol_ma5 > 0 and vol.iloc[-1] < vol_ma5 * 0.5:
                            continue  # 缩量，资金不关注

                    # 条件5: 短期趋势 (大盘择时调整)
                    ma5 = close.rolling(5).mean().iloc[-1]
                    if market_regime == "bearish":
                        if ma5 < ma20 * 0.98:  # 熊市: MA5不低于MA20太多
                            continue
                    # Removed: default MA5<MA20 filter was too strict, blocking all candidates
                    # elif ma5 < ma20 * 0.98:
                    #     continue

                    # 条件6: 个股风险过滤
                    # 6a: 近20日最大回撤 > 15% → 波动太大，避开
                    if len(close) >= 20:
                        rolling_max = close.rolling(20, min_periods=10).max()
                        drawdown = (close - rolling_max) / rolling_max
                        max_dd = drawdown.min()
                        if max_dd < -0.20:
                            continue  # 近20日最大回撤超15%

                    # 6b: 价格连续5日下跌 → 短期弱势
                    if len(close) >= 3:
                        if all(close.iloc[-i] < close.iloc[-i-1] for i in range(1, min(6, len(close)))):
                            continue  # 连续下跌中

                    # 6c: 成交额过低（日均<5000万）→ 流动性差
                    vol = stock_data.get('volume', pd.Series(dtype=float))
                    if len(vol) >= 5:
                        avg_vol = vol.tail(5).mean()
                        if avg_vol < 20000:  # ~50M volume
                            continue

                    # 条件7: 板块相对动量 — 跑输板块太多则跳过（板块拖累/个股弱势）
                    try:
                        from src.factors.technical import calc_sector_relative_momentum
                        srm = calc_sector_relative_momentum(dq_full[dq_full['code'].isin(scores.index)])
                        if code in srm.index and not pd.isna(srm.get(code, 0)):
                            if srm[code] < -8:  # 跑输板块均值8%以上
                                continue
                    except Exception:
                        pass  # 板块数据不可用时跳过此条件

                    factor_score = scores.loc[code, 'score_total'] if code in scores.index else 0
                    candidates.append({
                        'code': code,
                        'factor_score': factor_score,
                        'signal_score': tech['signal_score'],
                        'reason': f"因子{factor_score:.1f} 信号{tech['signal_score']} {tech.get('signal', '')}",
                    })

                if not candidates:
                    logger.info(f"无符合条件的买入候选 (过滤统计: {filter_stats})")
                    return

                # 按(因子分*0.6 + 信号分*0.4)排序
                candidates.sort(key=lambda x: x['factor_score'] * 0.6 + x['signal_score'] * 0.4, reverse=True)
                # 持仓已满时，允许加仓1-2只已有持仓
                if full_holdings:
                    max_buy = min(2, 3) if market_regime != "bearish" else 1
                else:
                    max_buy = min(5 - len(held), 3) if market_regime != "bearish" else 1

                # === 板块分散度检查 ===
                sector_file = PROJECT_ROOT / "data" / "sector_map.json"
                sector_map = {}
                if sector_file.exists():
                    import json as _json_sec
                    try:
                        sector_map = _json_sec.loads(sector_file.read_text())
                    except Exception:
                        pass

                # 统计当前持仓板块分布
                sector_counts = {}
                for h_code in held:
                    if h_code in sector_map:
                        sector = sector_map[h_code].get("sector", "未知")
                        sector_counts[sector] = sector_counts.get(sector, 0) + 1

                # 调整候选优先级：降低已集中板块的权重
                def _sector_penalty(code, score):
                    if code not in sector_map:
                        return score
                    sector = sector_map[code].get("sector", "未知")
                    count = sector_counts.get(sector, 0)
                    if count >= 2:
                        return score * 0.7  # 已有2+只，权重降30%
                    elif count >= 1:
                        return score * 0.85  # 已有1只，权重降15%
                    return score

                candidates.sort(key=lambda x: _sector_penalty(x['code'], x['factor_score'] * 0.6 + x['signal_score'] * 0.4), reverse=True)

                buy_list = candidates[:max_buy]

                # 检查板块集中度
                new_sector = None
                if buy_list and buy_list[0]['code'] in sector_map:
                    new_sector = sector_map[buy_list[0]['code']].get("sector", "未知")
                if new_sector and sector_counts.get(new_sector, 0) >= 2:
                    logger.warning(f"⚠️ 板块集中: {new_sector}已有{sector_counts[new_sector]}只，考虑分散")

                # Step 3: 获取实时价格并买入
                buy_codes = [c['code'] for c in buy_list]
                try:
                    buy_dq = fetch_realtime_quotes(buy_codes)
                except Exception:
                    buy_dq = dq

                per_stock = tracker.cash / len(buy_list)
                bought = []
                for c in buy_list:
                    code = c['code']
                    row = buy_dq[buy_dq['code'] == code] if 'code' in buy_dq.columns else None
                    if row is not None and len(row) > 0:
                        price = float(row.iloc[0]['close'])
                    else:
                        continue
                    shares = int(per_stock / price / 100) * 100
                    if shares >= 100:
                        # Devil's advocate check
                        try:
                            from src.evolution.devils_advocate import challenge_buy
                            review = challenge_buy(code, _sn(code), 
                                c.get('factor_score', 0), c.get('signal_score', 0),
                                c.get('reason', ''), tracker.holdings, market_regime)
                            if not review['approved']:
                                logger.warning(f"魔鬼代言人拒绝买入 {code}: {review['concerns']}")
                                continue
                        except Exception:
                            pass  # If devil's advocate fails, don't block trade
                        tracker._buy(code, shares, price, datetime.now().strftime('%Y-%m-%d %H:%M'), 'auto_buy')
                        bought.append(f"{_sn(code)} {shares}股@¥{price:.2f} ({c['reason']})")

                if bought:
                    _save_nav(tracker, dq)
                    msg = f"🟢 **自动买入** (5重过滤)\n可用¥{tracker.cash:,.0f}\n" + "\n".join(f"  • {s}" for s in bought)
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
                    logger.info(f"自动买入: {bought}")
                else:
                    logger.info("候选股价格不满足买入条件")
            except Exception as e:
                import traceback
                logger.error(f"自动买入失败: {e}\n{traceback.format_exc()}")

        async def _smart_rebalance(dq):
            """评分驱动的主动调仓 — 每5分钟检查

            调仓规则:
            1. 持仓股评分跌出前30% → 卖出
            2. 持仓股技术信号<35 → 减仓
            3. 非持仓股评分进入前10% + 技术面确认 → 买入
            4. 每次最多调换1只，避免频繁交易
            """
            try:
                from datetime import date as _date
                today = _date.today().isoformat()
                from src.simulator.nav_tracker import NAVTracker
                from src.factors.engine import FactorEngine
                from src.factors.technical_signals import score_stock
                from src.data.stock_names import stock_name as _sn
                from src.data.sina_adapter import fetch_realtime_quotes
                import json

                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                nav_data = json.loads(nav_file.read_text())
                tracker = NAVTracker.from_dict(nav_data)
                if len(tracker.holdings) == 0:
                    return

                # 评分排名
                engine = FactorEngine()
                dq_full = orch.context.read("data.daily_quote")
                if dq_full is None:
                    return
                codes_list = orch.context.read("codes", [])
                data = {"daily_quote": dq_full, "codes": codes_list}
                scores = engine.score_all(data)
                if scores.empty:
                    return

                held = set(tracker.holdings.keys())
                total_stocks = len(scores)
                threshold_rank = int(total_stocks * 0.3)  # 前30%
                top_rank = int(total_stocks * 0.1)  # 前10%

                # 获取实时价格
                rt_codes = list(held)
                try:
                    rt_dq = fetch_realtime_quotes(rt_codes)
                except Exception:
                    rt_dq = dq

                def _get_rt_price(code):
                    row = rt_dq[rt_dq['code'] == code] if 'code' in rt_dq.columns else None
                    if row is not None and len(row) > 0:
                        return float(row.iloc[0]['close'])
                    return None

                # === 卖出检查: 持仓评分跌出前30% 或 技术面恶化 ===
                # === 卖出检查: 按评分排序 ===
                sell_list = []  # [(code, reason)]
                for code in held:
                    if code not in scores.index:
                        sell_list.append((code, "无评分数据"))
                        continue
                    # T+1: 当天买入的不能卖
                    h = tracker.holdings[code]
                    buy_date = h.get('buy_date', '')
                    if buy_date == today:
                        continue
                    rank = list(scores.index).index(code) + 1
                    # 技术面恶化检查
                    stock_data = dq_full[dq_full['code'] == code].tail(60)
                    tech = score_stock(stock_data) if len(stock_data) >= 30 else {'signal_score': 50}
                    sig = tech.get('signal_score', 50)
                    if rank > threshold_rank:
                        sell_list.append((code, f"评分排名{rank}/{total_stocks}"))
                    elif sig < 35:
                        sell_list.append((code, f"技术信号={sig}"))

                # === 持仓相关性计算 ===
                def _calc_avg_correlation(code, held_codes, dq_data):
                    """Calculate average correlation of code with all other held stocks."""
                    try:
                        import numpy as np
                        target = dq_data[dq_data['code'] == code].tail(60)['close']
                        if len(target) < 30:
                            return 0.0
                        target_ret = target.pct_change().dropna().values
                        corrs = []
                        for other in held_codes:
                            if other == code:
                                continue
                            other_series = dq_data[dq_data['code'] == other].tail(60)['close']
                            if len(other_series) < 30:
                                continue
                            other_ret = other_series.pct_change().dropna().values
                            min_len = min(len(target_ret), len(other_ret))
                            t, o = target_ret[-min_len:], other_ret[-min_len:]
                            if np.std(t) > 0 and np.std(o) > 0:
                                c = np.corrcoef(t, o)[0, 1]
                                if not np.isnan(c):
                                    corrs.append(c)
                        return np.mean(corrs) if corrs else 0.0
                    except Exception:
                        return 0.0

                # === 减仓模式: 持仓>5只时一次性卖出所有差的 ===
                if len(tracker.holdings) > 5:
                    excess = len(tracker.holdings) - 5
                    # 排序：评分低优先 + 相关性高优先
                    def _sell_priority(item):
                        code = item[0]
                        rank = list(scores.index).index(code) + 1 if code in scores.index else 999
                        avg_corr = _calc_avg_correlation(code, held, dq_full)
                        # Higher rank (worse) = sell first, higher corr = sell first
                        return rank - avg_corr * 30  # correlation gives ~9 rank units bonus
                    sell_list.sort(key=_sell_priority, reverse=True)
                    to_sell = sell_list[:excess]
                    if not to_sell:
                        return
                    sold = []
                    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                    for code, reason in to_sell:
                        price = _get_rt_price(code)
                        if not price:
                            continue
                        h = tracker.holdings[code]
                        tracker._sell(code, price, now_str, 'reduce_to_5')
                        sold.append(f"{_sn(code)} {h['shares']}股@¥{price:.2f} ({reason})")
                    if sold:
                        _save_nav(tracker, dq)
                        msg = f"📉 **一次性减仓** ({len(tracker.holdings)+len(sold)}→{len(tracker.holdings)})\n" + "\n".join(f"  • {s}" for s in sold)
                        for uid in ALLOWED_USERS:
                            await app.bot.send_message(chat_id=uid, text=msg)
                        logger.info(f"减仓: 卖出{len(sold)}只")
                        await pages_update()
                    return

                # === 加减仓逻辑 ===
                # 每日操作记录 (防止重复加减仓)
                import json as _json_act
                _act_log_file = PROJECT_ROOT / 'data' / 'daily_actions.json'
                _daily_actions = {}
                today_act_key = today
                try:
                    _daily_actions = _json_act.loads(_act_log_file.read_text()) if _act_log_file.exists() else {}
                    _daily_actions = {k: v for k, v in _daily_actions.items() if k == today_act_key}
                except Exception:
                    _daily_actions = {}
                _today_reduced = set(_daily_actions.get(today_act_key, {}).get('reduce', []))
                _today_added = set(_daily_actions.get(today_act_key, {}).get('add', []))

                now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                rebalance_actions = []
                import json as _json_add
                from pathlib import Path as _Path_add
                _add_log_file = PROJECT_ROOT / "data" / "daily_adds.json"
                _daily_adds = {}
                try:
                    _daily_adds = _json_add.loads(_add_log_file.read_text()) if _add_log_file.exists() else {}
                    _daily_adds = {k: v for k, v in _daily_adds.items() if k == today}
                except Exception:
                    _daily_adds = {}

                for code in list(held):
                    if code not in tracker.holdings:
                        continue
                    h = tracker.holdings[code]
                    price = _get_rt_price(code)
                    if not price:
                        continue

                    # T+1: 当天买入的不能卖
                    buy_date = h.get('buy_date', '')
                    if buy_date == today:
                        continue

                    pnl_pct = (price - h['cost_price']) / h['cost_price']

                    # 分批止损: -10%减半, -15%全清
                    if pnl_pct <= -0.15:
                        tracker._sell(code, price, now_str, 'stop_loss_full')
                        rebalance_actions.append(f"🔴 全部止损 {_sn(code)} {h['shares']}股@¥{price:.2f} (亏损{pnl_pct*100:.1f}%)")
                        continue
                    elif pnl_pct <= -0.10:
                        half = h['shares'] // 2 // 100 * 100
                        if half >= 100:
                            tracker._partial_sell(code, half, price, now_str, 'stop_loss_half')
                            rebalance_actions.append(f"🟡 减半止损 {_sn(code)} {half}股@¥{price:.2f} (亏损{pnl_pct*100:.1f}%)")
                        continue

                    # 技术面减弱但不到卖出线 → 减仓1/3
                    if code in scores.index:
                        stock_data = dq_full[dq_full['code'] == code].tail(60)
                        if len(stock_data) >= 30:
                            tech = score_stock(stock_data)
                            sig = tech.get('signal_score', 50)
                            if 35 <= sig < 50:
                                if code not in _today_reduced:  # 今天未减仓过
                                    third = h['shares'] // 3 // 100 * 100
                                    if third >= 100:
                                        tracker._partial_sell(code, third, price, now_str, f'signal_weak_{sig}')
                                        rebalance_actions.append(f"⚠️ 减仓1/3 {_sn(code)} {third}股@¥{price:.2f} (信号{sig})")
                                        _today_reduced.add(code)

                if len(tracker.holdings) <= 5 and tracker.cash >= 10000:
                    for code in list(held):
                        if code not in tracker.holdings or code not in scores.index:
                            continue
                        if code in _today_added:
                            continue  # 今天已加仓过
                        rank = list(scores.index).index(code) + 1
                        stock_data = dq_full[dq_full['code'] == code].tail(60)
                        if len(stock_data) < 30:
                            continue
                        tech = score_stock(stock_data)
                        sig = tech.get('signal_score', 50)
                        close = stock_data['close']
                        ma5 = close.rolling(5).mean().iloc[-1]
                        ma20 = close.rolling(20).mean().iloc[-1]

                        # 加仓条件: 排名前15% + 信号≥60 + MA5>MA20*0.99 + 持仓<25%
                        if rank <= int(total_stocks * 0.15) and sig >= 60 and ma5 > ma20 * 0.99:
                            h = tracker.holdings[code]
                            total_val = sum(v['shares'] * _get_rt_price(c) for c, v in tracker.holdings.items() if _get_rt_price(c))
                            pos_weight = h['shares'] * _get_rt_price(code) / total_val if total_val > 0 else 0
                            if pos_weight < 0.25:
                                price = _get_rt_price(code)
                                if not price:
                                    continue
                                # 信号驱动加仓金额
                                top5 = rank <= int(total_stocks * 0.05)
                                if sig >= 90 and top5:
                                    add_pct = 0.30  # 重仓: 信号极强+前5%
                                    tier = "重仓"
                                elif sig >= 80:
                                    add_pct = 0.25  # 标准仓: 信号强
                                    tier = "标准"
                                else:
                                    add_pct = 0.15  # 轻仓: 信号一般
                                    tier = "轻仓"
                                add_amount = max(10000, min(tracker.cash * add_pct, 80000))
                                add_shares = int(add_amount / price / 100) * 100
                                if add_shares >= 100 and add_shares * price <= tracker.cash:
                                    tracker._add_position(code, add_shares, price, now_str, f'add_score{scores.loc[code,"score_total"]:.0f}_sig{sig}')
                                    rebalance_actions.append(f"🟢 加仓[{tier}] {_sn(code)} +{add_shares}股@¥{price:.2f} (排名{rank} 信号{sig} 加¥{add_amount/10000:.0f}万)")
                                    # 记录今天已加仓
                                    _today_added.add(code)
                                    _daily_adds[today] = list(_today_added)
                                    _add_log_file.parent.mkdir(exist_ok=True)
                                    _add_log_file.write_text(_json_add.dumps(_daily_adds))
                                    break  # 每轮最多加仓1只

                if rebalance_actions:
                    _save_nav(tracker, dq)
                    msg = "📊 **仓位调整**\n" + "\n".join(f"  • {a}" for a in rebalance_actions)
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
                    logger.info(f"仓位调整: {len(rebalance_actions)}笔")
                    await pages_update()
                    return  # 本轮已操作，跳过换仓

                if not sell_list:
                                        # 诊断日志
                    held_info = {c: (list(scores.index).index(c)+1 if c in scores.index else 999, round(scores.loc[c,'score_total'],1) if c in scores.index else 0) for c in held}
                    logger.info(f'调仓检查: 持仓评分={held_info}')
                    # 持仓都健康，但检查是否有明显更好的标的 → 强制换仓
                    # 找持仓中评分最低的
                    held_ranks = [(code, list(scores.index).index(code)+1, scores.loc[code, 'score_total']) 
                                  for code in held if code in scores.index]
                    held_ranks.sort(key=lambda x: x[1], reverse=True)  # 排名最差排前面
                    if not held_ranks:
                        return
                    worst_held_code, worst_held_rank, worst_held_score = held_ranks[0]
                    
                    # 找场外最好的非持仓股
                    best_outside = None
                    for code in scores.index[:top_rank]:  # 场外前10%
                        if code in held:
                            continue
                        stock_data = dq_full[dq_full['code'] == code].tail(60)
                        if len(stock_data) < 30:
                            continue
                        tech = score_stock(stock_data)
                        sig = tech.get('signal_score', 0)
                        if sig < 50:
                            continue
                        best_outside = (code, scores.loc[code, 'score_total'], sig)
                        break
                    
                    # 强制换仓条件: 场外标的评分比持仓最差的高15%以上
                    if best_outside and worst_held_score > 0:
                        score_improvement = (best_outside[1] - worst_held_score) / worst_held_score
                        if score_improvement >= 0.15:
                            sell_list = [(worst_held_code, f"评分{worst_held_score:.1f}(排名{worst_held_rank}) 远低于场外{best_outside[1]:.1f}")]
                            logger.info(f"强制换仓: {worst_held_code}(评分{worst_held_score:.1f}) → {best_outside[0]}(评分{best_outside[1]:.1f}) 提升{score_improvement*100:.0f}%")
                        else:
                            return
                    else:
                        return

                # 正常调仓: 卖评分最差的1只
                sell_list.sort(key=lambda x: list(scores.index).index(x[0])+1 if x[0] in scores.index else 999, reverse=True)
                sell_candidate, sell_reason = sell_list[0]

                buy_candidate = None
                buy_reason = ""

                for code in scores.index[:top_rank]:
                    if code in held:
                        continue
                    stock_data = dq_full[dq_full['code'] == code].tail(60)
                    if len(stock_data) < 30:
                        continue
                    tech = score_stock(stock_data)
                    sig = tech.get('signal_score', 0)
                    if sig < 50:
                        continue
                    close = stock_data['close']
                    ma20 = close.rolling(20).mean().iloc[-1]
                    ma5 = close.rolling(5).mean().iloc[-1]
                    if ma5 < ma20:
                        continue  # 下降趋势
                    buy_candidate = code
                    buy_reason = f"评分{scores.loc[code, 'score_total']:.1f} 信号{sig}"
                    break

                if not buy_candidate:
                    logger.info(f"调仓: 卖出候选={sell_candidate}({sell_reason}) 但无更好买入标的")
                    return  # 没有更好的标的

                # === 执行调仓: 卖1只 + 买1只 ===
                sell_price = _get_rt_price(sell_candidate)
                # 买入候选可能不在持仓中，需要单独获取价格
                buy_price = _get_rt_price(buy_candidate)
                if buy_price is None:
                    try:
                        buy_rt = fetch_realtime_quotes([buy_candidate])
                        if buy_rt is not None and len(buy_rt) > 0 and 'close' in buy_rt.columns:
                            buy_price = float(buy_rt.iloc[0]['close'])
                    except Exception:
                        pass
                if not sell_price or not buy_price:
                    logger.info(f"调仓: 无法获取价格 sell={sell_price} buy={buy_price}")
                    return

                # 卖出
                h = tracker.holdings[sell_candidate]
                sell_pnl = (sell_price - h['cost_price']) * h['shares']
                tracker._sell(sell_candidate, sell_price, datetime.now().strftime('%Y-%m-%d %H:%M'), 'smart_rebalance')

                # 买入（用卖出资金）
                sell_amount = h['shares'] * sell_price
                buy_shares = int(sell_amount / buy_price / 100) * 100
                if buy_shares < 100:
                    logger.info(f"调仓: 回滚 卖出资金{sell_amount:.0f} 不够买100股@{buy_price}")
                    # 钱不够买100股，回滚
                    tracker._buy(sell_candidate, h['shares'], h['cost_price'], datetime.now().strftime('%Y-%m-%d %H:%M'), 'rollback')
                    return
                tracker._buy(buy_candidate, buy_shares, buy_price, datetime.now().strftime('%Y-%m-%d %H:%M'), 'smart_rebalance')

                # 保存
                _save_nav(tracker, dq)

                # 推送通知
                msg = (
                    f"🔄 **智能调仓**\n"
                    f"  🔴 卖出: {_sn(sell_candidate)} {h['shares']}股@¥{sell_price:.2f} ({sell_reason})\n"
                    f"  🟢 买入: {_sn(buy_candidate)} {buy_shares}股@¥{buy_price:.2f} ({buy_reason})"
                )
                for uid in ALLOWED_USERS:
                    await app.bot.send_message(chat_id=uid, text=msg)
                logger.info(f"智能调仓: 卖{sell_candidate}({sell_reason}) 买{buy_candidate}({buy_reason})")

                # 同步Pages
                await pages_update()
            except Exception as e:
                logger.error(f"智能调仓失败: {e}")

        # Morning session: 9:35-11:30 every 5 min
        scheduler.add_job(alert_check, "cron", minute='35,40,45,50,55',
                          hour='9', day_of_week="mon-fri",
                          start_date='2026-01-01', timezone="Asia/Shanghai")
        scheduler.add_job(alert_check, "cron", minute='*/5',
                          hour='10', day_of_week="mon-fri",
                          start_date='2026-01-01', timezone="Asia/Shanghai")
        scheduler.add_job(alert_check, "cron", minute='0-30/5',
                          hour='11', day_of_week="mon-fri",
                          timezone="Asia/Shanghai")
        # Afternoon session: 13:05-15:00 every 5 min
        scheduler.add_job(alert_check, "cron", minute='*/5',
                          hour='13-14', day_of_week="mon-fri",
                          timezone="Asia/Shanghai")
        scheduler.add_job(alert_check, "cron", minute='0',
                          hour='15', day_of_week="mon-fri",
                          timezone="Asia/Shanghai")

        # D4 周度假设生成: 周六10:00
        async def weekly_evolution():
            logger.info("周度进化: 假设生成...")
            try:
                from src.evolution.hypothesis_gen import HypothesisGenerator
                from src.llm.client import LLMClient
                gen = HypothesisGenerator(LLMClient())
                dq = orch.context.read("data.daily_quote")
                data = {"daily_quote": dq, "codes": orch.context.read("codes", []),
                        "financial": orch.context.read("financial_data"), "northbound": None}
                import pandas as pd
                dates = sorted(pd.to_datetime(dq["date"]).unique())
                calc_date = pd.Timestamp(dates[-6]).strftime("%Y-%m-%d")
                result = await gen.weekly_run(data, calc_date)
                n = len(result.get("hypotheses", []))
                logger.info(f"周度进化完成: {n}个新假设")
            except Exception as e:
                logger.error(f"周度进化失败: {e}")
        scheduler.add_job(weekly_evolution, "cron", day_of_week="sat", hour=10, minute=0,
                          timezone="Asia/Shanghai")

        # D5 周六14:00 GitHub扫描
        async def github_scan():
            logger.info("GitHub项目扫描...")
            try:
                from src.evolution.github_scanner import scan_github
                results = scan_github()
                logger.info(f"GitHub扫描: {len(results)}个项目")
            except Exception as e:
                logger.warning(f"GitHub扫描失败: {e}")
        scheduler.add_job(github_scan, "cron", day_of_week="sat", hour=14, minute=0,
                          timezone="Asia/Shanghai")

        # D6 每月1日进化月报
        async def monthly_report():
            logger.info("生成进化月报...")
            try:
                from src.evolution.evolution_reporter import generate_monthly_report
                report = generate_monthly_report()
                for uid in ALLOWED_USERS:
                    await app.bot.send_message(chat_id=uid, text=report)
                logger.info("进化月报已推送")
            except Exception as e:
                logger.warning(f"进化月报失败: {e}")
        scheduler.add_job(monthly_report, "cron", day="1", hour=9, minute=0,
                          timezone="Asia/Shanghai")

        scheduler.start()
        logger.info("Scheduler: 数据→调仓→IC→日报→Pages→预警5min→复盘→ 周六:进化+GitHub扫描→ 月初:进化月报")

    app.post_init = post_init

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling (with auto-restart)...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            # 每次重试都重建Application（event loop关闭后无法复用）
            if attempt > 0:
                # 关键: 必须创建新event loop，旧的已被run_polling关闭
                asyncio.set_event_loop(asyncio.new_event_loop())
                app = Application.builder().token(token).build()
                app.add_handler(CommandHandler("start", cmd_start))
                app.add_handler(CommandHandler("help", cmd_help))
                app.add_handler(CommandHandler("top", lambda u, c: _quick_cmd(u, c, "评分排名")))
                app.add_handler(CommandHandler("nav", lambda u, c: _quick_cmd(u, c, "净值")))
                app.add_handler(CommandHandler("report", lambda u, c: _quick_cmd(u, c, "日报")))
                app.add_handler(CommandHandler("factors", lambda u, c: _quick_cmd(u, c, "因子状态")))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
                # 关键: 重试时也必须设置post_init，否则scheduler不会启动
                app.post_init = post_init
            
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Bot崩溃 (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time; time.sleep(10)
                logger.info("重建Application重试...")
            else:
                logger.error("达到最大重试次数，退出")


if __name__ == "__main__":
    main()
