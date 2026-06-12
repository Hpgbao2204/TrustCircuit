"""Mock ZK prover for TrustCircuit MVP benchmarks.

This is a placeholder for the future Circom/snarkjs flow. It creates proof-like
JSON from public inputs so the pipeline can be benchmarked before WSL/ZK setup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha256_json(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id", default="REQ_001")
    parser.add_argument("--asset-id", default="ASSET_001")
    parser.add_argument("--policy-hash", default="policy:research:aggregate")
    parser.add_argument("--epsilon-cost", type=int, default=500_000)
    parser.add_argument("--attestation-hash", default="attestation:mock")
    parser.add_argument("--output", type=Path, default=Path("results/tmp/zk/mock_proof.json"))
    args = parser.parse_args()

    start = time.perf_counter()
    public_inputs = {
        "requestId": args.request_id,
        "assetId": args.asset_id,
        "policyHash": args.policy_hash,
        "epsilonCost": args.epsilon_cost,
        "attestationHash": args.attestation_hash,
    }
    proof = {
        "system": "mock-zk",
        "publicInputs": public_inputs,
        "proofHash": sha256_json(public_inputs),
        "provingTimeMs": (time.perf_counter() - start) * 1000,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
