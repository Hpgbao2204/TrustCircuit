"""Parent-side benchmark client for the TrustCircuit Nitro worker."""

from __future__ import annotations

import argparse
import csv
import json
import socket
import statistics
import time
from pathlib import Path


def call_worker(cid: int, port: int, request: dict) -> tuple[dict, float]:
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    start = time.perf_counter()
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.connect((cid, port))
    sock.sendall(payload)
    response = sock.recv(1024 * 1024)
    sock.close()
    end_to_end_ms = (time.perf_counter() - start) * 1000.0
    return json.loads(response.decode("utf-8")), end_to_end_ms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cid", type=int, default=16)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--payload-mib", type=int, nargs="+", default=[1, 8, 32, 128])
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--include-attestation", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("results/raw/nitro_latency.csv"))
    args = parser.parse_args()

    rows = []
    for payload_mib in args.payload_mib:
        for trial in range(args.trials):
            request = {
                "requestId": f"NITRO_{payload_mib}_{trial:03d}",
                "assetId": "ASSET_001",
                "functionId": "aggregate_mean_v1",
                "rows": args.rows,
                "payloadMiB": payload_mib,
                "epsilonCost": 500_000,
                "workerId": "NITRO_01",
                "includeAttestation": args.include_attestation,
            }
            response, e2e_ms = call_worker(args.cid, args.port, request)
            row = {
                "payload_mib": payload_mib,
                "trial": trial,
                "rows": args.rows,
                "enclave_latency_ms": response.get("latencyMs"),
                "end_to_end_latency_ms": round(e2e_ms, 3),
                "attestation_mode": response.get("attestationMode"),
                "attestation_latency_ms": response.get("attestationLatencyMs"),
                "attestation_document_size": response.get("attestationDocumentSize"),
                "attestation_document_hash": response.get("attestationDocumentHash"),
                "tee_backend": response.get("teeBackend"),
                "attestation_hash": response.get("attestationHash"),
                "result_hash": response.get("resultHash"),
            }
            rows.append(row)
            print(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    for payload_mib in args.payload_mib:
        latencies = [r["end_to_end_latency_ms"] for r in rows if r["payload_mib"] == payload_mib]
        print(
            f"payload={payload_mib:>4} MiB  "
            f"mean={statistics.mean(latencies):.2f} ms  "
            f"median={statistics.median(latencies):.2f} ms"
        )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
