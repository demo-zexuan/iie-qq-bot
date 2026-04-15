"""
group_stats 插件入口

负责以下四项职责：
  I.  插件元信息声明（供 NoneBot 商店及 /help 命令识别）
  II. 模块级资源初始化（配置、数据库引擎、会话工厂、业务服务实例）
      资源在模块导入时创建，生命周期与进程一致
  III. NoneBot on_startup 钩子：应用就绪后自动建表并注册定时任务
    IV. 手动触发命令：群内 @机器人 /统计人数，立即触发当前群一次统计

@module plugins.group_stats
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from nonebot import get_driver, logger, on_command
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.rule import to_me
import asyncio
import base64

from .chart import render_group_trend_chart_png
from .config import load_config
from .db import create_engine, create_session_factory, init_database
from .scheduler import register_daily_job
from .service import GroupStatsService

# I. 插件元信息，NoneBot 框架读取此字段用于插件管理
__plugin_meta__ = PluginMetadata(
    name="group_stats",
    description="每日统计配置群人数并汇总到 PostgreSQL",
    usage="@机器人 /统计人数 手动触发当前群统计",
)

# II. 模块级资源初始化
# 注意：变量名使用 group_stats_ 前缀，避免与子模块同名导致类型检查误判
# （若命名为 "config"，会与子模块 .config 冲突，Pyright 会产生类型警告）
group_stats_config = load_config()
# 创建异步数据库引擎（含连接池）
engine = create_engine(group_stats_config)
# 创建 Session 工厂，供 service 在每次任务中获取独立 Session
session_factory = create_session_factory(engine)
# 业务服务实例，持有配置和数据库组件
group_stats_service = GroupStatsService(group_stats_config, engine, session_factory)

driver = get_driver()


@driver.on_startup
async def _startup() -> None:
    """
    NoneBot 启动完成后执行的初始化钩子

    1. 建表：若 group_member_stats 表不存在则自动创建（幂等操作）
    2. 注册定时任务：以配置的时间和时区注册每日统计 cron 任务
    """
    # 1. 自动建表（已存在则跳过，不会修改已有表结构）
    await init_database(engine)
    # 2. 注册每日定时任务到 APScheduler
    register_daily_job(
        group_stats_service,
        group_stats_config.daily_time,
        group_stats_config.timezone,
    )
    group_ids_text = ",".join(str(group_id) for group_id in group_stats_config.group_ids)
    logger.info(
        (
            "group_stats 插件启动完成，监控群数量={}，"
            "监控群ID=[{}]，daily_time={}，timezone={}，api_timeout={}s"
        ),
        len(group_stats_config.group_ids),
        group_ids_text,
        group_stats_config.daily_time,
        group_stats_config.timezone,
        group_stats_config.api_timeout,
    )


# IV. 手动触发命令：群内 @机器人 /统计人数
# 使用 to_me() 限定必须 @机器人，避免误触发普通聊天消息
manual_trigger = on_command(
    "统计人数",
    rule=to_me(),
    priority=10,
    block=True,
)


@manual_trigger.handle()
async def _handle_manual_trigger(event: GroupMessageEvent) -> None:
    """
    处理群内 @机器人 /统计人数 命令

    1. 仅允许配置群触发，避免写入未纳管群数据
    2. 调用 run_manual_for_group() 获取当前人数并完成写库
    3. 回复当前人数与上一次统计人数（若存在）
    """
    try:
        group_id = int(event.group_id)
        report = await group_stats_service.run_manual_for_group(group_id)
        if not report.success:
            await manual_trigger.finish(f"统计失败: {report.error}")

        group_display_name = report.group_name or str(group_id)
        summary_lines: list[str]
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
            diff_text = f"+{diff}" if diff > 0 else str(diff)
            summary_lines = [
                f"群 {group_display_name} 当前人数: {report.current_member_count}",
                (
                    "最近一次统计: "
                    f"{report.previous_member_count} "
                    f"({previous_time_text})"
                ),
                f"人数变化: {diff_text}",
                "本次统计结果已写入数据库",
            ]

        # 先发送文本统计结果，确保主流程稳定可见
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
        chart_desc = (
            "近30天群人数波动曲线"
            f"（{trend_result.aggregation_note}，原始点位={trend_result.raw_count}）"
        )
        await manual_trigger.finish(
            MessageSegment.text(f"{chart_desc}\n")
            + MessageSegment.image(f"base64://{chart_base64}")
        )
    except FinishedException:
        # FinishedException 是 NoneBot 内部流程控制异常，必须继续向上抛出
        raise
    except Exception as exc:
        # 3. 捕获并上报业务异常，防止 handler 静默失败
        logger.exception("手动触发群统计失败")
        await manual_trigger.finish(f"统计失败: {exc}")
