"""
group_stats 核心业务逻辑

职责：
  I.  群人数统计（原功能）
  II. 水群活跃统计查询（Top10 / Top1 / 小时趋势）
  III. 历史明细归档（保留最近 N 天明细）

@module plugins.group_stats.service
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .config import GroupStatsConfig
from .models import (
    GroupActivityDailyArchive,
    GroupHourlyStat,
    GroupMemberStat,
    GroupUserDailyStat,
    GroupUserHourlyStat,
)


@dataclass(slots=True)
class GroupStatResult:
    """单次群信息查询结果。"""

    group_id: int
    group_name: str
    member_count: int
    success: bool
    error: str = ""


@dataclass(slots=True)
class ManualGroupStatReport:
    """手动触发单群人数统计回传。"""

    group_id: int
    group_name: str
    current_member_count: int
    previous_member_count: int | None
    previous_stat_time: datetime | None
    success: bool
    error: str = ""


@dataclass(slots=True)
class GroupTrendPoint:
    """群人数趋势图数据点。"""

    stat_time: datetime
    member_count: int


@dataclass(slots=True)
class GroupTrendResult:
    """群人数趋势图数据集。"""

    points: list[GroupTrendPoint]
    aggregation_note: str
    raw_count: int


@dataclass(slots=True)
class ScheduledGroupReport:
    """定时任务中单个群的群人数统计回传。"""

    group_id: int
    group_name: str
    current_member_count: int
    previous_member_count: int | None
    success: bool
    error: str = ""


@dataclass(slots=True)
class ScheduledRunReport:
    """一次群人数定时统计任务汇总。"""

    success_count: int
    failed_count: int
    group_reports: list[ScheduledGroupReport]


@dataclass(slots=True)
class TopUserStat:
    """单个用户的日活跃统计。"""

    rank: int
    user_id: int
    display_name: str
    message_count: int
    first_message_at: datetime
    last_message_at: datetime


@dataclass(slots=True)
class HourlyDistributionPoint:
    """小时维度统计点。"""

    hour_bucket: int
    message_count: int


@dataclass(slots=True)
class GroupDailyWaterReport:
    """单群单日水群报告。"""

    group_id: int
    stat_date: date
    total_message_count: int
    top10_message_count: int
    top10_ratio: float
    top_users: list[TopUserStat]
    top1_user: TopUserStat | None


@dataclass(slots=True)
class GroupChampionReport:
    """多群冠军汇总项。"""

    group_id: int
    stat_date: date
    total_message_count: int
    top10_ratio: float
    top1_user: TopUserStat | None


@dataclass(slots=True)
class ArchiveReport:
    """一次归档任务回传结果。"""

    archived_days: int
    archived_groups: int
    archived_daily_rows: int
    deleted_user_daily_rows: int
    deleted_user_hourly_rows: int
    deleted_group_hourly_rows: int


class GroupStatsService:
    """
    群统计服务

    I.  群人数定时采集与写库
    II. 活跃度查询接口
    III. 明细归档任务
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
        self.tz = ZoneInfo(config.timezone)

    def now(self) -> datetime:
        """获取当前配置时区时间（秒级）。"""
        return datetime.now(self.tz).replace(microsecond=0)

    def today(self) -> date:
        """获取当前配置时区日期。"""
        return self.now().date()

    def _pick_bot(self) -> Bot | None:
        """从当前已连接的 Bot 实例中选取第一个 OneBot V11 Bot。"""
        for candidate in get_bots().values():
            if isinstance(candidate, Bot):
                return candidate
        return None

    async def _fetch_group_info(self, bot: Bot, group_id: int) -> GroupStatResult:
        """调用 NapCat API 获取单个群信息。"""
        try:
            data: Any = await bot.call_api(
                "get_group_info",
                group_id=group_id,
                no_cache=True,
            )
            return GroupStatResult(
                group_id=group_id,
                group_name=str(data.get("group_name", "")),
                member_count=int(data.get("member_count", 0)),
                success=True,
            )
        except Exception as exc:
            logger.exception("获取群信息失败 group_id={}", group_id)
            return GroupStatResult(
                group_id=group_id,
                group_name="",
                member_count=0,
                success=False,
                error=str(exc),
            )

    def _build_upsert_stmt(self, result: GroupStatResult, now: datetime):
        """构造 group_member_stats 的 UPSERT 语句。"""
        stmt = insert(GroupMemberStat).values(
            group_id=result.group_id,
            group_name=result.group_name,
            member_count=result.member_count,
            stat_date=now.date(),
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

    def _aggregate_trend_points(self, rows: list[GroupMemberStat]) -> GroupTrendResult:
        """按点位规模执行分层聚合，避免图像过密。"""
        raw_points = [
            GroupTrendPoint(
                stat_time=row.stat_time.astimezone(self.tz),
                member_count=row.member_count,
            )
            for row in rows
        ]
        raw_count = len(raw_points)
        if raw_count <= 90:
            return GroupTrendResult(points=raw_points, aggregation_note="原始点位", raw_count=raw_count)

        if raw_count <= 365:
            day_last_point: dict[tuple[int, int, int], GroupTrendPoint] = {}
            for point in raw_points:
                key = (point.stat_time.year, point.stat_time.month, point.stat_time.day)
                day_last_point[key] = point
            aggregated = [day_last_point[key] for key in sorted(day_last_point)]
            return GroupTrendResult(points=aggregated, aggregation_note="按天聚合", raw_count=raw_count)

        week_last_point: dict[tuple[int, int], GroupTrendPoint] = {}
        for point in raw_points:
            iso_year, iso_week, _ = point.stat_time.isocalendar()
            week_last_point[(iso_year, iso_week)] = point
        aggregated = [week_last_point[key] for key in sorted(week_last_point)]
        return GroupTrendResult(points=aggregated, aggregation_note="按周聚合", raw_count=raw_count)

    async def get_group_trend_data(self, group_id: int, days: int = 30) -> GroupTrendResult:
        """获取单群人数趋势图数据并执行分层聚合。"""
        days = max(1, days)
        start_date = (self.now() - timedelta(days=days - 1)).date()

        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GroupMemberStat)
                        .where(GroupMemberStat.group_id == group_id)
                        .where(GroupMemberStat.stat_date >= start_date)
                        .order_by(GroupMemberStat.stat_time.asc(), GroupMemberStat.updated_at.asc())
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            return GroupTrendResult(points=[], aggregation_note="无历史数据", raw_count=0)
        return self._aggregate_trend_points(rows)

    async def run_manual_for_group(self, group_id: int) -> ManualGroupStatReport:
        """手动触发单群人数统计。"""
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

        now = self.now()
        async with self.session_factory() as session:
            previous_row = (
                (
                    await session.execute(
                        select(GroupMemberStat)
                        .where(GroupMemberStat.group_id == group_id)
                        .order_by(GroupMemberStat.stat_time.desc(), GroupMemberStat.updated_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )

            result = await self._fetch_group_info(bot, group_id)
            if not result.success:
                return ManualGroupStatReport(
                    group_id=group_id,
                    group_name="",
                    current_member_count=0,
                    previous_member_count=(previous_row.member_count if previous_row else None),
                    previous_stat_time=(previous_row.stat_time if previous_row else None),
                    success=False,
                    error=result.error,
                )

            await session.execute(self._build_upsert_stmt(result, now))
            await session.commit()

        return ManualGroupStatReport(
            group_id=group_id,
            group_name=result.group_name,
            current_member_count=result.member_count,
            previous_member_count=(previous_row.member_count if previous_row else None),
            previous_stat_time=(previous_row.stat_time if previous_row else None),
            success=True,
        )

    async def run_once(self) -> ScheduledRunReport:
        """执行一轮群人数统计并写入数据库。"""
        if not self.config.group_ids:
            logger.warning("GROUP_STATS_GROUP_IDS 为空，跳过本次统计")
            return ScheduledRunReport(success_count=0, failed_count=0, group_reports=[])

        bot = self._pick_bot()
        if bot is None:
            logger.warning("未找到可用的 OneBot Bot 实例，跳过本次统计")
            return ScheduledRunReport(
                success_count=0,
                failed_count=len(self.config.group_ids),
                group_reports=[
                    ScheduledGroupReport(
                        group_id=gid,
                        group_name="",
                        current_member_count=0,
                        previous_member_count=None,
                        success=False,
                        error="未找到可用的 OneBot Bot 实例",
                    )
                    for gid in self.config.group_ids
                ],
            )

        now = self.now()
        success_count = 0
        failed_count = 0
        group_reports: list[ScheduledGroupReport] = []

        async with self.session_factory() as session:
            for group_id in self.config.group_ids:
                previous_row = (
                    (
                        await session.execute(
                            select(GroupMemberStat)
                            .where(GroupMemberStat.group_id == group_id)
                            .order_by(GroupMemberStat.stat_time.desc(), GroupMemberStat.updated_at.desc())
                            .limit(1)
                        )
                    )
                    .scalars()
                    .first()
                )
                previous_count = previous_row.member_count if previous_row else None

                result = await self._fetch_group_info(bot, group_id)
                if not result.success:
                    failed_count += 1
                    group_reports.append(
                        ScheduledGroupReport(
                            group_id=group_id,
                            group_name="",
                            current_member_count=0,
                            previous_member_count=previous_count,
                            success=False,
                            error=result.error,
                        )
                    )
                    continue

                await session.execute(self._build_upsert_stmt(result, now))
                success_count += 1
                group_reports.append(
                    ScheduledGroupReport(
                        group_id=group_id,
                        group_name=result.group_name,
                        current_member_count=result.member_count,
                        previous_member_count=previous_count,
                        success=True,
                    )
                )

            await session.commit()

        logger.info(
            "群人数统计完成 success={} failed={} total={}",
            success_count,
            failed_count,
            len(self.config.group_ids),
        )
        return ScheduledRunReport(
            success_count=success_count,
            failed_count=failed_count,
            group_reports=group_reports,
        )

    async def get_group_daily_water_report(
        self,
        group_id: int,
        stat_date: date | None = None,
        top_n: int = 10,
    ) -> GroupDailyWaterReport:
        """
        获取单群单日水群报告

        I.  统计当日总消息数
        II. 查询 TopN 用户（按消息数、末次时间排序）
        III. 计算 TopN 占比并返回 Top1
        """
        target_date = stat_date or self.today()
        top_n = max(1, top_n)

        async with self.session_factory() as session:
            total_message_count = int(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(GroupUserDailyStat.message_count), 0)).where(
                            GroupUserDailyStat.group_id == group_id,
                            GroupUserDailyStat.stat_date == target_date,
                        )
                    )
                ).scalar_one()
            )

            top_rows = (
                (
                    await session.execute(
                        select(GroupUserDailyStat)
                        .where(
                            GroupUserDailyStat.group_id == group_id,
                            GroupUserDailyStat.stat_date == target_date,
                        )
                        .order_by(
                            GroupUserDailyStat.message_count.desc(),
                            GroupUserDailyStat.last_message_at.desc(),
                        )
                        .limit(top_n)
                    )
                )
                .scalars()
                .all()
            )

        top_users: list[TopUserStat] = []
        for idx, row in enumerate(top_rows, start=1):
            top_users.append(
                TopUserStat(
                    rank=idx,
                    user_id=row.user_id,
                    display_name=row.display_name,
                    message_count=row.message_count,
                    first_message_at=row.first_message_at.astimezone(self.tz),
                    last_message_at=row.last_message_at.astimezone(self.tz),
                )
            )

        top10_message_count = sum(user.message_count for user in top_users)
        top10_ratio = (top10_message_count / total_message_count) if total_message_count > 0 else 0.0
        top1_user = top_users[0] if top_users else None

        return GroupDailyWaterReport(
            group_id=group_id,
            stat_date=target_date,
            total_message_count=total_message_count,
            top10_message_count=top10_message_count,
            top10_ratio=top10_ratio,
            top_users=top_users,
            top1_user=top1_user,
        )

    async def get_user_hourly_distribution(
        self,
        group_id: int,
        user_id: int,
        stat_date: date | None = None,
    ) -> list[HourlyDistributionPoint]:
        """获取用户在指定日期的 24 小时消息分布。"""
        target_date = stat_date or self.today()

        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GroupUserHourlyStat)
                        .where(
                            GroupUserHourlyStat.group_id == group_id,
                            GroupUserHourlyStat.user_id == user_id,
                            GroupUserHourlyStat.stat_date == target_date,
                        )
                        .order_by(GroupUserHourlyStat.hour_bucket.asc())
                    )
                )
                .scalars()
                .all()
            )

        row_map = {row.hour_bucket: row.message_count for row in rows}
        return [
            HourlyDistributionPoint(hour_bucket=hour, message_count=row_map.get(hour, 0))
            for hour in range(24)
        ]

    async def get_group_hourly_trend(
        self,
        group_id: int,
        stat_date: date | None = None,
    ) -> list[HourlyDistributionPoint]:
        """获取群在指定日期的 24 小时整体活跃趋势。"""
        target_date = stat_date or self.today()

        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GroupHourlyStat)
                        .where(
                            GroupHourlyStat.group_id == group_id,
                            GroupHourlyStat.stat_date == target_date,
                        )
                        .order_by(GroupHourlyStat.hour_bucket.asc())
                    )
                )
                .scalars()
                .all()
            )

        row_map = {row.hour_bucket: row.message_count for row in rows}
        return [
            HourlyDistributionPoint(hour_bucket=hour, message_count=row_map.get(hour, 0))
            for hour in range(24)
        ]

    async def get_all_groups_champions(self, stat_date: date | None = None) -> list[GroupChampionReport]:
        """汇总所有配置群的当日冠军信息。"""
        target_date = stat_date or self.today()
        reports: list[GroupChampionReport] = []
        for group_id in self.config.group_ids:
            daily = await self.get_group_daily_water_report(group_id, target_date, top_n=10)
            reports.append(
                GroupChampionReport(
                    group_id=group_id,
                    stat_date=target_date,
                    total_message_count=daily.total_message_count,
                    top10_ratio=daily.top10_ratio,
                    top1_user=daily.top1_user,
                )
            )
        return reports

    async def archive_old_activity_data(self, retention_days: int) -> ArchiveReport:
        """
        归档历史活跃明细数据

        I.  将早于保留窗口的日统计聚合写入归档表
        II. 删除三张明细表中同窗口数据
        """
        retention_days = max(1, retention_days)
        archive_before = self.today() - timedelta(days=retention_days)
        now = self.now()

        async with self.session_factory() as session:
            old_rows = (
                (
                    await session.execute(
                        select(GroupUserDailyStat)
                        .where(GroupUserDailyStat.stat_date < archive_before)
                        .order_by(
                            GroupUserDailyStat.stat_date.asc(),
                            GroupUserDailyStat.group_id.asc(),
                            GroupUserDailyStat.message_count.desc(),
                            GroupUserDailyStat.last_message_at.desc(),
                        )
                    )
                )
                .scalars()
                .all()
            )

            grouped: dict[tuple[int, date], list[GroupUserDailyStat]] = {}
            for row in old_rows:
                grouped.setdefault((row.group_id, row.stat_date), []).append(row)

            archived_daily_rows = 0
            archived_days = len({key[1] for key in grouped})
            archived_groups = len({key[0] for key in grouped})

            for (group_id, stat_date), rows in grouped.items():
                rows = sorted(
                    rows,
                    key=lambda item: (
                        -item.message_count,
                        -item.last_message_at.timestamp(),
                    ),
                )
                total = sum(item.message_count for item in rows)
                top10_rows = rows[:10]
                top10_count = sum(item.message_count for item in top10_rows)
                top10_ratio = (top10_count / total) if total > 0 else 0.0
                top1 = top10_rows[0] if top10_rows else None

                stmt = insert(GroupActivityDailyArchive).values(
                    group_id=group_id,
                    group_name="",
                    stat_date=stat_date,
                    total_message_count=total,
                    top10_message_count=top10_count,
                    top10_ratio=top10_ratio,
                    top1_user_id=(top1.user_id if top1 else None),
                    top1_display_name=(top1.display_name if top1 else ""),
                    top1_message_count=(top1.message_count if top1 else 0),
                    top1_first_message_at=(top1.first_message_at if top1 else None),
                    top1_last_message_at=(top1.last_message_at if top1 else None),
                    created_at=now,
                    updated_at=now,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_group_activity_daily_archive",
                        set_={
                            "group_name": stmt.excluded.group_name,
                            "total_message_count": stmt.excluded.total_message_count,
                            "top10_message_count": stmt.excluded.top10_message_count,
                            "top10_ratio": stmt.excluded.top10_ratio,
                            "top1_user_id": stmt.excluded.top1_user_id,
                            "top1_display_name": stmt.excluded.top1_display_name,
                            "top1_message_count": stmt.excluded.top1_message_count,
                            "top1_first_message_at": stmt.excluded.top1_first_message_at,
                            "top1_last_message_at": stmt.excluded.top1_last_message_at,
                            "updated_at": now,
                        },
                    )
                )
                archived_daily_rows += 1

            deleted_user_daily_rows = (
                await session.execute(
                    delete(GroupUserDailyStat).where(GroupUserDailyStat.stat_date < archive_before)
                )
            ).rowcount or 0
            deleted_user_hourly_rows = (
                await session.execute(
                    delete(GroupUserHourlyStat).where(GroupUserHourlyStat.stat_date < archive_before)
                )
            ).rowcount or 0
            deleted_group_hourly_rows = (
                await session.execute(
                    delete(GroupHourlyStat).where(GroupHourlyStat.stat_date < archive_before)
                )
            ).rowcount or 0

            await session.commit()

        return ArchiveReport(
            archived_days=archived_days,
            archived_groups=archived_groups,
            archived_daily_rows=archived_daily_rows,
            deleted_user_daily_rows=deleted_user_daily_rows,
            deleted_user_hourly_rows=deleted_user_hourly_rows,
            deleted_group_hourly_rows=deleted_group_hourly_rows,
        )
