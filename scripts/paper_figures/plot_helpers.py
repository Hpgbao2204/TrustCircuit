"""Reusable single-axes plot primitives."""

from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np

from .figure_style import COLORS
from .statistics import deterministic_jitter


def distribution_boxes(
    ax,
    datasets: Sequence[np.ndarray],
    positions: Sequence[float],
    colors: Sequence[str],
    *,
    widths: float | Sequence[float] = 0.56,
    horizontal: bool = False,
    raw_alpha: float = 0.24,
    salt: int = 0,
) -> None:
    bp = ax.boxplot(
        datasets,
        positions=positions,
        widths=widths,
        vert=not horizontal,
        patch_artist=True,
        showfliers=False,
        whis=(2.5, 97.5),
        medianprops={"color": COLORS["dark"], "linewidth": 1.5},
        whiskerprops={"color": COLORS["gray"], "linewidth": 0.8},
        capprops={"color": COLORS["gray"], "linewidth": 0.8},
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.42)
        patch.set_edgecolor(color)
    for index, (data, pos, color) in enumerate(zip(datasets, positions, colors)):
        jitter = deterministic_jitter(len(data), 0.15, salt + index)
        if horizontal:
            ax.scatter(data, pos + jitter, s=11, color=color, alpha=raw_alpha, edgecolors="none", zorder=2)
            ax.scatter(np.median(data), pos, marker="D", s=25, color=COLORS["dark"], zorder=4)
            ax.scatter(np.percentile(data, 95), pos, marker=">", s=31, color=COLORS["red"], zorder=4)
        else:
            ax.scatter(pos + jitter, data, s=11, color=color, alpha=raw_alpha, edgecolors="none", zorder=2)
            ax.scatter(pos, np.median(data), marker="D", s=25, color=COLORS["dark"], zorder=4)
            ax.scatter(pos, np.percentile(data, 95), marker="^", s=31, color=COLORS["red"], zorder=4)


def add_distribution_key(ax, *, loc: str = "upper left") -> None:
    handles = [
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95"),
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], alpha=0.45, label="trial"),
    ]
    ax.legend(handles=handles, loc=loc, ncol=3)


def annotate_bars(ax, bars, values: Sequence[float], formatter, *, fontsize: float = 7.2) -> None:
    for bar, value in zip(bars, values):
        ax.annotate(
            formatter(float(value)),
            (bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height()),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=fontsize,
        )
