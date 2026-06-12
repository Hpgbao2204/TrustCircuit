"""Paper-grade figures for the Q1 experiment suite.

Design constraints (per supervisor guidance):
  * NO plain line charts and NO "two parallel/diagonal straight lines" plots.
  * Every figure must carry real structure: grouped/stacked bars, heatmaps,
    or sized scatter.
  * 12x6 inch vector PDF, >=14 pt fonts (shared paper style).

All numbers come from results/q1/summary (measured) and results/q1/raw.

Outputs under results/q1/figures/{e2e,budget,tee,dp,sota,binding}/
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm

SUM = Path("results/q1/summary")
FIG = Path("results/q1/figures")
FIG_SIZE = (12.0, 6.0)
FONT = 16
PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf", "#8c564b", "#e377c2"]


def style() -> None:
    plt.rcParams.update({
        "figure.figsize": FIG_SIZE, "font.size": FONT, "axes.titlesize": FONT + 1,
        "axes.labelsize": FONT, "xtick.labelsize": FONT - 2, "ytick.labelsize": FONT - 2,
        "legend.fontsize": FONT - 3, "axes.axisbelow": True, "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(fig, sub: str, name: str) -> Path:
    out_dir = FIG / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.pdf"
    fig.set_size_inches(*FIG_SIZE, forward=True)
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return out


# ===========================================================================
# E2E ablation
# ===========================================================================
E2E_ORDER = ["OffChain", "ACL-Only", "NoBudget", "NoZK", "TC-Full-MockZK",
             "TC-Full-ZK-VerifyOnly", "TC-Full-ZK-ProveAndVerify"]
E2E_SHORT = {"OffChain": "OffChain", "ACL-Only": "ACL", "NoBudget": "NoBudget",
             "NoZK": "NoZK", "TC-Full-MockZK": "MockZK",
             "TC-Full-ZK-VerifyOnly": "ZK-Verify", "TC-Full-ZK-ProveAndVerify": "ZK-Prove+Verify"}


def fig_e2e() -> list[Path]:
    rows = {r["variant"]: r for r in read(SUM / "e2e_ablation_summary.csv")}
    variants = [v for v in E2E_ORDER if v in rows]
    labels = [E2E_SHORT[v] for v in variants]
    paths = []

    # (1) latency: bars (mean) with p95/p99 markers overlaid -> structured.
    mean_l = np.array([float(rows[v]["mean_latency_ms"]) for v in variants])
    p95 = np.array([float(rows[v]["p95_latency_ms"]) for v in variants])
    p99 = np.array([float(rows[v]["p99_latency_ms"]) for v in variants])
    style()
    fig, ax = plt.subplots()
    x = np.arange(len(variants))
    bars = ax.bar(x, mean_l, color=cm.viridis(np.linspace(0.15, 0.9, len(variants))), zorder=3)
    ax.scatter(x, p95, marker="D", color="#d62728", s=70, zorder=4, label="p95")
    ax.scatter(x, p99, marker="v", color="black", s=70, zorder=4, label="p99")
    ax.set_yscale("log")
    ax.set_ylabel("end-to-end latency (ms, log)")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=22, ha="right")
    for i, v in enumerate(mean_l):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=12)
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    paths.append(save(fig, "e2e", "q1_e2e_latency"))

    # (2) gas: stacked bars settlement vs proof gas.
    total = np.array([float(rows[v]["total_gas"]) for v in variants]) / 1000.0
    proof = np.array([float(rows[v]["proof_gas"]) for v in variants]) / 1000.0
    settle = np.clip(total - proof, 0, None)
    style()
    fig, ax = plt.subplots()
    ax.bar(x, settle, color="#4477aa", zorder=3, label="settlement gas")
    ax.bar(x, proof, bottom=settle, color="#ee6677", zorder=3, label="on-chain proof verify")
    ax.set_ylabel("gas per request (k)")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=22, ha="right")
    for i, v in enumerate(total):
        ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=12)
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    paths.append(save(fig, "e2e", "q1_e2e_gas"))

    # (3) throughput vs latency scatter (sized by gas) -> non-linear spread.
    thr = np.array([float(rows[v]["throughput_req_s"]) for v in variants])
    style()
    fig, ax = plt.subplots()
    sizes = 120 + (total / total.max()) * 700
    sc = ax.scatter(mean_l, thr, s=sizes, c=range(len(variants)), cmap="plasma", edgecolor="k", zorder=3)
    for lab, xx, yy in zip(labels, mean_l, thr):
        ax.annotate(lab, (xx, yy), fontsize=12, xytext=(6, 4), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlabel("mean latency (ms, log)"); ax.set_ylabel("throughput (req/s)")
    ax.grid(True, which="both", alpha=0.3)
    paths.append(save(fig, "e2e", "q1_e2e_throughput_frontier"))
    return paths


# ===========================================================================
# Budget composition + double-spend
# ===========================================================================
def fig_budget() -> list[Path]:
    comp = read(SUM / "budget_composition_summary.csv")
    regimes = sorted({r["regime"] for r in comp})
    eps = sorted({float(r["epsilon"]) for r in comp})
    paths = []

    # (1) heatmap regime x epsilon -> accepted requests (utility surface).
    acc = {}
    for r in comp:
        acc[(r["regime"], float(r["epsilon"]))] = int(r["accepted_requests"])
    mat = np.array([[acc[(rg, e)] for e in eps] for rg in regimes])
    style()
    fig, ax = plt.subplots()
    im = ax.imshow(mat, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(eps))); ax.set_xticklabels([str(e) for e in eps])
    ax.set_yticks(range(len(regimes))); ax.set_yticklabels([r.replace("TrustCircuit", "TC-") for r in regimes])
    ax.set_xlabel(r"$\varepsilon$ per request")
    for yy in range(mat.shape[0]):
        for xx in range(mat.shape[1]):
            ax.text(xx, yy, str(mat[yy, xx]), ha="center", va="center",
                    color="white" if mat[yy, xx] > mat.max() * 0.6 else "black", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("accepted requests")
    paths.append(save(fig, "budget", "q1_budget_accept_heatmap"))

    # (2) overspend / invariant violations per regime (averaged over epsilon).
    over = {rg: np.mean([float(r["overspend_amount"]) for r in comp if r["regime"] == rg]) for rg in regimes}
    viol = {rg: np.mean([int(r["budget_invariant_violations"]) for r in comp if r["regime"] == rg]) for rg in regimes}
    style()
    fig, ax = plt.subplots()
    x = np.arange(len(regimes)); w = 0.38
    short = [r.replace("TrustCircuit", "TC-") for r in regimes]
    b1 = ax.bar(x - w / 2, [over[r] for r in regimes], w, color="#d62728", label="mean overspend ($\\varepsilon$)")
    ax.set_ylabel("mean overspend ($\\varepsilon$)", color="#d62728")
    ax.tick_params(axis="y", labelcolor="#d62728")
    ax2 = ax.twinx()
    ax2.bar(x + w / 2, [viol[r] for r in regimes], w, color="#4477aa", label="invariant violations")
    ax2.set_ylabel("mean invariant violations", color="#4477aa")
    ax2.tick_params(axis="y", labelcolor="#4477aa")
    ax.set_xticks(x); ax.set_xticklabels(short, rotation=20, ha="right")
    ax.set_title("Only the unaccounted regime overspends; all ledger regimes conserve")
    paths.append(save(fig, "budget", "q1_budget_violations"))

    # (3) double-spend: grouped bars blocked vs attack-success vs consistency.
    ds = read(SUM / "budget_double_spend_by_concurrency.csv")
    conc = [int(r["concurrency"]) for r in ds]
    blocked = [float(r["blocked_rate"]) for r in ds]
    attack = [float(r["attack_success_rate"]) for r in ds]
    consistent = [float(r["final_budget_consistent_rate"]) for r in ds]
    style()
    fig, ax = plt.subplots()
    x = np.arange(len(conc)); w = 0.27
    ax.bar(x - w, blocked, w, color="#4477aa", label="blocked rate")
    ax.bar(x, attack, w, color="#d62728", label="attack success rate")
    ax.bar(x + w, consistent, w, color="#228833", label="budget consistent rate")
    ax.set_xticks(x); ax.set_xticklabels([str(c) for c in conc])
    ax.set_xlabel("concurrent double-spend attempts"); ax.set_ylabel("rate")
    ax.set_ylim(0, 1.15)
    for i in range(len(conc)):
        ax.text(i - w, blocked[i] + 0.02, f"{blocked[i]:.2f}", ha="center", fontsize=11)
    ax.legend(ncol=3, loc="upper center")
    paths.append(save(fig, "budget", "q1_overspend_vs_concurrency"))
    return paths


# ===========================================================================
# TEE redundancy
# ===========================================================================
def fig_tee() -> list[Path]:
    rows = read(SUM / "tee_redundancy_attacks_summary.csv")
    configs = ["single_worker", "3_worker_majority", "5_worker_majority", "7_worker_majority"]
    fracs = sorted({float(r["malicious_fraction"]) for r in rows})
    paths = []

    succ = {(r["config"], float(r["malicious_fraction"])): float(r["mean_attack_success_rate"]) for r in rows}
    det = {(r["config"], float(r["malicious_fraction"])): float(r["mean_detection_rate"]) for r in rows}

    # (1) heatmap config x malicious fraction -> attack success rate.
    mat = np.array([[succ[(c, f)] for f in fracs] for c in configs])
    style()
    fig, ax = plt.subplots()
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=1)
    ax.set_xticks(range(len(fracs))); ax.set_xticklabels([f"{f:.2f}" for f in fracs])
    ax.set_yticks(range(len(configs))); ax.set_yticklabels([c.replace("_", " ") for c in configs])
    ax.set_xlabel("malicious worker fraction")
    for yy in range(mat.shape[0]):
        for xx in range(mat.shape[1]):
            ax.text(xx, yy, f"{mat[yy, xx]:.2f}", ha="center", va="center", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("attack success rate")
    paths.append(save(fig, "tee", "q1_tee_attack_success_heatmap"))

    # (2) grouped bars: detection rate per config across a few fractions.
    sel = [f for f in fracs if f in (0.1, 0.25, 0.33, 0.5)]
    style()
    fig, ax = plt.subplots()
    x = np.arange(len(configs)); w = 0.2
    for i, f in enumerate(sel):
        ax.bar(x + (i - len(sel) / 2) * w + w / 2, [det[(c, f)] for c in configs], w,
               color=PALETTE[i], label=f"malicious={f:.2f}")
    ax.set_xticks(x); ax.set_xticklabels([c.replace("_worker_majority", "w").replace("single_worker", "1w") for c in configs])
    ax.set_ylabel("mean detection rate"); ax.set_ylim(0, 1.1)
    ax.legend(ncol=2)
    paths.append(save(fig, "tee", "q1_tee_detection_bars"))
    return paths


# ===========================================================================
# DP: public vs synthetic (grouped bars, NOT a line chart)
# ===========================================================================
def fig_dp() -> list[Path]:
    pub = read(SUM / "public_dp_utility_summary.csv")
    syn_path = Path("results/summary/dp_utility_summary.csv")
    eps = sorted({float(r["epsilon"]) for r in pub})
    pub_by = {}
    for r in pub:
        pub_by.setdefault(float(r["epsilon"]), []).append(float(r["relative_error_percent_mean"]))
    pub_mean = [float(np.mean(pub_by[e])) for e in eps]

    syn_mean = None
    if syn_path.exists():
        syn = read(syn_path)
        syn_by = {}
        for r in syn:
            syn_by.setdefault(float(r["epsilon"]), []).append(float(r["relative_error_percent_mean"]))
        syn_mean = [float(np.mean(syn_by[e])) for e in eps if e in syn_by]

    style()
    fig, ax = plt.subplots()
    x = np.arange(len(eps)); w = 0.38
    ax.bar(x - w / 2, pub_mean, w, color="#d62728", label="public (UCI Adult)")
    if syn_mean and len(syn_mean) == len(eps):
        ax.bar(x + w / 2, syn_mean, w, color="#1f77b4", label="synthetic (NHANES-calibrated)")
    ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels([str(e) for e in eps])
    ax.set_xlabel(r"privacy budget $\varepsilon$"); ax.set_ylabel("mean relative error (%, log)")
    ax.set_title("DP utility holds on real public data")
    ax.legend(); ax.grid(axis="y", which="both", alpha=0.3)
    return [save(fig, "dp", "q1_public_vs_synthetic")]


# ===========================================================================
# Modern SOTA capability heatmap (replaces the legacy comparison table figure)
# ===========================================================================
CAP_SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0, "n/r": 0.0}
CAP_LABEL = {"verifiable_dp": "Verif. DP", "zk_compliance": "ZK compliance",
             "blockchain_settlement": "Blockchain", "budget_accounting": "Budget acct.",
             "proof_binding": "Proof binding", "replay_nullifier": "Replay guard",
             "audit_support": "Audit", "confidential_compute": "Conf. compute"}


def fig_sota() -> list[Path]:
    rows = read(SUM / "modern_sota_capability.csv")
    dims = list(CAP_LABEL.keys())
    systems = [r["system"] for r in rows]
    mat = np.array([[CAP_SCORE[r[d]] for d in dims] for r in rows])
    style()
    fig, ax = plt.subplots()
    im = ax.imshow(mat, aspect="auto", cmap="YlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(dims))); ax.set_xticklabels([CAP_LABEL[d] for d in dims], rotation=35, ha="right")
    ax.set_yticks(range(len(systems)))
    ax.set_yticklabels([f"{s} ({r['year']})" for s, r in zip(systems, rows)])
    sym = {1.0: "\u2713", 0.5: "~", 0.0: "\u2014"}
    for yy in range(mat.shape[0]):
        for xx in range(mat.shape[1]):
            ax.text(xx, yy, sym[mat[yy, xx]], ha="center", va="center", fontsize=13,
                    color="black")
    ax.set_title("Capability coverage vs modern (2022--2026) SOTA")
    paths = [save(fig, "sota", "q1_modern_sota_capability")]
    return paths


# ===========================================================================
# Proof-binding outcome heatmap
# ===========================================================================
def fig_binding() -> list[Path]:
    rows = read(SUM / "proof_binding_attacks_summary.csv")
    cases = [r["attack_case"] for r in rows]
    verifiers = ["accepted_by_mock", "accepted_by_raw_verifier", "accepted_by_adapter"]
    vlabel = ["Mock", "Raw Groth16", "TrustCircuit adapter"]
    mat = np.array([[int(r[v]) for v in verifiers] for r in rows])
    style()
    fig, ax = plt.subplots()
    # green = correct outcome, red = insecure accept. Honest row: accept=good.
    color = np.zeros_like(mat, dtype=float)
    for i, case in enumerate(cases):
        for j in range(len(verifiers)):
            if case == "honest_valid":
                color[i, j] = 1.0 if mat[i, j] == 1 else 0.0
            else:
                color[i, j] = 1.0 if mat[i, j] == 0 else 0.0
    im = ax.imshow(color, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(verifiers))); ax.set_xticklabels(vlabel)
    ax.set_yticks(range(len(cases))); ax.set_yticklabels([c.replace("_", " ") for c in cases])
    for i in range(len(cases)):
        for j in range(len(verifiers)):
            ax.text(j, i, "accept" if mat[i, j] == 1 else "reject", ha="center", va="center", fontsize=12)
    ax.set_title("Proof-binding: a valid proof is not sufficient")
    return [save(fig, "binding", "q1_proof_binding_outcomes")]


def main() -> None:
    out = []
    out += fig_e2e()
    out += fig_budget()
    out += fig_tee()
    out += fig_dp()
    out += fig_sota()
    out += fig_binding()
    for p in out:
        print(p)


if __name__ == "__main__":
    main()
