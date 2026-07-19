from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
VBS_ROOT = ROOT / "tee" / "vbs"
sys.path.insert(0, str(VBS_ROOT))

from phase7_encoding import encode_phase7_context  # noqa: E402
from pipeline_client import execute_synthetic_request  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create one feature-matched Native or VBS sample for the Phase 8 "
            "controlled comparison."
        )
    )
    parser.add_argument(
        "--variant",
        choices=("tee_only", "local_dp_ledger", "trustcircuit"),
        required=True,
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--seed", type=int, default=20260719)
    parser.add_argument("--epsilon", type=float, default=0.5)
    parser.add_argument("--delta", type=float, default=0.00001)
    args = parser.parse_args()

    processor = "native" if args.variant == "local_dp_ledger" else "vbs"
    validate = processor == "vbs"
    request_id = f"phase8-comparison-{args.variant}-{args.run}-{time.time_ns()}"
    pipeline = execute_synthetic_request(
        vbs_root=VBS_ROOT,
        configuration=args.configuration,
        function_name="MEAN",
        rows=args.rows,
        seed=args.seed + args.run,
        epsilon=args.epsilon,
        delta=args.delta,
        request_id=request_id,
        asset_id=f"asset-phase8-comparison-{args.variant}-{args.run}",
        consumer_id="consumer-phase8-local",
        processor=processor,
        validate_attestation_evidence=validate,
    )

    accounting_started = time.perf_counter_ns()
    actual_cost = int(pipeline["execution"]["actual_privacy_cost_fixed"])
    local_budget_total = 5_000_000
    local_budget_remaining = local_budget_total - actual_cost
    if local_budget_remaining < 0:
        raise RuntimeError("comparison local DP budget would be overspent")
    accounting_latency_us = (time.perf_counter_ns() - accounting_started) // 1000

    result = {
        "schema": "TrustCircuit.Phase8ComparisonProcessorSample.v1",
        "measurement_type": "locally_measured",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "variant": args.variant,
        "configuration": args.configuration,
        "run": args.run,
        "seed": args.seed + args.run,
        "epsilon": args.epsilon,
        "delta": args.delta,
        **pipeline,
        "local_budget": {
            "enabled": args.variant == "local_dp_ledger",
            "total_fixed": local_budget_total,
            "consumed_fixed": actual_cost,
            "remaining_fixed": local_budget_remaining,
            "invariant_violation": False,
            "accounting_latency_us": int(accounting_latency_us),
        },
    }
    if args.variant == "trustcircuit":
        result["phase7"] = encode_phase7_context(
            pipeline["request"], pipeline["execution"]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "variant": args.variant,
                "output": str(args.output),
                "request_id": request_id,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
