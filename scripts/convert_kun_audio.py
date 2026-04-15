"""
kun 音频格式批量转换脚本

将 kun/ 目录下所有 .mp3 / .wav（含 IEEE Float 编码）文件
转换为 QQ 语音更稳定的发送格式：
    AMR-NB，单声道，8000 Hz

格式选择依据：
  I.  QQ 语音链路长期对 AMR / Silk 兼容性最好。
      预先转换为 AMR-NB（8000 Hz，单声道）后，可显著降低
      NapCat 在发送阶段再次转码失败的概率。
  II. 通过 base64:// 直接上传 AMR 数据时，可绕过本地 file:// 路径、
      URI 编码以及 NapCat 侧文件访问权限差异问题。
  III. WAV IEEE Float 格式（kun/ 目录中的 .wav 文件实际采用此编码）
      并非所有 OneBot 实现都能直接处理，预转换可提升跨实现兼容性。

使用方法：
    python scripts/convert_kun_audio.py           # 转换 kun/ 下所有音频
    python scripts/convert_kun_audio.py --dry-run # 仅列出待转换文件，不实际执行

输出目录：kun/amr/
    转换完成后，插件会自动优先使用 amr/ 中的文件。

依赖：ffmpeg 需已安装并在 PATH 中
  macOS:  brew install ffmpeg
  Ubuntu: sudo apt install ffmpeg

@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
import argparse
import subprocess
import sys
from pathlib import Path

# I. 路径常量
# 本文件位于 scripts/，上一级为项目根目录
PROJECT_ROOT: Path = Path(__file__).parent.parent
KUN_DIR: Path = PROJECT_ROOT / "kun"
OUTPUT_DIR: Path = KUN_DIR / "amr"

# 支持作为转换源的后缀名（不含已转换的 .wav 输出本身）
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"})

# 目标格式参数：AMR-NB，8000 Hz，单声道
_FFMPEG_TARGET_ARGS = [
    "-ar", "8000",    # 采样率 8 kHz（AMR-NB 标准）
    "-ac", "1",       # 单声道
    "-c:a", "libopencore_amrnb",  # AMR-NB 编码器
    "-b:a", "12.2k",  # AMR-NB 常用最高码率，语音质量更稳定
]


def _check_ffmpeg() -> None:
    """
    检查 ffmpeg 是否已安装并可调用

    若未找到 ffmpeg，打印错误提示后退出进程。
    """
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print("错误：未找到 ffmpeg，请先安装后再运行此脚本。", file=sys.stderr)
        print("  macOS:  brew install ffmpeg", file=sys.stderr)
        print("  Ubuntu: sudo apt install ffmpeg", file=sys.stderr)
        sys.exit(1)


def _convert_file(src: Path, dst: Path) -> bool:
    """
    使用 ffmpeg 将单个音频文件转换为目标格式

    I.  构造 ffmpeg 命令，覆盖已存在的目标文件（-y）
    II. 执行转换，捕获 stderr
    III. 返回执行结果

    @param src - 源文件完整路径
    @param dst - 目标 .amr 文件完整路径
    @returns True 表示转换成功，False 表示失败
    """
    # I. 构造命令：-y 覆盖旧文件，-vn 丢弃视频流（如 MP3 封面图）
    cmd = [
        "ffmpeg",
        "-y",          # 覆盖已存在的输出文件，无需交互确认
        "-i", str(src),
        "-vn",         # 忽略视频流（部分 MP3 含封面 APIC 帧）
        *_FFMPEG_TARGET_ARGS,
        str(dst),
    ]

    # II. 执行转换
    result = subprocess.run(cmd, capture_output=True, text=True)

    # III. 返回结果
    if result.returncode != 0:
        # 只打印最后 500 字符的 stderr，避免输出信息过长
        print(f"  ✗ 转换失败: {src.name}", file=sys.stderr)
        print(f"    ffmpeg: {result.stderr[-500:]}", file=sys.stderr)
        return False
    return True


def _collect_sources() -> list[Path]:
    """
    扫描 kun/ 目录，收集待转换的源文件列表

    排除 converted/ 子目录本身，以及非音频文件
    """
    if not KUN_DIR.exists():
        print(f"错误：目录不存在 {KUN_DIR}", file=sys.stderr)
        sys.exit(1)

    return sorted(
        p
        for p in KUN_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def main() -> None:
    """
    I.   解析命令行参数
    II.  检查 ffmpeg 可用性
    III. 扫描源文件列表
    IV.  创建输出目录（幂等）
    V.   逐文件执行转换
    VI.  打印汇总结果
    """
    # I. 解析命令行参数
    parser = argparse.ArgumentParser(description="将 kun/ 音频批量转换为 AMR-NB (8kHz, mono)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出待转换文件，不实际执行 ffmpeg 转换",
    )
    args = parser.parse_args()

    # II. 检查 ffmpeg
    if not args.dry_run:
        _check_ffmpeg()

    # III. 扫描源文件
    sources = _collect_sources()
    if not sources:
        print(f"kun/ 目录下未找到可转换的音频文件（支持：{', '.join(sorted(SUPPORTED_SUFFIXES))}）")
        return

    print(f"待转换文件共 {len(sources)} 个：")
    for src in sources:
        dst = OUTPUT_DIR / (src.stem + ".amr")
        print(f"  {src.name}  →  amr/{dst.name}")

    if args.dry_run:
        print("\n（dry-run 模式：已跳过实际转换）")
        return

    # IV. 创建输出目录（若已存在则跳过，幂等）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n输出目录: {OUTPUT_DIR}\n")

    # V. 逐文件转换
    success = 0
    failed = 0
    for src in sources:
        dst = OUTPUT_DIR / (src.stem + ".amr")
        print(f"  转换: {src.name} → amr/{dst.name} ...", end=" ", flush=True)
        if _convert_file(src, dst):
            print("✓")
            success += 1
        else:
            print("✗")
            failed += 1

    # VI. 汇总
    print(f"\n转换完成：成功={success}，失败={failed}")
    if success > 0:
        print(f"转换后文件位于: {OUTPUT_DIR}")
        print("插件启动时会自动优先加载 kun/amr/ 中的文件。")


if __name__ == "__main__":
    main()
