"""
group_stats 插件配置管理

从环境变量读取并构造运行时配置对象。读取优先级：
  I.  运行时注入的环境变量（Docker Compose environment 字段）
  II. NoneBot 初始化时自动加载的 .env 文件

所有配置项均提供默认值，方便本地开发快速启动无需额外配置。

@module plugins.group_stats.config
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
import os
from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class GroupStatsConfig:
    """
    群统计任务运行时配置（不可变值对象）

    I. 数据库连接参数
    1. pg_host      PostgreSQL 主机地址
    2. pg_port      PostgreSQL 端口
    3. pg_database  数据库名
    4. pg_user      登录用户名
    5. pg_password  登录密码

    II. 统计任务参数
    1. group_ids    待统计群号列表（由 GROUP_STATS_GROUP_IDS 逗号分隔解析而来）
    2. daily_time   每日执行时间，格式 HH:MM（如 "08:00"）
    3. timezone     cron 时区名称（如 "Asia/Shanghai"）
    4. api_timeout  调用 NapCat API 的超时秒数（当前为预留参数）
    """

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    group_ids: List[int]
    daily_time: str
    timezone: str
    api_timeout: float

    @property
    def database_url(self) -> str:
        """
        生成 SQLAlchemy asyncpg 异步连接字符串

        @returns postgresql+asyncpg 格式的连接 URL，供 create_async_engine 使用
        """
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )


def _parse_group_ids(raw: str) -> List[int]:
    """
    解析逗号分隔的群号字符串为整数列表

    I.  处理空值，直接返回空列表
    II. 按逗号分割后逐项校验：
        1. 过滤分割产生的空字符串（如末尾多余逗号）
        2. 非纯数字项立即抛出 ValueError，通知调用方配置有误
        3. 合法项转为 int 追加到结果列表

    @param raw - 原始字符串，如 "123456,234567"
    @returns 解析出的群号整数列表，输入为空时返回 []
    @raises ValueError 若存在非法群号（含非数字字符）
    """
    result: List[int] = []
    # I. 空输入快速返回，避免后续无效分割
    if not raw.strip():
        return result

    for item in raw.split(","):
        value = item.strip()
        # (1) 跳过分割后产生的空字符串（如 "123,,456" 中的双逗号情况）
        if not value:
            continue
        # (2) 群号必须为纯数字，否则立即中断并指出错误位置
        if not value.isdigit():
            raise ValueError(f"GROUP_STATS_GROUP_IDS 包含非法群号: {value}")
        result.append(int(value))
    return result


def load_config() -> GroupStatsConfig:
    """
    从环境变量加载并返回 GroupStatsConfig 实例

    读取优先级：运行时环境变量 > NoneBot 已加载的 .env 文件默认值。
    在 Docker Compose 场景中，可通过容器 environment 字段覆盖 .env 中的值。

    @returns 填充完毕的 GroupStatsConfig 实例
    """
    pg_password: str
    group_ids: List[int]
    daily_time: str
    timezone: str
    api_timeout: float

    @property
    def database_url(self) -> str:
        """
        生成 SQLAlchemy asyncpg 异步连接字符串

        @returns postgresql+asyncpg 格式的连接 URL，供 create_async_engine 使用
        """
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )


def _parse_group_ids(raw: str) -> List[int]:
    """
    解析逗号分隔的群号字符串为整数列表

    I.  处理空值，直接返回空列表
    II. 按逗号分割后逐项校验：
        1. 过滤分割产生的空字符串（如末尾多余逗号）
        2. 非纯数字项立即抛出 ValueError，通知调用方配置有误
        3. 合法项转为 int 追加到结果列表

    @param raw - 原始字符串，如 "123456,234567"
    @returns 解析出的群号整数列表，输入为空时返回 []
    @raises ValueError 若存在非法群号（含非数字字符）
    """
    result: List[int] = []
    # I. 空输入快速返回，避免后续无效分割
    if not raw.strip():
        return result

    for item in raw.split(","):
        value = item.strip()
        # (1) 跳过分割后产生的空字符串（如 "123,,456" 中的双逗号情况）
        if not value:
            continue
        # (2) 群号必须为纯数字，否则立即中断并指出错误位置
        if not value.isdigit():
            raise ValueError(f"GROUP_STATS_GROUP_IDS 包含非法群号: {value}")
        result.append(int(value))
    return result


def load_config() -> GroupStatsConfig:
    """
    从环境变量加载并返回 GroupStatsConfig 实例

    读取优先级：运行时环境变量 > NoneBot 已加载的 .env 文件默认值。
    在 Docker Compose 场景中，可通过容器 environment 字段覆盖 .env 中的值。

    @returns 填充完毕的 GroupStatsConfig 实例
    """
    # 环境变量优先，.env 作为兜底（NoneBot 启动时会加载 .env）
    return GroupStatsConfig(
        pg_host=os.getenv("PG_HOST", "127.0.0.1"),
        pg_port=int(os.getenv("PG_PORT", "5432")),
        pg_database=os.getenv("PG_DATABASE", "iie_qq_bot"),
        pg_user=os.getenv("PG_USER", "postgres"),
        pg_password=os.getenv("PG_PASSWORD", "postgres"),
        group_ids=_parse_group_ids(os.getenv("GROUP_STATS_GROUP_IDS", "")),
        daily_time=os.getenv("GROUP_STATS_DAILY_TIME", "08:00"),
        timezone=os.getenv("GROUP_STATS_TIMEZONE", "Asia/Shanghai"),
        api_timeout=float(os.getenv("GROUP_STATS_API_TIMEOUT", "10")),
    )
