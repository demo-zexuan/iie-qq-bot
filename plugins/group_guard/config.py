"""
group_guard 插件配置管理

通过环境变量控制群引流检测行为。默认仅在显式配置群号后启用，
避免误伤其他群聊。

@module plugins.group_guard.config
@author GitHub Copilot
@created 2026-04-16
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_group_ids(raw: str) -> list[int]:
    """解析逗号分隔的群号列表。"""
    result: list[int] = []
    if not raw.strip():
        return result

    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"GROUP_GUARD_GROUP_IDS 包含非法群号: {value}")
        result.append(int(value))
    return result


def _parse_keywords(raw: str) -> list[str]:
    """解析逗号分隔的关键词列表。"""
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_bool(raw: str, default: bool = False) -> bool:
    """解析布尔环境变量。"""
    normalized = raw.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _parse_positive_int(raw: str, default: int) -> int:
    """解析正整数环境变量。"""
    value = raw.strip()
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("GROUP_GUARD_MAX_REPLIES_PER_MINUTE 必须大于 0")
    return parsed


@dataclass(slots=True)
class GroupGuardConfig:
    """群引流检测插件运行时配置。"""

    enabled: bool
    group_ids: list[int]
    keywords: list[str]
    reply_text: str
    case_sensitive: bool
    max_replies_per_minute: int


def load_config() -> GroupGuardConfig:
    """从环境变量加载插件配置。"""
    keywords = _parse_keywords(
        os.getenv(
            "GROUP_GUARD_KEYWORDS",
            "引流,加群,vx,微信,私聊我,私信我,兼职,推广,代理",
        )
    )
    return GroupGuardConfig(
        enabled=_parse_bool(os.getenv("GROUP_GUARD_ENABLED", "false")),
        group_ids=_parse_group_ids(os.getenv("GROUP_GUARD_GROUP_IDS", "")),
        keywords=keywords,
        reply_text=os.getenv("GROUP_GUARD_REPLY_TEXT", "这个群禁止引流行为"),
        case_sensitive=_parse_bool(os.getenv("GROUP_GUARD_CASE_SENSITIVE", "false")),
        max_replies_per_minute=_parse_positive_int(
            os.getenv("GROUP_GUARD_MAX_REPLIES_PER_MINUTE", "3"),
            default=3,
        ),
    )