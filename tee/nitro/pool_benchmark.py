"""Concurrent parent-side benchmark across multiple Nitro Enclave workers."""

from __future__ import annotations

import argparse
import csv
import json
import socket
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def read_proc_stat() -> tuple[int, int]:
    with Path("/proc/stat").open("r", encoding="utf-8") as f:
        parts = f.readline().split()
    values = [int(v) for v in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total, idle


def cpu_util_percent(before: tuple[int, int], after: tuple[int, int]) -> float:
    total_delta = after[0] - before[0]
    idle_delta = after[1] - before[1]
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))


def call_worker(cid: int, port: int, request_id: str, rows: int, payload_mib: int) -> dict:
    request = {
        "requestId": request_id,
        "assetId": "ASSET_001",
        "functionId": "aggregate_mean_v1",
        "rows": rows,
        "payloadMiB": payload_mib,
        "epsilonCost": 500_000,
        "workerId": f"NITRO_CID_{cid}",
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    start = time.perf_counter()
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.connect((cid, port))
    sock.sendall(payload)
    response = json.loads(sock.recv(1024 * 1024).decode("utf-8"))
    sock.close()
    response["endToEndLatencyMs"] = round((time.perf_counter() - start) * 1000.0, 3)
    response["cid"] = cid
    return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cids", type=int, nargs="+", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--payload-mib", type=int, default=1)
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--out", type=Path, default=Path("results/raw/nitro_pool.csv"))
    args = parser.parse_args()

    cpu_before = read_proc_stat()
    start = time.perf_counter()
    rows = []
    with ThreadPoolExecutor(max_workers=len(args.cids)) as executor:
        futures = []
        for i in range(args.requests):
            cid = args.cids[i % len(args.cids)]
            futures.append(
                executor.submit(
                    call_worker,
                    cid,
                    args.port,
                    f"NITRO_POOL_{len(args.cids)}_{i:04d}",
                    args.rows,
                    args.payload_mib,
                )
            )
        for future in as_completed(futures):
            response = future.result()
            rows.append(
                {
                    "worker_count": len(args.cids),
                    "cid": response["cid"],
                    "request_id": response["requestId"],
                    "payload_mib": args.payload_mib,
                    "rows": args.rows,
                    "enclave_latency_ms": response["latencyMs"],
                    "end_to_end_latency_ms": response["endToEndLatencyMs"],
                }
            )

    elapsed_s = time.perf_counter() - start
    host_cpu = cpu_util_percent(cpu_before, read_proc_stat())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.out.exists()
    with args.out.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()) + [
                "batch_elapsed_s",
                "throughput_rps",
                "throughput_per_worker_rps",
                "host_cpu_util_percent",
            ],
        )
        if write_header:
            writer.writeheader()
        throughput = len(rows) / elapsed_s
        for row in rows:
            row["batch_elapsed_s"] = round(elapsed_s, 3)
            row["throughput_rps"] = round(throughput, 3)
            row["throughput_per_worker_rps"] = round(throughput / len(args.cids), 3)
            row["host_cpu_util_percent"] = round(host_cpu, 3)
            writer.writerow(row)

    lat = [float(r["end_to_end_latency_ms"]) for r in rows]
    print(
        f"workers={len(args.cids)} requests={len(rows)} elapsed={elapsed_s:.2f}s "
        f"throughput={throughput:.2f} req/s per_worker={throughput / len(args.cids):.2f} req/s "
        f"cpu={host_cpu:.1f}% median_latency={statistics.median(lat):.2f} ms"
    )
    print(f"wrote/appended {args.out}")


if __name__ == "__main__":
    main()
