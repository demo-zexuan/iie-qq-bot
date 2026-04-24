"""
wangdao 插件配置管理

通过环境变量控制关键词匹配、图片目录与按群限流策略。

@module plugins.wangdao.config
@author GitHub Copilot
@created 2026-04-24
"""
from __future__ import annotations

import os
from dataclasses import dataclass


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


def _parse_keywords(raw: str) -> list[str]:
    """解析逗号分隔关键词。"""
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_positive_int(raw: str, env_name: str, default: int) -> int:
    """解析正整数环境变量。"""
    value = raw.strip()
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{env_name} 必须为正整数，当前值: {parsed}")
    return parsed


def _parse_non_negative_int(raw: str, env_name: str, default: int) -> int:
    """解析非负整数环境变量。"""
    value = raw.strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{env_name} 必须为非负整数，当前值: {parsed}")
    return parsed


def _parse_group_rate_limit(raw: str) -> dict[int, tuple[int, int]]:
    """解析按群覆盖的限流规则。

    格式: group_id:max_count:window_seconds,group_id2:max_count:window_seconds
    max_count 支持 0（表示该群不限流）。
    """
    result: dict[int, tuple[int, int]] = {}
    if not raw.strip():
        return result

    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue

        parts = [part.strip() for part in text.split(":")]
        if len(parts) != 3:
            raise ValueError(
                "WANGDAO_RATE_LIMIT_BY_GROUP 格式错误，示例: 123456:1:300,234567:3:60"
            )

        group_id_text, max_count_text, window_seconds_text = parts
        if not group_id_text.isdigit():
            raise ValueError(f"WANGDAO_RATE_LIMIT_BY_GROUP 包含非法群号: {group_id_text}")

        max_count = _parse_non_negative_int(
            max_count_text,
            env_name="WANGDAO_RATE_LIMIT_BY_GROUP.max_count",
            default=0,
        )
        window_seconds = _parse_positive_int(
            window_seconds_text,
            env_name="WANGDAO_RATE_LIMIT_BY_GROUP.window_seconds",
            default=300,
        )

        result[int(group_id_text)] = (max_count, window_seconds)

    return result


@dataclass(slots=True)
class WangdaoConfig:
    """王道关键词图片插件运行时配置。"""

    enabled: bool
    group_whitelist: list[int]
    keywords: list[str]
    case_sensitive: bool
    image_dir: str
    max_triggers_per_window: int
    window_seconds: int
    rate_limit_by_group: dict[int, tuple[int, int]]


def load_config() -> WangdaoConfig:
    """从环境变量加载 wangdao 插件配置。"""
    return WangdaoConfig(
        enabled=_parse_bool(os.getenv("WANGDAO_ENABLED", "false")),
        group_whitelist=_parse_id_list(
            os.getenv("WANGDAO_GROUP_WHITELIST", ""),
            env_name="WANGDAO_GROUP_WHITELIST",
        ),
        keywords=_parse_keywords(os.getenv("WANGDAO_KEYWORDS", "王道")),
        case_sensitive=_parse_bool(os.getenv("WANGDAO_CASE_SENSITIVE", "false")),
        image_dir=os.getenv("WANGDAO_IMAGE_DIR", "wangdao").strip() or "wangdao",
        max_triggers_per_window=_parse_non_negative_int(
            os.getenv("WANGDAO_MAX_TRIGGERS_PER_WINDOW", "1"),
            env_name="WANGDAO_MAX_TRIGGERS_PER_WINDOW",
            default=1,
        ),
        window_seconds=_parse_positive_int(
            os.getenv("WANGDAO_WINDOW_SECONDS", "300"),
            env_name="WANGDAO_WINDOW_SECONDS",
            default=300,
        ),
        rate_limit_by_group=_parse_group_rate_limit(
            os.getenv("WANGDAO_RATE_LIMIT_BY_GROUP", "")
        ),
    )
