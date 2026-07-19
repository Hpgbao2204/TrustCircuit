from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VBS_ROOT = ROOT / "tee" / "vbs"
sys.path.insert(0, str(VBS_ROOT))

from phase7_encoding import encode_phase7_context  # noqa: E402
from pipeline_client import execute_synthetic_request  # noqa: E402
from tests.vbs_reference import (  # noqa: E402
    FIXED_SCALE,
    conservative_privacy_cost_fixed,
    delta_to_fixed,
    epsilon_to_fixed,
    gaussian_noise_multiplier,
)


PAYLOAD_ROWS = (126, 510, 2046, 8190, 32766, 99998)
# The enclave deliberately rejects epsilon > 1.0; stay within its validated
# Phase 5 request bounds instead of weakening validation for an experiment.
EPSILON_GRID = (0.05, 0.1, 0.2, 0.25, 0.5, 1.0)
RDP_ORDERS = tuple(range(2, 65))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def percentile(values: Iterable[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * percentile_value / 100
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def repeated_rdp_epsilon(epsilon: float, delta: float, releases: int) -> float:
    multiplier = gaussian_noise_multiplier(
        epsilon_to_fixed(epsilon), delta_to_fixed(delta)
    )
    return min(
        releases * alpha / (2.0 * multiplier * multiplier)
        + math.log(1.0 / delta) / (alpha - 1.0)
        for alpha in RDP_ORDERS
    )


def performance_row(
    pipeline: dict[str, Any], *, run: int, warmup: bool
) -> dict[str, Any]:
    reference = pipeline["reference"]
    execution = pipeline["execution"]
    timings = execution["timings_us"]
    client = pipeline["client_timings_us"]
    payload_bytes = reference["plaintext_bytes"]
    wall_us = client["host_subprocess_wall"]
    return {
        "measurement_type": "measured",
        "run": run,
        "is_warmup": int(warmup),
        "rows": reference["rows"],
        "payload_bytes": payload_bytes,
        "reference_aggregate_us": client["reference_aggregate"],
        "vbs_process_wall_us": wall_us,
        "vbs_host_total_us": timings.get("host_total", 0),
        "enclave_call_us": timings.get("enclave_call", 0),
        "decrypt_us": timings.get("decrypt", 0),
        "aggregate_us": timings.get("aggregate", 0),
        "dp_noise_us": timings.get("dp_noise", 0),
        "transcript_us": timings.get("transcript", 0),
        "attestation_generation_us": timings.get("attestation", 0),
        "attestation_validation_host_us": timings.get(
            "attestation_validation_host", 0
        ),
        "attestation_validation_enclave_us": timings.get(
            "attestation_validation_enclave", 0
        ),
        "host_peak_rss_bytes": reference["host_peak_rss_bytes"],
        "python_reference_rss_bytes": reference["python_rss_bytes"],
        "vbs_payload_throughput_mib_s": (
            payload_bytes / (1024 * 1024) / (wall_us / 1_000_000)
            if wall_us
            else 0
        ),
        "reference_payload_throughput_mib_s": (
            payload_bytes
            / (1024 * 1024)
            / (max(client["reference_aggregate"], 1) / 1_000_000)
        ),
        "vbs_slowdown_vs_python_reference": wall_us
        / max(client["reference_aggregate"], 1),
        "ok": int(execution["ok"] is True),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run measured VBS payload, DP, and concurrency-fixture experiments."
    )
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--performance-reps", type=int, default=5)
    parser.add_argument("--privacy-reps", type=int, default=8)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--concurrency-bundles", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260719)
    args = parser.parse_args()
    if min(
        args.performance_reps,
        args.privacy_reps,
        args.warmups,
        args.concurrency_bundles,
    ) < 1:
        parser.error("all repetition counts must be positive")

    raw_root = ROOT / "results" / "raw" / "phase8"
    bundle_root = raw_root / "concurrency_bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    performance_rows: list[dict[str, Any]] = []
    for rows in PAYLOAD_ROWS:
        for run in range(args.warmups + args.performance_reps):
            warmup = run < args.warmups
            pipeline = execute_synthetic_request(
                vbs_root=VBS_ROOT,
                configuration=args.configuration,
                function_name="MEAN",
                rows=rows,
                seed=args.seed + run,
                epsilon=1.0,
                delta=0.00001,
                request_id=f"phase8-perf-{rows}-{run}-{time.time_ns()}",
                asset_id=f"asset-phase8-payload-{rows}",
                consumer_id="consumer-phase8-local",
            )
            performance_rows.append(
                performance_row(pipeline, run=run, warmup=warmup)
            )
        print(f"[phase8-vbs] payload rows={rows} complete", flush=True)
    write_csv(raw_root / "vbs_performance.csv", performance_rows)

    privacy_rows: list[dict[str, Any]] = []
    for epsilon in EPSILON_GRID:
        reference_cost = conservative_privacy_cost_fixed(
            epsilon_to_fixed(epsilon), delta_to_fixed(0.00001)
        )
        for run in range(args.warmups + args.privacy_reps):
            warmup = run < args.warmups
            pipeline = execute_synthetic_request(
                vbs_root=VBS_ROOT,
                configuration=args.configuration,
                function_name="MEAN",
                rows=1000,
                seed=args.seed,
                epsilon=epsilon,
                delta=0.00001,
                request_id=f"phase8-dp-{epsilon}-{run}-{time.time_ns()}",
                asset_id="asset-phase8-dp",
                consumer_id="consumer-phase8-local",
            )
            execution = pipeline["execution"]
            reference = pipeline["reference"]
            true_value = reference["true_result_fixed"]
            noisy_value = execution["result_fixed"]
            actual_cost = execution["actual_privacy_cost_fixed"]
            privacy_rows.append(
                {
                    "measurement_type": "measured",
                    "epsilon_requested": epsilon,
                    "delta_requested": 0.00001,
                    "run": run,
                    "is_warmup": int(warmup),
                    "rows": reference["rows"],
                    "true_result_fixed": true_value,
                    "noisy_result_fixed": noisy_value,
                    "absolute_error_fixed": abs(noisy_value - true_value),
                    "relative_error": abs(noisy_value - true_value)
                    / max(abs(true_value), 1),
                    "actual_privacy_cost_fixed": actual_cost,
                    "python_reference_cost_fixed": reference_cost,
                    "rounding_gap_fixed": actual_cost - reference_cost,
                    "host_wall_us": pipeline["client_timings_us"][
                        "host_subprocess_wall"
                    ],
                    "ok": int(execution["ok"] is True),
                }
            )
        print(f"[phase8-vbs] epsilon={epsilon} complete", flush=True)
    write_csv(raw_root / "dp_vbs.csv", privacy_rows)

    composition_rows: list[dict[str, Any]] = []
    for epsilon in EPSILON_GRID:
        fixed_costs = [
            int(row["actual_privacy_cost_fixed"])
            for row in privacy_rows
            if not row["is_warmup"] and row["epsilon_requested"] == epsilon
        ]
        conservative_cost = max(fixed_costs)
        for releases in range(1, 33):
            reference_epsilon = repeated_rdp_epsilon(
                epsilon, 0.00001, releases
            )
            conservative_epsilon = releases * conservative_cost / FIXED_SCALE
            composition_rows.append(
                {
                    "measurement_type": "analytical_from_measured_cost",
                    "epsilon_requested": epsilon,
                    "delta": 0.00001,
                    "releases": releases,
                    "rdp_reference_epsilon": reference_epsilon,
                    "conservative_fixed_epsilon": conservative_epsilon,
                    "rounding_gap_epsilon": conservative_epsilon
                    - reference_epsilon,
                    "per_release_cost_fixed": conservative_cost,
                }
            )
    write_csv(raw_root / "dp_composition.csv", composition_rows)

    bundle_manifest: list[dict[str, Any]] = []
    for index in range(args.concurrency_bundles):
        pipeline = execute_synthetic_request(
            vbs_root=VBS_ROOT,
            configuration=args.configuration,
            function_name="MEAN",
            rows=64,
            seed=args.seed,
            epsilon=1.0,
            delta=0.00001,
            request_id=f"phase8-concurrency-{index}-{time.time_ns()}",
            asset_id="asset-phase8-concurrency",
            consumer_id="consumer-phase8-local",
        )
        phase7 = encode_phase7_context(pipeline["request"], pipeline["execution"])
        bundle = {
            "schema": "TrustCircuit.Phase7Bundle.v1",
            "measurement_type": "measured",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **pipeline,
            "phase7": phase7,
        }
        bundle_path = bundle_root / f"bundle_{index:02d}.json"
        bundle_path.write_text(
            json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8"
        )
        bundle_manifest.append(
            {
                "index": index,
                "path": str(bundle_path.relative_to(ROOT)).replace("\\", "/"),
                "request_id": pipeline["request"]["request_id"],
                "request_key": phase7["request_key"],
                "transcript_hash": pipeline["execution"]["transcript_hash"],
                "attestation_digest": phase7["attestation_digest"],
                "expires_at_unix_ms": phase7[
                    "attestation_expires_at_unix_ms"
                ],
            }
        )
    (raw_root / "concurrency_bundle_manifest.json").write_text(
        json.dumps(bundle_manifest, indent=2), encoding="utf-8"
    )

    measured_performance = [row for row in performance_rows if not row["is_warmup"]]
    config = {
        "schema": "TrustCircuit.Phase8VbsExperimentConfig.v1",
        "measurement_type": "measured",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": bool(git_value("status", "--porcelain")),
        "os": platform.platform(),
        "processor": platform.processor()
        or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "configuration": args.configuration,
        "seed": args.seed,
        "warmups": args.warmups,
        "performance_reps": args.performance_reps,
        "privacy_reps": args.privacy_reps,
        "payload_rows": PAYLOAD_ROWS,
        "epsilon_grid": EPSILON_GRID,
        "concurrency_bundles": args.concurrency_bundles,
        "duration_seconds": time.perf_counter() - started,
        "sanity": {
            "performance_success_rate": statistics.mean(
                row["ok"] for row in measured_performance
            ),
            "privacy_success_rate": statistics.mean(
                row["ok"] for row in privacy_rows if not row["is_warmup"]
            ),
        },
        "native_baseline_limitation": (
            "The repository has no non-enclave native C++ processor. "
            "reference_aggregate_us is the measured Python reference and is "
            "never labeled as a native C++ measurement."
        ),
    }
    (raw_root / "vbs_experiment_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "raw_root": str(raw_root),
                "performance_rows": len(performance_rows),
                "privacy_rows": len(privacy_rows),
                "concurrency_bundles": len(bundle_manifest),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
