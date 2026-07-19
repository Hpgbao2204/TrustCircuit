from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUST_MANIFEST = ROOT / "crypto" / "rabe_benchmark" / "Cargo.toml"
NODE_RUNNER = ROOT / "crypto" / "abe_policy_baseline.js"
RAW_DEFAULT = ROOT / "results" / "raw" / "cpabe_policy_benchmark.csv"
SUMMARY_DEFAULT = ROOT / "results" / "summary" / "cpabe_policy_summary.csv"
CONFIG_DEFAULT = ROOT / "results" / "summary" / "cpabe_policy_config.json"


def executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "cargo":
        candidate = Path.home() / ".cargo" / "bin" / "cargo.exe"
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(f"missing required executable: {name}")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def parse_rows(text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    required = {
        "implementation",
        "scheme",
        "operation",
        "policy_attributes",
        "repetition",
        "payload_bytes",
        "latency_ms",
        "success",
    }
    if not rows or set(rows[0]) != required:
        raise RuntimeError("benchmark emitted an unexpected CSV schema")
    return rows


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(rows: list[dict[str, str]], sizes: list[int], repetitions: int) -> list[dict[str, object]]:
    summary: list[dict[str, object]] = []
    for size in sizes:
        row: dict[str, object] = {"policy_attributes": size, "repetitions": repetitions}
        all_correct = True
        for implementation in ("kem_dem_baseline", "full_cpabe"):
            for operation in ("encrypt", "decrypt"):
                subset = [
                    item
                    for item in rows
                    if item["implementation"] == implementation
                    and item["operation"] == operation
                    and int(item["policy_attributes"]) == size
                ]
                if len(subset) != repetitions:
                    raise RuntimeError(
                        f"expected {repetitions} rows for {implementation}/{operation}/{size}, got {len(subset)}"
                    )
                values = [float(item["latency_ms"]) for item in subset]
                all_correct &= all(item["success"].lower() == "true" for item in subset)
                prefix = f"{implementation}_{operation}_ms"
                row[f"{prefix}_mean"] = round(statistics.mean(values), 6)
                row[f"{prefix}_std"] = round(statistics.stdev(values), 6) if len(values) > 1 else 0.0
                row[f"{prefix}_median"] = round(statistics.median(values), 6)
                row[f"{prefix}_p95"] = round(percentile(values, 0.95), 6)
        row["all_correct"] = all_correct
        summary.append(row)
    return summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def recorded_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark matched KEM-DEM and pairing-based AC17/FAME CP-ABE policy latency.")
    parser.add_argument("--policy-sizes", type=int, nargs="+", default=[5, 10, 15, 20, 25])
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--payload-bytes", type=int, default=32)
    parser.add_argument("--raw-output", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_DEFAULT)
    parser.add_argument("--config-output", type=Path, default=CONFIG_DEFAULT)
    args = parser.parse_args()
    if args.reps <= 0 or args.warmups < 0 or args.payload_bytes <= 0:
        parser.error("reps and payload bytes must be positive; warmups must be non-negative")
    if not args.policy_sizes or any(size <= 0 for size in args.policy_sizes):
        parser.error("policy sizes must be positive")

    cargo = executable("cargo")
    node = executable("node")
    sizes = ",".join(str(size) for size in args.policy_sizes)
    common = ["--policy-sizes", sizes, "--reps", str(args.reps), "--warmups", str(args.warmups), "--payload-bytes", str(args.payload_bytes)]

    run([cargo, "build", "--release", "--manifest-path", str(RUST_MANIFEST)])
    binary = RUST_MANIFEST.parent / "target" / "release" / "trustcircuit_cpabe_benchmark.exe"
    if not binary.is_file():
        raise RuntimeError(f"missing release binary: {binary}")

    baseline = parse_rows(run([node, str(NODE_RUNNER), *common]).stdout)
    full_cpabe = parse_rows(run([str(binary), *common]).stdout)
    measured = baseline + full_cpabe

    expected = len(args.policy_sizes) * args.reps * 2 * 2
    if len(measured) != expected:
        raise RuntimeError(f"expected {expected} total measurements, got {len(measured)}")
    if not all(row["success"].lower() == "true" for row in measured):
        raise RuntimeError("at least one encryption/decryption correctness check failed")

    run_id = f"cpabe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    raw_rows: list[dict[str, object]] = []
    for row in measured:
        raw_rows.append(
            {
                "run_id": run_id,
                "timestamp_utc": timestamp,
                "measurement_type": "measured",
                "implementation": row["implementation"],
                "scheme": row["scheme"],
                "operation": row["operation"],
                "policy_attributes": int(row["policy_attributes"]),
                "repetition": int(row["repetition"]),
                "payload_bytes": int(row["payload_bytes"]),
                "latency_ms": float(row["latency_ms"]),
                "success": row["success"].lower() == "true",
            }
        )

    summary = summarize(measured, args.policy_sizes, args.reps)
    write_csv(args.raw_output, raw_rows)
    write_csv(args.summary_output, summary)

    git_commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    git_dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())
    rustc_version = run([str(Path(cargo).with_name("rustc.exe")), "--version"]).stdout.strip()
    cargo_version = run([cargo, "--version"]).stdout.strip()
    raw_sha256 = hashlib.sha256(args.raw_output.read_bytes()).hexdigest()
    config = {
        "schema": "TrustCircuit.CpAbePolicyBenchmark.v1",
        "run_id": run_id,
        "timestamp_utc": timestamp,
        "measurement_type": "directly measured",
        "comparison": {
            "kem_dem_baseline": "TrustCircuit LSSS all-of-N + secp256k1 ECIES per leaf + AES-256-GCM",
            "full_cpabe": "AC17/FAME pairing-based CP-ABE via rabe 0.4.2",
        },
        "policy_model": "left-associated binary all-of-N conjunction; decryption key contains all N attributes",
        "policy_sizes": args.policy_sizes,
        "repetitions": args.reps,
        "warmups_per_policy": args.warmups,
        "payload_bytes": args.payload_bytes,
        "timed_operations": ["encrypt", "decrypt"],
        "excluded_from_timing": ["scheme setup", "master-key setup", "user secret-key generation", "process startup", "CSV serialization"],
        "execution": "single-process, sequential operations, release-optimized Rust binary",
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "logical_cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "node": run([node, "--version"]).stdout.strip(),
            "rustc": rustc_version,
            "cargo": cargo_version,
        },
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "raw_csv": recorded_path(args.raw_output),
        "raw_csv_sha256": raw_sha256,
        "summary_csv": recorded_path(args.summary_output),
        "limitations": [
            "Latency is host- and toolchain-specific.",
            "The benchmark isolates policy-dependent cryptography with a 32-byte payload; setup and key generation are not included.",
            "The KEM-DEM baseline and AC17/FAME implementation use different cryptographic groups and language runtimes, so the comparison is an implementation-level systems benchmark rather than a primitive-equivalence proof.",
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
