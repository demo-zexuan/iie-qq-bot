"""
group_guard 插件

监听指定群的每一条消息，命中配置关键词后直接发送提示语，
不追加 @ 用户。

@module plugins.group_guard
@author GitHub Copilot
@created 2026-04-16
"""
from __future__ import annotations

from collections import defaultdict, deque
from time import time

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.plugin import PluginMetadata

from .config import GroupGuardConfig, load_config

__plugin_meta__ = PluginMetadata(
    name="group_guard",
    description="在指定群检测引流关键词并直接发送提示语",
    usage="配置 GROUP_GUARD_* 环境变量后自动生效",
)

group_guard_config: GroupGuardConfig = load_config()
group_guard_matcher = on_message(priority=30, block=False)
_group_reply_timestamps: dict[int, deque[float]] = defaultdict(deque)


def _normalize_keyword(keyword: str) -> str:
    """根据配置归一化关键词，用于映射匹配。"""
    if group_guard_config.case_sensitive:
        return keyword
    return keyword.lower()


_keyword_reply_lookup: dict[str, str] = {
    _normalize_keyword(keyword): reply
    for keyword, reply in group_guard_config.keyword_replies.items()
}


def _normalize_text(text: str) -> str:
    """根据配置决定是否统一大小写。"""
    if group_guard_config.case_sensitive:
        return text
    return text.lower()


def _find_matched_keyword(text: str) -> str | None:
    """返回命中的第一个关键词。"""
    normalized_text = _normalize_text(text)
    for keyword in group_guard_config.keywords:
        normalized_keyword = _normalize_keyword(keyword)
        if normalized_keyword and normalized_keyword in normalized_text:
            return keyword
    return None


def _resolve_reply_text(matched_keyword: str) -> str:
    """优先使用关键词专属文案，未命中时回退默认文案。"""
    return _keyword_reply_lookup.get(
        _normalize_keyword(matched_keyword),
        group_guard_config.reply_text,
    )


def _resolve_group_rate_limit(group_id: int) -> int:
    """获取群级别限流配置，未覆盖时使用全局配置。"""
    return group_guard_config.max_replies_per_minute_by_group.get(
        group_id,
        group_guard_config.max_replies_per_minute,
    )


def _can_send_reply(group_id: int) -> bool:
    """按群限制每分钟内的自动回复次数。"""
    max_replies = _resolve_group_rate_limit(group_id)
    if max_replies == 0:
        return True

    now = time()
    timestamps = _group_reply_timestamps[group_id]

    while timestamps and now - timestamps[0] >= 60:
        timestamps.popleft()

    if len(timestamps) >= max_replies:
        return False

    timestamps.append(now)
    return True


@group_guard_matcher.handle()
async def _handle_group_guard(bot: Bot, event: GroupMessageEvent) -> None:
    """检测群消息中的引流关键词并发送提示语。"""
    if not group_guard_config.enabled:
        return

    group_id = int(event.group_id)
    if group_id not in group_guard_config.group_ids:
        return

    if int(event.user_id) == int(bot.self_id):
        return

    plain_text = (event.get_plaintext() or "").strip()
    if not plain_text:
        return

    matched_keyword = _find_matched_keyword(plain_text)
    if matched_keyword is None:
        return

    if not _can_send_reply(group_id):
        logger.info(
            "group_guard: group_id={} rate_limited=true max_replies_per_minute={}",
            group_id,
            _resolve_group_rate_limit(group_id),
        )
        return

    reply_text = _resolve_reply_text(matched_keyword)
    logger.info(
        "group_guard: group_id={} user_id={} matched_keyword={} custom_reply={}",
        group_id,
        event.user_id,
        matched_keyword,
        reply_text != group_guard_config.reply_text,
    )
    await bot.send_group_msg(group_id=group_id, message=reply_text)