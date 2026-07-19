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
    stage_matrix_rows: list[dict[str, Any]] = []
    gas_matrix_rows: list[dict[str, Any]] = []
    stage_names = ("access", "budget", "tee", "proof", "settlement", "audit")
    gas_stage_names = ("access", "budget", "proof", "settlement", "audit")
    for variant, rows in group_by(raw, "variant").items():
        latencies = [float(row["total_latency_ms"]) for row in rows]
        gas = [float(row["total_gas"]) for row in rows]
        throughputs = [float(row["throughput_req_s"]) for row in rows]
        summary.append(
            {
                "variant": variant,
                "measurement_type": rows[0]["measurement_type"],
                "runs": len(rows),
                "mean_latency_ms": statistics.mean(latencies),
                "std_latency_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "p50_latency_ms": percentile(latencies, 50),
                "p95_latency_ms": percentile(latencies, 95),
                "mean_throughput_req_s": statistics.mean(throughputs),
                "std_throughput_req_s": statistics.stdev(throughputs)
                if len(throughputs) > 1
                else 0,
                "p50_throughput_req_s": percentile(throughputs, 50),
                "p95_throughput_req_s": percentile(throughputs, 95),
                "mean_total_gas": statistics.mean(gas),
                "success_rate": statistics.mean(float(row["success"]) for row in rows),
            }
        )
        for stage in stage_names:
            values = [float(row[f"{stage}_latency_ms"]) for row in rows]
            stage_matrix_rows.append(
                {
                    "variant": variant,
                    "stage": stage,
                    "runs": len(rows),
                    "mean_latency_ms": statistics.mean(values),
                    "p95_latency_ms": percentile(values, 95),
                    "measurement_type": rows[0]["measurement_type"],
                }
            )
        for stage in gas_stage_names:
            values = [float(row[f"{stage}_gas"]) for row in rows]
            gas_matrix_rows.append(
                {
                    "variant": variant,
                    "stage": stage,
                    "runs": len(rows),
                    "mean_gas": statistics.mean(values),
                    "measurement_type": rows[0]["measurement_type"],
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
        write_csv("e2e_stage_by_variant.csv", stage_matrix_rows),
        write_csv("e2e_gas_by_variant.csv", gas_matrix_rows),
    ]


def summarize_vbs() -> list[Path]:
    raw = [
        row
        for row in read_csv("native_vbs_performance.csv")
        if row["is_warmup"] == "0"
    ]
    summary: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    overhead_trials: list[dict[str, Any]] = []
    for payload, rows in sorted(
        group_by(raw, "payload_bytes").items(), key=lambda item: int(item[0])
    ):
        native = [float(row["native_process_wall_us"]) / 1000 for row in rows]
        vbs = [float(row["vbs_process_wall_us"]) / 1000 for row in rows]
        native_throughput = [
            float(row["native_payload_throughput_mib_s"]) for row in rows
        ]
        vbs_throughput = [
            float(row["vbs_payload_throughput_mib_s"]) for row in rows
        ]
        slowdowns = [float(row["vbs_slowdown_vs_native"]) for row in rows]
        native_rss = [
            float(row["native_peak_rss_bytes"]) / (1024 * 1024) for row in rows
        ]
        vbs_rss = [
            float(row["vbs_peak_rss_bytes"]) / (1024 * 1024) for row in rows
        ]
        summary.append(
            {
                "payload_bytes": int(payload),
                "rows": int(rows[0]["rows"]),
                "runs": len(rows),
                "native_mean_latency_ms": statistics.mean(native),
                "native_std_latency_ms": statistics.stdev(native),
                "native_p2_5_latency_ms": percentile(native, 2.5),
                "native_p50_latency_ms": percentile(native, 50),
                "native_p95_latency_ms": percentile(native, 95),
                "native_p97_5_latency_ms": percentile(native, 97.5),
                "vbs_mean_latency_ms": statistics.mean(vbs),
                "vbs_std_latency_ms": statistics.stdev(vbs),
                "vbs_p2_5_latency_ms": percentile(vbs, 2.5),
                "vbs_p50_latency_ms": percentile(vbs, 50),
                "vbs_p95_latency_ms": percentile(vbs, 95),
                "vbs_p97_5_latency_ms": percentile(vbs, 97.5),
                "slowdown_mean": statistics.mean(slowdowns),
                "slowdown_p2_5": percentile(slowdowns, 2.5),
                "slowdown_p50": percentile(slowdowns, 50),
                "slowdown_p95": percentile(slowdowns, 95),
                "slowdown_p97_5": percentile(slowdowns, 97.5),
                "native_throughput_mean_mib_s": statistics.mean(native_throughput),
                "native_throughput_p2_5_mib_s": percentile(native_throughput, 2.5),
                "native_throughput_p50_mib_s": percentile(native_throughput, 50),
                "native_throughput_p97_5_mib_s": percentile(native_throughput, 97.5),
                "vbs_throughput_mean_mib_s": statistics.mean(vbs_throughput),
                "vbs_throughput_p2_5_mib_s": percentile(vbs_throughput, 2.5),
                "vbs_throughput_p50_mib_s": percentile(vbs_throughput, 50),
                "vbs_throughput_p97_5_mib_s": percentile(vbs_throughput, 97.5),
                "native_rss_mean_mib": statistics.mean(native_rss),
                "native_rss_p2_5_mib": percentile(native_rss, 2.5),
                "native_rss_p50_mib": percentile(native_rss, 50),
                "native_rss_p97_5_mib": percentile(native_rss, 97.5),
                "vbs_rss_mean_mib": statistics.mean(vbs_rss),
                "vbs_rss_p2_5_mib": percentile(vbs_rss, 2.5),
                "vbs_rss_p50_mib": percentile(vbs_rss, 50),
                "vbs_rss_p97_5_mib": percentile(vbs_rss, 97.5),
                "result_parity_rate": statistics.mean(
                    float(row["result_parity"]) for row in rows
                ),
                "measurement_type": "measured_paired",
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
                        float(row[f"vbs_{stage}_us"]) for row in rows
                    ),
                    "p50_latency_us": percentile(
                        [float(row[f"vbs_{stage}_us"]) for row in rows], 50
                    ),
                    "p95_latency_us": percentile(
                        [float(row[f"vbs_{stage}_us"]) for row in rows], 95
                    ),
                    "measurement_type": "measured_enclave_tsc",
                }
            )
        for row in rows:
            total_us = float(row["vbs_process_wall_us"]) + float(
                row["vbs_validation_wall_us"]
            )
            for stage, source_field in (
                ("Transcript", "vbs_transcript_us"),
                ("Evidence generation", "vbs_attestation_generation_us"),
                ("External validation", "vbs_validation_wall_us"),
            ):
                latency_us = float(row[source_field])
                overhead_trials.append(
                    {
                        "payload_bytes": int(payload),
                        "run": int(row["run"]),
                        "stage": stage,
                        "latency_us": latency_us,
                        "total_validated_vbs_us": total_us,
                        "percent_of_total_vbs_latency": 100 * latency_us / total_us,
                        "measurement_type": "measured_paired",
                    }
                )
    return [
        write_csv("vbs_performance_summary.csv", summary),
        write_csv("vbs_stage_breakdown.csv", stages),
        write_csv("vbs_attestation_overhead.csv", overhead_trials),
    ]


def summarize_dp() -> list[Path]:
    raw = [row for row in read_csv("dp_vbs.csv") if row["is_warmup"] == "0"]
    error_rows: list[dict[str, Any]] = []
    for epsilon, rows in sorted(group_by(raw, "epsilon_requested").items(), key=lambda item: float(item[0])):
        errors = [float(row["relative_error"]) for row in rows]
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
    rounding = read_csv("dp_rounding_boundaries.csv")
    rounding_values = [float(row["rounding_margin_micro_epsilon"]) for row in rounding]
    rounding_summary = [
        {
            "samples": len(rounding),
            "minimum_margin_micro_epsilon": min(rounding_values),
            "p50_margin_micro_epsilon": percentile(rounding_values, 50),
            "p95_margin_micro_epsilon": percentile(rounding_values, 95),
            "maximum_margin_micro_epsilon": max(rounding_values),
            "zero_margin_count": sum(value == 0 for value in rounding_values),
            "under_reporting_count": sum(int(row["under_reporting"]) for row in rounding),
            "measurement_type": "measured_with_analytical_margin",
        }
    ]
    composition = read_csv("dp_composition.csv")
    exhaustion = read_csv("budget_exhaustion.csv")
    exhaustion_trajectory: list[dict[str, Any]] = []
    exhaustion_summary: list[dict[str, Any]] = []
    for epsilon, rows in sorted(group_by(exhaustion, "epsilon_requested").items(), key=lambda item: float(item[0])):
        ordered_rows = sorted(rows, key=lambda row: int(row["request_index"]))
        cumulative_accepted = 0
        for row in ordered_rows:
            cumulative_accepted += int(row["accepted"])
            exhaustion_trajectory.append(
                {
                    **row,
                    "cumulative_accepted_requests": cumulative_accepted,
                }
            )
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
        write_csv("dp_rounding_margin.csv", rounding),
        write_csv("dp_rounding_summary.csv", rounding_summary),
        write_csv("dp_composition.csv", composition),
        write_csv("budget_exhaustion_trajectory.csv", exhaustion_trajectory),
        write_csv("budget_exhaustion_summary.csv", exhaustion_summary),
    ]


def summarize_protocol() -> list[Path]:
    attacks = read_csv("protocol_attacks.csv")
    concurrency = read_csv("settlement_concurrency.csv")
    attack_summary: list[dict[str, Any]] = []
    for attack_case, rows in group_by(attacks, "attack_case").items():
        latencies = [float(row["latency_ms"]) for row in rows]
        attack_summary.append(
            {
                "category": rows[0]["category"],
                "attack_case": attack_case,
                "runs": len(rows),
                "rejection_rate": statistics.mean(float(row["rejected"]) for row in rows),
                "mean_rejection_latency_ms": statistics.mean(latencies),
                "p2_5_rejection_latency_ms": percentile(latencies, 2.5),
                "p50_rejection_latency_ms": percentile(latencies, 50),
                "p95_rejection_latency_ms": percentile(latencies, 95),
                "p97_5_rejection_latency_ms": percentile(latencies, 97.5),
                "budget_invariant_violations": sum(
                    int(row["budget_invariant_violation"]) for row in rows
                ),
                "measurement_type": "measured_local_hardhat",
            }
        )
    attack_summary.sort(key=lambda row: (row["category"], row["attack_case"]))
    concurrency_summary: list[dict[str, Any]] = []
    for level, rows in sorted(
        group_by(concurrency, "concurrency").items(), key=lambda item: int(item[0])
    ):
        latencies = [float(row["settlement_mean_latency_ms"]) for row in rows]
        concurrency_summary.append(
            {
                "concurrency": int(level),
                "runs": len(rows),
                "mean_accepted": statistics.mean(float(row["accepted"]) for row in rows),
                "mean_reverted": statistics.mean(float(row["reverted"]) for row in rows),
                "mean_settlement_latency_ms": statistics.mean(latencies),
                "p2_5_settlement_latency_ms": percentile(latencies, 2.5),
                "p50_settlement_latency_ms": percentile(latencies, 50),
                "p95_settlement_latency_ms": percentile(latencies, 95),
                "p97_5_settlement_latency_ms": percentile(latencies, 97.5),
                "mean_throughput_req_s": statistics.mean(
                    float(row["throughput_req_s"]) for row in rows
                ),
                "budget_invariant_violations": sum(
                    int(row["budget_invariant_violations"]) for row in rows
                ),
                "measurement_type": "measured_local_hardhat",
            }
        )
    binding = read_csv("attack_binding_matrix.csv")
    return [
        write_csv("protocol_attack_latency.csv", attacks),
        write_csv("protocol_attack_summary.csv", attack_summary),
        write_csv("attack_binding_matrix.csv", binding),
        write_csv("settlement_concurrency_trials.csv", concurrency),
        write_csv("settlement_concurrency_summary.csv", concurrency_summary),
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
            "measured_paired": "paired Native/VBS executions over byte-identical payloads",
            "measured_enclave_tsc": "enclave TSC timing calibrated by the host",
            "measured_with_analytical_margin": "measured fixed-point output minus its unsmoothed analytical value",
            "measured_local_hardhat": "direct local Hardhat receipt or high-resolution wall timing",
            "functional_test_evidence": "first-rejecting-layer classification backed by named passing tests",
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
