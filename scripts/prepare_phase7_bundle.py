from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
VBS_ROOT = ROOT / "tee" / "vbs"
sys.path.insert(0, str(VBS_ROOT))

from phase7_encoding import encode_phase7_context  # noqa: E402
from pipeline_client import execute_synthetic_request  # noqa: E402


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one real VBS execution bundle for Phase 7 settlement."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--function", choices=("COUNT", "MEAN"), default="MEAN")
    parser.add_argument("--rows", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260719)
    parser.add_argument("--epsilon", type=float, default=1.0)
    parser.add_argument("--delta", type=float, default=0.00001)
    parser.add_argument("--request-id")
    parser.add_argument("--asset-id", default="asset-phase7-synthetic")
    parser.add_argument("--consumer-id", default="consumer-phase7-local")
    args = parser.parse_args()

    started_ns = time.perf_counter_ns()
    request_id = args.request_id or f"phase7-{int(time.time() * 1000)}"
    pipeline = execute_synthetic_request(
        vbs_root=VBS_ROOT,
        configuration=args.configuration,
        function_name=args.function,
        rows=args.rows,
        seed=args.seed,
        epsilon=args.epsilon,
        delta=args.delta,
        request_id=request_id,
        asset_id=args.asset_id,
        consumer_id=args.consumer_id,
    )
    encoding = encode_phase7_context(pipeline["request"], pipeline["execution"])
    bundle = {
        "schema": "TrustCircuit.Phase7Bundle.v1",
        "measurement_type": "measured",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "git_commit": git_value("rev-parse", "HEAD"),
            "git_dirty": bool(git_value("status", "--porcelain")),
            "os": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "configuration": args.configuration,
            "function": args.function,
            "rows": args.rows,
            "seed": args.seed,
            "epsilon": args.epsilon,
            "delta": args.delta,
        },
        **pipeline,
        "phase7": encoding,
        "prepare_total_us": (time.perf_counter_ns() - started_ns) // 1000,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output.resolve()),
                "request_id": request_id,
                "transcript_hash": pipeline["execution"]["transcript_hash"],
                "attestation_digest": encoding["attestation_digest"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

