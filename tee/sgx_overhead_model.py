"""Analytical Intel SGX overhead-projection model for TrustCircuit.

The TrustCircuit TEE layer is a *software* processor-pool simulator (see
worker_sim.py). The evaluation host is an AMD Ryzen platform that does not
implement Intel SGX, so the simulator cannot reproduce hardware-enclave
dynamics: encrypted-memory (MEE) access overhead, EPC paging when the working
set exceeds the Enclave Page Cache, enclave-transition (ECALL/OCALL) cost, and
remote-attestation (DCAP quote) latency.

Rather than presenting simulator timings as hardware-TEE performance, this
module *projects* a defensible interval for the per-request SGX latency and the
resulting single-worker throughput, by composing the measured simulator compute
time with overhead constants taken from the published SGX-microbenchmark
literature. Every constant is a documented range, so the projection is reported
as a [lower, upper] band rather than a single fabricated number.

Literature constants
--------------------
* ECALL/OCALL transition: 8,200 - 17,000 cycles per crossing
  (Weisse, Bertacco, Austin, "Regaining Lost Cycles with HotCalls", ISCA 2017).
* EPC page eviction/load (EWB+ELDU): ~12,000 - 40,000 cycles per 4 KiB page
  once the working set exceeds the EPC (Orenbach et al., "Eleos", EuroSys 2017).
* In-EPC MEE read/write slowdown (working set fits EPC): ~1.1x - 1.2x
  (SGX benchmark studies; library-OS overhead is within ~+/-10%).
* Usable EPC (SGXv1): ~93 MiB (128 MiB provisioned). SGXv2 lifts this to GBs.
* DCAP remote-attestation quote generation: ~10 - 50 ms (amortizable per session).

Content above was rephrased from the cited sources for licensing compliance.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POOL_SUMMARY = REPO / "results" / "summary" / "tee_pool_summary.csv"
OUT_CSV = REPO / "results" / "summary" / "sgx_projection.csv"
OUT_JSON = REPO / "results" / "summary" / "sgx_projection_config.json"


@dataclass(frozen=True)
class SgxConstants:
    clock_hz: float = 2.5e9          # enclave-capable CPU clock (conservative)
    transition_cycles_lo: int = 8_200
    transition_cycles_hi: int = 17_000
    n_transitions: int = 6           # enter, sealed-read, fetch, rng, emit, exit
    mee_slowdown_lo: float = 1.10    # in-EPC encrypted-memory overhead
    mee_slowdown_hi: float = 1.20
    epc_usable_mib: float = 93.0     # SGXv1 usable Enclave Page Cache
    page_cycles_lo: int = 12_000     # EWB+ELDU per 4 KiB page when paging
    page_cycles_hi: int = 40_000
    page_kib: float = 4.0
    attest_ms_lo: float = 10.0       # DCAP quote latency (amortizable)
    attest_ms_hi: float = 50.0


def cycles_to_ms(cycles: float, clock_hz: float) -> float:
    return 1_000.0 * cycles / clock_hz


def project_request(sim_compute_ms: float, working_set_mib: float,
                    k: SgxConstants, include_attest: bool) -> tuple[float, float]:
    """Return (lo_ms, hi_ms) projected per-request SGX latency."""
    # 1. encrypted-memory compute overhead (multiplicative, in-EPC)
    compute_lo = k.mee_slowdown_lo * sim_compute_ms
    compute_hi = k.mee_slowdown_hi * sim_compute_ms

    # 2. enclave transition cost (additive)
    tr_lo = k.n_transitions * cycles_to_ms(k.transition_cycles_lo, k.clock_hz)
    tr_hi = k.n_transitions * cycles_to_ms(k.transition_cycles_hi, k.clock_hz)

    # 3. EPC paging penalty, only when working set exceeds usable EPC
    overflow_mib = max(0.0, working_set_mib - k.epc_usable_mib)
    n_pages = overflow_mib * 1024.0 / k.page_kib
    pg_lo = n_pages * cycles_to_ms(k.page_cycles_lo, k.clock_hz)
    pg_hi = n_pages * cycles_to_ms(k.page_cycles_hi, k.clock_hz)

    # 4. remote-attestation quote (optional / amortizable)
    att_lo = k.attest_ms_lo if include_attest else 0.0
    att_hi = k.attest_ms_hi if include_attest else 0.0

    return (compute_lo + tr_lo + pg_lo + att_lo,
            compute_hi + tr_hi + pg_hi + att_hi)


def read_honest_compute() -> list[tuple[int, float]]:
    """(pool_size, honest compute_latency_mean_ms) from the simulator summary."""
    rows: list[tuple[int, float]] = []
    if not POOL_SUMMARY.exists():
        # fall back to documented single-worker simulator compute time
        return [(1, 0.415)]
    with POOL_SUMMARY.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("mode") == "honest":
                rows.append((int(r["pool_size"]), float(r["compute_latency_mean_ms"])))
    return rows or [(1, 0.415)]


def main() -> None:
    k = SgxConstants()
    honest = read_honest_compute()

    # Two regimes: the 50k-record aggregate query fits the EPC (no paging),
    # while a large analytics payload (~512 MiB) forces protected paging.
    scenarios = [
        ("fits_epc_no_attest", 32.0, False),
        ("fits_epc_attested", 32.0, True),
        ("exceeds_epc_attested", 512.0, True),
    ]

    out_rows = []
    for scenario, ws, attest in scenarios:
        for pool_size, sim_ms in honest:
            lo, hi = project_request(sim_ms, ws, k, attest)
            out_rows.append({
                "scenario": scenario,
                "working_set_mib": ws,
                "pool_size": pool_size,
                "sim_compute_ms": round(sim_ms, 4),
                "proj_latency_lo_ms": round(lo, 3),
                "proj_latency_hi_ms": round(hi, 3),
                "sim_throughput_rps": round(1000.0 / sim_ms, 2),
                "proj_throughput_lo_rps": round(1000.0 / hi, 3),
                "proj_throughput_hi_rps": round(1000.0 / lo, 3),
            })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    OUT_JSON.write_text(json.dumps(asdict(k), indent=2), encoding="utf-8")

    print(f"wrote {OUT_CSV}")
    for r in out_rows:
        print(f"{r['scenario']:>22} k={r['pool_size']:>2}  "
              f"sim={r['sim_compute_ms']:.3f}ms -> "
              f"SGX [{r['proj_latency_lo_ms']:.2f}, {r['proj_latency_hi_ms']:.2f}] ms  "
              f"thru [{r['proj_throughput_lo_rps']:.2f}, {r['proj_throughput_hi_rps']:.2f}] req/s")


if __name__ == "__main__":
    main()
