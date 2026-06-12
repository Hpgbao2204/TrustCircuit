"""Worker-pool benchmark for the TrustCircuit TEE simulator."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from statistics import mean, pstdev

import numpy as np

from worker_sim import VALID_MODES, assign_worker, build_request, run_worker, write_report


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def run(args: argparse.Namespace) -> None:
    raw_rows: list[dict[str, str | int | float | bool]] = []
    for pool_size in args.pool_sizes:
        for mode in args.modes:
            output_dir = args.tmp_dir / f"pool_{pool_size}" / mode
            for i in range(args.requests):
                request_id = f"REQ_{pool_size}_{mode}_{i:04d}"
                request = build_request(request_id, args.asset_id, args.epsilon)
                assign_start = time.perf_counter()
                worker_id = assign_worker(request_id, pool_size)
                assignment_latency_ms = (time.perf_counter() - assign_start) * 1000
                report = run_worker(request, worker_id, mode, output_dir)
                write_report(report, output_dir)
                raw_rows.append(
                    {
                        "pool_size": pool_size,
                        "mode": mode,
                        "request_id": request.requestId,
                        "worker_id": worker_id,
                        "assignment_latency_ms": assignment_latency_ms,
                        "compute_latency_ms": report.latencyMs,
                        "latency_ms": report.latencyMs,
                        "accepted": report.acceptedBySimulator,
                        "failed": not report.acceptedBySimulator,
                        "fallback_count": 0 if report.acceptedBySimulator else 1,
                        "epsilon_cost": report.epsilonCost,
                    }
                )

    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    with args.raw_output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "pool_size",
            "mode",
            "request_id",
            "worker_id",
            "assignment_latency_ms",
            "compute_latency_ms",
            "latency_ms",
            "accepted",
            "failed",
            "fallback_count",
            "epsilon_cost",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(raw_rows)

    grouped: dict[tuple[int, str], list[dict[str, str | int | float | bool]]] = {}
    for row in raw_rows:
        grouped.setdefault((int(row["pool_size"]), str(row["mode"])), []).append(row)

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    with args.summary_output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "pool_size",
            "mode",
            "requests",
            "assignment_latency_mean_ms",
            "assignment_latency_p95_ms",
            "compute_latency_mean_ms",
            "compute_latency_std_ms",
            "compute_latency_p50_ms",
            "compute_latency_p95_ms",
            "compute_latency_p99_ms",
            "success_rate",
            "failed_count",
            "fallback_count",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for (pool_size, mode), rows in sorted(grouped.items()):
            assignment_latencies = [float(row["assignment_latency_ms"]) for row in rows]
            compute_latencies = [float(row["compute_latency_ms"]) for row in rows]
            accepted_rate = sum(1 for row in rows if row["accepted"] is True) / len(rows)
            failed_count = sum(1 for row in rows if row["failed"] is True)
            fallback_count = sum(int(row["fallback_count"]) for row in rows)
            writer.writerow(
                {
                    "pool_size": pool_size,
                    "mode": mode,
                    "requests": len(rows),
                    "assignment_latency_mean_ms": mean(assignment_latencies),
                    "assignment_latency_p95_ms": percentile(assignment_latencies, 95),
                    "compute_latency_mean_ms": mean(compute_latencies),
                    "compute_latency_std_ms": pstdev(compute_latencies) if len(compute_latencies) > 1 else 0.0,
                    "compute_latency_p50_ms": percentile(compute_latencies, 50),
                    "compute_latency_p95_ms": percentile(compute_latencies, 95),
                    "compute_latency_p99_ms": percentile(compute_latencies, 99),
                    "success_rate": accepted_rate,
                    "failed_count": failed_count,
                    "fallback_count": fallback_count,
                }
            )

    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_text(
        json.dumps(
            {
                "asset_id": args.asset_id,
                "epsilon": args.epsilon,
                "requests": args.requests,
                "pool_sizes": args.pool_sizes,
                "modes": args.modes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.raw_output)
    print(args.summary_output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-id", default="ASSET_001")
    parser.add_argument("--epsilon", type=int, default=500_000)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--pool-sizes", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--modes", choices=VALID_MODES, nargs="+", default=["honest", "wrong_result", "under_report_epsilon"])
    parser.add_argument("--raw-output", type=Path, default=Path("results/raw/tee_pool.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("results/summary/tee_pool_summary.csv"))
    parser.add_argument("--config-output", type=Path, default=Path("results/summary/tee_pool_config.json"))
    parser.add_argument("--tmp-dir", type=Path, default=Path("results/tmp/tee_pool"))
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
