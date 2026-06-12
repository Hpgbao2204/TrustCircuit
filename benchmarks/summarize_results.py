"""Summarize and plot TrustCircuit benchmark CSV outputs."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

import numpy as np


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_summary(rows: list[dict[str, str]], output: Path) -> list[dict[str, str | float | int]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_run: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    all_by_variant: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        all_by_variant[row["variant"]].append(row)
        if row.get("success") != "true":
            continue
        grouped[(row["variant"], row["stage"])].append(row)
        by_run[(row["variant"], row["run_id"])].append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, str | float | int]] = []
    with output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "variant",
            "stage",
            "samples",
            "mean_latency_ms",
            "std_latency_ms",
            "p50_latency_ms",
            "p95_latency_ms",
            "p99_latency_ms",
            "mean_gas_used",
            "success_rate",
            "throughput_req_s",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for (variant, stage), values in sorted(grouped.items()):
            latencies = [float(row["latency_ms"]) for row in values]
            gas_values = [float(row["gas_used"]) for row in values if row["gas_used"]]
            summary = {
                "variant": variant,
                "stage": stage,
                "samples": len(values),
                "mean_latency_ms": mean(latencies),
                "std_latency_ms": pstdev(latencies) if len(latencies) > 1 else 0.0,
                "p50_latency_ms": percentile(latencies, 50),
                "p95_latency_ms": percentile(latencies, 95),
                "p99_latency_ms": percentile(latencies, 99),
                "mean_gas_used": mean(gas_values) if gas_values else 0.0,
                "success_rate": 1.0,
                "throughput_req_s": "",
            }
            writer.writerow(summary)
            summary_rows.append(summary)

        total_by_variant: dict[str, list[list[dict[str, str]]]] = defaultdict(list)
        for (variant, _run_id), values in by_run.items():
            total_by_variant[variant].append(values)

        for variant, runs in sorted(total_by_variant.items()):
            total_latencies = [sum(float(row["latency_ms"]) for row in run) for run in runs]
            total_gas = [sum(float(row["gas_used"]) for row in run if row["gas_used"]) for run in runs]
            all_rows = all_by_variant[variant]
            success_rate = sum(1 for row in all_rows if row.get("success") == "true") / max(len(all_rows), 1)
            mean_total_latency = mean(total_latencies)
            summary = {
                "variant": variant,
                "stage": "TOTAL_PIPELINE",
                "samples": len(runs),
                "mean_latency_ms": mean_total_latency,
                "std_latency_ms": pstdev(total_latencies) if len(total_latencies) > 1 else 0.0,
                "p50_latency_ms": percentile(total_latencies, 50),
                "p95_latency_ms": percentile(total_latencies, 95),
                "p99_latency_ms": percentile(total_latencies, 99),
                "mean_gas_used": mean(total_gas) if total_gas else 0.0,
                "success_rate": success_rate,
                "throughput_req_s": 1000 / mean_total_latency if mean_total_latency > 0 else 0.0,
            }
            writer.writerow(summary)
            summary_rows.append(summary)
    return summary_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("results/raw/e2e_pipeline.csv"))
    parser.add_argument("--summary", type=Path, default=Path("results/summary/e2e_pipeline_summary.csv"))
    args = parser.parse_args()

    rows = read_rows(args.input)
    write_summary(rows, args.summary)
    print(args.summary)


if __name__ == "__main__":
    main()
