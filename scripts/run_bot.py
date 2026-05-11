import json
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
        import asyncio as _asyncio
        _running_loop = _asyncio.get_running_loop()
        logger.info(f'Scheduler绑定event loop: {_running_loop}')
        scheduler = AsyncIOScheduler(event_loop=_running_loop)
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
            """保存nav状态并更新nav_history — 使用实时行情计算市值"""
            try:
                from datetime import date as _date
                prices = {}
                # 优先用实时行情计算持仓市值
                held_codes = list(tracker.holdings.keys())
                if held_codes:
                    try:
                        from src.data.sina_adapter import fetch_realtime_quotes
                        rt = fetch_realtime_quotes(held_codes)
                        if rt is not None and 'code' in rt.columns and len(rt) > 0:
                            for _, row in rt.iterrows():
                                prices[str(row['code'])] = float(row['close'])
                    except Exception:
                        pass  # fallback to dq
                # 实时行情没拿到的，用dq缓存补
                if dq is not None and 'code' in dq.columns:
                    for code in held_codes:
                        if code not in prices:
                            rows = dq[dq['code'] == code]
                            if len(rows) > 0:
                                prices[code] = float(rows.iloc[-1]['close'])
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

        def _incr_trade_count():
            """Increment global daily trade count"""
            try:
                _f = PROJECT_ROOT / 'data' / 'daily_trade_count.json'
                _t = datetime.now().strftime('%Y-%m-%d')
                try:
                    _d = json.loads(_f.read_text()) if _f.exists() else {}
                except Exception:
                    _d = {}
                _d[_t] = _d.get(_t, 0) + 1
                _f.write_text(json.dumps(_d))
            except Exception:
                pass

        async def alert_check():
            if not _is_trading_day():
                return
            # === 全局每日交易次数限制 ===
            _global_trade_file = PROJECT_ROOT / 'data' / 'daily_trade_count.json'
            _gt_today = datetime.now().strftime('%Y-%m-%d')
            try:
                _gt_data = json.loads(_global_trade_file.read_text()) if _global_trade_file.exists() else {}
            except Exception:
                _gt_data = {}
            _gt_count = _gt_data.get(_gt_today, 0)
            if _gt_count >= 10:
                logger.warning(f'⚠️ 今日已执行{_gt_count}笔交易，可能异常，跳过')
                return
            if _gt_count >= 5:
                logger.warning(f'⚠️ 今日已执行{_gt_count}笔交易，超过5笔请关注')

            try:
                import pandas as pd
                from src.simulator.alert_system import check_alerts, format_alerts
                from src.data.stock_names import stock_name as _sn
                from src.data.sina_adapter import fetch_realtime_quotes
                
                nav_data = json.load(open(PROJECT_ROOT / 'data' / 'nav_state_balanced.json'))
                holdings = nav_data.get('holdings', {})
                cash = nav_data.get('cash', 0)
                
                # 1. 获取行情
                dq = None
                try:
                    if holdings:
                        dq = fetch_realtime_quotes(list(holdings.keys()))
                    if dq is None or dq.empty:
                        dq = orch.context.read("data.daily_quote")
                except Exception:
                    dq = orch.context.read("data.daily_quote")
                
                if dq is None:
                    return

                # 2. 预警和被动卖出 (仅在有持仓时)
                if holdings:
                    alerts = check_alerts(holdings, dq)
                    if alerts:
                        names = {c: _sn(c) for c in holdings}
                        msg = format_alerts(alerts, names)
                        for uid in ALLOWED_USERS:
                            await app.bot.send_message(chat_id=uid, text=msg)
                        logger.info(f"预警推送: {len(alerts)}条")

                        from src.simulator.alert_system import get_auto_sell_codes
                        sell_codes = get_auto_sell_codes(alerts)
                        if sell_codes:
                            sold_count = await _auto_sell(sell_codes, dq)
                            if sold_count > 0:
                                await _auto_buy(dq)
                                await pages_update()

                    # 3. 主动调仓
                    await _smart_rebalance(dq)
                
                # 4. 主动建仓 (空仓或有现金都可触发)
                if cash >= 50000:
                    logger.info(f'主动建仓检查: 现金¥{cash:,.0f}')
                    await _auto_buy(dq)
            except Exception as e:
                logger.error(f"alert_check 逻辑出错: {e}", exc_info=True)