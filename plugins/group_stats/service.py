"""
group_stats 核心业务逻辑

负责以下两项核心职责：
  I.  通过 NapCat OneBot V11 API 拉取各配置群的成员数量
  II. 将拉取结果以 UPSERT 方式写入 PostgreSQL

并发安全：每次定时任务在 APScheduler 的 max_instances=1 限制下串行执行，
数据库层面通过唯一约束 + ON CONFLICT 兜底保证幂等性。

@module plugins.group_stats.service
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .config import GroupStatsConfig
from .models import GroupMemberStat


@dataclass(slots=True)
class GroupStatResult:
    """
    单次群信息查询结果（内部值对象，不直接暴露给外部）

    1. success=True  表示 API 调用成功，member_count 字段有效
    2. success=False 表示 API 调用失败，error 持有错误信息，
       写入层应跳过此条记录并计入 failed_count
    """

    group_id: int
    group_name: str
    member_count: int
    success: bool
    error: str = ""


@dataclass(slots=True)
class ManualGroupStatReport:
    """
    手动触发单群统计后的回传结果

    1. success=True  表示已成功获取当前人数并完成写库
    2. success=False 表示流程中断，error 持有失败原因
    """

    group_id: int
    group_name: str
    current_member_count: int
    previous_member_count: int | None
    previous_stat_time: datetime | None
    success: bool
    error: str = ""


@dataclass(slots=True)
class GroupTrendPoint:
    """群人数趋势图数据点"""

    stat_time: datetime
    member_count: int


@dataclass(slots=True)
class GroupTrendResult:
    """群人数趋势图数据集"""

    points: list[GroupTrendPoint]
    aggregation_note: str
    raw_count: int


class GroupStatsService:
    """
    群人数统计服务

    I.  接收配置（群号列表、时区、超时）和数据库组件（引擎、会话工厂）
    II. 对外暴露 run_once() 作为任务入口，有定时器调用和手动命令触发两种使用方式
    """

    def __init__(
        self,
        config: GroupStatsConfig,
        engine: AsyncEngine,
        session_factory: async_sessionmaker,
    ) -> None:
        self.config = config
        self.engine = engine
        self.session_factory = session_factory
        # 预先构建时区对象，避免在每次任务执行时重复解析时区字符串
        self.tz = ZoneInfo(config.timezone)

    def _pick_bot(self) -> Bot | None:
        """
        从当前已连接的 Bot 实例中选取第一个 OneBot V11 Bot

        NoneBot 支持同时接入多个 Bot 实例，此处仅需任意一个在线的 Bot
        来调用群信息接口，因此取第一个合法实例即可。

        @returns 可用的 Bot 实例，若无已连接的 OneBot Bot 则返回 None
        """
        for candidate in get_bots().values():
            if isinstance(candidate, Bot):
                return candidate
        return None

    async def _fetch_group_info(self, bot: Bot, group_id: int) -> GroupStatResult:
        """
        调用 NapCat API 获取单个群的信息

        I.  调用 get_group_info 接口（no_cache=True 强制 NapCat 刷新缓存）
        II. 提取 group_name 和 member_count 字段
        III. 任何异常（网络超时、群不存在、无权限等）均被捕获，
             返回 success=False 的 GroupStatResult，不向上抛出

        @param bot      - 用于调用 API 的 OneBot Bot 实例
        @param group_id - 目标群号
        @returns 包含查询结果或错误信息的 GroupStatResult
        """
        try:
            # I. 调用 NapCat API，no_cache=True 保证获取实时数据而非本地缓存
            data: Any = await bot.call_api(
                "get_group_info",
                group_id=group_id,
                no_cache=True,
            )
            # II. 提取关键字段，使用 get 提供默认值以应对字段缺失情况
            group_name = str(data.get("group_name", ""))
            member_count = int(data.get("member_count", 0))
            return GroupStatResult(
                group_id=group_id,
                group_name=group_name,
                member_count=member_count,
                success=True,
            )
        except Exception as exc:
            # III. 单群失败不影响其他群的统计，记录日志并返回失败结果
            logger.exception("获取群信息失败 group_id={}", group_id)
            return GroupStatResult(
                group_id=group_id,
                group_name="",
                member_count=0,
                success=False,
                error=str(exc),
            )

    def _build_upsert_stmt(self, result: GroupStatResult, now: datetime):
        """
        构造 group_member_stats 的 UPSERT 语句

        复用同一套写入逻辑，确保定时统计与手动统计的更新语义一致。
        """
        today = now.date()
        stmt = insert(GroupMemberStat).values(
            group_id=result.group_id,
            group_name=result.group_name,
            member_count=result.member_count,
            stat_date=today,
            stat_time=now,
            created_at=now,
            updated_at=now,
        )
        return stmt.on_conflict_do_update(
            constraint="uq_group_stat_date",
            set_={
                "group_name": result.group_name,
                "member_count": result.member_count,
                "stat_time": now,
                "updated_at": now,
            },
        )

    def _aggregate_trend_points(
        self,
        rows: list[GroupMemberStat],
    ) -> GroupTrendResult:
        """
        按点位规模执行分层聚合，避免图像过密

        I.   点位 <= 90    : 原始点位
        II.  90 < 点位 <=365: 按天保留最后一个点
        III. 点位 > 365    : 按周保留最后一个点
        """
        raw_points = [
            GroupTrendPoint(
                stat_time=row.stat_time.astimezone(self.tz),
                member_count=row.member_count,
            )
            for row in rows
        ]
        raw_count = len(raw_points)
        if raw_count <= 90:
            return GroupTrendResult(
                points=raw_points,
                aggregation_note="原始点位",
                raw_count=raw_count,
            )

        if raw_count <= 365:
            day_last_point: dict[tuple[int, int, int], GroupTrendPoint] = {}
            for point in raw_points:
                key = (point.stat_time.year, point.stat_time.month, point.stat_time.day)
                day_last_point[key] = point
            aggregated = [day_last_point[key] for key in sorted(day_last_point)]
            return GroupTrendResult(
                points=aggregated,
                aggregation_note="按天聚合",
                raw_count=raw_count,
            )

        week_last_point: dict[tuple[int, int], GroupTrendPoint] = {}
        for point in raw_points:
            iso_year, iso_week, _ = point.stat_time.isocalendar()
            week_last_point[(iso_year, iso_week)] = point
        aggregated = [week_last_point[key] for key in sorted(week_last_point)]
        return GroupTrendResult(
            points=aggregated,
            aggregation_note="按周聚合",
            raw_count=raw_count,
        )

    async def get_group_trend_data(
        self,
        group_id: int,
        days: int = 30,
    ) -> GroupTrendResult:
        """
        获取单群趋势图数据并执行分层聚合

        @param group_id - 目标群号
        @param days     - 时间窗口（天）
        @returns 趋势图数据与聚合说明
        """
        days = max(1, days)
        start_date = (datetime.now(self.tz) - timedelta(days=days - 1)).date()

        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GroupMemberStat)
                        .where(GroupMemberStat.group_id == group_id)
                        .where(GroupMemberStat.stat_date >= start_date)
                        .order_by(
                            GroupMemberStat.stat_time.asc(),
                            GroupMemberStat.updated_at.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            return GroupTrendResult(points=[], aggregation_note="无历史数据", raw_count=0)

        result = self._aggregate_trend_points(rows)
        logger.info(
            "趋势数据已生成 group_id={} raw_count={} chart_points={} aggregation={}",
            group_id,
            result.raw_count,
            len(result.points),
            result.aggregation_note,
        )
        return result

    async def run_manual_for_group(self, group_id: int) -> ManualGroupStatReport:
        """
        手动触发单群统计：返回当前人数与上一次统计结果，并完成写库

        I.   校验群号是否在配置白名单中
        II.  查询该群上一条统计记录（用于回显对比）
        III. 调用 QQ API 获取当前人数并执行 UPSERT

        @param group_id - 当前触发命令的群号
        @returns 手动统计回传结果
        """
        # I. 仅允许配置内群号触发手动统计，避免写入非业务群数据
        if group_id not in self.config.group_ids:
            return ManualGroupStatReport(
                group_id=group_id,
                group_name="",
                current_member_count=0,
                previous_member_count=None,
                previous_stat_time=None,
                success=False,
                error="当前群未在 GROUP_STATS_GROUP_IDS 配置中",
            )

        bot = self._pick_bot()
        if bot is None:
            return ManualGroupStatReport(
                group_id=group_id,
                group_name="",
                current_member_count=0,
                previous_member_count=None,
                previous_stat_time=None,
                success=False,
                error="未找到可用的 OneBot Bot 实例",
            )

        now = datetime.now(self.tz).replace(microsecond=0)

        async with self.session_factory() as session:
            # II. 读取该群最近一次统计结果，供回复消息展示“上次人数”
            previous_row = (
                (
                    await session.execute(
                        select(GroupMemberStat)
                        .where(GroupMemberStat.group_id == group_id)
                        .order_by(
                            GroupMemberStat.stat_time.desc(),
                            GroupMemberStat.updated_at.desc(),
                        )
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )

            # III. 查询当前实时人数
            result = await self._fetch_group_info(bot, group_id)
            if not result.success:
                return ManualGroupStatReport(
                    group_id=group_id,
                    group_name="",
                    current_member_count=0,
                    previous_member_count=(
                        previous_row.member_count if previous_row else None
                    ),
                    previous_stat_time=(previous_row.stat_time if previous_row else None),
                    success=False,
                    error=result.error,
                )

            # 与定时统计复用同一 UPSERT 逻辑
            await session.execute(self._build_upsert_stmt(result, now))
            await session.commit()

        logger.info(
            "手动群人数统计完成 group_id={} member_count={}",
            group_id,
            result.member_count,
        )
        return ManualGroupStatReport(
            group_id=group_id,
            group_name=result.group_name,
            current_member_count=result.member_count,
            previous_member_count=(previous_row.member_count if previous_row else None),
            previous_stat_time=(previous_row.stat_time if previous_row else None),
            success=True,
        )

    async def run_once(self) -> tuple[int, int]:
        """
        执行一轮群人数统计并写入数据库

        I.   前置检查
             1. 配置群号列表不为空
             2. 必须存在已连接的 OneBot Bot 实例
        II.  逐群查询并写入
             1. 调用 _fetch_group_info 查询群信息
             2. 查询失败则计入 failed_count，跳过写库
             3. 查询成功则构造 UPSERT 语句加入当前 Session
        III. 提交事务
             1. 批量提交本次所有 UPSERT 操作
             2. 记录统计日志

        幂等策略：ON CONFLICT (group_id, stat_date) DO UPDATE
        当天同一群号重复执行时，覆盖 member_count、group_name、
        stat_time、updated_at，created_at 保持首次写入不变。

        @returns (success_count, failed_count) 本次成功/失败的群数量
        """
        # I. 1. 群号列表为空则无需执行，提前返回
        if not self.config.group_ids:
            logger.warning("GROUP_STATS_GROUP_IDS 为空，跳过本次统计")
            return 0, 0

        # I. 2. 选取可用的 Bot 实例，无则整批失败
        bot = self._pick_bot()
        if bot is None:
            logger.warning("未找到可用的 OneBot Bot 实例，跳过本次统计")
            return 0, len(self.config.group_ids)

        # 以配置时区的当前时间作为本次统计时刻，去除微秒保持秒级精度
        now = datetime.now(self.tz).replace(microsecond=0)

        success_count = 0
        failed_count = 0

        # II. 逐群查询并写库，共享同一个 Session 以便批量提交
        async with self.session_factory() as session:
            for group_id in self.config.group_ids:
                result = await self._fetch_group_info(bot, group_id)
                # II. 2. API 失败则跳过写库，继续处理下一个群
                if not result.success:
                    failed_count += 1
                    continue

                # II. 3. 执行 UPSERT，同日重复统计时覆盖可变字段
                await session.execute(self._build_upsert_stmt(result, now))
                success_count += 1

            # III. 1. 批量提交本次所有群的 UPSERT 操作
            await session.commit()

        # III. 2. 统计结果日志，方便从日志追溯执行情况
        logger.info(
            "群人数统计完成 success={} failed={} total={}",
            success_count,
            failed_count,
            len(self.config.group_ids),
        )
        return success_count, failed_count
