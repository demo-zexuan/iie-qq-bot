"""
group_stats 数据库 ORM 模型定义

使用 SQLAlchemy 2.x Mapped + mapped_column 声明式风格，定义群成员统计表结构。

表设计要点：
  I.  唯一约束 (group_id, stat_date)：同一群同一天只存一条记录。
      结合写入层的 ON CONFLICT ... DO UPDATE 实现覆盖更新语义（当天保留最新值）。
  II. stat_date 存储天粒度日期，stat_time 存储秒粒度实际执行时刻，
      并同时维护 created_at（首次写入）和 updated_at（每次覆盖时刷新）两个时间戳。

@module plugins.group_stats.models
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的元数据基类，供 SQLAlchemy 扫描并自动注册表结构"""
    pass


class GroupMemberStat(Base):
    """
    群成员人数统计记录

    每日每群写入一条记录，同日重复统计时通过 UPSERT 覆盖当条数据。
    查询历史趋势时按 stat_date 范围筛选，按 group_id 分组聚合即可。
    """

    __tablename__ = "group_member_stats"
    __table_args__ = (
        # 唯一约束：同一群同一天只允许存在一条记录
        # 写入时使用 ON CONFLICT (uq_group_stat_date) DO UPDATE 实现覆盖更新
        UniqueConstraint("group_id", "stat_date", name="uq_group_stat_date"),
    )

    # 自增主键，仅作内部标识，业务查询优先使用 group_id + stat_date 组合
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # QQ 群号，使用 BigInteger 与 QQ 号数值范围保持一致
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # 群名称，冗余存储便于直接读取，避免统计查询时回调 QQ API
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 统计时刻的群成员总数（含群主、管理员、普通成员）
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 统计日期（天粒度），构成唯一键的一部分，用于控制每日只保留一条
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 实际执行统计的精确时刻（带时区），秒级精度，UPSERT 时同步更新
    stat_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 该条记录首次插入的时间，UPSERT 时不覆盖此字段，保留初始写入时刻
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 该条记录最后一次被覆盖更新的时间，每次 UPSERT 均刷新
class Base(DeclarativeBase):
    """所有 ORM 模型的元数据基类，供 SQLAlchemy 扫描并自动注册表结构"""
    pass


class GroupMemberStat(Base):
    """
    群成员人数统计记录

    每日每群写入一条记录，同日重复统计时通过 UPSERT 覆盖当条数据。
    查询历史趋势时按 stat_date 范围筛选，按 group_id 分组聚合即可。
    """

    __tablename__ = "group_member_stats"
    __table_args__ = (
        # 唯一约束：同一群同一天只允许存在一条记录
        # 写入时使用 ON CONFLICT (uq_group_stat_date) DO UPDATE 实现覆盖更新
        UniqueConstraint("group_id", "stat_date", name="uq_group_stat_date"),
    )

    # 自增主键，仅作内部标识，业务查询优先使用 group_id + stat_date 组合
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # QQ 群号，使用 BigInteger 与 QQ 号数值范围保持一致
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # 群名称，冗余存储便于直接读取，避免统计查询时回调 QQ API
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 统计时刻的群成员总数（含群主、管理员、普通成员）
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 统计日期（天粒度），构成唯一键的一部分，用于控制每日只保留一条
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 实际执行统计的精确时刻（带时区），秒级精度，UPSERT 时同步更新
    stat_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 该条记录首次插入的时间，UPSERT 时不覆盖此字段，保留初始写入时刻
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 该条记录最后一次被覆盖更新的时间，每次 UPSERT 均刷新
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
