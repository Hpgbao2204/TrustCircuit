"""Aggregate the Q1 experiment raw CSVs into paper-ready summaries.

Inputs  (results/q1/raw):
    e2e_ablation.csv
    budget_composition.csv
    budget_double_spend.csv
    proof_binding_attacks.csv

Outputs (results/q1/summary):
    e2e_ablation_summary.csv
    budget_composition_summary.csv
    budget_double_spend_summary.csv
    proof_binding_attacks_summary.csv
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

import numpy as np

RAW = Path("results/q1/raw")
SUM = Path("results/q1/summary")


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p)) if values else 0.0


# ---------------------------------------------------------------------------
# E2E ablation: per-variant totals (latency percentiles, gas, proof gas, etc.)
# ---------------------------------------------------------------------------
PROOF_STAGES = {"submitProof", "zk_verify_proof"}


def summarize_e2e() -> None:
    rows = read(RAW / "e2e_ablation.csv")
    by_run: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_variant: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_variant[r["variant"]].append(r)
        by_run[(r["variant"], r["run_id"])].append(r)

    out = []
    for variant in sorted(by_variant):
        runs = [v for (vv, _), v in by_run.items() if vv == variant]
        total_lat, total_gas, proof_gas = [], [], []
        for run in runs:
            lat = sum(float(x["latency_ms"]) for x in run if x.get("success") == "true")
            gas = sum(float(x["gas_used"]) for x in run if x.get("gas_used"))
            pg = sum(float(x["gas_used"]) for x in run if x.get("gas_used") and x["stage"] in PROOF_STAGES)
            total_lat.append(lat)
            total_gas.append(gas)
            proof_gas.append(pg)
        allr = by_variant[variant]
        success_rate = sum(1 for x in allr if x.get("success") == "true") / max(len(allr), 1)
        m_lat = mean(total_lat) if total_lat else 0.0
        out.append({
            "variant": variant,
            "runs": len(runs),
            "mean_latency_ms": round(m_lat, 4),
            "std_latency_ms": round(pstdev(total_lat), 4) if len(total_lat) > 1 else 0.0,
            "p50_latency_ms": round(pct(total_lat, 50), 4),
            "p95_latency_ms": round(pct(total_lat, 95), 4),
            "p99_latency_ms": round(pct(total_lat, 99), 4),
            "total_gas": round(mean(total_gas), 1) if total_gas else 0.0,
            "proof_gas": round(mean(proof_gas), 1) if proof_gas else 0.0,
            "success_rate": round(success_rate, 4),
            "throughput_req_s": round(1000.0 / m_lat, 3) if m_lat > 0 else 0.0,
        })
    write(SUM / "e2e_ablation_summary.csv", out, list(out[0].keys()))


# ---------------------------------------------------------------------------
# Budget composition: final state per (regime, epsilon) after 100 requests.
# ---------------------------------------------------------------------------
def summarize_budget_composition() -> None:
    rows = read(RAW / "budget_composition.csv")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["regime"], r["epsilon"])].append(r)

    out = []
    for (regime, epsilon), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], float(kv[0][1]))):
        last = max(rs, key=lambda x: int(x["request_index"]))
        gas_vals = [float(x["gas_per_request"]) for x in rs if float(x["gas_per_request"]) > 0]
        out.append({
            "regime": regime,
            "epsilon": float(epsilon),
            "accepted_requests": int(last["accepted_requests"]),
            "rejected_requests": int(last["rejected_requests"]),
            "remaining_budget": float(last["remaining_budget"]),
            "cumulative_epsilon": float(last["cumulative_epsilon"]),
            "overspend_amount": float(last["overspend_amount"]),
            "budget_invariant_violations": int(last["budget_invariant_violations"]),
            "mean_gas_per_request": round(mean(gas_vals), 1) if gas_vals else 0.0,
            "utility_loss": round(int(last["rejected_requests"]) / max(int(last["accepted_requests"]) + int(last["rejected_requests"]), 1), 4),
        })
    write(SUM / "budget_composition_summary.csv", out, list(out[0].keys()))


# ---------------------------------------------------------------------------
# Double-spend: rates per (concurrency, epsilon, budget) over trials.
# ---------------------------------------------------------------------------
def summarize_double_spend() -> None:
    rows = read(RAW / "budget_double_spend.csv")
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(int(r["concurrency"]), float(r["epsilon"]), float(r["budget"]))].append(r)

    out = []
    for (conc, eps, bud), rs in sorted(groups.items()):
        n = len(rs)
        accepted = [int(x["accepted"]) for x in rs]
        capacity = int(rs[0]["capacity"])
        overspend = [int(x["overspend_accepted"]) for x in rs]
        attack = [int(x["attack_success"]) for x in rs]
        consistent = [int(x["final_budget_consistent"]) for x in rs]
        out.append({
            "concurrency": conc,
            "epsilon": eps,
            "budget": bud,
            "trials": n,
            "capacity": capacity,
            "mean_accepted": round(mean(accepted), 3),
            "overspend_accepted_rate": round(mean([1 if o > 0 else 0 for o in overspend]), 4),
            "blocked_rate": round(mean([(conc - a) / conc for a in accepted]), 4),
            "attack_success_rate": round(mean(attack), 4),
            "final_budget_consistent_rate": round(mean(consistent), 4),
        })
    write(SUM / "budget_double_spend_summary.csv", out, list(out[0].keys()))

    # also a compact view aggregated over epsilon/budget per concurrency.
    by_conc: dict[int, list[dict]] = defaultdict(list)
    for r in out:
        by_conc[r["concurrency"]].append(r)
    compact = []
    for conc in sorted(by_conc):
        rs = by_conc[conc]
        compact.append({
            "concurrency": conc,
            "overspend_accepted_rate": round(mean([r["overspend_accepted_rate"] for r in rs]), 4),
            "blocked_rate": round(mean([r["blocked_rate"] for r in rs]), 4),
            "attack_success_rate": round(mean([r["attack_success_rate"] for r in rs]), 4),
            "final_budget_consistent_rate": round(mean([r["final_budget_consistent_rate"] for r in rs]), 4),
        })
    write(SUM / "budget_double_spend_by_concurrency.csv", compact, list(compact[0].keys()))


# ---------------------------------------------------------------------------
# Proof binding: pass-through (already one row per attack), normalised.
# ---------------------------------------------------------------------------
def summarize_proof_binding() -> None:
    rows = read(RAW / "proof_binding_attacks.csv")
    out = []
    for r in rows:
        reason = r.get("adapter_revert_reason", "")
        # extract the custom-error name for a tidy table column.
        short = ""
        if "custom error '" in reason:
            short = reason.split("custom error '", 1)[1].split("(", 1)[0]
        elif reason:
            short = reason[:32]
        out.append({
            "attack_case": r["attack_case"],
            "accepted_by_mock": int(r["accepted_by_mock"]),
            "accepted_by_raw_verifier": int(r["accepted_by_raw_verifier"]),
            "accepted_by_adapter": int(r["accepted_by_adapter"]),
            "adapter_outcome": "accept" if r["accepted_by_adapter"] == "1" else "reject",
            "adapter_revert": short,
        })
    write(SUM / "proof_binding_attacks_summary.csv", out, list(out[0].keys()))


def main() -> None:
    summarize_e2e()
    summarize_budget_composition()
    summarize_double_spend()
    summarize_proof_binding()
    for p in ["e2e_ablation_summary.csv", "budget_composition_summary.csv",
              "budget_double_spend_summary.csv", "budget_double_spend_by_concurrency.csv",
              "proof_binding_attacks_summary.csv"]:
        print(SUM / p)


if __name__ == "__main__":
    main()
