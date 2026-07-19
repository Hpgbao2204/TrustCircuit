from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VBS_ROOT = ROOT / "tee" / "vbs"
sys.path.insert(0, str(VBS_ROOT))

from phase7_encoding import encode_phase7_context  # noqa: E402
from attestation_validator import attach_validated_attestation  # noqa: E402
from pipeline_client import (  # noqa: E402
    _run_with_process_metrics,
    execute_synthetic_request,
    host_path,
)
from tests.vbs_reference import (  # noqa: E402
    FIXED_SCALE,
    aes_256_gcm_encrypt,
    aggregate_reference,
    build_canonical_aad,
    conservative_privacy_cost_fixed,
    delta_to_fixed,
    encode_dataset,
    epsilon_to_fixed,
    gaussian_noise_multiplier,
    make_request,
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


def native_path(vbs_root: Path, configuration: str) -> Path:
    value = vbs_root / "x64" / configuration / "TrustCircuitNative.exe"
    if not value.is_file():
        raise FileNotFoundError(f"missing Native processor: {value}")
    return value


def invoke_json_processor(
    binary: Path, request_path: Path
) -> tuple[dict[str, Any], dict[str, int | float]]:
    completed, process_metrics = _run_with_process_metrics(
        [str(binary), str(request_path)], cwd=binary.parent, timeout=30
    )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{binary.name} did not emit JSON") from error
    if completed.returncode != 0 or response.get("ok") is not True:
        raise RuntimeError(
            f"{binary.name} rejected paired benchmark input: "
            f"{completed.stderr.strip()}"
        )
    return response, process_metrics


def exact_privacy_cost_epsilon(
    epsilon_requested_fixed: int, delta_requested_fixed: int
) -> float:
    multiplier = gaussian_noise_multiplier(
        epsilon_requested_fixed, delta_requested_fixed
    )
    delta = delta_requested_fixed / 1_000_000_000_000
    minimum_rdp = min(
        alpha / (2.0 * multiplier * multiplier)
        + math.log(1.0 / delta) / (alpha - 1.0)
        for alpha in RDP_ORDERS
    )
    return max(epsilon_requested_fixed / FIXED_SCALE, minimum_rdp)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run measured VBS payload, DP, and concurrency-fixture experiments."
    )
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--performance-reps", type=int, default=30)
    parser.add_argument("--privacy-reps", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--concurrency-bundles", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260719)
    args = parser.parse_args()
    if args.performance_reps < 30 or args.privacy_reps < 30:
        parser.error(
            "Phase 8 retains at least 30 measured runs for performance and privacy experiments"
        )
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
    vbs_host = host_path(VBS_ROOT, args.configuration)
    native_host = native_path(VBS_ROOT, args.configuration)
    config_identity = {
        "schema": "TrustCircuit.Phase8MeasurementConfig.v2",
        "configuration": args.configuration,
        "performance_reps": args.performance_reps,
        "privacy_reps": args.privacy_reps,
        "warmups": args.warmups,
        "concurrency_bundles": args.concurrency_bundles,
        "seed": args.seed,
        "payload_rows": PAYLOAD_ROWS,
        "epsilon_grid": EPSILON_GRID,
    }
    config_hash = hashlib.sha256(
        json.dumps(config_identity, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    performance_rows: list[dict[str, Any]] = []
    for rows in PAYLOAD_ROWS:
        for run in range(args.warmups + args.performance_reps):
            warmup = run < args.warmups
            seed = args.seed + run
            generator = random.Random(seed)
            values = [generator.randint(0, 100) * FIXED_SCALE for _ in range(rows)]
            plaintext = encode_dataset(values)
            payload_sha256 = hashlib.sha256(plaintext).hexdigest()
            expected_result = aggregate_reference(2, values)
            with tempfile.TemporaryDirectory(
                prefix="trustcircuit-native-vbs-"
            ) as temporary:
                directory = Path(temporary)
                ciphertext_path = directory / "dataset.enc"
                request, _ = make_request(
                    ciphertext_path,
                    plaintext,
                    2,
                    0,
                    100 * FIXED_SCALE,
                    int(time.time() * 1000) + 300_000,
                    apply_dp=False,
                    key=os.urandom(32),
                    nonce=os.urandom(12),
                )
                request.update(
                    {
                        "request_id": (
                            f"phase8-paired-{rows}-{run}-{time.time_ns()}"
                        ),
                        "asset_id": f"asset-phase8-payload-{rows}",
                        "consumer_id": "consumer-phase8-local",
                        "policy_hash": hashlib.sha256(
                            b"TrustCircuit.Phase8.NativeVbs.Policy.v1"
                        ).hexdigest(),
                        "policy_version": 1,
                    }
                )
                aad = build_canonical_aad(request)
                ciphertext, tag = aes_256_gcm_encrypt(
                    bytes.fromhex(str(request["key_hex"])),
                    bytes.fromhex(str(request["nonce"])),
                    aad,
                    plaintext,
                )
                request["aad"] = aad.hex()
                request["authentication_tag"] = tag.hex()
                ciphertext_path.write_bytes(ciphertext)
                request_path = directory / "request.json"
                request_path.write_text(
                    json.dumps(request, separators=(",", ":")),
                    encoding="utf-8",
                )

                order = (
                    (("native", native_host), ("vbs", vbs_host))
                    if run % 2 == 0
                    else (("vbs", vbs_host), ("native", native_host))
                )
                executions: dict[str, dict[str, Any]] = {}
                process_metrics: dict[str, dict[str, int | float]] = {}
                for name, binary in order:
                    execution, metrics = invoke_json_processor(binary, request_path)
                    executions[name] = execution
                    process_metrics[name] = metrics

                validation_started = time.perf_counter_ns()
                validated_vbs = attach_validated_attestation(
                    vbs_host,
                    request,
                    executions["vbs"],
                    working_directory=directory,
                )
                validation_wall_us = (
                    time.perf_counter_ns() - validation_started
                ) // 1000
                native = executions["native"]
                vbs = validated_vbs
                parity = (
                    native["result_fixed"] == vbs["result_fixed"]
                    == expected_result
                    and native["result_hash"] == vbs["result_hash"]
                    and native["row_count"] == vbs["row_count"] == rows
                    and native["actual_privacy_cost_fixed"]
                    == vbs["actual_privacy_cost_fixed"]
                    == 0
                )
                if not parity:
                    raise RuntimeError("Native/VBS deterministic parity failed")
                native_timing = native["timings_us"]
                vbs_timing = vbs["timings_us"]
                native_metrics = process_metrics["native"]
                vbs_metrics = process_metrics["vbs"]
                native_wall = int(round(float(native_metrics["wall_ms"]) * 1000))
                vbs_wall = int(round(float(vbs_metrics["wall_ms"]) * 1000))
                performance_rows.append(
                    {
                        "measurement_type": "measured_paired",
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "config_hash": config_hash,
                        "configuration": args.configuration,
                        "run": run,
                        "is_warmup": int(warmup),
                        "execution_order": "native_first"
                        if order[0][0] == "native"
                        else "vbs_first",
                        "seed": seed,
                        "request_id": request["request_id"],
                        "rows": rows,
                        "payload_bytes": len(plaintext),
                        "payload_sha256": payload_sha256,
                        "native_process_wall_us": native_wall,
                        "vbs_process_wall_us": vbs_wall,
                        "native_process_startup_us": max(
                            native_wall - int(native_timing["host_total"]), 0
                        ),
                        "vbs_process_startup_us": max(
                            vbs_wall - int(vbs_timing["host_total"]), 0
                        ),
                        "vbs_validation_wall_us": int(validation_wall_us),
                        "native_process_cpu_time_ms": native_metrics[
                            "process_cpu_time_ms"
                        ],
                        "vbs_process_cpu_time_ms": vbs_metrics[
                            "process_cpu_time_ms"
                        ],
                        "native_normalized_peak_cpu_percent": native_metrics[
                            "normalized_peak_cpu_percent"
                        ],
                        "vbs_normalized_peak_cpu_percent": vbs_metrics[
                            "normalized_peak_cpu_percent"
                        ],
                        "native_host_total_us": native_timing["host_total"],
                        "vbs_host_total_us": vbs_timing["host_total"],
                        "native_decrypt_us": native_timing["decrypt"],
                        "vbs_decrypt_us": vbs_timing["decrypt"],
                        "native_hash_us": native_timing["hash"],
                        "vbs_hash_us": vbs_timing["hash"],
                        "native_aggregate_us": native_timing["aggregate"],
                        "vbs_aggregate_us": vbs_timing["aggregate"],
                        "native_dp_noise_us": native_timing["dp_noise"],
                        "vbs_dp_noise_us": vbs_timing["dp_noise"],
                        "native_transcript_us": native_timing["transcript"],
                        "vbs_transcript_us": vbs_timing["transcript"],
                        "vbs_attestation_generation_us": vbs_timing[
                            "attestation"
                        ],
                        "vbs_attestation_validation_host_us": vbs_timing[
                            "attestation_validation_host"
                        ],
                        "vbs_attestation_validation_enclave_us": vbs_timing[
                            "attestation_validation_enclave"
                        ],
                        "native_peak_rss_bytes": native_metrics[
                            "peak_working_set_bytes"
                        ],
                        "vbs_peak_rss_bytes": vbs_metrics[
                            "peak_working_set_bytes"
                        ],
                        "native_peak_private_bytes": native_metrics[
                            "peak_private_bytes"
                        ],
                        "vbs_peak_private_bytes": vbs_metrics[
                            "peak_private_bytes"
                        ],
                        "native_resource_sample_count": native_metrics[
                            "resource_sample_count"
                        ],
                        "vbs_resource_sample_count": vbs_metrics[
                            "resource_sample_count"
                        ],
                        "native_result_fixed": native["result_fixed"],
                        "vbs_result_fixed": vbs["result_fixed"],
                        "result_hash_match": int(
                            native["result_hash"] == vbs["result_hash"]
                        ),
                        "result_parity": int(parity),
                        "native_payload_throughput_mib_s": (
                            len(plaintext)
                            / (1024 * 1024)
                            / (native_wall / 1_000_000)
                        ),
                        "vbs_payload_throughput_mib_s": (
                            len(plaintext)
                            / (1024 * 1024)
                            / (vbs_wall / 1_000_000)
                        ),
                        "vbs_slowdown_vs_native": vbs_wall / native_wall,
                        "native_ok": int(native["ok"] is True),
                        "vbs_ok": int(vbs["ok"] is True),
                        "failure_status": "",
                    }
                )
        print(f"[phase8-vbs] payload rows={rows} complete", flush=True)
    write_csv(raw_root / "native_vbs_performance.csv", performance_rows)

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
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "config_hash": config_hash,
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
                    "host_process_startup_us": max(
                        int(pipeline["client_timings_us"]["host_subprocess_wall"])
                        - int(execution["timings_us"]["host_total"]),
                        0,
                    ),
                    "host_process_cpu_time_ms": reference[
                        "host_process_cpu_time_ms"
                    ],
                    "host_normalized_peak_cpu_percent": reference[
                        "host_normalized_peak_cpu_percent"
                    ],
                    "host_peak_working_set_bytes": reference[
                        "host_peak_rss_bytes"
                    ],
                    "host_peak_private_bytes": reference[
                        "host_peak_private_bytes"
                    ],
                    "throughput_req_s": 1_000_000
                    / max(
                        int(pipeline["client_timings_us"]["host_subprocess_wall"]),
                        1,
                    ),
                    "ok": int(execution["ok"] is True),
                    "failure_status": "",
                }
            )
        print(f"[phase8-vbs] epsilon={epsilon} complete", flush=True)
    write_csv(raw_root / "dp_vbs.csv", privacy_rows)

    boundary_rows: list[dict[str, Any]] = []
    boundary_centers = [
        round(10_000 + index * (980_000 / 47)) for index in range(48)
    ]
    for boundary_index, center_fixed in enumerate(boundary_centers):
        # Stay a half micro-unit to either side. Exact decimal boundaries can
        # be represented infinitesimally above the integer by long double and
        # would exercise JSON floating representation rather than accounting.
        for offset_micro in (-0.49, 0.49):
            epsilon = (center_fixed + offset_micro) / FIXED_SCALE
            epsilon_fixed = epsilon_to_fixed(epsilon)
            delta_fixed = delta_to_fixed(0.00001)
            exact_cost = exact_privacy_cost_epsilon(
                epsilon_fixed, delta_fixed
            )
            reference_fixed = conservative_privacy_cost_fixed(
                epsilon_fixed, delta_fixed
            )
            pipeline = execute_synthetic_request(
                vbs_root=VBS_ROOT,
                configuration=args.configuration,
                function_name="MEAN",
                rows=64,
                seed=args.seed,
                epsilon=epsilon,
                delta=0.00001,
                request_id=(
                    f"phase8-boundary-{boundary_index}-{offset_micro}-"
                    f"{time.time_ns()}"
                ),
                asset_id="asset-phase8-boundary",
                consumer_id="consumer-phase8-local",
            )
            actual_fixed = int(
                pipeline["execution"]["actual_privacy_cost_fixed"]
            )
            if actual_fixed != reference_fixed:
                raise RuntimeError(
                    "VBS/Python fixed-point privacy cost mismatch at boundary"
                )
            boundary_rows.append(
                {
                    "measurement_type": "measured_with_analytical_margin",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "config_hash": config_hash,
                    "boundary_index": boundary_index,
                    "boundary_center_fixed": center_fixed,
                    "offset_micro_epsilon": offset_micro,
                    "epsilon_requested": format(epsilon, ".9f"),
                    "epsilon_requested_fixed": epsilon_fixed,
                    "delta_requested_fixed": delta_fixed,
                    "exact_conservative_cost_epsilon": format(
                        exact_cost, ".15f"
                    ),
                    "exact_conservative_cost_micro_epsilon": format(
                        exact_cost * FIXED_SCALE, ".9f"
                    ),
                    "vbs_cost_fixed": actual_fixed,
                    "python_reference_cost_fixed": reference_fixed,
                    "rounding_margin_micro_epsilon": format(
                        reference_fixed - exact_cost * FIXED_SCALE, ".9f"
                    ),
                    "under_reporting": int(actual_fixed < exact_cost * FIXED_SCALE),
                    "ok": int(pipeline["execution"]["ok"] is True),
                }
            )
    write_csv(raw_root / "dp_rounding_boundaries.csv", boundary_rows)
    print(
        f"[phase8-vbs] fixed-point boundary samples={len(boundary_rows)} complete",
        flush=True,
    )

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
    toolset_file = Path(
        "C:/Program Files/Microsoft Visual Studio/2022/Community/VC/"
        "Auxiliary/Build/Microsoft.VCToolsVersion.default.txt"
    )
    config = {
        "schema": "TrustCircuit.Phase8VbsExperimentConfig.v1",
        "measurement_type": "mixed_see_each_csv_row",
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
        "rounding_boundary_samples": len(boundary_rows),
        "payload_rows": PAYLOAD_ROWS,
        "epsilon_grid": EPSILON_GRID,
        "concurrency_bundles": args.concurrency_bundles,
        "config_hash": config_hash,
        "process_execution_mode": "one_process_per_request",
        "process_startup_definition": (
            "external process wall time minus the processor-reported host_total; "
            "reported separately and never attributed to the enclave call"
        ),
        "resource_counters": {
            "collector": "psutil sampled from the Python parent process",
            "sample_interval_ms": 1,
            "normalized_peak_cpu_percent": (
                "maximum sampled process CPU-time delta divided by wall-time "
                "delta and logical CPU count, clipped to [0,100]"
            ),
            "peak_working_set_bytes": "maximum sampled process RSS",
            "peak_private_bytes": (
                "maximum sampled psutil memory_full_info.private on Windows"
            ),
            "scope": "host process; not enclave-only memory",
        },
        "duration_seconds": time.perf_counter() - started,
        "sanity": {
            "performance_success_rate": statistics.mean(
                row["native_ok"] and row["vbs_ok"]
                for row in measured_performance
            ),
            "paired_result_parity_rate": statistics.mean(
                row["result_parity"] for row in measured_performance
            ),
            "privacy_success_rate": statistics.mean(
                row["ok"] for row in privacy_rows if not row["is_warmup"]
            ),
            "boundary_under_reporting_count": sum(
                row["under_reporting"] for row in boundary_rows
            ),
        },
        "native_vbs_pairing": (
            "Each row invokes TrustCircuitNative.exe and TrustCircuitHost.exe "
            "over the same request JSON, key, nonce, AAD, ciphertext, and "
            "TCVBSDS1 payload; execution order alternates by run."
        ),
        "compiler": {
            "platform": "x64",
            "toolset": "v143",
            "language_standard": "C++20",
            "msvc_tools_version": toolset_file.read_text(encoding="utf-8").strip()
            if toolset_file.is_file()
            else "unknown",
            "runtime": "MultiThreadedDebug"
            if args.configuration == "Debug"
            else "MultiThreaded",
        },
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
