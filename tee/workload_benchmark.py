"""TEE Worker Simulator workload benchmark.

This benchmark stresses the simulator with configurable worker counts. It is a
local Python simulation, not SGX.
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
import platform
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, pstdev

import numpy as np


SECRET = b"trustcircuit-tee-workload-secret"
DATASET_ID = "synthetic_healthcare_workload_v1"
DATASET_HASH = hashlib.sha256(DATASET_ID.encode("utf-8")).hexdigest()
CODE_HASH = hashlib.sha256(b"tee_workload_sim_v1").hexdigest()
POLICY_HASH = hashlib.sha256(b"purpose:research|query:mean_age").hexdigest()


@dataclass(frozen=True)
class WorkloadTrial:
    run_id: str
    worker_count: int
    request_index: int
    rows: int
    scratch_mb: int
    cpu_hash_rounds: int
    latency_ms: float
    cpu_time_ms: float
    peak_ram_kb: float
    query_latency_ms: float
    dp_noise_latency_ms: float
    attestation_latency_ms: float
    report_size_bytes: int
    utility_loss: float
    throughput_req_s: float
    success: bool


def synthetic_data(rows: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(48, 15, rows).clip(18, 90)


def touch_scratch_memory(scratch_mb: int, seed: int) -> int:
    scratch = bytearray(max(0, scratch_mb) * 1024 * 1024)
    checksum = 0
    step = 4096
    for i in range(0, len(scratch), step):
        value = (seed + i) % 251
        scratch[i] = value
        checksum += value
    return checksum


def cpu_hash_work(rounds: int, seed: str) -> str:
    digest = seed.encode("utf-8")
    for i in range(rounds):
        digest = hashlib.sha256(digest + i.to_bytes(4, "little", signed=False)).digest()
    return digest.hex()


def sign_payload(payload: str) -> str:
    return hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_attestation(request_id: str, result_hash: str, epsilon_cost: int) -> dict[str, str | int]:
    report = {
        "request_id": request_id,
        "code_hash": CODE_HASH,
        "policy_hash": POLICY_HASH,
        "dataset_hash": DATASET_HASH,
        "result_hash": result_hash,
        "epsilon_cost": epsilon_cost,
        "timestamp": int(time.time()),
    }
    material = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    report["report_hash"] = report_hash
    report["signature"] = sign_payload(report_hash)
    return report


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def run_request(job: tuple[str, int, int, int, int, int]) -> WorkloadTrial:
    run_id, worker_count, request_index, rows, scratch_mb, cpu_hash_rounds = job
    seed = 10_000 + worker_count * 101 + request_index
    request_id = f"REQ_WORKLOAD_{worker_count}_{request_index:05d}"
    tracemalloc.start()
    cpu_start = time.process_time()
    wall_start = time.perf_counter()

    checksum = touch_scratch_memory(scratch_mb, seed)
    digest = cpu_hash_work(cpu_hash_rounds, f"{request_id}:{checksum}")

    query_start = time.perf_counter()
    ages = synthetic_data(rows, seed)
    true_value = float(np.mean(ages))
    query_latency = (time.perf_counter() - query_start) * 1000

    dp_start = time.perf_counter()
    rng = np.random.default_rng(seed)
    noise = float(rng.normal(0, 2.0))
    noisy_result = true_value + noise
    dp_latency = (time.perf_counter() - dp_start) * 1000

    attestation_start = time.perf_counter()
    result_hash = hashlib.sha256(f"{request_id}:{noisy_result:.8f}:{digest[:16]}".encode("utf-8")).hexdigest()
    report = make_attestation(request_id, result_hash, 500_000)
    attestation_latency = (time.perf_counter() - attestation_start) * 1000

    latency = (time.perf_counter() - wall_start) * 1000
    cpu_time = (time.process_time() - cpu_start) * 1000
    _, peak_ram = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return WorkloadTrial(
        run_id=run_id,
        worker_count=worker_count,
        request_index=request_index,
        rows=rows,
        scratch_mb=scratch_mb,
        cpu_hash_rounds=cpu_hash_rounds,
        latency_ms=latency,
        cpu_time_ms=cpu_time,
        peak_ram_kb=peak_ram / 1024,
        query_latency_ms=query_latency,
        dp_noise_latency_ms=dp_latency,
        attestation_latency_ms=attestation_latency,
        report_size_bytes=len(json.dumps(report, sort_keys=True).encode("utf-8")),
        utility_loss=abs(noise),
        throughput_req_s=1000 / latency if latency > 0 else 0.0,
        success=True,
    )


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def write_raw(path: Path, rows: list[WorkloadTrial]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_summary(path: Path, rows: list[WorkloadTrial], group_wall_times: dict[int, float]) -> None:
    if not rows:
        return
    grouped: dict[int, list[WorkloadTrial]] = {}
    for row in rows:
        grouped.setdefault(row.worker_count, []).append(row)

    fields = [
        "worker_count",
        "total_requests",
        "rows",
        "scratch_mb_per_worker",
        "cpu_hash_rounds",
        "wall_time_s",
        "throughput_req_s",
        "throughput_per_worker_req_s",
        "mean_latency_ms",
        "std_latency_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "mean_cpu_time_ms",
        "cpu_utilization_estimate_pct",
        "mean_peak_ram_mb",
        "estimated_active_ram_mb",
        "mean_report_size_bytes",
        "mean_utility_loss",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for worker_count in sorted(grouped):
            items = grouped[worker_count]
            latencies = [item.latency_ms for item in items]
            cpu_times = [item.cpu_time_ms for item in items]
            wall_time = group_wall_times[worker_count]
            throughput = len(items) / wall_time if wall_time > 0 else 0.0
            cpu_util = sum(cpu_times) / (wall_time * 1000 * worker_count) * 100 if wall_time > 0 else 0.0
            mean_ram_mb = mean([item.peak_ram_kb for item in items]) / 1024
            writer.writerow(
                {
                    "worker_count": worker_count,
                    "total_requests": len(items),
                    "rows": items[0].rows,
                    "scratch_mb_per_worker": items[0].scratch_mb,
                    "cpu_hash_rounds": items[0].cpu_hash_rounds,
                    "wall_time_s": wall_time,
                    "throughput_req_s": throughput,
                    "throughput_per_worker_req_s": throughput / worker_count,
                    "mean_latency_ms": mean(latencies),
                    "std_latency_ms": pstdev(latencies) if len(latencies) > 1 else 0.0,
                    "p50_latency_ms": percentile(latencies, 50),
                    "p95_latency_ms": percentile(latencies, 95),
                    "p99_latency_ms": percentile(latencies, 99),
                    "mean_cpu_time_ms": mean(cpu_times),
                    "cpu_utilization_estimate_pct": cpu_util,
                    "mean_peak_ram_mb": mean_ram_mb,
                    "estimated_active_ram_mb": mean_ram_mb * worker_count,
                    "mean_report_size_bytes": mean([item.report_size_bytes for item in items]),
                    "mean_utility_loss": mean([item.utility_loss for item in items]),
                }
            )


def write_config(path: Path, args: argparse.Namespace, scratch_mb: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed_note": "deterministic per worker_count/request_index",
        "worker_counts": args.worker_counts,
        "requests_per_worker": args.requests_per_worker,
        "rows": args.rows,
        "cpu_hash_rounds": args.cpu_hash_rounds,
        "memory_budget_mb": args.memory_budget_mb,
        "memory_safety_factor": args.memory_safety_factor,
        "auto_reduce_on_memory_error": args.auto_reduce_on_memory_error,
        "scratch_mb_per_worker": scratch_mb,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "note": "TEE worker workload simulation only; not SGX.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def compute_scratch_mb(args: argparse.Namespace, max_workers: int) -> int:
    if args.scratch_mb is not None:
        return args.scratch_mb
    reserve_mb = args.memory_reserve_mb
    usable_mb = max(512, args.memory_budget_mb - reserve_mb)
    safe_usable_mb = usable_mb * args.memory_safety_factor
    return max(1, int(safe_usable_mb / max_workers))


def run_worker_count(worker_count: int, args: argparse.Namespace, scratch_mb: int) -> tuple[list[WorkloadTrial], float]:
    requests = max(1, worker_count * args.requests_per_worker)
    run_id = f"tee-workload-w{worker_count}"
    jobs = [
        (run_id, worker_count, request_index, args.rows, scratch_mb, args.cpu_hash_rounds)
        for request_index in range(requests)
    ]
    print(f"[tee-workload] workers={worker_count} requests={requests} scratch={scratch_mb}MB", flush=True)
    start = time.perf_counter()
    rows: list[WorkloadTrial] = []
    last_progress = start
    with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(run_request, job) for job in jobs]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            rows.append(future.result())
            now = time.perf_counter()
            if completed == requests or now - last_progress >= args.progress_every_seconds:
                elapsed = now - start
                rate = completed / elapsed if elapsed > 0 else 0.0
                eta = (requests - completed) / rate if rate > 0 else 0.0
                print(
                    "[tee-workload] "
                    f"workers={worker_count} {completed}/{requests} "
                    f"elapsed={format_duration(elapsed)} eta={format_duration(eta)} rate={rate:.2f} req/s",
                    flush=True,
                )
                last_progress = now
    wall_time = time.perf_counter() - start
    return rows, wall_time


def write_partials(args: argparse.Namespace, rows: list[WorkloadTrial], group_wall_times: dict[int, float]) -> None:
    write_raw(args.raw_output.with_suffix(".partial.csv"), rows)
    write_summary(args.summary_output.with_suffix(".partial.csv"), rows, group_wall_times)


def run(args: argparse.Namespace) -> None:
    max_workers = max(args.worker_counts)
    scratch_mb = compute_scratch_mb(args, max_workers)
    print(
        "[tee-workload] "
        f"worker_counts={args.worker_counts} rows={args.rows} cpu_hash_rounds={args.cpu_hash_rounds} "
        f"memory_budget={args.memory_budget_mb}MB scratch={scratch_mb}MB/worker",
        flush=True,
    )

    all_rows: list[WorkloadTrial] = []
    group_wall_times: dict[int, float] = {}
    for worker_count in args.worker_counts:
        active_scratch_mb = scratch_mb
        while True:
            try:
                rows, wall_time = run_worker_count(worker_count, args, active_scratch_mb)
                break
            except MemoryError:
                next_scratch_mb = int(active_scratch_mb * args.memory_retry_factor)
                if not args.auto_reduce_on_memory_error or next_scratch_mb < args.min_scratch_mb:
                    write_partials(args, all_rows, group_wall_times)
                    print(
                        "[tee-workload] memory error; partial raw/summary files were written. "
                        f"failed_workers={worker_count} scratch={active_scratch_mb}MB",
                        flush=True,
                    )
                    raise
                print(
                    "[tee-workload] memory error; retrying current worker count with lower scratch. "
                    f"workers={worker_count} scratch={active_scratch_mb}MB -> {next_scratch_mb}MB",
                    flush=True,
                )
                active_scratch_mb = next_scratch_mb
        all_rows.extend(rows)
        group_wall_times[worker_count] = wall_time
        write_partials(args, all_rows, group_wall_times)

    write_raw(args.raw_output, all_rows)
    write_summary(args.summary_output, all_rows, group_wall_times)
    write_config(args.config_output, args, scratch_mb)
    print(args.raw_output)
    print(args.summary_output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-counts", type=int, nargs="+", default=[1, 2, 4, 6, 8, 10, 20, 30, 40, 50])
    parser.add_argument("--requests-per-worker", type=int, default=4)
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--cpu-hash-rounds", type=int, default=50_000)
    parser.add_argument("--memory-budget-mb", type=int, default=20_000)
    parser.add_argument("--memory-reserve-mb", type=int, default=4096)
    parser.add_argument("--memory-safety-factor", type=float, default=0.55)
    parser.add_argument("--memory-retry-factor", type=float, default=0.65)
    parser.add_argument("--min-scratch-mb", type=int, default=64)
    parser.add_argument("--auto-reduce-on-memory-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--scratch-mb", type=int, default=None)
    parser.add_argument("--progress-every-seconds", type=float, default=5.0)
    parser.add_argument("--raw-output", type=Path, default=Path("results/raw/tee_workload_benchmark.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("results/summary/tee_workload_summary.csv"))
    parser.add_argument("--config-output", type=Path, default=Path("results/summary/tee_workload_config.json"))
    args = parser.parse_args()
    cpu_count = os.cpu_count() or 1
    args.worker_counts = sorted({max(1, count) for count in args.worker_counts})
    args.memory_safety_factor = min(1.0, max(0.05, args.memory_safety_factor))
    args.memory_retry_factor = min(0.95, max(0.1, args.memory_retry_factor))
    args.memory_reserve_mb = max(0, args.memory_reserve_mb)
    args.min_scratch_mb = max(1, args.min_scratch_mb)
    if max(args.worker_counts) > cpu_count * 3:
        print(f"[tee-workload] warning: max worker count is high for {cpu_count} logical CPUs.", flush=True)
    args.progress_every_seconds = max(0.5, args.progress_every_seconds)
    return args


if __name__ == "__main__":
    run(parse_args())
