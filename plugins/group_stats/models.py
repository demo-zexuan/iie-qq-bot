"""
group_stats 数据库 ORM 模型定义

使用 SQLAlchemy 2.x Mapped + mapped_column 声明式风格。
除原有群人数统计外，新增“人维度消息统计 + 小时桶 + 日归档”表。

@module plugins.group_stats.models
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的元数据基类。"""


class GroupMemberStat(Base):
    """群成员人数统计记录（原有功能）。"""

    __tablename__ = "group_member_stats"
    __table_args__ = (
        UniqueConstraint("group_id", "stat_date", name="uq_group_stat_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stat_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupUserDailyStat(Base):
    """群成员日发言统计：昵称+ID+消息数+最早/最晚发言时间。"""

    __tablename__ = "group_user_daily_stats"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", "stat_date", name="uq_group_user_daily_stat"),
        Index("ix_group_user_daily_group_date", "group_id", "stat_date"),
        Index("ix_group_user_daily_user_date", "user_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupUserHourlyStat(Base):
    """群成员小时桶发言统计：用于 Top1 时间分布图。"""

    __tablename__ = "group_user_hourly_stats"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "user_id",
            "stat_date",
            "hour_bucket",
            name="uq_group_user_hourly_stat",
        ),
        CheckConstraint("hour_bucket >= 0 AND hour_bucket <= 23", name="ck_group_user_hourly_bucket"),
        Index("ix_group_user_hourly_group_date", "group_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour_bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupHourlyStat(Base):
    """群整体小时桶发言统计：用于全群活跃度趋势图。"""

    __tablename__ = "group_hourly_stats"
    __table_args__ = (
        UniqueConstraint("group_id", "stat_date", "hour_bucket", name="uq_group_hourly_stat"),
        CheckConstraint("hour_bucket >= 0 AND hour_bucket <= 23", name="ck_group_hourly_bucket"),
        Index("ix_group_hourly_group_date", "group_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour_bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupActivityDailyArchive(Base):
    """群活跃度日归档摘要：长期保留，降低明细表规模。"""

    __tablename__ = "group_activity_daily_archives"
    __table_args__ = (
        UniqueConstraint("group_id", "stat_date", name="uq_group_activity_daily_archive"),
        Index("ix_group_activity_daily_group_date", "group_id", "stat_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top10_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top10_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    top1_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top1_display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    top1_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top1_first_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    top1_last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
