"""Derive three deployment-profile views from the existing Phase 8 ablation runs.

This script never synthesizes timing values. It filters and renames three variants
that were measured by the same harness/configuration, then recomputes statistics
from those saved per-run rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "results" / "raw" / "phase8" / "e2e_ablation.csv"
DEFAULT_SOURCE_CONFIG = (
    ROOT / "results" / "raw" / "phase8" / "chain_experiment_config.json"
)
DEFAULT_OUTPUT = ROOT / "results" / "deployment_profiles"

PROFILE_MAP = {
    "access_only": "TC-Lite",
    "no_zk": "TC-Protected",
    "full_trustcircuit": "TC-Full",
}

CAPABILITIES = [
    {
        "profile": "TC-Lite",
        "tee": 0,
        "dp_budget": 0,
        "zkp": 0,
        "on_chain_audit": 1,
        "guarantee_score": 1,
        "main_guarantee": "Authorized and auditable access",
    },
    {
        "profile": "TC-Protected",
        "tee": 1,
        "dp_budget": 1,
        "zkp": 0,
        "on_chain_audit": 1,
        "guarantee_score": 3,
        "main_guarantee": "Confidential execution and budget control",
    },
    {
        "profile": "TC-Full",
        "tee": 1,
        "dp_budget": 1,
        "zkp": 1,
        "on_chain_audit": 1,
        "guarantee_score": 4,
        "main_guarantee": "Verifiable policy and budget binding",
    },
]

NUMERIC_FIELDS = [
    "total_latency_ms",
    "throughput_req_s",
    "total_gas",
    "access_latency_ms",
    "budget_latency_ms",
    "tee_latency_ms",
    "proof_latency_ms",
    "settlement_latency_ms",
    "audit_latency_ms",
    "process_cpu_time_ms",
    "normalized_peak_cpu_percent",
    "peak_working_set_bytes",
    "peak_private_bytes",
]

SUMMARY_METRICS = [
    "total_latency_ms",
    "throughput_req_s",
    "total_gas",
    "proof_latency_ms",
    "normalized_peak_cpu_percent",
    "peak_working_set_bytes",
]

STAGES = [
    "access_latency_ms",
    "budget_latency_ms",
    "tee_latency_ms",
    "proof_latency_ms",
    "settlement_latency_ms",
    "audit_latency_ms",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260721)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_mean_ci(
    values: list[float], samples: int, rng: random.Random
) -> tuple[float, float]:
    means = []
    count = len(values)
    for _ in range(samples):
        means.append(statistics.fmean(values[rng.randrange(count)] for _ in range(count)))
    return percentile(means, 0.025), percentile(means, 0.975)


def write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))

    selected = []
    for row in source_rows:
        source_variant = row["variant"]
        if source_variant not in PROFILE_MAP or row["is_warmup"] != "0":
            continue
        if row["success"] != "1":
            raise ValueError(
                f"Source contains failed row: {source_variant} run={row['run']}"
            )
        converted = dict(row)
        converted["profile"] = PROFILE_MAP[source_variant]
        converted["source_variant"] = source_variant
        converted["measurement_type"] = "reused_local_measurement"
        converted["source_measurement_type"] = row["measurement_type"]
        converted["network_bytes"] = ""
        selected.append(converted)

    expected = set(PROFILE_MAP.values())
    observed = {row["profile"] for row in selected}
    if observed != expected:
        raise ValueError(f"Missing profiles: {sorted(expected - observed)}")

    config_hashes = {row["config_hash"] for row in selected}
    if len(config_hashes) != 1:
        raise ValueError(f"Profiles do not share one config hash: {config_hashes}")

    counts = {
        profile: sum(row["profile"] == profile for row in selected)
        for profile in expected
    }
    if len(set(counts.values())) != 1 or min(counts.values()) < 30:
        raise ValueError(f"Need balanced >=30-run profiles, got {counts}")

    selected.sort(key=lambda row: (list(PROFILE_MAP.values()).index(row["profile"]), int(row["run"])))
    return selected


def summarize(
    rows: list[dict], bootstrap_samples: int, bootstrap_seed: int
) -> tuple[list[dict], list[dict]]:
    summary_rows = []
    stage_rows = []
    rng = random.Random(bootstrap_seed)
    capability_by_profile = {item["profile"]: item for item in CAPABILITIES}

    for profile in PROFILE_MAP.values():
        profile_rows = [row for row in rows if row["profile"] == profile]
        summary = {
            "profile": profile,
            "source_variant": profile_rows[0]["source_variant"],
            "measurement_type": "reused_local_measurement",
            "runs": len(profile_rows),
            "config_hash": profile_rows[0]["config_hash"],
            "guarantee_score": capability_by_profile[profile]["guarantee_score"],
        }
        for metric in SUMMARY_METRICS:
            values = [float(row[metric]) for row in profile_rows]
            low, high = bootstrap_mean_ci(values, bootstrap_samples, rng)
            summary[f"mean_{metric}"] = statistics.fmean(values)
            summary[f"median_{metric}"] = statistics.median(values)
            summary[f"std_{metric}"] = statistics.stdev(values)
            summary[f"p95_{metric}"] = percentile(values, 0.95)
            summary[f"ci95_low_{metric}"] = low
            summary[f"ci95_high_{metric}"] = high
        summary_rows.append(summary)

        for stage in STAGES:
            values = [float(row[stage]) for row in profile_rows]
            low, high = bootstrap_mean_ci(values, bootstrap_samples, rng)
            stage_rows.append(
                {
                    "profile": profile,
                    "stage": stage.removesuffix("_latency_ms"),
                    "runs": len(values),
                    "mean_latency_ms": statistics.fmean(values),
                    "median_latency_ms": statistics.median(values),
                    "std_latency_ms": statistics.stdev(values),
                    "p95_latency_ms": percentile(values, 0.95),
                    "ci95_low_latency_ms": low,
                    "ci95_high_latency_ms": high,
                }
            )
    return summary_rows, stage_rows


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    source_config_path = args.source_config.resolve()
    output = args.output.resolve()
    rows = load_rows(source)
    summary_rows, stage_rows = summarize(
        rows, args.bootstrap_samples, args.bootstrap_seed
    )

    raw_fields = [
        "measurement_type",
        "source_measurement_type",
        "timestamp_utc",
        "config_hash",
        "profile",
        "source_variant",
        "run",
        "is_warmup",
        *NUMERIC_FIELDS,
        "network_bytes",
        "success",
        "failure_status",
    ]
    write_csv(output / "raw" / "deployment_profile_trials.csv", rows, raw_fields)
    write_csv(
        output / "summary" / "deployment_profile_summary.csv",
        summary_rows,
        list(summary_rows[0]),
    )
    write_csv(
        output / "summary" / "deployment_profile_stage_summary.csv",
        stage_rows,
        list(stage_rows[0]),
    )
    write_csv(
        output / "summary" / "deployment_profile_capabilities.csv",
        CAPABILITIES,
        list(CAPABILITIES[0]),
    )

    with source_config_path.open(encoding="utf-8") as handle:
        source_config = json.load(handle)
    derived_config = {
        "schema": "TrustCircuit.DeploymentProfilesReused.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "measurement_type": "reused_local_measurement",
        "source_csv": source.relative_to(ROOT).as_posix(),
        "source_csv_sha256": sha256_file(source),
        "source_config": source_config_path.relative_to(ROOT).as_posix(),
        "source_config_hash": source_config.get("config_hash"),
        "source_git_commit": source_config.get("git_commit"),
        "source_environment": {
            "platform": source_config.get("platform"),
            "cpu": source_config.get("cpu"),
            "logical_cpus": source_config.get("logical_cpus"),
        },
        "runs_per_profile": len(rows) // len(PROFILE_MAP),
        "warmups_in_source_excluded": True,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.bootstrap_seed,
        "profile_mapping": PROFILE_MAP,
        "limitations": [
            "No new VBS execution was performed.",
            "TC-Lite reuses access_only, whose recurring timer covers registry, access control, and audit but not CP-ABE/AES payload cryptography.",
            "Network-byte counts were not present in the source CSV and remain unavailable.",
            "Peak RSS and CPU are host benchmark-process counters, not enclave-only counters.",
        ],
    }
    config_path = output / "summary" / "deployment_profile_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(derived_config, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} reused trial rows to {output}")


if __name__ == "__main__":
    main()
