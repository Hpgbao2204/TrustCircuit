"""TEE Worker Simulator for TrustCircuit.

This is not SGX. It produces deterministic-enough reports, witness files, and
malicious-mode behavior so the rest of the TrustCircuit pipeline can be tested
and benchmarked before any real TEE work exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


VALID_MODES = (
    "honest",
    "wrong_result",
    "under_report_epsilon",
    "skip_dp_noise",
    "stale_attestation",
    "invalid_witness",
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkerRequest:
    requestId: str
    assetId: str
    functionId: str
    epsilonRequested: int
    payloadHash: str


@dataclass(frozen=True)
class WorkerReport:
    requestId: str
    assetId: str
    workerId: str
    codeHash: str
    dataHash: str
    resultHash: str
    epsilonCost: int
    attestationHash: str
    signature: str
    sealedWitnessPath: str
    mode: str
    acceptedBySimulator: bool
    latencyMs: float


def assign_worker(request_id: str, pool_size: int) -> str:
    digest = int(sha256_text(request_id), 16)
    return f"TEE_{(digest % pool_size) + 1:02d}"


def build_request(request_id: str, asset_id: str, epsilon: int) -> WorkerRequest:
    return WorkerRequest(
        requestId=request_id,
        assetId=asset_id,
        functionId="aggregate_mean_v1",
        epsilonRequested=epsilon,
        payloadHash=sha256_text(f"payload|{asset_id}|{request_id}"),
    )


def run_worker(request: WorkerRequest, worker_id: str, mode: str, output_dir: Path) -> WorkerReport:
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported mode: {mode}")

    start = time.perf_counter()
    code_hash = sha256_text(request.functionId)
    data_hash = sha256_text(f"synthetic-healthcare|{request.assetId}")
    true_result = 48.0
    noisy_result = true_result + 0.42
    result_value = noisy_result
    epsilon_cost = request.epsilonRequested

    if mode == "wrong_result":
        result_value = 999.0
    elif mode == "under_report_epsilon":
        epsilon_cost = max(1, request.epsilonRequested // 5)
    elif mode == "skip_dp_noise":
        result_value = true_result

    result_hash = sha256_text(f"{request.requestId}|{request.functionId}|{result_value:.6f}")
    attestation_request_id = "STALE_REQUEST" if mode == "stale_attestation" else request.requestId
    attestation_material = (
        f"{attestation_request_id}|{request.assetId}|{worker_id}|{code_hash}|"
        f"{data_hash}|{result_hash}|{epsilon_cost}"
    )
    attestation_hash = sha256_text(attestation_material)

    witness_dir = output_dir / "witness"
    witness_dir.mkdir(parents=True, exist_ok=True)
    sealed_witness_path = witness_dir / f"{request.requestId}.json"
    witness_payload = {
        "requestId": request.requestId,
        "assetId": request.assetId,
        "workerId": worker_id,
        "functionId": request.functionId,
        "mode": mode,
        "trueResult": true_result,
        "resultValue": result_value,
        "epsilonRequested": request.epsilonRequested,
        "epsilonCost": epsilon_cost,
        "payloadHash": request.payloadHash,
    }
    if mode == "invalid_witness":
        witness_payload["requestId"] = "CORRUPTED_REQUEST"

    sealed_witness_path.write_text(json.dumps(witness_payload, indent=2), encoding="utf-8")

    accepted = mode in ("honest", "skip_dp_noise")
    latency_ms = (time.perf_counter() - start) * 1000
    return WorkerReport(
        requestId=request.requestId,
        assetId=request.assetId,
        workerId=worker_id,
        codeHash=code_hash,
        dataHash=data_hash,
        resultHash=result_hash,
        epsilonCost=epsilon_cost,
        attestationHash=attestation_hash,
        signature=sha256_text(f"sig|{worker_id}|{attestation_hash}"),
        sealedWitnessPath=str(sealed_witness_path),
        mode=mode,
        acceptedBySimulator=accepted,
        latencyMs=latency_ms,
    )


def write_report(report: WorkerReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{report.requestId}_report.json"
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id", default="REQ_001")
    parser.add_argument("--asset-id", default="ASSET_001")
    parser.add_argument("--worker-id", default="")
    parser.add_argument("--pool-size", type=int, default=3)
    parser.add_argument("--epsilon", type=int, default=500_000)
    parser.add_argument("--mode", choices=VALID_MODES, default="honest")
    parser.add_argument("--output-dir", type=Path, default=Path("results/tmp/tee"))
    args = parser.parse_args()

    request = build_request(args.request_id, args.asset_id, args.epsilon)
    worker_id = args.worker_id or assign_worker(args.request_id, args.pool_size)
    report = run_worker(request, worker_id, args.mode, args.output_dir)
    report_path = write_report(report, args.output_dir)
    print(report_path)


if __name__ == "__main__":
    main()
