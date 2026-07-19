"""Deterministic statistical and monotone-rendering helpers."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator


def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    denominator = np.sum((y - np.mean(y)) ** 2)
    r2 = 1.0 - np.sum((y - predicted) ** 2) / denominator if denominator else 1.0
    return float(slope), float(intercept), float(r2)


def pchip(
    x: np.ndarray,
    y: np.ndarray,
    *,
    points: int = 240,
    log_x: bool = False,
    clamp_min: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a monotone-shape-preserving guide through real observations."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3:
        return x, y
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(np.unique(x)) != len(x):
        raise ValueError("PCHIP x values must be unique")
    if log_x:
        if np.any(x <= 0):
            raise ValueError("log-x PCHIP requires positive x values")
        tx = np.log10(x)
        dense_tx = np.linspace(tx.min(), tx.max(), points)
        dense_x = 10**dense_tx
    else:
        tx = x
        dense_tx = np.linspace(x.min(), x.max(), points)
        dense_x = dense_tx
    dense_y = np.asarray(PchipInterpolator(tx, y)(dense_tx), dtype=float)
    if clamp_min is not None:
        dense_y = np.maximum(dense_y, clamp_min)
    return dense_x, dense_y


def pchip_band(
    x: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    *,
    log_x: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dense_x, dense_low = pchip(x, low, log_x=log_x)
    _, dense_high = pchip(x, high, log_x=log_x)
    return dense_x, np.minimum(dense_low, dense_high), np.maximum(dense_low, dense_high)


def smooth_empirical_cdf(data: np.ndarray, points: int = 260) -> tuple[np.ndarray, np.ndarray]:
    """PCHIP guide through unique empirical-CDF knots; observations stay unchanged."""
    x = np.sort(np.asarray(data, dtype=float))
    y = np.arange(1, len(x) + 1, dtype=float) / len(x)
    unique_x, first = np.unique(x, return_index=True)
    counts = np.diff(np.r_[first, len(x)])
    unique_y = np.cumsum(counts) / len(x)
    if len(unique_x) < 3:
        return unique_x, unique_y
    dense_x = np.linspace(unique_x.min(), unique_x.max(), points)
    dense_y = PchipInterpolator(unique_x, unique_y)(dense_x)
    return dense_x, np.clip(dense_y, 0, 1)


def normalized_to_first(values: np.ndarray) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    baseline = data[0]
    if baseline == 0:
        return np.ones_like(data)
    return data / baseline

