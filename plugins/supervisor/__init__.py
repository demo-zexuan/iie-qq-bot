"""
supervisor 插件

在滚动时间窗口内统计白名单群成员发言数量，达到阈值后自动 @ 提醒。
支持群白名单、用户黑名单与提醒文案模板配置。

@module plugins.supervisor
@author GitHub Copilot
@created 2026-04-18
"""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.plugin import PluginMetadata

from .config import SupervisorConfig, load_config

__plugin_meta__ = PluginMetadata(
    name="supervisor",
    description="监控指定群成员在滚动时间窗口内的发言数量并触发 @ 提醒",
    usage="配置 SUPERVISOR_* 环境变量后自动生效",
)

supervisor_config: SupervisorConfig = load_config()
supervisor_matcher = on_message(priority=35, block=False)

# key: (group_id, user_id) -> timestamps within recent window
_message_timestamps: dict[tuple[int, int], deque[datetime]] = {}
# key: (group_id, user_id) -> whether the latest state is already reminded
_reminded_state: dict[tuple[int, int], bool] = {}
_WARN_IMAGE_PATHS = [
    Path(__file__).with_name("warn_img.png"),
    Path(__file__).with_name("warn_img2.jpg"),
]


def _render_remind_text(group_id: int, user_id: int, count: int) -> str:
    """渲染提醒文案，支持固定占位符。"""
    template = supervisor_config.remind_template
    payload = {
        "group_id": group_id,
        "user_id": user_id,
        "count": count,
        "threshold": supervisor_config.message_threshold,
        "window_minutes": supervisor_config.window_minutes,
    }

    try:
        return template.format(**payload)
    except Exception:
        logger.warning(
            "supervisor: remind_template format failed, fallback to raw template"
        )
        return template


def _current_count_in_window(key: tuple[int, int], now: datetime) -> int:
    """更新并返回用户在滚动窗口内的消息数。"""
    bucket = _message_timestamps.get(key)
    if bucket is None:
        bucket = deque()
        _message_timestamps[key] = bucket

    bucket.append(now)
    threshold_time = now - timedelta(minutes=supervisor_config.window_minutes)
    while bucket and bucket[0] < threshold_time:
        bucket.popleft()

    return len(bucket)


def _build_warn_segments() -> list[MessageSegment]:
    """构建预警图片消息段，图片不存在或读取失败时跳过。"""
    segments: list[MessageSegment] = []

    for path in _WARN_IMAGE_PATHS:
        if not path.exists():
            logger.warning("supervisor: warn image not found: {}", path)
            continue

        try:
            image_bytes = path.read_bytes()
        except Exception as exc:
            logger.warning("supervisor: read warn image failed: {}", exc)
            continue

        # 使用 base64:// 避免 OneBot 侧无法访问当前进程本地路径。
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        segments.append(MessageSegment.image(file=f"base64://{image_base64}"))

    return segments


@supervisor_matcher.handle()
async def _handle_supervisor(bot: Bot, event: GroupMessageEvent) -> None:
    """统计消息并在达到阈值后提醒。"""
    if not supervisor_config.enabled:
        return

    group_id = int(event.group_id)
    if group_id not in supervisor_config.group_whitelist:
        return

    user_id = int(event.user_id)
    if user_id == int(bot.self_id):
        return
    if user_id in supervisor_config.user_blacklist:
        return

    if not (event.get_plaintext() or "").strip():
        return

    now = datetime.now(supervisor_config.timezone)
    key = (group_id, user_id)
    current_count = _current_count_in_window(key, now)

    if current_count < supervisor_config.message_threshold:
        if _reminded_state.get(key):
            _reminded_state[key] = False
        return

    if _reminded_state.get(key, False):
        return

    _reminded_state[key] = True

    remind_text = _render_remind_text(group_id, user_id, current_count)
    message = Message(MessageSegment.at(user_id) + MessageSegment.text(f" {remind_text}"))
    for segment in _build_warn_segments():
        message.append(MessageSegment.text("\n"))
        message.append(segment)

    logger.info(
        "supervisor: group_id={} user_id={} count={} threshold={} window_minutes={}",
        group_id,
        user_id,
        current_count,
        supervisor_config.message_threshold,
        supervisor_config.window_minutes,
    )
    try:
        await bot.send_group_msg(group_id=group_id, message=message)
    except ActionFailed as exc:
        logger.warning("supervisor: send merged warn message failed: {}", exc)
