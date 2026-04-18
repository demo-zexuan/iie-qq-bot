"""
supervisor 插件配置管理

通过 .env 环境变量控制滚动窗口时长、阈值、白名单群与黑名单用户。

@module plugins.supervisor.config
@author GitHub Copilot
@created 2026-04-18
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _parse_bool(raw: str, default: bool = False) -> bool:
    """解析布尔环境变量。"""
    normalized = raw.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _parse_id_list(raw: str, env_name: str) -> list[int]:
    """解析逗号分隔的数字 ID 列表。"""
    result: list[int] = []
    if not raw.strip():
        return result

    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"{env_name} 包含非法 ID: {value}")
        result.append(int(value))
    return result


def _parse_positive_int(raw: str, env_name: str, default: int) -> int:
    """解析正整数。"""
    value = raw.strip()
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{env_name} 必须为正整数，当前值: {parsed}")
    return parsed


def _parse_timezone(raw: str) -> ZoneInfo:
    """解析时区名称。"""
    value = raw.strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"SUPERVISOR_TIMEZONE 非法: {value}") from exc


@dataclass(slots=True)
class SupervisorConfig:
    """监工插件运行时配置。"""

    enabled: bool
    group_whitelist: list[int]
    user_blacklist: set[int]
    message_threshold: int
    window_minutes: int
    timezone: ZoneInfo
    remind_template: str


def load_config() -> SupervisorConfig:
    """从环境变量加载配置。"""
    return SupervisorConfig(
        enabled=_parse_bool(os.getenv("SUPERVISOR_ENABLED", "false")),
        group_whitelist=_parse_id_list(
            os.getenv("SUPERVISOR_GROUP_WHITELIST", ""),
            env_name="SUPERVISOR_GROUP_WHITELIST",
        ),
        user_blacklist=set(
            _parse_id_list(
                os.getenv("SUPERVISOR_USER_BLACKLIST", ""),
                env_name="SUPERVISOR_USER_BLACKLIST",
            )
        ),
        message_threshold=_parse_positive_int(
            os.getenv("SUPERVISOR_MESSAGE_THRESHOLD", "20"),
            env_name="SUPERVISOR_MESSAGE_THRESHOLD",
            default=20,
        ),
        window_minutes=_parse_positive_int(
            os.getenv("SUPERVISOR_WINDOW_MINUTES", "60"),
            env_name="SUPERVISOR_WINDOW_MINUTES",
            default=60,
        ),
        timezone=_parse_timezone(os.getenv("SUPERVISOR_TIMEZONE", "Asia/Shanghai")),
        remind_template=os.getenv(
            "SUPERVISOR_REMIND_TEMPLATE",
            "你在最近 {window_minutes} 分钟内已发送 {count} 条消息，达到阈值 {threshold} 条，请注意节奏。",
        ),
    )
