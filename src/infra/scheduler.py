"""定时任务调度器 - 基于APScheduler"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.infra.logger import setup_logger

logger = setup_logger()


class StockAgentScheduler:
    """盯盘Agent定时调度器"""

    def __init__(self):
        self.scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        self._jobs = {}

    def add_daily_jobs(self, data_update_fn, scoring_fn, strategy_fn,
                       trade_fn, news_fn, report_fn):
        """添加每日定时任务"""
        self._jobs["data_update"] = self.scheduler.add_job(
            data_update_fn, CronTrigger(hour=15, minute=30),
            id="data_update", name="数据更新",
        )
        self._jobs["scoring"] = self.scheduler.add_job(
            scoring_fn, CronTrigger(hour=16, minute=0),
            id="scoring", name="因子计算+评分",
        )
        self._jobs["strategy"] = self.scheduler.add_job(
            strategy_fn, CronTrigger(hour=16, minute=10),
            id="strategy", name="策略评估",
        )
        self._jobs["trade"] = self.scheduler.add_job(
            trade_fn, CronTrigger(hour=16, minute=20),
            id="trade", name="模拟交易",
        )
        self._jobs["news"] = self.scheduler.add_job(
            news_fn, CronTrigger(hour=16, minute=30),
            id="news", name="新闻采集",
        )
        self._jobs["report"] = self.scheduler.add_job(
            report_fn, CronTrigger(hour=16, minute=40),
            id="report", name="日报推送",
        )
        logger.info("已添加每日定时任务（15:30-16:40）")

    def add_weekly_job(self, weekly_fn):
        """添加每周日任务"""
        self._jobs["weekly"] = self.scheduler.add_job(
            weekly_fn, CronTrigger(day_of_week="sun", hour=20, minute=0),
            id="weekly", name="周报+因子研究",
        )
        logger.info("已添加每周日20:00任务")

    def start(self):
        """启动调度器（阻塞）"""
        logger.info("调度器启动，等待触发...")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器停止")

    def run_now(self, job_id: str):
        """立即执行指定任务（用于调试）"""
        self.scheduler.get_job(job_id).modify(next_run_time=None)
