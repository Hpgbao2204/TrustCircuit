from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw" / "phase8"
PROCESSED = ROOT / "results" / "processed"


def read_csv(name: str) -> list[dict[str, str]]:
    path = RAW / name
    if not path.is_file():
        raise FileNotFoundError(f"missing raw experiment data: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, rows: list[dict[str, Any]]) -> Path:
    if not rows:
        raise ValueError(f"refusing to write empty processed CSV: {name}")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def percentile(values: Iterable[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        result.setdefault(row[key], []).append(row)
    return result


def summarize_ablation() -> list[Path]:
    raw = read_csv("e2e_ablation.csv")
    summary: list[dict[str, Any]] = []
    for variant, rows in group_by(raw, "variant").items():
        latencies = [float(row["total_latency_ms"]) for row in rows]
        gas = [float(row["total_gas"]) for row in rows]
        summary.append(
            {
                "variant": variant,
                "measurement_type": rows[0]["measurement_type"],
                "runs": len(rows),
                "mean_latency_ms": statistics.mean(latencies),
                "std_latency_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "p50_latency_ms": percentile(latencies, 50),
                "p95_latency_ms": percentile(latencies, 95),
                "mean_throughput_req_s": statistics.mean(
                    float(row["throughput_req_s"]) for row in rows
                ),
                "mean_total_gas": statistics.mean(gas),
                "success_rate": statistics.mean(float(row["success"]) for row in rows),
            }
        )
    variant_order = {
        name: index
        for index, name in enumerate(
            (
                "baseline_minimal",
                "access_only",
                "no_budget",
                "no_zk",
                "no_tee",
                "full_trustcircuit",
            )
        )
    }
    summary.sort(key=lambda row: variant_order[row["variant"]])
    full = [row for row in raw if row["variant"] == "full_trustcircuit"]
    stage_names = ("access", "budget", "tee", "proof", "settlement", "audit")
    stage_rows = [
        {
            "stage": stage,
            "measurement_type": "measured",
            "mean_latency_ms": statistics.mean(
                float(row[f"{stage}_latency_ms"]) for row in full
            ),
            "p95_latency_ms": percentile(
                [float(row[f"{stage}_latency_ms"]) for row in full], 95
            ),
        }
        for stage in stage_names
    ]
    gas_stage_names = ("access", "budget", "proof", "settlement", "audit")
    gas_rows = [
        {
            "stage": stage,
            "measurement_type": "measured_local_hardhat",
            "mean_gas": statistics.mean(
                float(row[f"{stage}_gas"]) for row in full
            ),
        }
        for stage in gas_stage_names
    ]
    return [
        write_csv("e2e_ablation_summary.csv", summary),
        write_csv("e2e_stage_breakdown.csv", stage_rows),
        write_csv("e2e_gas_breakdown.csv", gas_rows),
    ]


def summarize_vbs() -> list[Path]:
    raw = [row for row in read_csv("vbs_performance.csv") if row["is_warmup"] == "0"]
    summary: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    overhead: list[dict[str, Any]] = []
    for payload, rows in sorted(group_by(raw, "payload_bytes").items(), key=lambda item: int(item[0])):
        vbs = [float(row["vbs_process_wall_us"]) / 1000 for row in rows]
        reference = [float(row["reference_aggregate_us"]) / 1000 for row in rows]
        summary.append(
            {
                "payload_bytes": int(payload),
                "rows": int(rows[0]["rows"]),
                "runs": len(rows),
                "reference_name": "Python reference (native C++ unavailable)",
                "reference_mean_latency_ms": statistics.mean(reference),
                "vbs_mean_latency_ms": statistics.mean(vbs),
                "vbs_p95_latency_ms": percentile(vbs, 95),
                "slowdown_vs_python_reference": statistics.mean(
                    float(row["vbs_slowdown_vs_python_reference"]) for row in rows
                ),
                "vbs_throughput_mib_s": statistics.mean(
                    float(row["vbs_payload_throughput_mib_s"]) for row in rows
                ),
                "reference_throughput_mib_s": statistics.mean(
                    float(row["reference_payload_throughput_mib_s"]) for row in rows
                ),
                "host_peak_rss_mib": statistics.mean(
                    float(row["host_peak_rss_bytes"]) / (1024 * 1024) for row in rows
                ),
                "reference_rss_mib": statistics.mean(
                    float(row["python_reference_rss_bytes"]) / (1024 * 1024)
                    for row in rows
                ),
                "measurement_type": "measured",
            }
        )
        for stage in (
            "decrypt",
            "aggregate",
            "dp_noise",
            "transcript",
            "attestation_generation",
        ):
            stages.append(
                {
                    "payload_bytes": int(payload),
                    "stage": stage,
                    "mean_latency_us": statistics.mean(
                        float(row[f"{stage}_us"]) for row in rows
                    ),
                    "measurement_type": "measured_enclave_tsc",
                }
            )
        transcript = statistics.mean(float(row["transcript_us"]) for row in rows)
        generation = statistics.mean(
            float(row["attestation_generation_us"]) for row in rows
        )
        validation = statistics.mean(
            float(row["attestation_validation_host_us"]) for row in rows
        )
        overhead.append(
            {
                "payload_bytes": int(payload),
                "transcript_us": transcript,
                "attestation_generation_us": generation,
                "attestation_validation_host_us": validation,
                "combined_overhead_us": transcript + generation + validation,
                "measurement_type": "measured",
            }
        )
    return [
        write_csv("vbs_performance_summary.csv", summary),
        write_csv("vbs_stage_breakdown.csv", stages),
        write_csv("vbs_attestation_overhead.csv", overhead),
    ]


def summarize_dp() -> list[Path]:
    raw = [row for row in read_csv("dp_vbs.csv") if row["is_warmup"] == "0"]
    error_rows: list[dict[str, Any]] = []
    rounding_rows: list[dict[str, Any]] = []
    for epsilon, rows in sorted(group_by(raw, "epsilon_requested").items(), key=lambda item: float(item[0])):
        errors = [float(row["relative_error"]) for row in rows]
        gaps = [float(row["rounding_gap_fixed"]) for row in rows]
        error_rows.append(
            {
                "epsilon_requested": float(epsilon),
                "runs": len(rows),
                "mean_relative_error": statistics.mean(errors),
                "std_relative_error": statistics.stdev(errors) if len(errors) > 1 else 0,
                "p95_relative_error": percentile(errors, 95),
                "measurement_type": "measured",
            }
        )
        rounding_rows.append(
            {
                "epsilon_requested": float(epsilon),
                "runs": len(rows),
                "mean_rounding_gap_fixed": statistics.mean(gaps),
                "max_rounding_gap_fixed": max(gaps),
                "under_reporting_count": sum(gap < 0 for gap in gaps),
                "measurement_type": "measured",
            }
        )
    composition = read_csv("dp_composition.csv")
    exhaustion = read_csv("budget_exhaustion.csv")
    exhaustion_summary: list[dict[str, Any]] = []
    for epsilon, rows in sorted(group_by(exhaustion, "epsilon_requested").items(), key=lambda item: float(item[0])):
        exhaustion_summary.append(
            {
                "epsilon_requested": float(epsilon),
                "privacy_cost_fixed": rows[0]["privacy_cost_fixed"],
                "requests_attempted": len(rows),
                "accepted_requests": sum(int(row["accepted"]) for row in rows),
                "reverted_requests": sum(int(row["reverted"]) for row in rows),
                "budget_invariant_violations": sum(
                    int(row["budget_invariant_violations"]) for row in rows
                ),
                "measurement_type": "measured_local_hardhat",
            }
        )
    return [
        write_csv("dp_error_summary.csv", error_rows),
        write_csv("dp_rounding_summary.csv", rounding_rows),
        write_csv("dp_composition.csv", composition),
        write_csv("budget_exhaustion_summary.csv", exhaustion_summary),
    ]


def summarize_protocol() -> list[Path]:
    attacks = read_csv("protocol_attacks.csv")
    concurrency = read_csv("settlement_concurrency.csv")
    return [
        write_csv("protocol_attack_summary.csv", attacks),
        write_csv("settlement_concurrency_summary.csv", concurrency),
    ]


def summarize_zk() -> list[Path]:
    scaling = read_csv("zk_scaling.csv")
    backends = read_csv("zk_backends.csv")
    ablation = read_csv("e2e_ablation.csv")
    full = [row for row in ablation if row["variant"] == "full_trustcircuit"]
    base_without_proof = statistics.mean(
        float(row["total_latency_ms"]) - float(row["proof_latency_ms"])
        for row in full
    )
    circulation: list[dict[str, Any]] = []
    for row in backends:
        prove = float(row["prove_time_ms_mean"])
        verify = float(row["verify_time_ms_mean"])
        latency = base_without_proof + prove + verify
        circulation.append(
            {
                "scheme": row["scheme"],
                "base_measured_latency_ms": base_without_proof,
                "prove_time_ms": prove,
                "verify_time_ms": verify,
                "full_circulation_latency_ms": latency,
                "full_circulation_throughput_req_s": 1000 / latency,
                "measurement_type": "model_calibrated_from_measured_components",
            }
        )
    return [
        write_csv("zk_scaling.csv", scaling),
        write_csv("zk_backends.csv", backends),
        write_csv("zk_backend_circulation.csv", circulation),
    ]


def main() -> int:
    outputs: list[Path] = []
    for function in (
        summarize_ablation,
        summarize_vbs,
        summarize_dp,
        summarize_protocol,
        summarize_zk,
    ):
        outputs.extend(function())
    inventory = {
        "schema": "TrustCircuit.ProcessedExperimentInventory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_root": str(RAW.relative_to(ROOT)).replace("\\", "/"),
        "processed_files": [
            str(path.relative_to(ROOT)).replace("\\", "/") for path in outputs
        ],
        "measurement_labels": {
            "measured": "direct structured timing or local-chain receipt",
            "measured_enclave_tsc": "enclave TSC timing calibrated by the host",
            "analytical_from_measured_cost": "RDP formula using measured fixed-point cost",
            "model_calibrated_from_measured_components": "sum/substitution of separately measured components",
            "not_executed": "dependency/configuration absent; no number fabricated",
        },
    }
    (PROCESSED / "experiment_inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "processed_files": len(outputs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

