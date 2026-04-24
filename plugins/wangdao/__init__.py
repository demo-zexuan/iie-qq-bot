"""
wangdao 插件

监听群消息中的关键词，命中后引用消息并 @ 发送者，随机发送 wangdao 目录下图片。
支持按群滚动窗口限流，避免刷屏。

@module plugins.wangdao
@author GitHub Copilot
@created 2026-04-24
"""
from __future__ import annotations

import base64
import random
from collections import defaultdict, deque
from pathlib import Path
from time import time

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.plugin import PluginMetadata

from .config import WangdaoConfig, load_config

__plugin_meta__ = PluginMetadata(
    name="wangdao",
    description="命中王道关键词后随机回复图片并 @ 用户，支持按群限流",
    usage="配置 WANGDAO_* 环境变量后自动生效",
)

wangdao_config: WangdaoConfig = load_config()
wangdao_matcher = on_message(priority=36, block=False)
_group_trigger_timestamps: dict[int, deque[float]] = defaultdict(deque)
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _normalize(text: str) -> str:
    """按配置归一化文本，用于关键词匹配。"""
    if wangdao_config.case_sensitive:
        return text
    return text.lower()


def _is_enabled_group(group_id: int) -> bool:
    """判断当前群是否启用插件。"""
    if not wangdao_config.group_whitelist:
        return True
    return group_id in wangdao_config.group_whitelist


def _match_keyword(plain_text: str) -> str | None:
    """返回命中的第一个关键词。"""
    target = _normalize(plain_text)
    for keyword in wangdao_config.keywords:
        normalized_keyword = _normalize(keyword)
        if normalized_keyword and normalized_keyword in target:
            return keyword
    return None


def _resolve_limit(group_id: int) -> tuple[int, int]:
    """获取群级限流配置，未覆盖则使用全局配置。"""
    return wangdao_config.rate_limit_by_group.get(
        group_id,
        (wangdao_config.max_triggers_per_window, wangdao_config.window_seconds),
    )


def _can_send(group_id: int) -> bool:
    """按群滑动时间窗口限流。"""
    max_count, window_seconds = _resolve_limit(group_id)
    if max_count == 0:
        return True

    now = time()
    timestamps = _group_trigger_timestamps[group_id]

    while timestamps and now - timestamps[0] >= window_seconds:
        timestamps.popleft()

    if len(timestamps) >= max_count:
        return False

    timestamps.append(now)
    return True


def _resolve_image_dir() -> Path:
    """解析图片目录，支持绝对路径或相对项目根目录。"""
    configured = Path(wangdao_config.image_dir)
    if configured.is_absolute():
        return configured

    project_root = Path(__file__).resolve().parents[2]
    return (project_root / configured).resolve()


def _list_candidate_images() -> list[Path]:
    """列出可发送图片。"""
    image_dir = _resolve_image_dir()
    if not image_dir.exists() or not image_dir.is_dir():
        logger.warning("wangdao: image dir not found or not dir: {}", image_dir)
        return []

    return [
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    ]


def _build_message(event: GroupMessageEvent, user_id: int, image_path: Path) -> Message:
    """构建引用+@+图片消息。"""
    message_id = str(getattr(event, "message_id", "")).strip()
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")

    message = Message()
    if message_id:
        message.append(MessageSegment.reply(message_id))
    message.append(MessageSegment.at(user_id))
    message.append(MessageSegment.text(" 王道！"))
    message.append(MessageSegment.text("\n"))
    message.append(MessageSegment.image(file=f"base64://{image_base64}"))
    return message


@wangdao_matcher.handle()
async def _handle_wangdao(bot: Bot, event: GroupMessageEvent) -> None:
    """检测关键词并随机发送王道图片。"""
    if not wangdao_config.enabled:
        return

    group_id = int(event.group_id)
    if not _is_enabled_group(group_id):
        return

    user_id = int(event.user_id)
    if user_id == int(bot.self_id):
        return

    plain_text = (event.get_plaintext() or "").strip()
    if not plain_text:
        return

    matched_keyword = _match_keyword(plain_text)
    if matched_keyword is None:
        return

    if not _can_send(group_id):
        max_count, window_seconds = _resolve_limit(group_id)
        logger.info(
            "wangdao: group_id={} rate_limited=true max_count={} window_seconds={}",
            group_id,
            max_count,
            window_seconds,
        )
        return

    candidates = _list_candidate_images()
    if not candidates:
        logger.warning("wangdao: no image files available, skip reply")
        return

    image_path = random.choice(candidates)
    logger.info(
        "wangdao: group_id={} user_id={} keyword={} image={}",
        group_id,
        user_id,
        matched_keyword,
        image_path.name,
    )

    try:
        message = _build_message(event, user_id, image_path)
        await bot.send_group_msg(group_id=group_id, message=message)
    except ActionFailed as exc:
        logger.warning("wangdao: send image failed: {}", exc)
    except Exception as exc:
        logger.warning("wangdao: build/send message failed: {}", exc)
