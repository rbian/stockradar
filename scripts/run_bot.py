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
                
                # 保存IC状态
                import json as _json
                state = {}
                for name, s in tracker.factor_statuses.items():
                    state[name] = {"ic_today": round(s.ic_today, 4), "ic_20d_avg": round(s.ic_20d_avg, 4),
                                   "current_weight": round(s.current_weight, 3), "is_suspended": s.is_suspended}
                from pathlib import Path as _Path
                _Path("data/cache/factor_ic_state.json").write_text(_json.dumps(state, indent=2))
                
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
                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                nav_data = json.loads(nav_file.read_text())
                tracker = NAVTracker.from_dict(nav_data)

                if tracker.cash < 10000:
                    return
                if len(tracker.holdings) >= 5:
                    logger.info("持仓已达5只上限，跳过买入")
                    return
                # 仓位上限: 股票市值占总资产>=80%时停止买入
                total_assets = tracker.cash + sum(
                    h['shares'] * _get_rt_price(c)
                    for c, h in tracker.holdings.items()
                    if _get_rt_price(c)
                )
                position_pct = (total_assets - tracker.cash) / total_assets if total_assets > 0 else 0
                if position_pct >= 0.80:
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

                # Step 2: 多条件过滤候选股
                candidates = []
                for code in scores.index:
                    if code in held:
                        continue
                    if len(candidates) >= 5:
                        break

                    # 获取该股历史数据
                    stock_data = dq_full[dq_full['code'] == code].tail(60)
                    if len(stock_data) < 30:
                        continue

                    # 条件1: 技术信号评分 >= 50
                    tech = score_stock(stock_data)
                    if tech.get('signal_score', 0) < 50:
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
                        if vol_ma5 > 0 and vol.iloc[-1] < vol_ma5 * 0.8:
                            continue  # 缩量，资金不关注

                    # 条件5: 短期趋势偏多 (MA5 > MA20)
                    ma5 = close.rolling(5).mean().iloc[-1]
                    if ma5 < ma20:
                        continue

                    factor_score = scores.loc[code, 'score_total'] if code in scores.index else 0
                    candidates.append({
                        'code': code,
                        'factor_score': factor_score,
                        'signal_score': tech['signal_score'],
                        'reason': f"因子{factor_score:.1f} 信号{tech['signal_score']} {tech.get('signal', '')}",
                    })

                if not candidates:
                    logger.info("无符合条件的买入候选")
                    return

                # 按(因子分*0.6 + 信号分*0.4)排序
                candidates.sort(key=lambda x: x['factor_score'] * 0.6 + x['signal_score'] * 0.4, reverse=True)
                buy_list = candidates[:3]

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
                logger.error(f"自动买入失败: {e}")

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

                # === 减仓模式: 持仓>5只时一次性卖出所有差的 ===
                if len(tracker.holdings) > 5:
                    excess = len(tracker.holdings) - 5
                    # 按评分从低到高排序（优先卖评分最差的）
                    sell_list.sort(key=lambda x: list(scores.index).index(x[0])+1 if x[0] in scores.index else 999, reverse=True)
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

                    # 分批止损: -8%减半, -12%全清
                    if pnl_pct <= -0.12:
                        tracker._sell(code, price, now_str, 'stop_loss_full')
                        rebalance_actions.append(f"🔴 全部止损 {_sn(code)} {h['shares']}股@¥{price:.2f} (亏损{pnl_pct*100:.1f}%)")
                        continue
                    elif pnl_pct <= -0.08:
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

                        # 加仓条件: 排名前10% + 信号≥75 + MA5>MA20 + 持仓<25%
                        if rank <= int(total_stocks * 0.10) and sig >= 75 and ma5 > ma20:
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
                                    _daily_adds[today_add_key] = list(_today_added)
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
                    return  # 持仓都健康，不调仓

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
                    return  # 没有更好的标的

                # === 执行调仓: 卖1只 + 买1只 ===
                sell_price = _get_rt_price(sell_candidate)
                buy_price = _get_rt_price(buy_candidate)
                if not sell_price or not buy_price:
                    return

                # 卖出
                h = tracker.holdings[sell_candidate]
                sell_pnl = (sell_price - h['cost_price']) * h['shares']
                tracker._sell(sell_candidate, sell_price, datetime.now().strftime('%Y-%m-%d %H:%M'), 'smart_rebalance')

                # 买入（用卖出资金）
                sell_amount = h['shares'] * sell_price
                buy_shares = int(sell_amount / buy_price / 100) * 100
                if buy_shares < 100:
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
                app = Application.builder().token(token).build()
                app.add_handler(CommandHandler("start", cmd_start))
                app.add_handler(CommandHandler("help", cmd_help))
                app.add_handler(CommandHandler("top", lambda u, c: _quick_cmd(u, c, "评分排名")))
                app.add_handler(CommandHandler("nav", lambda u, c: _quick_cmd(u, c, "净值")))
                app.add_handler(CommandHandler("report", lambda u, c: _quick_cmd(u, c, "日报")))
                app.add_handler(CommandHandler("factors", lambda u, c: _quick_cmd(u, c, "因子状态")))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            
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
