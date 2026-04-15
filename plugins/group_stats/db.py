"""
group_stats 数据库初始化与会话管理

提供异步引擎、会话工厂的构建，以及应用启动时的自动建表逻辑。
使用 SQLAlchemy 2.x 异步接口（async engine + async session），底层驱动为 asyncpg。

注意：此模块只负责基础设施构建，不直接执行业务查询，业务逻辑由 service.py 承载。

@module plugins.group_stats.db
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import GroupStatsConfig
from .models import Base


def create_engine(config: GroupStatsConfig) -> AsyncEngine:
    """
    根据配置创建 SQLAlchemy 异步引擎

    连接池参数说明：
    1. pool_pre_ping  每次取出连接前发送 SELECT 1 探活，防止长时间闲置后连接失效
    2. pool_size      连接池维持的常驻连接数，适配小规模定时任务场景
    3. max_overflow   超出 pool_size 后允许额外建立的连接数上限，应对突发并发

    @param config - 已加载的运行时配置
    @returns 配置好连接池的异步数据库引擎实例
    """
    return create_async_engine(
        config.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """
    创建异步 Session 工厂

    expire_on_commit=False：Session 提交后不自动标记 ORM 对象属性为过期。
    在异步上下文中，提交后的懒加载（lazy load）会触发 DetachedInstanceError，
    因此关闭自动过期避免此类问题，由调用方显式决定是否刷新数据。

    @param engine - 已初始化的异步引擎
    @returns async_sessionmaker 实例，每次调用（即 async with）产生一个新 AsyncSession
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_database(engine: AsyncEngine) -> None:
    """
    应用启动时自动建表（DDL）

    扫描所有注册到 Base 的 ORM 模型，对不存在的表执行 CREATE TABLE IF NOT EXISTS，
    已存在的表结构不会被修改（非迁移工具，仅适用于新建场景）。

    注意：这是 MVP 快速建表方案。如后续需要字段变更，建议引入 Alembic 管理 schema 版本。

    @param engine - 已初始化的异步引擎
    """
    async with engine.begin() as conn:
        # run_sync 将同步的 create_all 包装进异步事务上下文执行
        await conn.run_sync(Base.metadata.create_all)
