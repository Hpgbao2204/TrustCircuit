"""Reusable primitives for dense scientific panels."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .figure_style import ANNOTATION_SIZE, COLORS
from .statistics import pchip, pchip_band


def smooth_line(
    ax,
    x: np.ndarray,
    y: np.ndarray,
    *,
    color: str,
    label: str,
    marker: str = "o",
    linestyle: str = "-",
    log_x: bool = False,
    linewidth: float = 1.8,
    zorder: int = 4,
) -> None:
    dense_x, dense_y = pchip(x, y, log_x=log_x)
    ax.plot(dense_x, dense_y, color=color, linestyle=linestyle, linewidth=linewidth, label=label)
    ax.plot(x, y, linestyle="none", marker=marker, color=color, markeredgecolor="white",
            markeredgewidth=0.6, zorder=zorder)


def percentile_ribbon(
    ax,
    x: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    *,
    color: str,
    label: str,
    log_x: bool = False,
    alpha: float = 0.16,
) -> None:
    dense_x, dense_low, dense_high = pchip_band(x, low, high, log_x=log_x)
    ax.fill_between(dense_x, dense_low, dense_high, color=color, alpha=alpha, label=label)
    ax.plot(x, low, linestyle="none", marker=".", color=color, alpha=0.75)
    ax.plot(x, high, linestyle="none", marker=".", color=color, alpha=0.75)


def annotate_bar_values(ax, bars, values: Sequence[float], fmt: str = "{:.1f}") -> None:
    for bar, value in zip(bars, values):
        ax.annotate(
            fmt.format(float(value)),
            (bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height()),
            xytext=(0, 4), textcoords="offset points", ha="center", va="bottom",
            fontsize=ANNOTATION_SIZE,
        )


def style_secondary_axis(ax, color: str = COLORS["red"]) -> None:
    ax.spines["right"].set_visible(True)
    ax.spines["right"].set_color(color)
    ax.tick_params(axis="y", colors=color)
