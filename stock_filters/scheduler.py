import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from data.akshare_source import AKShareDataSource
from engine import Engine
from notifier import DingTalkNotifier

logger = logging.getLogger(__name__)


class StockScheduler:
    """调度器：管理定时任务"""

    def __init__(self, config: dict):
        self.config = config
        self.data = AKShareDataSource()
        self.engine = Engine(config, self.data, is_production=True)
        self.notifier = DingTalkNotifier(config.get("dingtalk", {}), config.get("dingtalk_test", {}))
        self.scheduler = BlockingScheduler()
        self._start_time = datetime.datetime.now()

    def setup_jobs(self):
        """配置定时任务"""
        # 每个交易日14:15执行初筛并缓存股票池
        self.scheduler.add_job(
            self._run_screener_job,
            "cron",
            hour=14,
            minute=15,
            day_of_week="mon-fri",
            id="screener",
            name="初筛缓存",
        )
        # 每个交易日14:28执行策略+通知
        self.scheduler.add_job(
            self._run_strategy_job,
            "cron",
            hour=14,
            minute=28,
            day_of_week="mon-fri",
            id="strategy_1428",
            name="策略+通知(14:28)",
        )
        # 每10分钟发送健康报告（测试机器人）
        self.scheduler.add_job(
            self._health_check_job,
            "interval",
            minutes=10,
            id="health_check",
            name="健康报告",
        )
        # 启动后立即触发一次健康报告
        self.scheduler.add_job(
            self._health_check_job,
            "date",
            id="health_check_startup",
            name="启动健康报告",
        )
        logger.info("定时任务已配置: 14:15初筛, 14:28策略+通知, 每10分钟健康报告")

    def start(self):
        """启动调度器"""
        self.setup_jobs()
        logger.info("调度器启动")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器停止")

    def _run_screener_job(self):
        """定时任务：执行初筛并缓存"""
        logger.info("定时任务：执行初筛")
        try:
            self.engine.run_screener(force=True)
            logger.info("初筛完成，股票池已缓存")
        except Exception as e:
            logger.error(f"初筛失败: {e}")

    def _run_strategy_job(self):
        """定时任务：策略扫描+通知"""
        logger.info("定时任务：策略扫描+通知")
        try:
            self.engine.run_strategies_and_notify()
        except Exception as e:
            logger.error(f"策略扫描失败: {e}")

    def _health_check_job(self):
        """定时任务：发送健康报告到测试钉钉机器人"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        uptime = datetime.datetime.now() - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        jobs = self.scheduler.get_jobs()
        job_info = []
        for job in jobs:
            next_run = getattr(job, 'next_run_time', None)
            next_str = next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "待调度"
            job_info.append(f"  {job.name}: 下次运行 {next_str}")

        msg = (
            f"💚 系统健康报告\n"
            f"时间: {now}\n"
            f"运行时长: {hours}h{minutes}m{seconds}s (启动于 {self._start_time.strftime('%Y-%m-%d %H:%M:%S')})\n"
            f"定时任务({len(jobs)}个):\n"
            + "\n".join(job_info)
        )

        try:
            self.notifier.send(msg, test=True)
            logger.info("健康报告已发送")
        except Exception as e:
            logger.error(f"健康报告发送失败: {e}")
