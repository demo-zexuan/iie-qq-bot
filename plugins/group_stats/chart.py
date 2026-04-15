"""
group_stats 趋势图绘制模块

负责将群人数时间序列数据渲染为 PNG 图像，供 OneBot 群消息发送。
默认使用 Matplotlib 绘制折线图，并在字体可用时启用中文文案。

@module plugins.group_stats.chart
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Sequence

import matplotlib.dates as mdates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties

# 候选中文字体（按常见环境优先级排序）
_FONT_CANDIDATES = [
    "PingFang SC",
    "Microsoft YaHei",
    "WenQuanYi Zen Hei",
    "Noto Sans CJK SC",
    "SimHei",
    "Arial Unicode MS",
]


def _pick_font() -> FontProperties | None:
    """
    选择可用中文字体

    I.  优先尝试项目内 fonts 目录下的字体文件
    II. 再尝试系统字体名称
    III. 均不可用时返回 None，交由调用方做降级文案
    """
    local_fonts = [
        Path("fonts/NotoSansCJK-Regular.ttc"),
        Path("fonts/NotoSansCJKsc-Regular.otf"),
        Path("fonts/SourceHanSansSC-Regular.otf"),
        Path("fonts/SimHei.ttf"),
    ]
    for font_path in local_fonts:
        if font_path.exists():
            return FontProperties(fname=str(font_path))

    for font_name in _FONT_CANDIDATES:
        try:
            matched = font_manager.findfont(font_name, fallback_to_default=False)
            if matched:
                return FontProperties(fname=matched)
        except Exception:
            continue
    return None


def render_group_trend_chart_png(
    group_name: str,
    group_id: int,
    points: Sequence[tuple[datetime, int]],
    aggregation_note: str,
) -> bytes:
    """
    渲染群人数趋势图并返回 PNG 二进制

    @param group_name       - 群名称
    @param group_id         - 群号
    @param points           - 时间序列点，元素为 (时间, 人数)
    @param aggregation_note - 聚合说明（如“原始点位”“按天聚合”）
    @returns PNG 字节流
    """
    if not points:
        raise ValueError("趋势数据为空，无法绘图")

    font_prop = _pick_font()
    has_zh_font = font_prop is not None

    times = [item[0] for item in points]
    counts = [item[1] for item in points]

    # I. 计算 Y 轴显示范围，放大趋势变化可读性
    y_min, y_max = min(counts), max(counts)
    y_range = y_max - y_min
    y_padding = max(y_range * 0.3, 5)
    y_bottom = max(0, y_min - y_padding)
    y_top = y_max + y_padding

    # 使用 Figure + FigureCanvasAgg 纯离屏渲染，避免 GUI backend 在子线程报错
    fig = Figure(figsize=(10, 5.6), dpi=92)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")
    ax.grid(True, color="#E5E7EB", linewidth=0.8)

    marker_size = 3 if len(points) <= 120 else 2
    ax.plot(
        times,
        counts,
        color="#1F77B4",
        linewidth=2,
        marker="o",
        markersize=marker_size,
        markerfacecolor="#1F77B4",
    )
    # II. fill 填充到 y_bottom 而非 0，与 Y 轴范围保持一致
    ax.fill_between(times, counts, y_bottom, color="#1F77B4", alpha=0.12)
    ax.set_ylim(bottom=y_bottom, top=y_top)

    latest_x, latest_y = times[-1], counts[-1]
    max_idx = max(range(len(counts)), key=counts.__getitem__)
    min_idx = min(range(len(counts)), key=counts.__getitem__)

    ax.scatter([times[max_idx]], [counts[max_idx]], color="#D7263D", s=35, zorder=5)
    ax.scatter([times[min_idx]], [counts[min_idx]], color="#2A9D8F", s=35, zorder=5)
    ax.scatter([latest_x], [latest_y], color="#F4A261", s=35, zorder=5)

    # III. 标注各数据点的纵坐标值
    # (1) 点数少时标注所有点位；点数多时只标注最大、最小、最新三个关键点
    n = len(points)
    ann_fp = {"fontproperties": font_prop} if font_prop else {}
    if n <= 15:
        annotate_indices: Sequence[int] = range(n)
    else:
        annotate_indices = sorted({max_idx, min_idx, n - 1})
    for idx in annotate_indices:
        ax.annotate(
            str(counts[idx]),
            xy=(times[idx], counts[idx]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#333333",
            **ann_fp,
        )

    title_text = (
        f"群人数波动曲线 - {group_name or group_id}"
        if has_zh_font
        else f"Group Member Trend - {group_name or group_id}"
    )
    x_label = "统计时间" if has_zh_font else "Time"
    y_label = "群成员人数" if has_zh_font else "Member Count"
    note_label = (
        f"展示粒度: {aggregation_note}"
        if has_zh_font
        else f"Display Granularity: {aggregation_note}"
    )

    if font_prop:
        ax.set_title(title_text, fontsize=14, fontproperties=font_prop)
        ax.set_xlabel(x_label, fontsize=11, fontproperties=font_prop)
        ax.set_ylabel(y_label, fontsize=11, fontproperties=font_prop)
    else:
        ax.set_title(title_text, fontsize=14)
        ax.set_xlabel(x_label, fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)

    # IV. X 轴刻度：按 mm-dd 格式去重，每个日期最多出现一次
    if n <= 35:
        # (1) 点数少时依次扫描，保留每个日期第一个时间点作为刻度
        seen: set[str] = set()
        tick_positions = []
        for t in times:
            label = t.strftime("%m-%d")
            if label not in seen:
                seen.add(label)
                tick_positions.append(t)
        ax.set_xticks(tick_positions)
    else:
        # (2) 点数多时先均匀降采样再去重
        tick_step = max(1, n // 12)
        seen = set()
        tick_positions = []
        for t in times[::tick_step]:
            label = t.strftime("%m-%d")
            if label not in seen:
                seen.add(label)
                tick_positions.append(t)
        ax.set_xticks(tick_positions)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate(rotation=28)

    if font_prop:
        ax.text(
            0.99,
            0.03,
            note_label,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=10,
            color="#4A5568",
            fontproperties=font_prop,
        )
    else:
        ax.text(
            0.99,
            0.03,
            note_label,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=10,
            color="#4A5568",
        )

    ax.margins(x=0.02)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()
