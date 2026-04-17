"""
group_stats 插件入口

职责：
  I.   群人数统计（原功能）
  II.  水群活跃统计采集与查询
  III. 定时播报、缓存刷盘与历史归档

@module plugins.group_stats
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime

from nonebot import get_bots, get_driver, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

from .chart import (
    render_group_hourly_trend_png,
    render_group_trend_chart_png,
    render_top1_hourly_distribution_png,
)
from .config import load_config
from .db import create_engine, create_session_factory, init_database
from .message_stats import MessageStatsCollector
from .scheduler import register_daily_job, register_interval_job
from .service import GroupStatsService, TopUserStat

# I. 插件元信息
__plugin_meta__ = PluginMetadata(
    name="group_stats",
    description="每日统计群人数与水群活跃度并汇总到 PostgreSQL",
    usage="@机器人 /统计人数 | /水群榜 | /水群画像",
)

# II. 模块级资源初始化
group_stats_config = load_config()
engine = create_engine(group_stats_config)
session_factory = create_session_factory(engine)
group_stats_service = GroupStatsService(group_stats_config, engine, session_factory)
message_stats_collector = MessageStatsCollector(session_factory, group_stats_config.timezone)

driver = get_driver()


def _pick_bot() -> Bot | None:
    """选取可用 Bot 实例。"""
    for candidate in get_bots().values():
        if isinstance(candidate, Bot):
            return candidate
    return None


def _format_user_display(user: TopUserStat) -> str:
    """格式化榜单用户显示名。"""
    return f"{user.display_name or '未知用户'}({user.user_id})"


def _format_hms(value: datetime) -> str:
    """按插件时区格式化时分秒。"""
    return value.astimezone(group_stats_service.tz).strftime("%H:%M:%S")


async def _flush_message_stats() -> None:
    """执行消息统计缓存刷盘。"""
    snapshot = await message_stats_collector.flush()
    if (
        snapshot.daily_user_rows > 0
        or snapshot.user_hourly_rows > 0
        or snapshot.group_hourly_rows > 0
    ):
        logger.info(
            (
                "消息统计缓存已刷盘: daily_user_rows={} "
                "user_hourly_rows={} group_hourly_rows={}"
            ),
            snapshot.daily_user_rows,
            snapshot.user_hourly_rows,
            snapshot.group_hourly_rows,
        )


async def _run_archive_task() -> None:
    """执行历史活跃明细归档。"""
    await _flush_message_stats()
    report = await group_stats_service.archive_old_activity_data(
        retention_days=group_stats_config.archive_retention_days
    )
    logger.info(
        (
            "活跃明细归档完成: archived_days={} archived_groups={} archived_daily_rows={} "
            "deleted_user_daily_rows={} deleted_user_hourly_rows={} deleted_group_hourly_rows={}"
        ),
        report.archived_days,
        report.archived_groups,
        report.archived_daily_rows,
        report.deleted_user_daily_rows,
        report.deleted_user_hourly_rows,
        report.deleted_group_hourly_rows,
    )


async def _send_group_image(bot: Bot, group_id: int, description: str, image_bytes: bytes) -> None:
    """发送图像消息（base64）。"""
    chart_base64 = base64.b64encode(image_bytes).decode("ascii")
    await bot.send_group_msg(
        group_id=group_id,
        message=MessageSegment.text(f"{description}\n")
        + MessageSegment.image(f"base64://{chart_base64}"),
    )


async def _run_scheduled_task() -> None:
    """
    定时统计任务包装器

    I.   群人数采集与播报
    II.  活跃度冠军播报
    III. 发送 Top1 分布图与全群小时趋势图
    """
    await _flush_message_stats()

    report = await group_stats_service.run_once()
    if not report.group_reports:
        return

    bot = _pick_bot()
    if bot is None:
        logger.warning("定时推送失败：未找到可用的 OneBot Bot 实例")
        return

    for group_report in report.group_reports:
        if not group_report.success:
            continue

        group_id = group_report.group_id
        group_name = group_report.group_name or str(group_id)

        # I. 人数播报
        summary_lines = [
            "📊 [定时任务] 群人数每日播报",
            f"群 {group_name}: {group_report.current_member_count} 人",
        ]
        if group_report.previous_member_count is not None:
            diff = group_report.current_member_count - group_report.previous_member_count
            summary_lines.append(f"与上次相比: {diff:+d}")

        try:
            await bot.send_group_msg(group_id=group_id, message="\n".join(summary_lines))
        except Exception:
            logger.exception("定时推送文字消息失败 group_id={}", group_id)
            continue

        # I.2 人数趋势图
        trend_result = await group_stats_service.get_group_trend_data(group_id, days=30)
        if trend_result.points:
            try:
                chart_bytes = await asyncio.to_thread(
                    render_group_trend_chart_png,
                    group_name,
                    group_id,
                    [(point.stat_time, point.member_count) for point in trend_result.points],
                    trend_result.aggregation_note,
                )
                await _send_group_image(
                    bot,
                    group_id,
                    (
                        "近30天群人数波动曲线"
                        f"（{trend_result.aggregation_note}，原始点位={trend_result.raw_count}）"
                    ),
                    chart_bytes,
                )
            except Exception:
                logger.exception("定时推送人数趋势图失败 group_id={}", group_id)

        # II. 活跃度播报
        try:
            water_report = await group_stats_service.get_group_daily_water_report(group_id)
            if water_report.total_message_count <= 0 or water_report.top1_user is None:
                await bot.send_group_msg(
                    group_id=group_id,
                    message="📌 [定时任务] 今日暂无可用水群活跃数据",
                )
                continue

            top1_user = water_report.top1_user
            await bot.send_group_msg(
                group_id=group_id,
                message=(
                    "📈 [定时任务] 水群活跃日报\n"
                    f"日期: {water_report.stat_date.isoformat()}\n"
                    f"总消息数: {water_report.total_message_count}\n"
                    f"Top10 占比: {water_report.top10_ratio:.2%}"
                    f" ({water_report.top10_message_count}/{water_report.total_message_count})\n"
                    "冠军: "
                    f"{_format_user_display(top1_user)}，"
                    f"消息 {top1_user.message_count} 条，"
                    f"首条 {_format_hms(top1_user.first_message_at)}，"
                    f"末条 {_format_hms(top1_user.last_message_at)}"
                ),
            )

            top10_lines = [
                "📊 [定时任务] 今日水群榜（Top10）",
                f"日期: {water_report.stat_date.isoformat()}",
                f"总消息数: {water_report.total_message_count}",
                (
                    f"Top10 占比: {water_report.top10_ratio:.2%} "
                    f"({water_report.top10_message_count}/{water_report.total_message_count})"
                ),
            ]
            for user in water_report.top_users:
                top10_lines.append(
                    (
                        f"{user.rank:>2}. {_format_user_display(user)} - {user.message_count} 条 | "
                        f"首条 {_format_hms(user.first_message_at)} | 末条 {_format_hms(user.last_message_at)}"
                    )
                )
            await bot.send_group_msg(group_id=group_id, message="\n".join(top10_lines))

            top1_distribution = await group_stats_service.get_user_hourly_distribution(
                group_id=group_id,
                user_id=top1_user.user_id,
                stat_date=water_report.stat_date,
            )
            top1_chart = await asyncio.to_thread(
                render_top1_hourly_distribution_png,
                group_name,
                group_id,
                water_report.stat_date,
                top1_user.display_name,
                top1_user.user_id,
                top1_user.first_message_at,
                top1_user.last_message_at,
                [(point.hour_bucket, point.message_count) for point in top1_distribution],
            )
            await _send_group_image(bot, group_id, "Top1 消息时间分布图", top1_chart)

            group_trend = await group_stats_service.get_group_hourly_trend(
                group_id=group_id,
                stat_date=water_report.stat_date,
            )
            group_trend_chart = await asyncio.to_thread(
                render_group_hourly_trend_png,
                group_name,
                group_id,
                water_report.stat_date,
                [(point.hour_bucket, point.message_count) for point in group_trend],
            )
            await _send_group_image(bot, group_id, "全群小时活跃趋势图", group_trend_chart)
        except Exception:
            logger.exception("定时推送水群活跃日报失败 group_id={}", group_id)


@driver.on_startup
async def _startup() -> None:
    """应用启动时初始化数据库与调度任务。"""
    await init_database(engine)

    register_daily_job(
        _run_scheduled_task,
        group_stats_config.daily_time,
        group_stats_config.timezone,
        job_id="group_stats_daily_job",
    )
    register_interval_job(
        _flush_message_stats,
        group_stats_config.message_flush_interval_seconds,
        job_id="group_stats_message_flush_job",
    )
    register_daily_job(
        _run_archive_task,
        group_stats_config.archive_time,
        group_stats_config.timezone,
        job_id="group_stats_archive_job",
    )

    group_ids_text = ",".join(str(group_id) for group_id in group_stats_config.group_ids)
    logger.info(
        (
            "group_stats 插件启动完成，监控群数量={}，"
            "监控群ID=[{}]，daily_time={}，archive_time={}，timezone={}，"
            "flush_interval={}s，archive_retention={}d"
        ),
        len(group_stats_config.group_ids),
        group_ids_text,
        group_stats_config.daily_time,
        group_stats_config.archive_time,
        group_stats_config.timezone,
        group_stats_config.message_flush_interval_seconds,
        group_stats_config.archive_retention_days,
    )


@driver.on_shutdown
async def _shutdown() -> None:
    """应用关闭时执行最终刷盘。"""
    try:
        await _flush_message_stats()
    except Exception:
        logger.exception("关闭阶段刷盘失败")


# III. 消息采集监听器
message_activity_collector = on_message(priority=98, block=False)


@message_activity_collector.handle()
async def _collect_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    """采集群消息并写入内存聚合。"""
    group_id = int(event.group_id)
    if group_id not in group_stats_config.group_ids:
        return

    user_id = int(event.user_id)
    if user_id == int(bot.self_id):
        return

    sender = getattr(event, "sender", None)
    display_name = ""
    if sender is not None:
        display_name = str(getattr(sender, "card", "") or getattr(sender, "nickname", "") or "")
    if not display_name:
        display_name = str(user_id)

    await message_stats_collector.collect_message(
        group_id=group_id,
        user_id=user_id,
        display_name=display_name,
        event_time=group_stats_service.now(),
    )


# IV. 手动命令
manual_trigger = on_command("统计人数", rule=to_me(), priority=10, block=True)
water_rank_trigger = on_command("水群榜", rule=to_me(), priority=10, block=True)
water_profile_trigger = on_command("水群画像", rule=to_me(), priority=10, block=True)


@manual_trigger.handle()
async def _handle_manual_trigger(event: GroupMessageEvent) -> None:
    """处理群内 @机器人 /统计人数 命令。"""
    try:
        group_id = int(event.group_id)
        report = await group_stats_service.run_manual_for_group(group_id)
        if not report.success:
            await manual_trigger.finish(f"统计失败: {report.error}")

        group_display_name = report.group_name or str(group_id)
        if report.previous_member_count is None:
            summary_lines = [
                f"群 {group_display_name} 当前人数: {report.current_member_count}",
                "最近一次统计: 无历史记录（已完成本次写入）",
            ]
        else:
            previous_time = report.previous_stat_time
            if previous_time is None:
                await manual_trigger.finish("统计失败: 历史记录时间缺失，请检查数据库数据")
            previous_time_text = previous_time.astimezone(group_stats_service.tz).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            diff = report.current_member_count - report.previous_member_count
            summary_lines = [
                f"群 {group_display_name} 当前人数: {report.current_member_count}",
                f"最近一次统计: {report.previous_member_count} ({previous_time_text})",
                f"人数变化: {diff:+d}",
                "本次统计结果已写入数据库",
            ]

        await manual_trigger.send("\n".join(summary_lines))

        trend_result = await group_stats_service.get_group_trend_data(group_id, days=30)
        if not trend_result.points:
            await manual_trigger.finish("暂未查询到可绘制的历史数据，已完成本次统计写入")

        chart_bytes = await asyncio.to_thread(
            render_group_trend_chart_png,
            group_display_name,
            group_id,
            [(point.stat_time, point.member_count) for point in trend_result.points],
            trend_result.aggregation_note,
        )
        chart_base64 = base64.b64encode(chart_bytes).decode("ascii")
        await manual_trigger.send(
            MessageSegment.text(
                (
                    "近30天群人数波动曲线"
                    f"（{trend_result.aggregation_note}，原始点位={trend_result.raw_count}）\n"
                )
            )
            + MessageSegment.image(f"base64://{chart_base64}")
        )
        await manual_trigger.finish()
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("手动触发群统计失败")
        await manual_trigger.finish(f"统计失败: {exc}")


@water_rank_trigger.handle()
async def _handle_water_rank(event: GroupMessageEvent) -> None:
    """处理群内 @机器人 /水群榜 命令。"""
    try:
        group_id = int(event.group_id)
        if group_id not in group_stats_config.group_ids:
            await water_rank_trigger.finish("当前群未纳入统计配置")

        await _flush_message_stats()
        report = await group_stats_service.get_group_daily_water_report(group_id, top_n=10)
        if report.total_message_count <= 0:
            await water_rank_trigger.finish("今天还没有统计到群消息，稍后再试")

        lines = [
            "📊 今日水群榜（Top10）",
            f"日期: {report.stat_date.isoformat()}",
            f"总消息数: {report.total_message_count}",
            (
                f"Top10 占比: {report.top10_ratio:.2%} "
                f"({report.top10_message_count}/{report.total_message_count})"
            ),
        ]
        for user in report.top_users:
            lines.append(
                (
                    f"{user.rank:>2}. {_format_user_display(user)} - {user.message_count} 条 | "
                    f"首条 {_format_hms(user.first_message_at)} | 末条 {_format_hms(user.last_message_at)}"
                )
            )

        await water_rank_trigger.finish("\n".join(lines))
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("手动查询水群榜失败")
        await water_rank_trigger.finish(f"查询失败: {exc}")


@water_profile_trigger.handle()
async def _handle_water_profile(event: GroupMessageEvent) -> None:
    """处理群内 @机器人 /水群画像 命令。"""
    try:
        group_id = int(event.group_id)
        if group_id not in group_stats_config.group_ids:
            await water_profile_trigger.finish("当前群未纳入统计配置")

        await _flush_message_stats()
        report = await group_stats_service.get_group_daily_water_report(group_id, top_n=10)
        if report.total_message_count <= 0 or report.top1_user is None:
            await water_profile_trigger.finish("今天还没有统计到可用活跃数据，稍后再试")

        top1_user = report.top1_user
        bot = _pick_bot()
        if bot is None:
            await water_profile_trigger.finish("当前没有可用 Bot 实例，暂时无法发送图像")

        await water_profile_trigger.send(
            (
                "📈 今日活跃画像\n"
                f"日期: {report.stat_date.isoformat()}\n"
                f"总消息数: {report.total_message_count}\n"
                f"Top10 占比: {report.top10_ratio:.2%}\n"
                "Top1: "
                f"{_format_user_display(top1_user)}，"
                f"消息 {top1_user.message_count} 条，"
                f"首条 {_format_hms(top1_user.first_message_at)}，"
                f"末条 {_format_hms(top1_user.last_message_at)}"
            )
        )

        top1_distribution = await group_stats_service.get_user_hourly_distribution(
            group_id=group_id,
            user_id=top1_user.user_id,
            stat_date=report.stat_date,
        )
        top1_chart = await asyncio.to_thread(
            render_top1_hourly_distribution_png,
            str(group_id),
            group_id,
            report.stat_date,
            top1_user.display_name,
            top1_user.user_id,
            top1_user.first_message_at,
            top1_user.last_message_at,
            [(point.hour_bucket, point.message_count) for point in top1_distribution],
        )
        await _send_group_image(bot, group_id, "Top1 消息时间分布图", top1_chart)

        group_hourly = await group_stats_service.get_group_hourly_trend(
            group_id=group_id,
            stat_date=report.stat_date,
        )
        group_chart = await asyncio.to_thread(
            render_group_hourly_trend_png,
            str(group_id),
            group_id,
            report.stat_date,
            [(point.hour_bucket, point.message_count) for point in group_hourly],
        )
        await _send_group_image(bot, group_id, "全群小时活跃趋势图", group_chart)
        await water_profile_trigger.finish()
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("手动查询水群画像失败")
        await water_profile_trigger.finish(f"查询失败: {exc}")
