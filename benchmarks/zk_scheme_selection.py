"""Build a ZK proof-system selection matrix.

Three schemes (Groth16, PLONK, fflonk) are instantiated on the *same*
compliance circuit and measured locally in this repository. Two further
families (STARK and Bulletproofs) are characterised from the literature and
clearly flagged measured=0, because their EVM-side verification is not part of
the snarkjs/Circom toolchain used here. The matrix is meant to justify the
Groth16 default and document the trade-offs of switching schemes.

Sources for the non-measured rows: STARK (transparent, post-quantum, large
proofs, EVM verification typically delegated to L2) and Bulletproofs (no
trusted setup, short logarithmic proofs, linear verifier cost). These columns
are representative literature values, not local measurements.

Output: results/summary/zk_scheme_selection.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

SUMMARY = Path("results/summary")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    sm = {r["scheme"]: r for r in read_csv(SUMMARY / "zk_schemes_summary.csv")}
    gas = {r["scheme"]: int(r["verify_gas"]) for r in read_csv(SUMMARY / "zk_schemes_gas.csv")}

    rows: list[dict] = []

    def measured_row(scheme, transparent, pq, rec):
        r = sm[scheme]
        rows.append({
            "scheme": scheme,
            "setup_model": r["setup_model"],
            "transparent": transparent,
            "post_quantum": pq,
            "proof_size_bytes": int(r["proof_size_bytes"]),
            "prove_time_ms": round(float(r["prove_time_ms_mean"]), 1),
            "verify_onchain_gas": gas.get(scheme, 0),
            "measured": 1,
            "recommendation": rec,
        })

    measured_row("groth16", 0, 0, "Default: smallest proof and cheapest constant EVM verify; per-circuit setup.")
    measured_row("plonk", 0, 0, "Universal setup: edit rules without a new ceremony; larger proof and verify gas.")
    measured_row("fflonk", 0, 0, "Universal setup: lowest verify gas of the three but heaviest prover and key.")

    # Literature-characterised families (not measured in this toolchain).
    rows.append({
        "scheme": "stark", "setup_model": "transparent", "transparent": 1, "post_quantum": 1,
        "proof_size_bytes": 100000, "prove_time_ms": 800, "verify_onchain_gas": 5000000,
        "measured": 0,
        "recommendation": "Transparent + post-quantum; large proofs make direct EVM verify impractical (suited to L2).",
    })
    rows.append({
        "scheme": "bulletproofs", "setup_model": "transparent", "transparent": 1, "post_quantum": 0,
        "proof_size_bytes": 1400, "prove_time_ms": 3000, "verify_onchain_gas": 1500000,
        "measured": 0,
        "recommendation": "No trusted setup, short logarithmic proofs; linear verifier too costly for frequent on-chain checks.",
    })

    out = SUMMARY / "zk_scheme_selection.csv"
    fields = list(rows[0].keys())
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['scheme']}: proof={r['proof_size_bytes']}B gas={r['verify_onchain_gas']} measured={r['measured']}")
    print(out)


if __name__ == "__main__":
    main()
