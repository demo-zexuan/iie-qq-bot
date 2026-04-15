"""
group_stats 消息活动统计收集器

职责：
  I.  接收群消息事件并做内存聚合（按用户日维度与小时桶）
  II. 定时将缓存批量 UPSERT 到数据库
  III. 通过批写降低高频消息对数据库的冲击

@module plugins.group_stats.message_stats
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import GroupHourlyStat, GroupUserDailyStat, GroupUserHourlyStat


@dataclass(slots=True)
class _DailyUserCounter:
    """用户日维度聚合值。"""

    display_name: str
    message_count: int
    first_message_at: datetime
    last_message_at: datetime


@dataclass(slots=True)
class FlushSnapshot:
    """一次 flush 的快照统计信息。"""

    daily_user_rows: int
    user_hourly_rows: int
    group_hourly_rows: int


class MessageStatsCollector:
    """
    群消息统计收集器

    I.   `collect_message()` 在消息事件中调用，执行内存累加
    II.  `flush()` 定时批量落库，清空内存缓存
    III. `flush()` 线程安全，支持多协程并发调用
    """

    def __init__(self, session_factory: async_sessionmaker, timezone: str) -> None:
        self._session_factory = session_factory
        self._tz = ZoneInfo(timezone)
        self._lock = asyncio.Lock()

        # key: (group_id, user_id, stat_date)
        self._daily_user_counters: dict[tuple[int, int, date], _DailyUserCounter] = {}
        # key: (group_id, user_id, stat_date, hour_bucket)
        self._user_hourly_counters: dict[tuple[int, int, date, int], int] = {}
        # key: (group_id, stat_date, hour_bucket)
        self._group_hourly_counters: dict[tuple[int, date, int], int] = {}

    async def collect_message(
        self,
        group_id: int,
        user_id: int,
        display_name: str,
        event_time: datetime | None = None,
    ) -> None:
        """
        记录一条群消息到内存聚合

        @param group_id - 群号
        @param user_id - 用户 ID
        @param display_name - 用户展示名（优先群名片）
        @param event_time - 事件时间（为空时使用当前时间）
        """
        now = (event_time or datetime.now(self._tz)).astimezone(self._tz).replace(microsecond=0)
        stat_date = now.date()
        hour_bucket = now.hour

        daily_key = (group_id, user_id, stat_date)
        user_hourly_key = (group_id, user_id, stat_date, hour_bucket)
        group_hourly_key = (group_id, stat_date, hour_bucket)

        async with self._lock:
            counter = self._daily_user_counters.get(daily_key)
            if counter is None:
                self._daily_user_counters[daily_key] = _DailyUserCounter(
                    display_name=display_name,
                    message_count=1,
                    first_message_at=now,
                    last_message_at=now,
                )
            else:
                counter.message_count += 1
                counter.display_name = display_name or counter.display_name
                if now < counter.first_message_at:
                    counter.first_message_at = now
                if now > counter.last_message_at:
                    counter.last_message_at = now

            self._user_hourly_counters[user_hourly_key] = (
                self._user_hourly_counters.get(user_hourly_key, 0) + 1
            )
            self._group_hourly_counters[group_hourly_key] = (
                self._group_hourly_counters.get(group_hourly_key, 0) + 1
            )

    async def flush(self) -> FlushSnapshot:
        """
        将当前缓存批量写入数据库并清空缓存

        @returns FlushSnapshot 包含本次写入的键数量
        """
        async with self._lock:
            if (
                not self._daily_user_counters
                and not self._user_hourly_counters
                and not self._group_hourly_counters
            ):
                return FlushSnapshot(0, 0, 0)

            daily_snapshot = self._daily_user_counters
            user_hourly_snapshot = self._user_hourly_counters
            group_hourly_snapshot = self._group_hourly_counters

            self._daily_user_counters = {}
            self._user_hourly_counters = {}
            self._group_hourly_counters = {}

        now = datetime.now(self._tz).replace(microsecond=0)
        async with self._session_factory() as session:
            # I. 批量写入用户日统计
            for (group_id, user_id, stat_date), counter in daily_snapshot.items():
                stmt = insert(GroupUserDailyStat).values(
                    group_id=group_id,
                    user_id=user_id,
                    display_name=counter.display_name,
                    stat_date=stat_date,
                    message_count=counter.message_count,
                    first_message_at=counter.first_message_at,
                    last_message_at=counter.last_message_at,
                    created_at=now,
                    updated_at=now,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_group_user_daily_stat",
                        set_={
                            "display_name": stmt.excluded.display_name,
                            "message_count": GroupUserDailyStat.message_count + stmt.excluded.message_count,
                            "first_message_at": func.least(
                                GroupUserDailyStat.first_message_at,
                                stmt.excluded.first_message_at,
                            ),
                            "last_message_at": func.greatest(
                                GroupUserDailyStat.last_message_at,
                                stmt.excluded.last_message_at,
                            ),
                            "updated_at": now,
                        },
                    )
                )

            # II. 批量写入用户小时桶统计
            for (group_id, user_id, stat_date, hour_bucket), message_count in user_hourly_snapshot.items():
                stmt = insert(GroupUserHourlyStat).values(
                    group_id=group_id,
                    user_id=user_id,
                    stat_date=stat_date,
                    hour_bucket=hour_bucket,
                    message_count=message_count,
                    created_at=now,
                    updated_at=now,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_group_user_hourly_stat",
                        set_={
                            "message_count": GroupUserHourlyStat.message_count + stmt.excluded.message_count,
                            "updated_at": now,
                        },
                    )
                )

            # III. 批量写入群小时桶统计
            for (group_id, stat_date, hour_bucket), message_count in group_hourly_snapshot.items():
                stmt = insert(GroupHourlyStat).values(
                    group_id=group_id,
                    stat_date=stat_date,
                    hour_bucket=hour_bucket,
                    message_count=message_count,
                    created_at=now,
                    updated_at=now,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_group_hourly_stat",
                        set_={
                            "message_count": GroupHourlyStat.message_count + stmt.excluded.message_count,
                            "updated_at": now,
                        },
                    )
                )

            await session.commit()

        return FlushSnapshot(
            daily_user_rows=len(daily_snapshot),
            user_hourly_rows=len(user_hourly_snapshot),
            group_hourly_rows=len(group_hourly_snapshot),
        )
