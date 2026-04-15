"""
group_stats 趋势图绘制模块

负责将群人数时间序列数据渲染为 PNG 图像，供 OneBot 群消息发送。
默认使用 Matplotlib 绘制折线图，并在字体可用时启用中文文案。

@module plugins.group_stats.chart
@author Zexuan Peng <pengzexuan2001@gmail.com>
@created 2026-04-15
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Sequence

import matplotlib.dates as mdates
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Polygon

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


def _build_smoothed_series(
    times: Sequence[datetime], counts: Sequence[int]
) -> tuple[np.ndarray, np.ndarray, bool]:
    """
    构建平滑时间序列

    I.  将 datetime 映射为 Matplotlib 数值时间轴
    II. 通过插值 + 滑动平均降低折线锯齿感
    III. 点位过少时回退原始序列，避免过度处理
    """
    x_raw = mdates.date2num(times)
    y_raw = np.asarray(counts, dtype=float)

    if len(times) < 4 or np.isclose(x_raw[0], x_raw[-1]):
        return x_raw, y_raw, False

    dense_points = min(360, max(120, len(times) * 10))
    x_dense = np.linspace(x_raw[0], x_raw[-1], dense_points)
    y_linear = np.interp(x_dense, x_raw, y_raw)

    window = max(7, dense_points // 36)
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=float) / window
    pad = window // 2
    y_padded = np.pad(y_linear, (pad, pad), mode="edge")
    y_smooth = np.convolve(y_padded, kernel, mode="valid")

    # 将原始观测点重新锚定到平滑曲线上，确保关键值不漂移
    for x_point, y_point in zip(x_raw, y_raw):
        nearest = int(np.argmin(np.abs(x_dense - x_point)))
        y_smooth[nearest] = y_point

    return x_dense, y_smooth, True


def _draw_gradient_fill(
    ax,
    x_values: np.ndarray,
    y_values: np.ndarray,
    y_bottom: float,
    y_top: float,
) -> None:
    """绘制折线下方的渐变填充区域"""
    vertices = [(x_values[0], y_bottom)]
    vertices.extend((x, y) for x, y in zip(x_values, y_values))
    vertices.append((x_values[-1], y_bottom))

    clip_poly = Polygon(vertices, closed=True, facecolor="none", edgecolor="none")
    ax.add_patch(clip_poly)

    gradient = np.linspace(0, 1, 256, dtype=float).reshape(256, 1)
    cmap = LinearSegmentedColormap.from_list("group_trend_fill", ["#E8F1FB", "#1F77B4"])
    image = ax.imshow(
        gradient,
        extent=[x_values.min(), x_values.max(), y_bottom, y_top],
        origin="lower",
        aspect="auto",
        cmap=cmap,
        alpha=0.32,
        zorder=1,
    )
    image.set_clip_path(clip_poly)


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
    time_nums = mdates.date2num(times)
    counts = [item[1] for item in points]

    # I. 计算 Y 轴显示范围，放大趋势变化可读性
    y_min, y_max = min(counts), max(counts)
    y_range = y_max - y_min
    y_padding = max(y_range * 0.3, 5)
    y_bottom = max(0, y_min - y_padding)
    y_top = y_max + y_padding

    # II. 生成平滑绘图序列，让趋势变化更连贯
    x_plot, y_plot, is_smoothed = _build_smoothed_series(times, counts)

    # 使用 Figure + FigureCanvasAgg 纯离屏渲染，避免 GUI backend 在子线程报错
    fig = Figure(figsize=(10, 5.6), dpi=92)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")
    ax.grid(True, color="#E5E7EB", linewidth=0.8)

    ax.plot(
        x_plot,
        y_plot,
        color="#1F77B4",
        linewidth=2.2,
        zorder=3,
    )
    marker_size = 10 if len(points) <= 120 else 8
    ax.scatter(time_nums, counts, color="#1F77B4", s=marker_size, alpha=0.68, zorder=4)

    # III. 渐变填充到 y_bottom，与 Y 轴范围保持一致
    _draw_gradient_fill(ax, x_plot, y_plot, y_bottom, y_top)
    ax.set_ylim(bottom=y_bottom, top=y_top)

    avg_count = sum(counts) / len(counts)
    ref_meta = (
        [("最大值", y_max, "#D7263D"), ("平均值", avg_count, "#6B7280"), ("最小值", y_min, "#2A9D8F")]
        if has_zh_font
        else [("Max", y_max, "#D7263D"), ("Avg", avg_count, "#6B7280"), ("Min", y_min, "#2A9D8F")]
    )
    for ref_label, ref_value, ref_color in ref_meta:
        ax.axhline(
            y=ref_value,
            color=ref_color,
            linewidth=1.0,
            linestyle=(0, (4, 3)),
            alpha=0.52,
            zorder=0,
        )
        ref_annot = ax.annotate(
            f"{ref_label}: {ref_value:.0f}",
            xy=(time_nums[-1], ref_value),
            xytext=(7, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=9,
            color=ref_color,
        )
        if font_prop:
            ref_annot.set_fontproperties(font_prop)

    latest_y = counts[-1]
    max_idx = max(range(len(counts)), key=counts.__getitem__)
    min_idx = min(range(len(counts)), key=counts.__getitem__)

    ax.scatter([time_nums[max_idx]], [counts[max_idx]], color="#D7263D", s=35, zorder=5)
    ax.scatter([time_nums[min_idx]], [counts[min_idx]], color="#2A9D8F", s=35, zorder=5)
    ax.scatter([time_nums[-1]], [latest_y], color="#F4A261", s=35, zorder=5)

    # IV. 标注各数据点的纵坐标值
    # (1) 点数少时标注所有点位；点数多时只标注最大、最小、最新三个关键点
    n = len(points)
    if n <= 15:
        annotate_indices: Sequence[int] = range(n)
    else:
        annotate_indices = sorted({max_idx, min_idx, n - 1})
    for idx in annotate_indices:
        point_annot = ax.annotate(
            str(counts[idx]),
            xy=(time_nums[idx], counts[idx]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#333333",
        )
        if font_prop:
            point_annot.set_fontproperties(font_prop)

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
    if is_smoothed:
        note_label = (
            f"{note_label} | 曲线平滑显示" if has_zh_font else f"{note_label} | Smoothed line"
        )

    if font_prop:
        ax.set_title(title_text, fontsize=14, fontproperties=font_prop)
        ax.set_xlabel(x_label, fontsize=11, fontproperties=font_prop)
        ax.set_ylabel(y_label, fontsize=11, fontproperties=font_prop)
    else:
        ax.set_title(title_text, fontsize=14)
        ax.set_xlabel(x_label, fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)

    # V. X 轴刻度：按 mm-dd 格式去重，每个日期最多出现一次
    if n <= 35:
        # (1) 点数少时依次扫描，保留每个日期第一个时间点作为刻度
        seen: set[str] = set()
        tick_positions = []
        for t in times:
            label = t.strftime("%m-%d")
            if label not in seen:
                seen.add(label)
                tick_positions.append(mdates.date2num(t))
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
                tick_positions.append(mdates.date2num(t))
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


def render_top1_hourly_distribution_png(
    group_name: str,
    group_id: int,
    stat_date: date,
    user_name: str,
    user_id: int,
    first_message_at: datetime,
    last_message_at: datetime,
    points: Sequence[tuple[int, int]],
) -> bytes:
    """
    渲染 Top1 用户小时分布图

    @param group_name - 群名称
    @param group_id - 群号
    @param stat_date - 统计日期
    @param user_name - 用户展示名
    @param user_id - 用户 ID
    @param first_message_at - 最早消息时间
    @param last_message_at - 最晚消息时间
    @param points - 小时桶数据，元素为 (hour_bucket, message_count)
    @returns PNG 字节流
    """
    if len(points) != 24:
        raise ValueError("Top1 小时分布数据必须为 24 个小时桶")

    font_prop = _pick_font()
    has_zh_font = font_prop is not None

    hours = [item[0] for item in points]
    counts = [item[1] for item in points]

    fig = Figure(figsize=(10, 5.6), dpi=92)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")
    ax.grid(True, color="#E5E7EB", linewidth=0.8, axis="y")

    ax.bar(hours, counts, color="#3B82F6", alpha=0.86, zorder=2)
    ax.plot(hours, counts, color="#1D4ED8", linewidth=2.0, zorder=3)

    peak_hour = max(range(24), key=lambda idx: counts[idx])
    peak_count = counts[peak_hour]
    ax.scatter([peak_hour], [peak_count], color="#EF4444", s=42, zorder=4)
    peak_annot = ax.annotate(
        f"{peak_hour:02d}:00 ({peak_count})",
        xy=(peak_hour, peak_count),
        xytext=(0, 10),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#B91C1C",
    )
    if font_prop:
        peak_annot.set_fontproperties(font_prop)

    title_text = (
        f"Top1 水群时段分布 - {group_name or group_id}"
        if has_zh_font
        else f"Top1 Hourly Distribution - {group_name or group_id}"
    )
    subtitle = (
        f"用户: {user_name} ({user_id})  日期: {stat_date.isoformat()}"
        if has_zh_font
        else f"User: {user_name} ({user_id})  Date: {stat_date.isoformat()}"
    )
    x_label = "小时" if has_zh_font else "Hour"
    y_label = "消息数" if has_zh_font else "Message Count"
    timeline_text = (
        f"首条: {first_message_at.strftime('%H:%M:%S')}  末条: {last_message_at.strftime('%H:%M:%S')}"
        if has_zh_font
        else f"First: {first_message_at.strftime('%H:%M:%S')}  Last: {last_message_at.strftime('%H:%M:%S')}"
    )

    if font_prop:
        ax.set_title(title_text, fontsize=14, fontproperties=font_prop)
        ax.set_xlabel(x_label, fontsize=11, fontproperties=font_prop)
        ax.set_ylabel(y_label, fontsize=11, fontproperties=font_prop)
    else:
        ax.set_title(title_text, fontsize=14)
        ax.set_xlabel(x_label, fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)

    ax.set_xticks(list(range(24)))
    ax.set_xticklabels([f"{hour:02d}" for hour in range(24)], fontsize=8)
    ax.text(
        0.01,
        0.98,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        color="#334155",
        fontproperties=font_prop,
    )
    ax.text(
        0.01,
        0.92,
        timeline_text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        color="#334155",
        fontproperties=font_prop,
    )

    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def render_group_hourly_trend_png(
    group_name: str,
    group_id: int,
    stat_date: date,
    points: Sequence[tuple[int, int]],
) -> bytes:
    """
    渲染群整体小时活跃趋势图

    @param group_name - 群名称
    @param group_id - 群号
    @param stat_date - 统计日期
    @param points - 小时桶数据，元素为 (hour_bucket, message_count)
    @returns PNG 字节流
    """
    if len(points) != 24:
        raise ValueError("群小时趋势数据必须为 24 个小时桶")

    font_prop = _pick_font()
    has_zh_font = font_prop is not None

    hours = np.asarray([item[0] for item in points], dtype=float)
    counts = np.asarray([item[1] for item in points], dtype=float)

    fig = Figure(figsize=(10, 5.6), dpi=92)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")
    ax.grid(True, color="#E5E7EB", linewidth=0.8)

    ax.plot(hours, counts, color="#10B981", linewidth=2.2, zorder=3)
    ax.fill_between(hours, counts, color="#6EE7B7", alpha=0.35, zorder=2)
    ax.scatter(hours, counts, color="#059669", s=20, zorder=4)

    peak_idx = int(np.argmax(counts))
    peak_hour = int(hours[peak_idx])
    peak_count = int(counts[peak_idx])
    total_count = int(np.sum(counts))
    ax.scatter([peak_hour], [peak_count], color="#DC2626", s=44, zorder=5)

    peak_annot = ax.annotate(
        f"{peak_hour:02d}:00 ({peak_count})",
        xy=(peak_hour, peak_count),
        xytext=(0, 10),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#B91C1C",
    )
    if font_prop:
        peak_annot.set_fontproperties(font_prop)

    title_text = (
        f"群整体活跃度趋势 - {group_name or group_id}"
        if has_zh_font
        else f"Group Hourly Activity Trend - {group_name or group_id}"
    )
    x_label = "小时" if has_zh_font else "Hour"
    y_label = "消息数" if has_zh_font else "Message Count"
    summary_text = (
        f"日期: {stat_date.isoformat()}  总消息数: {total_count}  峰值时段: {peak_hour:02d}:00"
        if has_zh_font
        else f"Date: {stat_date.isoformat()}  Total: {total_count}  Peak: {peak_hour:02d}:00"
    )

    if font_prop:
        ax.set_title(title_text, fontsize=14, fontproperties=font_prop)
        ax.set_xlabel(x_label, fontsize=11, fontproperties=font_prop)
        ax.set_ylabel(y_label, fontsize=11, fontproperties=font_prop)
    else:
        ax.set_title(title_text, fontsize=14)
        ax.set_xlabel(x_label, fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)

    ax.set_xticks(list(range(24)))
    ax.set_xticklabels([f"{hour:02d}" for hour in range(24)], fontsize=8)
    ax.text(
        0.01,
        0.98,
        summary_text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        color="#334155",
        fontproperties=font_prop,
    )

    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()
