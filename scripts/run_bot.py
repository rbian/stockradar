"""Telegram Bot — StockRadar多Agent系统"""

import asyncio
import os
import sys
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
    "📈 持仓建议": "当前持仓建议",
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

    async def daily_rebalance():
        """15:25 自动调仓"""
        logger.info("定时调仓...")
        try:
            result = await asyncio.wait_for(
                orch.process_user_message("调仓", user_id=list(ALLOWED_USERS)[0] if ALLOWED_USERS else ""), 
                timeout=120
            )
            logger.info(f"调仓完成: {result[:100]}")
        except Exception as e:
            logger.error(f"调仓失败: {e}")

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
        # 调仓: 15:25
        scheduler.add_job(daily_rebalance, "cron", hour=15, minute=25,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        # IC追踪: 15:27 (调仓后)
        async def ic_track():
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
                import subprocess
                subprocess.run(["python3", "scripts/export_pages.py"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                subprocess.run(["git", "add", "docs/"], cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "commit", "-m",
                              f"pages: {__import__('datetime').date.today()}"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "push", "origin", "master"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                logger.info("GitHub Pages 已更新")
            except Exception as e:
                logger.warning(f"Pages更新失败(不影响主功能): {e}")
        scheduler.add_job(pages_update, "cron", hour=15, minute=35,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")

        # 交易复盘: 15:40 (调仓+日报之后)
        async def trade_review():
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
            except Exception as e:
                logger.warning(f"交易复盘失败: {e}")
        scheduler.add_job(trade_review, "cron", hour=15, minute=40,
                          day_of_week="mon-fri", timezone="Asia/Shanghai")
        async def alert_check():
            try:
                import json, pandas as pd
                from src.simulator.alert_system import check_alerts, format_alerts
                from src.data.stock_names import stock_name as _sn
                nav_data = json.load(open(PROJECT_ROOT / 'data' / 'nav_state_balanced.json'))
                dq = orch.context.read("data.daily_quote")
                holdings = nav_data.get('holdings', {})
                if not holdings or dq is None:
                    return
                alerts = check_alerts(holdings, dq)
                if alerts:
                    names = {c: _sn(c) for c in holdings}
                    msg = format_alerts(alerts, names)
                    for uid in ALLOWED_USERS:
                        await app.bot.send_message(chat_id=uid, text=msg)
                    logger.info(f"预警推送: {len(alerts)}条")
            except Exception as e:
                logger.debug(f"预警检查失败: {e}")
        # Morning session: 9:35-11:30 every 5 min
        scheduler.add_job(alert_check, "cron", minute='*/5',
                          hour='9-10', day_of_week="mon-fri",
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
        scheduler.start()
        logger.info("Scheduler: 数据15:10 + 调仓15:25 + IC15:27 + 日报15:30 + Pages15:35 + 预警5min + 复盘15:40 + 周六进化10:00")

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
