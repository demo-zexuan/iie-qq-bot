"""
kun_response 插件

当机器人在群中被 @ 且消息未被任何更高优先级的处理器（如 /统计人数 指令）匹配时，
随机从 kun/ 目录中选取一个音频文件，以语音消息的形式回复到群中。

音频格式说明：
  I.  kun/amr/ 目录（优先）
      由 scripts/convert_kun_audio.py 预转换生成：
      AMR-NB，8000 Hz，单声道。
      该格式更接近 QQ 语音链路，可减少 NapCat 发送 record 时
      出现“语音转换失败”的概率。

  II. kun/converted/ 目录（次优先）
      保留旧版预转换 WAV：16-bit PCM WAV，16000 Hz，单声道。
      若 amr/ 不存在或为空，则回退使用。

  III. kun/（最终回退）
      若预转换目录均不存在或为空，则直接使用原始 .mp3 / .wav 文件。

优先级说明：
  本插件 priority=20，group_stats 手动指令 priority=10。
  NoneBot2 优先级数字越小越先匹配，且 block=True 的处理器匹配后不再
  向下传递。因此，当 @机器人 + /统计人数 时，本处理器不会触发；
  当 @机器人 + 任意其他内容（或空内容）时，本处理器触发。

@module plugins.kun_response
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
import random
from pathlib import Path

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

# I. 插件元信息
__plugin_meta__ = PluginMetadata(
    name="kun_response",
    description="被 @ 且无匹配指令时，随机回复一段坤音频语音消息",
    usage="群内 @机器人（不携带任何已知指令）",
)

# II. 音频文件列表构建
# 本文件位于 plugins/kun_response/__init__.py，上推两级即项目根目录
_PROJECT_ROOT: Path = Path(__file__).parents[2]
_AMR_DIR: Path = _PROJECT_ROOT / "kun" / "amr"
_CONVERTED_DIR: Path = _PROJECT_ROOT / "kun" / "converted"
_ORIGINAL_DIR: Path = _PROJECT_ROOT / "kun"

# 支持的音频后缀（预转换目录可能含 .amr / .wav，原始目录可能含 .mp3）
_AUDIO_SUFFIXES: frozenset[str] = frozenset({".amr", ".wav", ".mp3"})


def _scan_audio_files() -> list[Path]:
    """
    扫描并返回可发送的音频文件列表

    I.  优先使用 kun/amr/ 目录（预转换 AMR 文件）
        (1) 目录存在且包含 .amr 文件时使用
        (2) 排除非音频文件
    II. 次优先使用 kun/converted/ 目录（预转换 WAV 文件）
        (1) 目录存在且包含音频文件时使用
        (2) 排除非音频文件（如 manifest.json、avatar.png 等）
    III. 回退到 kun/ 目录中的原始 .mp3 / .wav 文件
        (1) 跳过 converted/ 子目录本身
        (2) 跳过非音频文件

    @returns 按文件名排序的音频文件路径列表（排序保证列表顺序稳定，便于日志追踪）
    """
    # I. 优先尝试 amr/ 目录
    if _AMR_DIR.exists():
        amr_files = sorted(
            p for p in _AMR_DIR.iterdir() if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
        )
        if amr_files:
            logger.info(
                "kun_response: 使用预转换音频目录 kun/amr/，共 {} 个文件",
                len(amr_files),
            )
            return amr_files

    # II. 次优先尝试 converted/ 目录
    if _CONVERTED_DIR.exists():
        converted_files = sorted(
            p
            for p in _CONVERTED_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
        )
        if converted_files:
            logger.info(
                "kun_response: 使用预转换音频目录 kun/converted/，共 {} 个文件",
                len(converted_files),
            )
            return converted_files

    # III. 回退到原始目录
    original_files = sorted(
        p
        for p in _ORIGINAL_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
    )
    if original_files:
        logger.warning(
            "kun_response: kun/amr/ 与 kun/converted/ 均不存在或为空，"
            "回退使用原始文件目录，共 {} 个文件。"
            "建议运行 python scripts/convert_kun_audio.py 进行预转换",
            len(original_files),
        )
    else:
        logger.warning(
            "kun_response: kun/ 目录下未找到任何音频文件，插件将不响应 @ 事件"
        )
    return original_files


# 模块级预扫描：NoneBot 启动时执行一次，避免每次事件触发时重复扫描磁盘
_KUN_AUDIO_FILES: list[Path] = _scan_audio_files()

# III. 处理器注册
# priority=20：低于 group_stats 的 priority=10，确保具体指令优先匹配
# block=True：本处理器匹配后，不再传递给更低优先级的处理器
_kun_fallback = on_message(rule=to_me(), priority=20, block=True)


@_kun_fallback.handle()
async def _send_random_kun(bot: Bot, event: GroupMessageEvent) -> None:
    """
    随机回复一段坤音频语音消息

    I.  检查音频文件列表是否非空（启动时已扫描）
    II. 随机选取一个音频文件
    III. 读取音频字节并通过 base64:// 方式发送

    格式兼容说明：
    (1) 直接发送音频字节可避免 file:// 路径编码、挂载路径不一致、
        NapCat 进程访问权限差异等问题
    (2) kun/amr/ 中的 AMR-NB 文件优先级最高，可显著降低语音转换失败概率
    (3) 若单个文件发送失败，则继续尝试其他音频，避免 matcher 直接报错
    """
    # I. 音频文件列表为空则静默退出，避免抛出 IndexError
    if not _KUN_AUDIO_FILES:
        return

    # II. 打乱候选列表，逐个尝试发送
    candidates: list[Path] = _KUN_AUDIO_FILES[:]
    random.shuffle(candidates)

    # III. 优先发送预转换音频，失败则回退到其他文件
    for chosen in candidates:
        logger.info(
            "kun_response: group_id={} 触发，尝试发送音频: {}",
            event.group_id,
            chosen.name,
        )
        try:
            await bot.send_group_msg(
                group_id=int(event.group_id),
                message=Message(MessageSegment.record(chosen.read_bytes())),
            )
            return
        except ActionFailed as exc:
            logger.warning(
                "kun_response: 音频发送失败 group_id={} file={} error={}",
                event.group_id,
                chosen.name,
                str(exc),
            )

    logger.error("kun_response: group_id={} 所有音频均发送失败", event.group_id)
