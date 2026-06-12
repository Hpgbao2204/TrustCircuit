"""Measure AWS Nitro NSM attestation-document latency."""

from __future__ import annotations

import argparse
import csv
import json
import socket
import statistics
import time
from pathlib import Path


def call_worker(cid: int, port: int, trial: int, rows: int, payload_mib: int) -> dict:
    request = {
        "requestId": f"NITRO_ATT_{trial:04d}",
        "assetId": "ASSET_001",
        "functionId": "aggregate_mean_v1",
        "rows": rows,
        "payloadMiB": payload_mib,
        "epsilonCost": 500_000,
        "workerId": "NITRO_01",
        "includeAttestation": True,
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    start = time.perf_counter()
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.connect((cid, port))
    sock.sendall(payload)
    response = json.loads(sock.recv(1024 * 1024).decode("utf-8"))
    sock.close()
    response["endToEndLatencyMs"] = round((time.perf_counter() - start) * 1000.0, 3)
    response["trial"] = trial
    return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cid", type=int, default=16)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--payload-mib", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("results/raw/nitro_attestation.csv"))
    args = parser.parse_args()

    rows = []
    for trial in range(args.trials):
        response = call_worker(args.cid, args.port, trial, args.rows, args.payload_mib)
        row = {
            "trial": trial,
            "attestation_latency_ms": response["attestationLatencyMs"],
            "end_to_end_latency_ms": response["endToEndLatencyMs"],
            "attestation_document_size": response["attestationDocumentSize"],
            "attestation_document_hash": response["attestationDocumentHash"],
            "attestation_mode": response["attestationMode"],
        }
        rows.append(row)
        print(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    att = [float(r["attestation_latency_ms"]) for r in rows]
    print(
        f"attestation latency ms: mean={statistics.mean(att):.2f} "
        f"median={statistics.median(att):.2f} min={min(att):.2f} max={max(att):.2f}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
