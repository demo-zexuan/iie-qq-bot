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
    1. group_ids                     待统计群号列表
    2. daily_time                    每日群人数/活跃度播报时间（HH:MM）
    3. timezone                      时区名称（如 Asia/Shanghai）
    4. api_timeout                   调用 NapCat API 的超时秒数（预留）
    5. message_flush_interval_seconds 消息统计缓存刷盘周期（秒）
    6. archive_time                  每日归档执行时间（HH:MM）
    7. archive_retention_days        明细数据保留天数
    """

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    group_ids: list[int]
    daily_time: str
    timezone: str
    api_timeout: float
    message_flush_interval_seconds: int
    archive_time: str
    archive_retention_days: int

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


def _parse_group_ids(raw: str) -> list[int]:
    """
    解析逗号分隔的群号字符串为整数列表

    I.  处理空值，直接返回空列表
    II. 按逗号分割后逐项校验：
        (1) 过滤分割产生的空字符串
        (2) 非纯数字项立即抛出 ValueError
        (3) 合法项转为 int 追加到结果列表

    @param raw - 原始字符串，如 "123456,234567"
    @returns 解析出的群号整数列表，输入为空时返回 []
    @raises ValueError 若存在非法群号（含非数字字符）
    """
    result: list[int] = []
    if not raw.strip():
        return result

    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"GROUP_STATS_GROUP_IDS 包含非法群号: {value}")
        result.append(int(value))
    return result


def _parse_positive_int(raw: str, default: int, env_name: str) -> int:
    """解析正整数环境变量，非法值回退默认并抛错提示调用方修复配置。"""
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{env_name} 必须为正整数，当前值: {value}")
    return value


def load_config() -> GroupStatsConfig:
    """
    从环境变量加载并返回 GroupStatsConfig 实例

    读取优先级：运行时环境变量 > NoneBot 已加载的 .env 文件默认值。

    @returns 填充完毕的 GroupStatsConfig 实例
    """
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
        message_flush_interval_seconds=_parse_positive_int(
            os.getenv("GROUP_STATS_MESSAGE_FLUSH_INTERVAL_SECONDS", "60"),
            default=60,
            env_name="GROUP_STATS_MESSAGE_FLUSH_INTERVAL_SECONDS",
        ),
        archive_time=os.getenv("GROUP_STATS_ARCHIVE_TIME", "03:30"),
        archive_retention_days=_parse_positive_int(
            os.getenv("GROUP_STATS_ARCHIVE_RETENTION_DAYS", "30"),
            default=30,
            env_name="GROUP_STATS_ARCHIVE_RETENTION_DAYS",
        ),
    )
