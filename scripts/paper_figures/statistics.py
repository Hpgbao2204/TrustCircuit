"""Small deterministic statistical and geometry helpers for figures."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator


RNG_SEED = 20260719


def deterministic_jitter(n: int, width: float = 0.12, salt: int = 0) -> np.ndarray:
    rng = np.random.default_rng(RNG_SEED + salt)
    return rng.uniform(-width, width, n)


def ecdf(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(np.asarray(data, dtype=float))
    y = np.arange(1, len(x) + 1, dtype=float) / len(x)
    return x, y


def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    denom = np.sum((y - np.mean(y)) ** 2)
    r2 = 1.0 - np.sum((y - pred) ** 2) / denom if denom else 1.0
    return float(slope), float(intercept), float(r2)


def pchip_logx(x: np.ndarray, y: np.ndarray, points: int = 240) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.any(x <= 0) or len(x) < 3:
        return x, y
    lx = np.log10(x)
    dense_lx = np.linspace(lx.min(), lx.max(), points)
    dense_y = PchipInterpolator(lx, y)(dense_lx)
    return 10**dense_lx, np.asarray(dense_y, dtype=float)


def area_sizes(values: np.ndarray, low: float = 90.0, high: float = 560.0) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if np.ptp(values) == 0:
        return np.full_like(values, (low + high) / 2)
    scaled = (values - values.min()) / np.ptp(values)
    return low + scaled * (high - low)


def pareto_min_x_max_y(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.ones(len(x), dtype=bool)
    for i in range(len(x)):
        dominates = (x <= x[i]) & (y >= y[i]) & ((x < x[i]) | (y > y[i]))
        if np.any(dominates):
            mask[i] = False
    return mask

