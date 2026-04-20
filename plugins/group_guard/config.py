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


def _parse_keyword_replies(raw: str) -> dict[str, str]:
    """解析关键词到回复文案映射。

    格式: keyword=>reply;;keyword2=>reply2
    """
    result: dict[str, str] = {}
    if not raw.strip():
        return result

    for item in raw.split(";;"):
        pair = item.strip()
        if not pair:
            continue
        if "=>" not in pair:
            raise ValueError(
                "GROUP_GUARD_KEYWORD_REPLIES 格式错误，示例: 抄=>文案A;;引=>文案B"
            )
        key, value = pair.split("=>", 1)
        keyword = key.strip()
        reply = value.strip()
        if not keyword:
            raise ValueError("GROUP_GUARD_KEYWORD_REPLIES 存在空关键词")
        if not reply:
            raise ValueError(f"GROUP_GUARD_KEYWORD_REPLIES 关键词 {keyword} 的文案为空")
        result[keyword] = reply

    return result


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


def _parse_non_negative_int(raw: str, env_name: str, default: int) -> int:
    """解析非负整数环境变量。"""
    value = raw.strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{env_name} 必须大于等于 0")
    return parsed


def _parse_group_rate_limit_map(raw: str) -> dict[int, int]:
    """解析按群覆盖的每分钟限流。

    格式: group_id:count,group_id2:count2
    count 支持 0（表示该群不限流）。
    """
    result: dict[int, int] = {}
    if not raw.strip():
        return result

    for item in raw.split(","):
        pair = item.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(
                "GROUP_GUARD_MAX_REPLIES_PER_MINUTE_BY_GROUP 格式错误，示例: 123456:1,234567:3"
            )

        group_raw, count_raw = pair.split(":", 1)
        group_text = group_raw.strip()
        count_text = count_raw.strip()

        if not group_text.isdigit():
            raise ValueError(
                f"GROUP_GUARD_MAX_REPLIES_PER_MINUTE_BY_GROUP 包含非法群号: {group_text}"
            )

        count = _parse_non_negative_int(
            count_text,
            env_name="GROUP_GUARD_MAX_REPLIES_PER_MINUTE_BY_GROUP",
            default=0,
        )
        result[int(group_text)] = count

    return result


@dataclass(slots=True)
class GroupGuardConfig:
    """群引流检测插件运行时配置。"""

    enabled: bool
    group_ids: list[int]
    keywords: list[str]
    keyword_replies: dict[str, str]
    reply_text: str
    case_sensitive: bool
    max_replies_per_minute: int
    max_replies_per_minute_by_group: dict[int, int]


def load_config() -> GroupGuardConfig:
    """从环境变量加载插件配置。"""
    keywords = _parse_keywords(
        os.getenv(
            "GROUP_GUARD_KEYWORDS",
            "引流,加群,vx,微信,私聊我,私信我,兼职,推广,代理,抄",
        )
    )
    return GroupGuardConfig(
        enabled=_parse_bool(os.getenv("GROUP_GUARD_ENABLED", "false")),
        group_ids=_parse_group_ids(os.getenv("GROUP_GUARD_GROUP_IDS", "")),
        keywords=keywords,
        keyword_replies=_parse_keyword_replies(
            os.getenv(
                "GROUP_GUARD_KEYWORD_REPLIES",
                "抄=>不如抄底软微，一年冷一年热，27的机会来了",
            )
        ),
        reply_text=os.getenv("GROUP_GUARD_REPLY_TEXT", "这个群禁止引流行为"),
        case_sensitive=_parse_bool(os.getenv("GROUP_GUARD_CASE_SENSITIVE", "false")),
        max_replies_per_minute=_parse_non_negative_int(
            os.getenv("GROUP_GUARD_MAX_REPLIES_PER_MINUTE", "3"),
            env_name="GROUP_GUARD_MAX_REPLIES_PER_MINUTE",
            default=3,
        ),
        max_replies_per_minute_by_group=_parse_group_rate_limit_map(
            os.getenv("GROUP_GUARD_MAX_REPLIES_PER_MINUTE_BY_GROUP", "")
        ),
    )