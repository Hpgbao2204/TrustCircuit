"""Strict CSV loading for paper figures; this module never writes data."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

from .figure_style import REPO


PROCESSED = REPO / "results" / "processed"
RAW_PHASE8 = REPO / "results" / "raw" / "phase8"
SUMMARY = REPO / "results" / "summary"


def read_csv(path: Path, required: Iterable[str] = ()) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required figure source is missing: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = set(reader.fieldnames or [])
    if not rows:
        raise ValueError(f"Required figure source has no data rows: {path}")
    missing = sorted(set(required) - fields)
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
    return rows


def processed(name: str, required: Iterable[str] = ()) -> list[dict[str, str]]:
    return read_csv(PROCESSED / name, required)


def raw(name: str, required: Iterable[str] = ()) -> list[dict[str, str]]:
    return read_csv(RAW_PHASE8 / name, required)


def summary(name: str, required: Iterable[str] = ()) -> list[dict[str, str]]:
    return read_csv(SUMMARY / name, required)


def values(rows: Iterable[dict[str, str]], column: str) -> np.ndarray:
    try:
        result = np.asarray([float(row[column]) for row in rows], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Column {column!r} is not complete numeric data") from exc
    if not np.all(np.isfinite(result)):
        raise ValueError(f"Column {column!r} contains non-finite data")
    return result


def groups(rows: Iterable[dict[str, str]], column: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row[column]].append(row)
    return dict(grouped)


def indexed(rows: Iterable[dict[str, str]], column: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row[column]
        if key in result:
            raise ValueError(f"Duplicate key {key!r} in column {column!r}")
        result[key] = row
    return result

