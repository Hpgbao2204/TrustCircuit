"""Attack simulation harness for the TrustCircuit TEE Worker Simulator.

The harness models policy checks, query execution, DP noise, mock attestation,
HMAC signing, audit logging, and a set of malicious request/report mutations.
It is a local simulation, not SGX.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import hmac
import json
import math
import os
import shutil
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, pstdev

import numpy as np


ATTACK_TYPES = (
    "honest",
    "invalid_purpose",
    "invalid_query",
    "budget_overuse",
    "tampered_result",
    "tampered_attestation",
    "replay_request",
    "dataset_substitution",
    "skip_dp_noise",
    "wrong_epsilon",
)

SECRET = b"trustcircuit-tee-worker-secret"
ALLOWED_PURPOSES = {"research", "analytics"}
ALLOWED_QUERIES = {"mean_age", "diabetes_count", "high_bp_count"}
DATASET_ID = "synthetic_healthcare_v1"
DATASET_HASH = hashlib.sha256(DATASET_ID.encode("utf-8")).hexdigest()
CODE_HASH = hashlib.sha256(b"tee_worker_sim_v1").hexdigest()
POLICY_HASH = hashlib.sha256(b"purpose:research|queries:mean_age,diabetes_count,high_bp_count").hexdigest()
TOTAL_BUDGET = 5_000_000


@dataclass(frozen=True)
class AttackRequest:
    request_id: str
    purpose: str
    query: str
    epsilon: int
    nonce: str
    dataset_hash: str


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    attack_type: str
    severity: float
    detector_score: float
    request_id: str
    accepted: bool
    blocked: bool
    detected: bool
    attack_success: bool
    false_accept: bool
    false_reject: bool
    detection_reason: str
    policy_check_latency_ms: float
    query_computation_latency_ms: float
    dp_noise_latency_ms: float
    mock_attestation_latency_ms: float
    result_signing_latency_ms: float
    total_tee_latency_ms: float
    throughput_req_s: float
    cpu_time_ms: float
    peak_ram_kb: float
    attestation_report_size: int
    privacy_budget_consumed: int
    utility_loss: float
    report_hash: str


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sign_payload(payload: str) -> str:
    return hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def synthetic_data(rows: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    ages = rng.normal(48, 15, rows).clip(18, 90)
    diabetic = rng.binomial(1, 0.18, rows)
    bp = rng.normal(124, 18, rows).clip(80, 210)
    return {"age": ages, "diabetic": diabetic, "bp": bp}


def touch_scratch_memory(scratch_mb: int, seed: int) -> int:
    if scratch_mb <= 0:
        return 0
    scratch = bytearray(scratch_mb * 1024 * 1024)
    checksum = 0
    step = 4096
    for i in range(0, len(scratch), step):
        value = (i + seed) % 251
        scratch[i] = value
        checksum += value
    return checksum


def cpu_hash_work(rounds: int, seed: str) -> str:
    digest = seed.encode("utf-8")
    for i in range(rounds):
        digest = hashlib.sha256(digest + str(i).encode("utf-8")).digest()
    return digest.hex()


def build_request(attack_type: str, trial: int, severity: float) -> AttackRequest:
    purpose = "research"
    query = "mean_age"
    epsilon = 500_000
    nonce = f"nonce-{trial}"
    dataset_hash = DATASET_HASH
    severity_tag = str(severity).replace(".", "_")
    request_id = f"REQ_ATTACK_{attack_type}_{severity_tag}_{trial:04d}"

    if attack_type == "invalid_purpose":
        purpose = "marketing" if severity >= 0.4 else "research_adjacent"
    elif attack_type == "invalid_query":
        query = "raw_records_dump" if severity >= 0.4 else "mean_age_debug"
    elif attack_type == "budget_overuse":
        epsilon = int(TOTAL_BUDGET * (1.0 + severity))
    elif attack_type == "dataset_substitution":
        dataset_hash = sha256_text(f"substituted_dataset:{severity:.2f}")
    elif attack_type == "replay_request":
        request_id = "REQ_REPLAY_FIXED"
        nonce = "reused-nonce"
    elif attack_type == "wrong_epsilon":
        epsilon = max(1, int(500_000 * (1.0 - severity * 0.8)))

    return AttackRequest(request_id, purpose, query, epsilon, nonce, dataset_hash)


def check_policy(request: AttackRequest, remaining_budget: int, seen_requests: set[str]) -> tuple[bool, str]:
    if request.request_id in seen_requests:
        return False, "replay_request"
    if request.purpose not in ALLOWED_PURPOSES:
        return False, "invalid_purpose"
    if request.query not in ALLOWED_QUERIES:
        return False, "invalid_query"
    if request.epsilon <= 0 or request.epsilon > remaining_budget:
        return False, "budget_overuse"
    if request.dataset_hash != DATASET_HASH:
        return False, "dataset_substitution"
    return True, ""


def run_query(request: AttackRequest, data: dict[str, np.ndarray]) -> float:
    if request.query == "mean_age":
        return float(np.mean(data["age"]))
    if request.query == "diabetes_count":
        return float(np.sum(data["diabetic"]))
    if request.query == "high_bp_count":
        return float(np.sum(data["bp"] >= 140))
    raise ValueError(f"unsupported query: {request.query}")


def add_dp_noise(true_value: float, epsilon: int, rng: np.random.Generator, skip_noise: bool) -> tuple[float, float]:
    if skip_noise:
        return true_value, 0.0
    epsilon_float = max(epsilon / 1_000_000, 1e-9)
    sigma = 1.0 / epsilon_float
    noise = float(rng.normal(0, sigma))
    return true_value + noise, abs(noise)


def probabilistic_detect(
    attack_type: str,
    severity: float,
    rng: np.random.Generator,
    deterministic_detected: bool,
    deterministic_blocked: bool,
    args: argparse.Namespace,
) -> tuple[bool, float]:
    if attack_type == "honest":
        false_reject_score = args.false_reject_base + severity * 0.01
        return rng.random() < false_reject_score, false_reject_score

    if deterministic_blocked and args.strict_policy_blocks:
        return True, 1.0

    base_by_attack = {
        "invalid_purpose": 0.45,
        "invalid_query": 0.42,
        "budget_overuse": 0.55,
        "tampered_result": 0.20,
        "tampered_attestation": 0.35,
        "replay_request": 0.50,
        "dataset_substitution": 0.30,
        "skip_dp_noise": 0.18,
        "wrong_epsilon": 0.22,
    }
    slope_by_attack = {
        "invalid_purpose": 0.45,
        "invalid_query": 0.45,
        "budget_overuse": 0.40,
        "tampered_result": 0.65,
        "tampered_attestation": 0.58,
        "replay_request": 0.38,
        "dataset_substitution": 0.55,
        "skip_dp_noise": 0.62,
        "wrong_epsilon": 0.60,
    }
    score = base_by_attack.get(attack_type, 0.25) + slope_by_attack.get(attack_type, 0.5) * severity
    if deterministic_detected:
        score += 0.15
    score *= args.detector_strength
    score = max(args.min_detection_probability, min(args.max_detection_probability, score))
    return rng.random() < score, score


def make_attestation(request: AttackRequest, result_hash: str, epsilon_cost: int, timestamp: int) -> dict[str, str | int]:
    report = {
        "request_id": request.request_id,
        "code_hash": CODE_HASH,
        "policy_hash": POLICY_HASH,
        "dataset_hash": request.dataset_hash,
        "result_hash": result_hash,
        "epsilon_cost": epsilon_cost,
        "timestamp": timestamp,
    }
    report_material = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report_hash = sha256_text(report_material)
    report["report_hash"] = report_hash
    report["signature"] = sign_payload(report_hash)
    return report


def verify_attestation(request: AttackRequest, report: dict[str, str | int], expected_result_hash: str) -> tuple[bool, str]:
    if report.get("request_id") != request.request_id:
        return False, "attestation_request_mismatch"
    if report.get("dataset_hash") != DATASET_HASH:
        return False, "dataset_hash_mismatch"
    if report.get("result_hash") != expected_result_hash:
        return False, "result_hash_mismatch"
    signature = str(report.get("signature", ""))
    report_hash = str(report.get("report_hash", ""))
    if not hmac.compare_digest(signature, sign_payload(report_hash)):
        return False, "attestation_signature_mismatch"

    unsigned = dict(report)
    unsigned.pop("report_hash", None)
    unsigned.pop("signature", None)
    recomputed_hash = sha256_text(json.dumps(unsigned, sort_keys=True, separators=(",", ":")))
    if not hmac.compare_digest(report_hash, recomputed_hash):
        return False, "attestation_hash_mismatch"
    return True, ""


def run_trial(attack_type: str, trial: int, severity: float, args: argparse.Namespace, seen_requests: set[str]) -> TrialResult:
    rng = np.random.default_rng(args.seed + trial)
    data = synthetic_data(args.rows, args.seed)
    request = build_request(attack_type, trial, severity)
    remaining_budget = TOTAL_BUDGET
    malicious = attack_type != "honest"
    tracemalloc.start()
    cpu_start = time.process_time()
    total_start = time.perf_counter()

    start = time.perf_counter()
    if attack_type == "replay_request":
        seen_requests.add(request.request_id)
    policy_ok, policy_reason = check_policy(request, remaining_budget, seen_requests)
    policy_latency = (time.perf_counter() - start) * 1000

    blocked = not policy_ok
    detected = False
    deterministic_detected = False
    detector_score = 0.0
    detection_reason = policy_reason
    true_value = 0.0
    noisy_result = 0.0
    utility_loss = 0.0
    attestation_size = 0
    report_hash = ""
    query_latency = 0.0
    dp_latency = 0.0
    attestation_latency = 0.0
    signing_latency = 0.0
    budget_consumed = 0

    scratch_checksum = touch_scratch_memory(args.scratch_mb, args.seed + trial)
    cpu_digest = cpu_hash_work(args.cpu_hash_rounds, f"{attack_type}:{trial}:{severity}:{scratch_checksum}")

    if policy_ok:
        seen_requests.add(request.request_id)
        start = time.perf_counter()
        true_value = run_query(request, data)
        query_latency = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        skip_noise = attack_type == "skip_dp_noise"
        epsilon_used = 2_000_000 if attack_type == "wrong_epsilon" else request.epsilon
        noisy_result, utility_loss = add_dp_noise(true_value, epsilon_used, rng, skip_noise)
        dp_latency = (time.perf_counter() - start) * 1000

        expected_result_hash = sha256_text(f"{request.request_id}|{request.query}|{noisy_result:.8f}")
        if attack_type == "tampered_result":
            noisy_result += 1000.0 * severity

        result_hash = sha256_text(f"{request.request_id}|{request.query}|{noisy_result:.8f}")
        start = time.perf_counter()
        report = make_attestation(request, result_hash, request.epsilon, int(time.time()))
        attestation_latency = (time.perf_counter() - start) * 1000

        if attack_type == "tampered_attestation":
            report["report_hash"] = sha256_text(f"tampered:{severity}:{cpu_digest[:16]}")
        if attack_type == "wrong_epsilon":
            report["epsilon_cost"] = int(request.epsilon * (1.0 + severity))

        start = time.perf_counter()
        valid_attestation, attestation_reason = verify_attestation(request, report, expected_result_hash)
        signing_latency = (time.perf_counter() - start) * 1000
        attestation_size = len(json.dumps(report, sort_keys=True).encode("utf-8"))
        report_hash = str(report.get("report_hash", ""))

        if not valid_attestation:
            deterministic_detected = True
            detection_reason = attestation_reason
        elif attack_type == "skip_dp_noise":
            deterministic_detected = severity >= 0.8
            detection_reason = "dp_noise_missing"
        elif attack_type == "wrong_epsilon":
            deterministic_detected = severity >= 0.8
            detection_reason = "epsilon_mismatch"
        else:
            budget_consumed = request.epsilon

    detected, detector_score = probabilistic_detect(
        attack_type=attack_type,
        severity=severity,
        rng=rng,
        deterministic_detected=deterministic_detected,
        deterministic_blocked=blocked,
        args=args,
    )
    if detected and not detection_reason:
        detection_reason = "statistical_detector"

    accepted = policy_ok and not detected
    attack_success = malicious and accepted
    false_accept = attack_success
    false_reject = (not malicious) and (not accepted)
    total_latency = (time.perf_counter() - total_start) * 1000
    cpu_time = (time.process_time() - cpu_start) * 1000
    _, peak_ram = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return TrialResult(
        trial_id=f"{attack_type}_{severity_bucket(severity)}_{trial:04d}",
        attack_type=attack_type,
        severity=severity,
        detector_score=detector_score,
        request_id=request.request_id,
        accepted=accepted,
        blocked=blocked,
        detected=detected,
        attack_success=attack_success,
        false_accept=false_accept,
        false_reject=false_reject,
        detection_reason=detection_reason,
        policy_check_latency_ms=policy_latency,
        query_computation_latency_ms=query_latency,
        dp_noise_latency_ms=dp_latency,
        mock_attestation_latency_ms=attestation_latency,
        result_signing_latency_ms=signing_latency,
        total_tee_latency_ms=total_latency,
        throughput_req_s=1000 / total_latency if total_latency > 0 else 0.0,
        cpu_time_ms=cpu_time,
        peak_ram_kb=peak_ram / 1024,
        attestation_report_size=attestation_size,
        privacy_budget_consumed=budget_consumed,
        utility_loss=utility_loss,
        report_hash=report_hash,
    )


def run_trial_job(job: tuple[str, int, float, argparse.Namespace]) -> TrialResult:
    attack_type, trial, severity, args = job
    return run_trial(attack_type, trial, severity, args, set())


def write_raw(path: Path, rows: list[TrialResult]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_logs(log_dir: Path, rows: list[TrialResult]) -> None:
    if not rows:
        return
    if log_dir.exists():
        shutil.rmtree(log_dir)
    for row in rows:
        attack_dir = log_dir / row.attack_type
        attack_dir.mkdir(parents=True, exist_ok=True)
        (attack_dir / f"{row.trial_id}.json").write_text(json.dumps(asdict(row), indent=2), encoding="utf-8")


def severity_bucket(severity: float) -> str:
    return f"{severity:.2f}"


def write_summary(path: Path, rows: list[TrialResult]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[str, str], list[TrialResult]] = {}
    for row in rows:
        grouped.setdefault((row.attack_type, severity_bucket(row.severity)), []).append(row)

    fields = [
        "attack_type",
        "severity",
        "total_trials",
        "blocked_count",
        "detected_count",
        "attack_success_count",
        "detection_rate",
        "attack_success_rate",
        "false_accept_rate",
        "false_reject_rate",
        "mean_total_tee_latency_ms",
        "p95_total_tee_latency_ms",
        "mean_cpu_time_ms",
        "mean_peak_ram_kb",
        "mean_attestation_report_size",
        "privacy_budget_consumed",
        "mean_utility_loss",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for (attack_type, bucket), items in sorted(grouped.items()):
            malicious_items = [item for item in items if item.attack_type != "honest"]
            denominator = len(malicious_items) if malicious_items else len(items)
            latencies = [item.total_tee_latency_ms for item in items]
            writer.writerow(
                {
                    "attack_type": attack_type,
                    "severity": bucket,
                    "total_trials": len(items),
                    "blocked_count": sum(1 for item in items if item.blocked),
                    "detected_count": sum(1 for item in items if item.detected),
                    "attack_success_count": sum(1 for item in items if item.attack_success),
                    "detection_rate": sum(1 for item in malicious_items if item.detected or item.blocked) / denominator,
                    "attack_success_rate": sum(1 for item in malicious_items if item.attack_success) / denominator,
                    "false_accept_rate": sum(1 for item in items if item.false_accept) / len(items),
                    "false_reject_rate": sum(1 for item in items if item.false_reject) / len(items),
                    "mean_total_tee_latency_ms": mean(latencies),
                    "p95_total_tee_latency_ms": percentile(latencies, 95),
                    "mean_cpu_time_ms": mean([item.cpu_time_ms for item in items]),
                    "mean_peak_ram_kb": mean([item.peak_ram_kb for item in items]),
                    "mean_attestation_report_size": mean([item.attestation_report_size for item in items]),
                    "privacy_budget_consumed": sum(item.privacy_budget_consumed for item in items),
                    "mean_utility_loss": mean([item.utility_loss for item in items]),
                }
            )


def write_config(path: Path, args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "rows": args.rows,
                "trials": args.trials,
                "severity_levels": args.severity_levels,
                "cpu_hash_rounds": args.cpu_hash_rounds,
                "scratch_mb": args.scratch_mb,
                "detector_strength": args.detector_strength,
                "attacks": args.attacks,
                "note": "TEE attack simulation only; not real SGX.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_jobs(args: argparse.Namespace) -> list[tuple[str, int, float, argparse.Namespace]]:
    return [
        (attack_type, trial, severity, args)
        for attack_type in args.attacks
        for severity in args.severity_levels
        for trial in range(args.trials)
    ]


def estimate_ram_per_worker_mb(args: argparse.Namespace) -> float:
    dataset_mb = args.rows * 3 * 8 / (1024 * 1024)
    return args.scratch_mb + dataset_mb + 96


def format_duration(seconds: float) -> str:
    if seconds == math.inf or seconds != seconds:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def print_run_header(args: argparse.Namespace, total: int) -> None:
    per_worker_mb = estimate_ram_per_worker_mb(args)
    estimated_active_mb = per_worker_mb * max(1, args.workers)
    print(
        "[tee-attack] "
        f"jobs={total} attacks={len(args.attacks)} severity_levels={len(args.severity_levels)} "
        f"trials={args.trials} rows={args.rows} workers={args.workers}",
        flush=True,
    )
    print(
        "[tee-attack] "
        f"scratch={args.scratch_mb}MB/worker cpu_hash_rounds={args.cpu_hash_rounds} "
        f"estimated_active_ram={estimated_active_mb:.0f}MB",
        flush=True,
    )
    print("[tee-attack] progress is printed during the run; checkpoint CSVs are written periodically.", flush=True)


def print_progress(start_time: float, completed: int, total: int, rows: list[TrialResult], label: str) -> None:
    elapsed = time.perf_counter() - start_time
    rate = completed / elapsed if elapsed > 0 else 0.0
    eta = (total - completed) / rate if rate > 0 else math.inf
    pct = completed / total * 100 if total else 100.0
    recent = rows[-min(len(rows), 20) :] if rows else []
    avg_latency = mean([item.total_tee_latency_ms for item in recent]) if recent else 0.0
    avg_cpu = mean([item.cpu_time_ms for item in recent]) if recent else 0.0
    avg_ram = mean([item.peak_ram_kb for item in recent]) / 1024 if recent else 0.0
    print(
        "[tee-attack] "
        f"{label} {completed}/{total} ({pct:.1f}%) "
        f"elapsed={format_duration(elapsed)} eta={format_duration(eta)} "
        f"rate={rate:.2f} trials/s recent_latency={avg_latency:.1f}ms "
        f"recent_cpu={avg_cpu:.1f}ms recent_peak_ram={avg_ram:.1f}MB",
        flush=True,
    )


def checkpoint(args: argparse.Namespace, rows: list[TrialResult], force: bool = False) -> None:
    if args.disable_checkpoints or not rows:
        return
    partial_raw = args.raw_output.with_suffix(".partial.csv")
    partial_summary = args.summary_output.with_suffix(".partial.csv")
    write_raw(partial_raw, rows)
    write_summary(partial_summary, rows)
    if force:
        print(f"[tee-attack] checkpoint written: {partial_raw} ({len(rows)} rows)", flush=True)


def run_sequential(args: argparse.Namespace, jobs: list[tuple[str, int, float, argparse.Namespace]]) -> list[TrialResult]:
    rows: list[TrialResult] = []
    seen_by_attack: dict[str, set[str]] = {}
    start_time = time.perf_counter()
    last_progress = start_time
    total = len(jobs)

    for index, (attack_type, trial, severity, _) in enumerate(jobs, start=1):
        seen_requests = seen_by_attack.setdefault(attack_type, set())
        rows.append(run_trial(attack_type, trial, severity, args, seen_requests))
        now = time.perf_counter()
        if (
            index == total
            or index % args.checkpoint_every == 0
            or now - last_progress >= args.progress_every_seconds
        ):
            checkpoint(args, rows, force=index % args.checkpoint_every == 0)
            print_progress(start_time, index, total, rows, f"current={attack_type}/{severity_bucket(severity)}/{trial:04d}")
            last_progress = now
    return rows


def run_parallel(args: argparse.Namespace, jobs: list[tuple[str, int, float, argparse.Namespace]]) -> list[TrialResult]:
    rows: list[TrialResult] = []
    start_time = time.perf_counter()
    last_progress = start_time
    total = len(jobs)

    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_trial_job, job) for job in jobs]
        try:
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                rows.append(future.result())
                now = time.perf_counter()
                if (
                    index == total
                    or index % args.checkpoint_every == 0
                    or now - last_progress >= args.progress_every_seconds
                ):
                    checkpoint(args, rows, force=index % args.checkpoint_every == 0)
                    print_progress(start_time, index, total, rows, "parallel")
                    last_progress = now
        except KeyboardInterrupt:
            for future in futures:
                future.cancel()
            checkpoint(args, rows, force=True)
            print("[tee-attack] interrupted; partial CSV checkpoint was kept.", flush=True)
            raise
    return rows


def run(args: argparse.Namespace) -> None:
    jobs = build_jobs(args)
    print_run_header(args, len(jobs))
    try:
        rows = run_parallel(args, jobs) if args.workers > 1 else run_sequential(args, jobs)
    except KeyboardInterrupt:
        print("[tee-attack] stopped by user.", file=sys.stderr, flush=True)
        return

    write_raw(args.raw_output, rows)
    write_summary(args.summary_output, rows)
    write_logs(args.log_dir, rows)
    write_config(args.config_output, args)
    checkpoint(args, rows, force=True)
    print(args.raw_output)
    print(args.summary_output)
    print(args.log_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--severity-levels", type=float, nargs="+", default=[0.1, 0.25, 0.5, 0.75, 1.0])
    parser.add_argument("--cpu-hash-rounds", type=int, default=20_000)
    parser.add_argument("--scratch-mb", type=int, default=32)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--progress-every-seconds", type=float, default=5.0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--disable-checkpoints", action="store_true")
    parser.add_argument("--detector-strength", type=float, default=0.82)
    parser.add_argument("--min-detection-probability", type=float, default=0.03)
    parser.add_argument("--max-detection-probability", type=float, default=0.97)
    parser.add_argument("--false-reject-base", type=float, default=0.01)
    parser.add_argument("--strict-policy-blocks", action="store_true")
    parser.add_argument("--attacks", nargs="+", choices=ATTACK_TYPES, default=list(ATTACK_TYPES))
    parser.add_argument("--raw-output", type=Path, default=Path("results/raw/tee_attack_trials.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("results/summary/tee_attack_summary.csv"))
    parser.add_argument("--config-output", type=Path, default=Path("results/summary/tee_attack_config.json"))
    parser.add_argument("--log-dir", type=Path, default=Path("results/attacks/tee"))
    args = parser.parse_args()
    args.workers = max(1, min(args.workers, os.cpu_count() or 1))
    args.checkpoint_every = max(1, args.checkpoint_every)
    args.progress_every_seconds = max(0.5, args.progress_every_seconds)
    return args


if __name__ == "__main__":
    run(parse_args())
