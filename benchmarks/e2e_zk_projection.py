"""Project end-to-end pipeline latency/throughput when the compliance prover is
each measured ZK scheme (Groth16 / PLONK / fflonk).

The projection substitutes the *measured* proof-generation time of each scheme
into the critical path, on top of the measured TEE-compute and on-chain
settlement stages of a TC-Full circulation. All component numbers come from
committed measurements:

    prove / off-chain verify : results/summary/zk_schemes_summary.csv
    on-chain verify gas      : results/summary/zk_schemes_gas.csv
    TEE compute (median)     : results/summary/e2e_pipeline_summary.csv (tee_compute)
    on-chain settlement      : results/summary/e2e_pipeline_summary.csv (on-chain stages)

Output: results/summary/e2e_zk_schemes.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

SUMMARY = Path("results/summary")

# Measured non-prover stage latencies of a TC-Full circulation (ms).
# TEE confidential compute (median of TC-Full tee_compute) and the aggregate
# of all on-chain settlement calls excluding the proof stage.
TEE_COMPUTE_MS = 44.0
ONCHAIN_SETTLEMENT_MS = 13.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    schemes = read_csv(SUMMARY / "zk_schemes_summary.csv")
    gas = {r["scheme"]: int(r["verify_gas"]) for r in read_csv(SUMMARY / "zk_schemes_gas.csv")}

    out_rows = []
    for r in schemes:
        scheme = r["scheme"]
        prove = float(r["prove_time_ms_mean"])
        verify_off = float(r["verify_time_ms_mean"])
        e2e = TEE_COMPUTE_MS + ONCHAIN_SETTLEMENT_MS + prove + verify_off
        out_rows.append(
            {
                "scheme": scheme,
                "setup_model": r["setup_model"],
                "tee_compute_ms": f"{TEE_COMPUTE_MS:.1f}",
                "onchain_settlement_ms": f"{ONCHAIN_SETTLEMENT_MS:.1f}",
                "prove_ms": f"{prove:.1f}",
                "offchain_verify_ms": f"{verify_off:.2f}",
                "e2e_latency_ms": f"{e2e:.1f}",
                "throughput_req_s": f"{1000.0 / e2e:.3f}",
                "onchain_verify_gas": gas.get(scheme, 0),
                "proof_size_bytes": r["proof_size_bytes"],
            }
        )

    out = SUMMARY / "e2e_zk_schemes.csv"
    fields = list(out_rows[0].keys())
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    for r in out_rows:
        print(f"{r['scheme']}: e2e={r['e2e_latency_ms']}ms thr={r['throughput_req_s']} gas={r['onchain_verify_gas']}")
    print(out)


if __name__ == "__main__":
    main()
