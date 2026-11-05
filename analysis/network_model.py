"""Multi-party request-network model (TNSE revision, R3.1).

Model-based analysis of TrustCircuit as a network of consumers, TEE workers,
provers, a validator quorum, and the ledger, parameterized with the measured
values of the revision benchmarks. Three results:

1. Pipeline capacity  X <= min{ w x_w, p / T_prove, floor(G / g_settle) / tau_blk }.
2. Budget contention  among consumers that share one asset's non-replenishable
   privacy budget, simulated with the contract's exact charging rule
   (BudgetLedger.reserveRdp / consumeRdp, kappa = 1e6). Abandoned reservations
   are released at the deadline t_dead (releaseExpiredReservation). Little's
   law predicts the budget they lock: L_ab = lambda p_ab t_dead E[b_req].
3. Validator quorum   liveness Pr[Bin(n, a) >= k] and compromise Pr[Bin(n, c) >= k].

Run (from the repository root):
    .venv/Scripts/python.exe analysis/network_model.py
Outputs: results/summary/revision/network_model.json,
         results/raw/revision/network_contention.csv, network_locked.csv,
         results/figures/revision/fig_network_dynamics.pdf
"""

from __future__ import annotations

import csv
import heapq
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary" / "revision"
RAW = ROOT / "results" / "raw" / "revision"
FIGURES = ROOT / "results" / "figures" / "revision"

KAPPA = 1_000_000
DELTA = 1e-5
ORDERS = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64]
CAL_MIX = [0.05, 0.10, 0.20, 0.50]
EPS_TOTAL = 4.0
LAMBDA = 2.0
DEADLINES = [10, 30, 100, 300]
ABANDON = [0.05, 0.20, 0.50]
SEEDS_A = 30
SEEDS_B = 10


# ---------------------------------------------------------------------------
# Measured parameters
# ---------------------------------------------------------------------------
def measured_parameters() -> dict:
    vcp = json.loads((SUMMARY / "vcp_v3_summary.json").read_text())
    gas = json.loads((SUMMARY / "gas_benchmarks.json").read_text())
    base_path = SUMMARY / "base_sepolia_v3_summary.json"
    if base_path.exists():
        base = json.loads(base_path.read_text())
        inclusion_s = base["inclusion_latency_s"]["p50"]
        settle_gas = base["settle_gas"]["p50"]
        inclusion_source = "Base Sepolia v3 campaign"
    else:
        legacy = json.loads((ROOT / "results" / "summary" / "base_sepolia_vcp_v2_summary.json").read_text())
        inclusion_s = legacy["settlement_inclusion_ms"]["p50"] / 1000.0
        settle_gas = gas["ablation"]["trustcircuit"]["settle_gas"]["p50"]
        inclusion_source = "first-round Base Sepolia campaign (v2); settle gas from Hardhat v3"
    nitro = _nitro_worker_rate()
    t_prove = vcp["full_prove_time_ms"]["mean"] / 1000.0
    t_prove_source = "VCP v3 benchmark (full_prove_time_ms mean)"
    if os.environ.get("TC_TPROVE_S"):
        t_prove = float(os.environ["TC_TPROVE_S"])
        t_prove_source = os.environ.get("TC_TPROVE_SOURCE", "override via TC_TPROVE_S")
    return {
        "T_prove_s": t_prove,
        "T_prove_source": t_prove_source,
        "inclusion_s": inclusion_s,
        "settle_gas": settle_gas,
        "tee_s": 0.06,
        "worker_rate_rps": nitro,
        "block_time_s": 2.0,
        "gas_share": 10_000_000,
        "inclusion_source": inclusion_source,
    }


def _find(obj, key, default):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                return v
            found = _find(v, key, None)
            if found is not None:
                return found
    return default


def _nitro_worker_rate() -> float:
    path = ROOT / "results" / "summary" / "nitro_pool_projection_summary.csv"
    if path.exists():
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row.get("workers") in {"1", "1.0"}:
                    for key in ("throughput_rps", "projected_throughput_rps", "requests_per_s"):
                        if row.get(key):
                            return float(row[key])
    return 15.87


# ---------------------------------------------------------------------------
# Contract-exact RDP charging
# ---------------------------------------------------------------------------
def sigma_fixed(eps_cal: float) -> int:
    return math.ceil(math.sqrt(2 * math.log(1.25 / DELTA)) / eps_cal * 1e6)


def increment(alpha: int, sigma: int, sens: int = 1_000_000) -> int:
    num = KAPPA * alpha * sens * sens
    den = 2 * sigma * sigma
    return (num + den - 1) // den


OFFSETS = [math.ceil(KAPPA * math.log(1 / DELTA) / (a - 1)) for a in ORDERS]
INCREMENTS = {eps: [increment(a, sigma_fixed(eps)) for a in ORDERS] for eps in CAL_MIX}


def conversion(vector: list[int]) -> int:
    if not any(vector):
        return 0
    return min(v + c for v, c in zip(vector, OFFSETS))


def reservation(eps: float, consumed_nonzero: bool) -> int:
    return INCREMENTS[eps][-1] + (0 if consumed_nonzero else min(OFFSETS))


E_BREQ_UNITS = sum(INCREMENTS[e][-1] for e in CAL_MIX) / len(CAL_MIX)


# ---------------------------------------------------------------------------
# Discrete-event simulation of one asset
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    arrivals: int
    rejected: int
    premature: int
    locked_time_avg_units: float


def simulate(seed: int, t_dead: float, p_ab: float, service_s: float, binding: bool, horizon: float) -> RunResult:
    rng = np.random.default_rng(seed)
    total = int(math.floor(KAPPA * EPS_TOTAL)) if binding else 10**18
    used = 0
    reserved = 0
    abandoned_reserved = 0
    consumed = [0] * len(ORDERS)
    events: list[tuple[float, int, str, int, float]] = []  # (time, seq, kind, amount, eps)
    seq = 0
    t = 0.0
    arrivals = rejected = premature = 0
    locked_area = 0.0
    last_t = 0.0
    while True:
        t_next = t + rng.exponential(1.0 / LAMBDA)
        # Process internal events before the next arrival.
        while events and events[0][0] <= t_next:
            et, _, kind, amount, eps = heapq.heappop(events)
            if et > horizon:
                break
            locked_area += abandoned_reserved * (et - last_t)
            last_t = et
            if kind == "settle":
                before = conversion(consumed)
                for i, inc in enumerate(INCREMENTS[eps]):
                    consumed[i] += inc
                charge = conversion(consumed) - before
                reserved -= amount
                used += charge
            else:  # release of an abandoned reservation
                reserved -= amount
                abandoned_reserved -= amount
        t = t_next
        if t > horizon or (binding and used >= 0.95 * total):
            break
        locked_area += abandoned_reserved * (t - last_t)
        last_t = t
        arrivals += 1
        eps = CAL_MIX[rng.integers(len(CAL_MIX))]
        amount = reservation(eps, any(consumed))
        available = total - used - reserved
        if amount > available:
            rejected += 1
            if amount <= available + abandoned_reserved:
                premature += 1
            continue
        reserved += amount
        seq += 1
        if rng.random() < p_ab:
            abandoned_reserved += amount
            heapq.heappush(events, (t + t_dead, seq, "release", amount, eps))
        else:
            heapq.heappush(events, (t + service_s, seq, "settle", amount, eps))
    elapsed = max(last_t, 1e-9)
    return RunResult(arrivals, rejected, premature, locked_area / elapsed)


def mean_ci(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    if len(arr) < 2:
        return float(arr.mean()), 0.0
    return float(arr.mean()), float(1.96 * arr.std(ddof=1) / math.sqrt(len(arr)))


def binom_tail(n: int, k: int, p: float) -> float:
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


# ---------------------------------------------------------------------------
def main() -> None:
    params = measured_parameters()
    service = params["tee_s"] + params["T_prove_s"] + params["inclusion_s"]

    # 1. Pipeline capacity
    prover_rate = 1.0 / params["T_prove_s"]
    ledger_rate = math.floor(params["gas_share"] / params["settle_gas"]) / params["block_time_s"]
    capacity = {
        "worker_rate_rps": params["worker_rate_rps"],
        "prover_rate_pps": prover_rate,
        "ledger_rate_per_10M_gas_sps": ledger_rate,
        "provers_to_match_one_worker": math.ceil(params["worker_rate_rps"] / prover_rate),
        "provers_to_match_64_workers": math.ceil(64 * 14.67 / prover_rate),
        "provers_absorbed_by_10M_gas": ledger_rate / prover_rate,
        "bottleneck": "prover",
    }

    # 2a. Premature rejection under a binding budget
    contention_rows = []
    contention = {}
    for p_ab in ABANDON:
        for t_dead in DEADLINES:
            shares = []
            for seed in range(1, SEEDS_A + 1):
                r = simulate(seed, t_dead, p_ab, service, binding=True, horizon=3600.0)
                shares.append(r.premature / max(r.arrivals, 1))
                contention_rows.append({"p_ab": p_ab, "t_dead_s": t_dead, "seed": seed, "arrivals": r.arrivals,
                                        "rejected": r.rejected, "premature": r.premature})
            m, ci = mean_ci(shares)
            contention[f"pab{p_ab}_t{t_dead}"] = {"p_ab": p_ab, "t_dead_s": t_dead, "premature_share": m, "ci95": ci}
            print(f"[network] p_ab={p_ab:.2f} t_dead={t_dead:>3}s premature {100*m:6.2f}% +/- {100*ci:.2f}")

    # 2b. Budget locked by abandoned reservations (non-binding budget) vs Little's law
    locked_rows = []
    locked = {}
    for p_ab in ABANDON:
        for t_dead in DEADLINES:
            horizon = 10 * t_dead + 200
            values = []
            for seed in range(1, SEEDS_B + 1):
                r = simulate(1000 + seed, t_dead, p_ab, service, binding=False, horizon=horizon)
                values.append(r.locked_time_avg_units / KAPPA)
                locked_rows.append({"p_ab": p_ab, "t_dead_s": t_dead, "seed": seed, "locked_eps": r.locked_time_avg_units / KAPPA})
            m, ci = mean_ci(values)
            predicted = LAMBDA * p_ab * t_dead * E_BREQ_UNITS / KAPPA * (1 - t_dead / (2 * horizon))
            locked[f"pab{p_ab}_t{t_dead}"] = {"p_ab": p_ab, "t_dead_s": t_dead, "simulated_eps": m, "ci95": ci,
                                               "littles_law_eps": predicted}

    # Admissible abandonment rate for L_ab <= 10% of eps_tot at t_dead = 60 s
    admissible = 0.10 * EPS_TOTAL / (60 * E_BREQ_UNITS / KAPPA)

    # 3. Validator quorum
    quorum = {}
    for n, k in [(1, 1), (3, 2), (5, 3)]:
        quorum[f"{k}-of-{n}"] = {"liveness": binom_tail(n, k, 0.99), "compromise": binom_tail(n, k, 0.05)}

    result = {
        "schema": "TrustCircuit.Revision.NetworkModel.v1",
        "parameters": {**params, "pipeline_latency_s": service, "lambda_rps": LAMBDA, "eps_total": EPS_TOTAL,
                       "delta": DELTA, "orders": ORDERS, "calibration_mix": CAL_MIX,
                       "E_b_req_eps": E_BREQ_UNITS / KAPPA, "seeds_contention": SEEDS_A, "seeds_locked": SEEDS_B},
        "pipeline_capacity": capacity,
        "budget_contention": contention,
        "abandoned_lock": locked,
        "admissible_abandon_rate_at_60s": admissible,
        "validator_quorum": quorum,
    }
    SUMMARY.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    (SUMMARY / "network_model.json").write_text(json.dumps(result, indent=2) + "\n")
    for name, rows in [("network_contention.csv", contention_rows), ("network_locked.csv", locked_rows)]:
        with (RAW / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    plot(result)
    print(json.dumps({"pipeline_latency_s": service, **capacity, "E_b_req_eps": E_BREQ_UNITS / KAPPA,
                      "admissible_abandon_rate_at_60s": admissible}, indent=2))


def plot(result: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif", "font.size": 7.5, "axes.labelsize": 7.5, "legend.fontsize": 6.5,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "axes.linewidth": 0.6, "pdf.fonttype": 42,
    })
    colors = {0.05: "#1f5fa8", 0.20: "#d9822b", 0.50: "#2a9d8f"}
    markers = {0.05: "o", 0.20: "s", 0.50: "^"}
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(3.45, 1.65), constrained_layout=True)
    for p_ab in ABANDON:
        pts = [result["budget_contention"][f"pab{p_ab}_t{t}"] for t in DEADLINES]
        ax_a.errorbar(DEADLINES, [100 * p["premature_share"] for p in pts], yerr=[100 * p["ci95"] for p in pts],
                      color=colors[p_ab], marker=markers[p_ab], ms=2.8, lw=0.9, capsize=1.5, elinewidth=0.6,
                      label=f"$p_{{ab}}={p_ab:.2f}$")
        pts_b = [result["abandoned_lock"][f"pab{p_ab}_t{t}"] for t in DEADLINES]
        ax_b.errorbar(DEADLINES, [p["simulated_eps"] for p in pts_b], yerr=[p["ci95"] for p in pts_b],
                      color=colors[p_ab], marker=markers[p_ab], ms=2.8, lw=0, elinewidth=0.6, capsize=1.5)
        ax_b.plot(DEADLINES, [p["littles_law_eps"] for p in pts_b], color=colors[p_ab], lw=0.8, ls="--")
    for ax in (ax_a, ax_b):
        ax.set_xscale("log")
        ax.set_xticks(DEADLINES)
        ax.set_xticklabels([str(t) for t in DEADLINES])
        ax.set_xlabel("Deadline $t_{dead}$ (s)")
        ax.grid(True, which="major", lw=0.3, alpha=0.5)
        ax.spines[["top", "right"]].set_visible(False)
    ax_a.set_ylabel("Premature rejections (%)")
    ax_a.set_title("(a)", fontsize=7.5)
    ax_b.set_yscale("log")
    ax_b.set_ylabel(r"Locked budget ($\varepsilon$)")
    ax_b.set_title("(b)", fontsize=7.5)
    ax_a.legend(frameon=False, loc="upper left", handlelength=1.2)
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "fig_network_dynamics.pdf")
    fig.savefig(FIGURES / "fig_network_dynamics.png", dpi=220)


if __name__ == "__main__":
    main()
