"""
group_stats 定时任务注册

封装 APScheduler cron 任务的注册逻辑，将解析好的时间字符串写入调度器。
APScheduler 由 nonebot-plugin-apscheduler 管理生命周期，跟随 NoneBot 启动与停止。

调度策略说明：
  I.  coalesce=True：若任务因服务重启等原因积压了多次未执行，
      补偿时只执行一次，避免短时间内重复写库
  II. misfire_grace_time=300：允许任务最多延迟 300 秒（5 分钟）触发，
      超出此时间窗口则视为本次错过，等待下一个周期
  III. max_instances=1：同一任务不允许并发执行，防止并发写库导致数据冲突

@module plugins.group_stats.scheduler
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from collections.abc import Awaitable, Callable

from nonebot import logger
from nonebot.plugin import require

# 声明对 nonebot_plugin_apscheduler 的依赖，确保该插件在本插件之前完成加载
# 必须在 import scheduler 之前调用，否则 scheduler 对象可能尚未初始化
require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402


def register_daily_job(
    task_fn: Callable[[], Awaitable[None]],
    daily_time: str,
    timezone: str,
    job_id: str = "group_stats_daily_job",
) -> None:
    """
    向 APScheduler 注册每日群人数统计 cron 任务

    I.  解析 daily_time 字符串（格式 "HH:MM"）提取小时和分钟
    II. 以 cron 触发器注册任务，配置如下调度策略：
        1. id=job_id                    唯一任务 ID，replace_existing=True 保证重启不重复注册
        2. coalesce=True               积压多次时只补偿一次
        3. misfire_grace_time=300      允许 5 分钟内的延迟触发，超时则跳过本次
        4. max_instances=1             禁止并发执行同一任务

    @param task_fn    - 定时触发的异步无参任务函数（通常为 _run_scheduled_task）
    @param daily_time - 每日执行时间字符串，格式为 "HH:MM"（如 "08:00"）
    @param timezone   - 时区名称（如 "Asia/Shanghai"），决定 cron 基准时区
    @param job_id     - 任务唯一 ID，用于区分不同日任务
    """
    # I. 解析时间字符串，拆分出小时和分钟
    hour_text, minute_text = daily_time.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)

    # II. 注册 cron 任务到 NoneBot 管理的共享调度器
    scheduler.add_job(
        task_fn,
        "cron",
        hour=hour,
        minute=minute,
        second=0,
        timezone=timezone,
        id=job_id,
        replace_existing=True,   # 重启后重新注册同名任务，避免 ID 冲突报错
        coalesce=True,           # 积压多次只补一次
        misfire_grace_time=300,  # 容忍 5 分钟内的调度延迟
        max_instances=1,         # 禁止并发执行
    )
    logger.info(
        (
            "已注册群统计日任务: id={} "
            "trigger=cron {}:00 timezone={} "
            "coalesce=true misfire_grace_time=300 max_instances=1"
        ),
        job_id,
        daily_time,
        timezone,
    )


def register_interval_job(
    task_fn: Callable[[], Awaitable[None]],
    seconds: int,
    job_id: str,
) -> None:
    """
    向 APScheduler 注册固定间隔任务

    I.  使用 interval 触发器按秒执行
    II. 复用 coalesce/misfire/max_instances 保护并发与积压

    @param task_fn - 定时触发的异步无参任务函数
    @param seconds - 间隔秒数，必须 > 0
    @param job_id  - 任务唯一 ID
    """
    if seconds <= 0:
        raise ValueError("interval seconds 必须为正整数")

    scheduler.add_job(
        task_fn,
        "interval",
        seconds=seconds,
        id=job_id,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=max(30, seconds * 2),
        max_instances=1,
    )
    logger.info(
        (
            "已注册群统计间隔任务: id={} trigger=interval {}s "
            "coalesce=true max_instances=1"
        ),
        job_id,
        seconds,
    )
