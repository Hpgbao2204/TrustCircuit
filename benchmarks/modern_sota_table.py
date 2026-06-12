"""Modern (2024-2026) SOTA comparison generator for TrustCircuit.

This replaces the legacy comparison that ranked TrustCircuit against systems
from 2015-2019 (Zyskind, MedRec, Hawk, zkLedger, Ekiden, FastKitten). Reviewers
of a Q1 venue correctly object that (i) those baselines predate verifiable
differential privacy and modern ZK compliance, and (ii) a subjective "coverage"
score is not defensible.

We therefore emit three machine-checkable artifacts that the paper renders as
tables:

  modern_sota_capability.csv   - qualitative mechanism matrix vs 2024-2026 SOTA
                                 (Table A: no gas, no coverage score).
  modern_sota_comparison.csv   - quantitative ZK/VDP overhead vs modern systems.
                                 TrustCircuit rows are *measured* in this repo;
                                 external rows are *literature* values copied
                                 from the cited paper and flagged source=lit,
                                 with n/r where the paper does not report it.
  modern_sota_groups.csv       - the baseline taxonomy (group A-E) used in the
                                 related-work narrative.

Design rule: we never present a literature value as if we measured it. Every
external number carries (source, year, ref) so the claim is auditable.

Output dir: results/q1/summary/
"""

from __future__ import annotations

import csv
from pathlib import Path

SUMMARY = Path("results/summary")
Q1 = Path("results/q1/summary")

# Marker tokens shared with the LaTeX renderer.
YES = "yes"        # direct support  -> \ding{51}
PARTIAL = "partial"  # indirect/limited -> $\sim$
NO = "no"          # out of scope    -> ---
NR = "n/r"         # not reported in the source paper


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def measured_trustcircuit() -> dict[str, float]:
    """Pull the real, repository-measured numbers that anchor TrustCircuit."""
    zk_sel = {r["scheme"]: r for r in read_csv(SUMMARY / "zk_scheme_selection.csv")}
    g = zk_sel["groth16"]
    return {
        "proof_time_ms": float(g["prove_time_ms"]),
        "proof_size_bytes": int(g["proof_size_bytes"]),
        "verify_onchain_gas": int(g["verify_onchain_gas"]),
    }


# ---------------------------------------------------------------------------
# Table A: qualitative mechanism comparison vs modern (2024-2026) SOTA.
# Dimensions chosen to be objective (a capability is either in the system's
# design or it is not), not a numeric quality score.
# ---------------------------------------------------------------------------
CAP_DIMS = [
    "verifiable_dp",        # proves the DP/noise step is correct
    "zk_compliance",        # succinct proof of a policy/compliance predicate
    "blockchain_settlement",# on-chain settlement of the request/result
    "budget_accounting",    # composable privacy-budget ledger
    "proof_binding",        # proof bound to request/asset/consumer/policy/eps
    "replay_nullifier",     # single-use nullifier / replay protection
    "audit_support",        # tamper-evident per-operation audit evidence
    "confidential_compute", # TEE / MPC / encrypted execution
]

# (system, year, group, scores over CAP_DIMS, main_limitation, ref)
CAPABILITY = [
    ("VDP (Biswas-Cormode)", 2022, "A",
     [YES, YES, NO, PARTIAL, NO, NO, NO, NO],
     "Proves a single release is DP+reliable; no lifecycle/ledger settlement.",
     "biswas2022verifiable"),
    ("VDP-ZKP (Springer)", 2025, "A",
     [YES, YES, NO, NO, PARTIAL, NO, NO, NO],
     "Cost tied to data precision; standalone DP proof, no request binding.",
     "vdpzkp2025"),
    ("VDDP (client-server-verifier)", 2025, "A",
     [YES, YES, NO, PARTIAL, PARTIAL, NO, NO, PARTIAL],
     "Distributed DP verification; not bound to on-chain budget/audit.",
     "vddp2025"),
    ("Verifiable Exp. Mechanism", 2025, "A",
     [YES, YES, NO, NO, PARTIAL, NO, NO, NO],
     "Verifies one mechanism (median); not a circulation framework.",
     "vexp2025"),
    ("Khadka et al. (selective disc.)", 2026, "B",
     [NO, YES, YES, NO, PARTIAL, NO, PARTIAL, NO],
     "Compliance via selective disclosure; no DP budget accounting.",
     "khadka2026poster"),
    ("Robust+Secure FL w/ VDP (TDSC)", 2025, "C",
     [YES, PARTIAL, NO, PARTIAL, NO, NO, NO, PARTIAL],
     "Optimizes FL accuracy/robustness; not per-request settlement.",
     "robustfl2025"),
    ("VerifBFL (blockchain FL+zk)", 2025, "C",
     [NO, YES, YES, NO, PARTIAL, NO, YES, NO],
     "Verifies model updates; no DP budget or data-request lifecycle.",
     "verifbfl2025"),
    ("zkGPT (USENIX Sec.)", 2025, "D",
     [NO, PARTIAL, NO, NO, NO, NO, NO, NO],
     "Fast ZK for LLM inference; not a DP/compliance protocol.",
     "zkgpt2025"),
    ("Oasis Sapphire (conf. EVM)", 2024, "E",
     [NO, NO, YES, NO, NO, NO, PARTIAL, YES],
     "Confidential EVM via TEE; no DP budget or compliance proof.",
     "oasissapphire"),
    ("Secret Network", 2024, "E",
     [NO, NO, YES, NO, NO, NO, PARTIAL, YES],
     "Encrypted contracts; trust in enclave, no verifiable DP.",
     "secretnetwork"),
    ("TrustCircuit", 2026, "-",
     [YES, YES, YES, YES, YES, YES, YES, YES],
     "Prototype TEE simulator (not hardware SGX); stable-policy circuit.",
     "this"),
]


def write_capability() -> Path:
    Q1.mkdir(parents=True, exist_ok=True)
    out = Q1 / "modern_sota_capability.csv"
    fields = ["system", "year", "group", *CAP_DIMS, "main_limitation", "ref"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for system, year, group, scores, limit, ref in CAPABILITY:
            row = {"system": system, "year": year, "group": group,
                   "main_limitation": limit, "ref": ref}
            row.update(dict(zip(CAP_DIMS, scores)))
            w.writerow(row)
    return out


# ---------------------------------------------------------------------------
# Table 3: quantitative ZK/VDP overhead. Only TrustCircuit rows are measured
# here; external rows are literature values (per their cited paper) and are
# explicitly flagged. Mixed units are avoided: we compare the proof system that
# each work uses for its verifiable claim.
# ---------------------------------------------------------------------------
def write_comparison() -> Path:
    """Quantitative head-to-head table (the MAIN SOTA experiment table).

    Columns follow the supervisor's spec. `lifecycle_binding` is the column
    where TrustCircuit wins: how many request-context fields the proof is bound
    to (request, asset, consumer, policy, epsilon, nullifier, audit). External
    rows carry the paper's own reported numbers; n/r when not reported.
    """
    zk_sel = {r["scheme"]: r for r in read_csv(SUMMARY / "zk_scheme_selection.csv")}
    zk_sum = {r["scheme"]: r for r in read_csv(SUMMARY / "zk_schemes_summary.csv")}

    rows: list[dict] = []

    # --- measured TrustCircuit, three proof systems on the SAME circuit ---
    for scheme in ("groth16", "plonk", "fflonk"):
        r = zk_sel[scheme]
        rows.append({
            "system": f"TrustCircuit-{scheme}", "year": 2026,
            "target_problem": "data-circulation compliance",
            "proof_type": "DP+compliance",
            "onchain_verify": YES,
            "proof_system": scheme,
            "prove_time_ms": round(float(r["prove_time_ms"]), 1),
            "verify_time_ms": round(float(zk_sum[scheme]["verify_time_ms_mean"]), 2),
            "proof_size_bytes": int(r["proof_size_bytes"]),
            "onchain_gas": int(r["verify_onchain_gas"]),
            "lifecycle_binding": "full (7 fields)",
            "source": "measured",
            "ref": "this",
        })

    # --- literature-reported modern baselines ---
    rows.append({
        "system": "Khadka et al.", "year": 2026,
        "target_problem": "compliance (selective disclosure)",
        "proof_type": "compliance",
        "onchain_verify": YES,
        "proof_system": "zk-SNARK",
        "prove_time_ms": "<200", "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "partial (credential)",
        "source": "literature", "ref": "khadka2026poster",
    })
    rows.append({
        "system": "VDP-ZKP", "year": 2025,
        "target_problem": "single DP release",
        "proof_type": "DP proof",
        "onchain_verify": NO,
        "proof_system": "zk-SNARK",
        "prove_time_ms": "60-280", "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "none",
        "source": "literature", "ref": "vdpzkp2025",
    })
    rows.append({
        "system": "VDDP", "year": 2025,
        "target_problem": "distributed DP",
        "proof_type": "DP proof",
        "onchain_verify": NO,
        "proof_system": "ZKP/MPC",
        "prove_time_ms": NR, "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "none",
        "source": "literature", "ref": "vddp2025",
    })
    rows.append({
        "system": "Robust FL+VDP", "year": 2025,
        "target_problem": "federated-learning privacy",
        "proof_type": "DP (FL)",
        "onchain_verify": NO,
        "proof_system": "--",
        "prove_time_ms": NR, "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "none",
        "source": "literature", "ref": "robustfl2025",
    })
    rows.append({
        "system": "VerifBFL", "year": 2025,
        "target_problem": "FL model-update integrity",
        "proof_type": "compliance",
        "onchain_verify": YES,
        "proof_system": "zk-SNARK",
        "prove_time_ms": NR, "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "partial (update)",
        "source": "literature", "ref": "verifbfl2025",
    })
    rows.append({
        "system": "zkGPT", "year": 2025,
        "target_problem": "LLM inference (GPT-2)",
        "proof_type": "computation",
        "onchain_verify": NO,
        "proof_system": "GKR/sumcheck",
        "prove_time_ms": 25000.0, "verify_time_ms": NR,
        "proof_size_bytes": NR, "onchain_gas": NR,
        "lifecycle_binding": "none",
        "source": "literature", "ref": "zkgpt2025",
    })

    out = Q1 / "modern_sota_comparison.csv"
    fields = ["system", "year", "target_problem", "proof_type", "onchain_verify",
              "proof_system", "prove_time_ms", "verify_time_ms", "proof_size_bytes",
              "onchain_gas", "lifecycle_binding", "source", "ref"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out


def write_groups() -> Path:
    groups = [
        ("A", "Verifiable DP / ZKP-DP",
         "Prove a DP mechanism executed correctly on a release.",
         "Standalone proof of one mechanism; no request/budget/audit lifecycle."),
        ("B", "Blockchain / ZK compliance",
         "On-chain selective-disclosure or compliance checks.",
         "No composable DP budget accounting."),
        ("C", "Verifiable FL / ML with VDP",
         "Verifiable privacy in federated/collaborative training.",
         "Targets model accuracy, not per-request data circulation."),
        ("D", "Modern ZK systems",
         "Proof-generation performance for large computations.",
         "Not DP/compliance protocols; performance reference only."),
        ("E", "Confidential blockchain / TEE",
         "Confidential smart contracts via hardware enclaves.",
         "Trust in hardware; no verifiable DP budget/compliance proof."),
    ]
    out = Q1 / "modern_sota_groups.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "name", "focus", "gap_vs_trustcircuit"])
        w.writerows(groups)
    return out


def main() -> None:
    p1 = write_capability()
    p2 = write_comparison()
    p3 = write_groups()
    for p in (p1, p2, p3):
        print(p)


if __name__ == "__main__":
    main()
