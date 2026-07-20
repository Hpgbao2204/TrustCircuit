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
import shutil
import statistics
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "crypto" / "aes_gcm_scaling_worker.js"
RAW_DEFAULT = ROOT / "results" / "raw" / "aes_gcm_scaling_v2.csv"
SUMMARY_DEFAULT = ROOT / "results" / "summary" / "aes_gcm_scaling_v2_summary.csv"
CONFIG_DEFAULT = ROOT / "results" / "summary" / "aes_gcm_scaling_v2_config.json"

T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def executable(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"missing required executable: {name}")
    return found


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    critical = T_CRITICAL_95.get(len(values) - 1, 1.96)
    return critical * statistics.stdev(values) / math.sqrt(len(values))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process-isolated AES-256-GCM throughput and RSS benchmark.")
    parser.add_argument("--sizes-mib", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32, 64, 128, 256, 512])
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--chunk-mib", type=int, default=4)
    parser.add_argument("--raw-output", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_DEFAULT)
    parser.add_argument("--config-output", type=Path, default=CONFIG_DEFAULT)
    args = parser.parse_args()
    if args.reps < 2 or args.chunk_mib <= 0 or not args.sizes_mib or any(size <= 0 for size in args.sizes_mib):
        parser.error("reps must be >=2 and sizes/chunk must be positive")

    node = executable("node")
    run_id = f"aes-gcm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    raw: list[dict[str, object]] = []

    for variant in ("full_buffer", "chunked"):
        for payload_mib in args.sizes_mib:
            for repetition in range(args.reps):
                command = [
                    node, "--expose-gc", str(WORKER),
                    "--variant", variant,
                    "--payload-mib", str(payload_mib),
                    "--chunk-mib", str(args.chunk_mib),
                ]
                completed = subprocess.run(
                    command, cwd=ROOT, check=True, capture_output=True,
                    text=True, encoding="utf-8", timeout=180,
                )
                result = json.loads(completed.stdout)
                if not result["success"]:
                    raise RuntimeError(f"correctness failure: {variant}/{payload_mib}/{repetition}")
                idle = float(result["idle_rss_mib"])
                peak = float(result["peak_rss_mib"])
                row = {
                    "run_id": run_id,
                    "timestamp_utc": timestamp,
                    "measurement_type": "directly measured",
                    "variant": variant,
                    "payload_mib": payload_mib,
                    "repetition": repetition,
                    "chunk_mib": int(result["chunk_mib"]),
                    "encrypt_ms": round(float(result["encrypt_ms"]), 6),
                    "decrypt_ms": round(float(result["decrypt_ms"]), 6),
                    "encrypt_mib_s": round(payload_mib / (float(result["encrypt_ms"]) / 1000), 6),
                    "decrypt_mib_s": round(payload_mib / (float(result["decrypt_ms"]) / 1000), 6),
                    "idle_rss_mib": round(idle, 6),
                    "peak_rss_mib": round(peak, 6),
                    "incremental_peak_rss_mib": round(max(0.0, peak - idle), 6),
                    "success": True,
                }
                raw.append(row)
            print(f"measured {variant} payload={payload_mib} MiB ({args.reps} runs)")

    summary: list[dict[str, object]] = []
    metric_names = [
        "encrypt_ms", "decrypt_ms", "encrypt_mib_s", "decrypt_mib_s",
        "idle_rss_mib", "peak_rss_mib", "incremental_peak_rss_mib",
    ]
    for variant in ("full_buffer", "chunked"):
        for payload_mib in args.sizes_mib:
            subset = [row for row in raw if row["variant"] == variant and row["payload_mib"] == payload_mib]
            item: dict[str, object] = {
                "variant": variant,
                "payload_mib": payload_mib,
                "repetitions": len(subset),
                "chunk_mib": args.chunk_mib if variant == "chunked" else 0,
            }
            for metric in metric_names:
                values = [float(row[metric]) for row in subset]
                item[f"{metric}_mean"] = round(statistics.mean(values), 6)
                item[f"{metric}_std"] = round(statistics.stdev(values), 6)
                item[f"{metric}_ci95"] = round(ci95(values), 6)
            item["memory_amplification"] = round(float(item["incremental_peak_rss_mib_mean"]) / payload_mib, 6)
            item["all_correct"] = all(bool(row["success"]) for row in subset)
            summary.append(item)

    write_csv(args.raw_output, raw)
    write_csv(args.summary_output, summary)
    raw_digest = hashlib.sha256(args.raw_output.read_bytes()).hexdigest()
    node_meta = json.loads(subprocess.run(
        [node, "-p", "JSON.stringify({versions:process.versions,arch:process.arch,platform:process.platform})"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    config = {
        "schema": "TrustCircuit.AesGcmScaling.v2",
        "run_id": run_id,
        "timestamp_utc": timestamp,
        "measurement_type": "directly measured",
        "scope": "host-side bulk symmetric encryption; not access-control throughput and not enclave memory",
        "backend": f"Node.js crypto backed by OpenSSL {node_meta['versions']['openssl']}",
        "threading": "single JavaScript thread; synchronous crypto API",
        "payload_sizes_mib": args.sizes_mib,
        "repetitions_per_point": args.reps,
        "chunk_mib": args.chunk_mib,
        "variants": {
            "full_buffer": "whole plaintext, ciphertext, and recovered plaintext retained concurrently",
            "chunked": "AES-GCM encrypt/decrypt updates in bounded chunks; output consumed immediately",
        },
        "timing": "process startup, payload allocation, correctness comparison, and warm-up excluded; measured wall-clock crypto calls",
        "memory": "fresh process per repetition; idle RSS sampled after warm-up/GC; incremental RSS = observed peak RSS - idle RSS",
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "logical_cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "node": node_meta["versions"]["node"],
            "openssl": node_meta["versions"]["openssl"],
            "arch": node_meta["arch"],
        },
        "git_commit": git_commit,
        "raw_csv": str(args.raw_output.resolve().relative_to(ROOT)),
        "raw_csv_sha256": raw_digest,
        "summary_csv": str(args.summary_output.resolve().relative_to(ROOT)),
        "limitations": [
            "RSS is host-process RSS sampled at stage/chunk boundaries, not an OS event-traced instantaneous maximum.",
            "The benchmark does not run inside Nitro or VBS enclaves.",
            "Chunked mode models bounded-buffer processing and does not write ciphertext to persistent storage.",
        ],
    }
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(args.raw_output)
    print(args.summary_output)
    print(args.config_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
