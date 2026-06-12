"""Minimal AWS Nitro Enclaves worker for TrustCircuit experiments.

The parent instance sends JSON requests over vsock. The enclave performs a
deterministic aggregate workload, adds deterministic DP-like noise for
reproducible benchmarking, and returns a TrustCircuit-style report.

This first worker validates real Nitro isolation and vsock execution. Real
Nitro attestation-document generation is intentionally added as a later layer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import time

try:
    import aws_nsm_interface
except Exception:  # pragma: no cover - only present inside Nitro image
    aws_nsm_interface = None


PORT = 5000


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deterministic_aggregate(rows: int, payload_mib: int) -> tuple[float, str]:
    """Return a synthetic mean and data hash without external dependencies."""
    h = hashlib.sha256()
    total = 0.0
    state = 0xC0FFEE
    chunk = bytearray(1024 * 1024)

    for i in range(rows):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        total += 48.0 + ((state % 1000) - 500) / 100.0

    for block in range(payload_mib):
        seed = (state + block * 2654435761) & 0xFFFFFFFF
        for j in range(0, len(chunk), 8):
            seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF
            chunk[j : j + 8] = seed.to_bytes(4, "little") * 2
        h.update(chunk)

    return total / max(rows, 1), h.hexdigest()


def handle_request(request: dict) -> dict:
    start = time.perf_counter()
    request_id = str(request.get("requestId", "REQ_NITRO_001"))
    asset_id = str(request.get("assetId", "ASSET_001"))
    function_id = str(request.get("functionId", "aggregate_mean_v1"))
    rows = int(request.get("rows", 50_000))
    payload_mib = int(request.get("payloadMiB", 1))
    epsilon_cost = int(request.get("epsilonCost", 500_000))
    worker_id = str(request.get("workerId", "NITRO_01"))

    mean_value, data_hash = deterministic_aggregate(rows, payload_mib)
    noise = math.sin(rows + payload_mib) * 0.01
    result_value = mean_value + noise

    code_hash = sha256_text("tee/nitro/enclave_worker.py|v1")
    result_hash = sha256_text(f"{request_id}|{function_id}|{result_value:.8f}")
    transcript = (
        f"{request_id}|{asset_id}|{worker_id}|{function_id}|{code_hash}|"
        f"{data_hash}|{result_hash}|{epsilon_cost}|{rows}|{payload_mib}"
    )
    attestation_hash = sha256_text(transcript)
    attestation_mode = "transcript-hash-only"
    attestation_doc_hash = ""
    attestation_doc_size = 0
    attestation_latency_ms = 0.0

    if bool(request.get("includeAttestation", False)):
        att_start = time.perf_counter()
        if aws_nsm_interface is None:
            raise RuntimeError("aws_nsm_interface is not available in this enclave image")
        fd = os.open("/dev/nsm", os.O_RDWR)
        try:
            doc = aws_nsm_interface.get_attestation_doc(
                fd,
                nonce=sha256_text(request_id).encode("utf-8")[:32],
                user_data=attestation_hash.encode("utf-8"),
            )["document"]
        finally:
            os.close(fd)
        attestation_doc_hash = hashlib.sha256(doc).hexdigest()
        attestation_doc_size = len(doc)
        attestation_latency_ms = (time.perf_counter() - att_start) * 1000.0
        attestation_hash = sha256_text(f"{attestation_hash}|{attestation_doc_hash}")
        attestation_mode = "nitro-nsm-document"

    latency_ms = (time.perf_counter() - start) * 1000.0

    return {
        "requestId": request_id,
        "assetId": asset_id,
        "workerId": worker_id,
        "codeHash": code_hash,
        "dataHash": data_hash,
        "resultHash": result_hash,
        "epsilonCost": epsilon_cost,
        "attestationHash": attestation_hash,
        "attestationDocumentHash": attestation_doc_hash,
        "attestationDocumentSize": attestation_doc_size,
        "attestationLatencyMs": round(attestation_latency_ms, 3),
        "signature": sha256_text(f"nitro-sig|{worker_id}|{attestation_hash}"),
        "rows": rows,
        "payloadMiB": payload_mib,
        "resultValue": round(result_value, 8),
        "latencyMs": round(latency_ms, 3),
        "teeBackend": "aws-nitro-enclaves",
        "attestationMode": attestation_mode,
    }


def main() -> None:
    server = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    server.bind((socket.VMADDR_CID_ANY, PORT))
    server.listen(32)
    print(f"nitro worker listening on vsock port {PORT}", flush=True)

    while True:
        conn, _ = server.accept()
        try:
            data = conn.recv(1024 * 1024)
            request = json.loads(data.decode("utf-8"))
            response = handle_request(request)
            conn.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8"))
        except Exception as exc:  # keep enclave alive during benchmark failures
            error = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            conn.sendall(json.dumps(error).encode("utf-8"))
        finally:
            conn.close()


if __name__ == "__main__":
    main()
