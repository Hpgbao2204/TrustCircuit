"""Summarize contract gas benchmark rows."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

import numpy as np


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def summarize(input_path: Path, output_path: Path) -> None:
    with input_path.open("r", newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f) if row.get("success") == "true"]

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_run: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        variant = row.get("variant", "TC-Full")
        grouped[(variant, row["operation"])].append(row)
        by_run[(variant, row["run_id"])].append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "variant",
            "operation",
            "samples",
            "mean_gas",
            "std_gas",
            "min_gas",
            "max_gas",
            "p50_gas",
            "p95_gas",
            "p99_gas",
            "percent_of_total",
            "mean_latency_ms",
            "p95_latency_ms",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        mean_total_by_variant: dict[str, float] = {}
        for (variant, _run_id), items in by_run.items():
            mean_total_by_variant.setdefault(variant, 0.0)
        for variant in list(mean_total_by_variant):
            totals = [
                sum(float(row["gas_used"]) for row in items)
                for (run_variant, _run_id), items in by_run.items()
                if run_variant == variant
            ]
            mean_total_by_variant[variant] = mean(totals) if totals else 0.0

        for (variant, operation), items in sorted(grouped.items()):
            gas = [float(row["gas_used"]) for row in items]
            latency = [float(row["latency_ms"]) for row in items]
            mean_gas = mean(gas)
            mean_total = mean_total_by_variant.get(variant, 0.0)
            writer.writerow(
                {
                    "variant": variant,
                    "operation": operation,
                    "samples": len(items),
                    "mean_gas": mean_gas,
                    "std_gas": pstdev(gas) if len(gas) > 1 else 0.0,
                    "min_gas": min(gas),
                    "max_gas": max(gas),
                    "p50_gas": percentile(gas, 50),
                    "p95_gas": percentile(gas, 95),
                    "p99_gas": percentile(gas, 99),
                    "percent_of_total": (mean_gas / mean_total * 100) if mean_total else 0.0,
                    "mean_latency_ms": mean(latency),
                    "p95_latency_ms": percentile(latency, 95),
                }
            )

        total_by_variant: dict[str, list[list[dict[str, str]]]] = defaultdict(list)
        for (variant, _run_id), items in by_run.items():
            total_by_variant[variant].append(items)

        for variant, runs in sorted(total_by_variant.items()):
            total_gas = [sum(float(row["gas_used"]) for row in items) for items in runs]
            total_latency = [sum(float(row["latency_ms"]) for row in items) for items in runs]
            writer.writerow(
                {
                    "variant": variant,
                    "operation": "TOTAL_PIPELINE",
                    "samples": len(total_gas),
                    "mean_gas": mean(total_gas),
                    "std_gas": pstdev(total_gas) if len(total_gas) > 1 else 0.0,
                    "min_gas": min(total_gas),
                    "max_gas": max(total_gas),
                    "p50_gas": percentile(total_gas, 50),
                    "p95_gas": percentile(total_gas, 95),
                    "p99_gas": percentile(total_gas, 99),
                    "percent_of_total": 100.0,
                    "mean_latency_ms": mean(total_latency),
                    "p95_latency_ms": percentile(total_latency, 95),
                }
            )
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("results/raw/contract_gas_benchmark.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/summary/contract_gas_summary.csv"))
    args = parser.parse_args()
    summarize(args.input, args.output)


if __name__ == "__main__":
    main()
