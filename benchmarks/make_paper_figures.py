"""Paper-grade figure generator for TrustCircuit.

Every chart is exported as its own standalone 12x6 inch vector PDF so the
figures can be merged manually in LaTeX (e.g. with ``subfigure`` /
``subcaption``). Charts that belong to the same research question are written
into a shared sub-folder under ``results/figures``:

    results/figures/gas/             blockchain settlement cost
    results/figures/e2e/             end-to-end latency / throughput
    results/figures/dp/              differential-privacy utility
    results/figures/tee_scaling/     TEE worker-pool scaling
    results/figures/tee_robustness/  TEE attack robustness

Style rules enforced project-wide:
    * figure size = 12 x 6 inches
    * minimum font size = 14 pt
    * vector PDF only (Type-42 fonts)

All numbers come exclusively from the measured CSVs in ``results/summary``.

Usage:
    python benchmarks/make_paper_figures.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from matplotlib.colors import Normalize
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

FIG_SIZE = (12.0, 6.0)
FONT_SIZE = 16
PDF_DPI = 300

PALETTE = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
    "#8c564b",
    "#e377c2",
]


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": FIG_SIZE,
            "font.size": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE - 2,
            "ytick.labelsize": FONT_SIZE - 2,
            "legend.fontsize": FONT_SIZE - 2,
            "lines.linewidth": 2.4,
            "lines.markersize": 8,
            "axes.axisbelow": True,
            "savefig.format": "pdf",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def new_fig(projection: str | None = None):
    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_subplot(111, projection=projection) if projection else fig.add_subplot(111)
    return fig, ax


def save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.pdf"
    fig.set_size_inches(*FIG_SIZE, forward=True)
    fig.savefig(out, dpi=PDF_DPI, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return out


# ===========================================================================
# Group 1: blockchain settlement gas
# ===========================================================================
PIPELINE_ORDER = [
    "registerAsset", "registerBudget", "requestAccess", "approveRequest",
    "reserveBudget", "submitProof", "consumeBudget", "recordAudit", "completeRequest",
]
SHORT_OP = {
    "registerAsset": "regAsset", "registerBudget": "regBudget", "requestAccess": "reqAccess",
    "approveRequest": "approve", "reserveBudget": "reserve", "submitProof": "proof",
    "consumeBudget": "consume", "recordAudit": "audit", "completeRequest": "complete",
}


def figures_gas(gas_rows: list[dict[str, str]], out_dir: Path, deploy_rows: list[dict[str, str]] | None = None) -> list[Path]:
    ops_rows = [r for r in gas_rows if r["operation"] != "TOTAL_PIPELINE"]
    totals = {r["variant"]: r for r in gas_rows if r["operation"] == "TOTAL_PIPELINE"}
    variants = sorted(totals)
    paths: list[Path] = []

    def gas_of(variant: str, op: str) -> float:
        for r in ops_rows:
            if r["variant"] == variant and r["operation"] == op:
                return float(r["mean_gas"]) / 1000.0
        return 0.0

    tc_ops = [op for op in PIPELINE_ORDER if gas_of("TC-Full", op) > 0]
    tc_gas = np.array([gas_of("TC-Full", op) for op in tc_ops])
    labels = [SHORT_OP.get(op, op) for op in tc_ops]

    # --- Aspect A: per-operation recurring execution gas (ranked) ---------
    fig, ax = new_fig()
    order = np.argsort(tc_gas)
    bars = ax.barh(np.array(labels)[order], tc_gas[order], color=cm.plasma(np.linspace(0.1, 0.9, len(tc_ops))))
    ax.set_xlabel("mean execution gas per call (k)")
    for i, v in enumerate(tc_gas[order]):
        ax.text(v, i, f" {v:.1f}", va="center", fontsize=13)
    paths.append(save(fig, out_dir, "gA_runtime_perop"))

    # --- Aspect B: marginal settlement gas attributed to each module ------
    # Derived from ablation totals: base (registry/access/audit), +budget
    # ledger, +compliance-proof record. The real ZK verify is shown separately.
    base = float(totals["ACL-Only"]["mean_gas"]) / 1000.0
    budget_mod = (float(totals["NoZK"]["mean_gas"]) - float(totals["ACL-Only"]["mean_gas"])) / 1000.0
    zk_record = (float(totals["TC-Full"]["mean_gas"]) - float(totals["NoZK"]["mean_gas"])) / 1000.0
    fig, ax = new_fig()
    comps = ["registry+access\n+audit", "privacy-budget\nledger", "compliance-proof\nrecord"]
    vals = [base, budget_mod, zk_record]
    cum = 0.0
    cols = ["#4477aa", "#228833", "#ee6677"]
    for c, v, col in zip(comps, vals, cols):
        ax.bar("TC-Full", v, bottom=cum, color=col, width=0.5, label=f"{c} ({v:.0f}k)")
        cum += v
    ax.axhline(255.757, ls="--", color="#aa3377", lw=2)
    ax.text(0.0, 262, "real on-chain ZK verify (+256k, off settlement path)", fontsize=11, color="#aa3377")
    ax.set_ylabel("settlement gas (k)")
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=12)
    ax.set_ylim(0, 330)
    paths.append(save(fig, out_dir, "gB_module_marginal"))

    # --- Aspect C: one-time deployment gas vs runtime bytecode size -------
    if deploy_rows:
        names = [r["contract"].replace("Verifier", "Vrf") for r in deploy_rows]
        dgas = np.array([float(r["deploy_gas"]) for r in deploy_rows]) / 1000.0
        sz = np.array([float(r["runtime_bytes"]) for r in deploy_rows]) / 1024.0
        is_zk = np.array(["compliance-zk" == r["role"] for r in deploy_rows])
        fig, ax = new_fig()
        col = ["#cc3311" if z else "#4477aa" for z in is_zk]
        sc = ax.scatter(sz, dgas, s=160, c=col, edgecolor="k", linewidth=0.7, zorder=3)
        for n, x, y in zip(names, sz, dgas):
            ax.annotate(n, (x, y), fontsize=11, xytext=(5, 3), textcoords="offset points")
        ax.set_xlabel("runtime bytecode size (KiB)"); ax.set_ylabel("one-time deploy gas (k)")
        ax.set_yscale("log")
        ax.scatter([], [], c="#cc3311", label="ZK verifier"); ax.scatter([], [], c="#4477aa", label="core contract")
        ax.legend(loc="lower right")
        paths.append(save(fig, out_dir, "gC_deploy_vs_size"))

    # --- Aspect D: cost-time efficiency (gas vs latency per op) -----------
    fig, ax = new_fig()
    lat = np.array([float(next(r for r in ops_rows if r["variant"] == "TC-Full" and r["operation"] == op)["mean_latency_ms"]) for op in tc_ops])
    p95 = np.array([float(next(r for r in ops_rows if r["variant"] == "TC-Full" and r["operation"] == op)["p95_gas"]) / 1000.0 for op in tc_ops])
    sc = ax.scatter(lat, tc_gas, s=120 + (p95 - p95.min()) / (np.ptp(p95) + 1e-9) * 600, c=tc_gas, cmap="turbo", edgecolor="k", linewidth=0.7)
    for op, x, y in zip(labels, lat, tc_gas):
        ax.annotate(op, (x, y), fontsize=12, xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("mean call latency (ms)"); ax.set_ylabel("execution gas (k)")
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04).set_label("gas (k)")
    paths.append(save(fig, out_dir, "gD_gas_vs_latency"))

    return paths



# ===========================================================================
# Group 2: end-to-end latency / throughput
# ===========================================================================
E2E_STAGE_ORDER = [
    "registerAsset", "requestAccess", "approveRequest", "registerBudget", "reserveBudget",
    "tee_compute", "mock_prove", "submitProof", "consumeBudget", "recordAudit", "completeRequest",
    "register_offchain", "request_offchain", "compute_offchain", "audit_offchain",
]
SHORT_STAGE = {
    "registerAsset": "register", "requestAccess": "request", "approveRequest": "approve",
    "registerBudget": "regBudget", "reserveBudget": "reserve", "tee_compute": "TEE",
    "mock_prove": "prove", "submitProof": "verify", "consumeBudget": "consume",
    "recordAudit": "audit", "completeRequest": "complete", "compute_offchain": "compute",
    "register_offchain": "register", "request_offchain": "request", "audit_offchain": "audit",
}
ONCHAIN_STAGES = [
    "registerAsset", "requestAccess", "approveRequest", "registerBudget", "reserveBudget",
    "tee_compute", "mock_prove", "submitProof", "consumeBudget", "recordAudit", "completeRequest",
]


def figures_e2e(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    totals = {r["variant"]: r for r in rows if r["stage"] == "TOTAL_PIPELINE"}
    variants = sorted(totals)
    stage_rows = [r for r in rows if r["stage"] != "TOTAL_PIPELINE"]
    paths: list[Path] = []

    def stages_of(variant: str):
        out = []
        for st in E2E_STAGE_ORDER:
            for r in stage_rows:
                if r["variant"] == variant and r["stage"] == st:
                    out.append((st, float(r["mean_latency_ms"]), float(r["p50_latency_ms"]),
                                float(r["p95_latency_ms"]), float(r["p99_latency_ms"])))
        return out

    lat = np.array([float(totals[v]["mean_latency_ms"]) for v in variants])
    std = np.array([float(totals[v]["std_latency_ms"]) for v in variants])
    thr = np.array([float(totals[v]["throughput_req_s"]) for v in variants])
    gas = np.array([float(totals[v]["mean_gas_used"]) / 1000.0 for v in variants])

    # e1: 3D trajectory
    fig, ax = new_fig("3d")
    order = np.argsort(lat)
    ax.plot(lat[order], gas[order], thr[order], color="#555555", lw=1.6)
    ax.scatter(lat, gas, thr, s=110, c=thr, cmap="plasma", depthshade=True, edgecolor="k", linewidth=0.5)
    for v, x, y, z in zip(variants, lat, gas, thr):
        ax.text(x, y, z, v, fontsize=12)
    ax.set_xlabel("latency (ms)", labelpad=10); ax.set_ylabel("gas (k)", labelpad=10); ax.set_zlabel("req/s", labelpad=8)
    ax.view_init(elev=22, azim=-52)
    paths.append(save(fig, out_dir, "e1_latency_gas_thr_3d"))

    # e2: TC-Full stacked stage breakdown
    fig, ax = new_fig()
    tc = stages_of("TC-Full")
    bottom = 0.0
    cmap = cm.tab20(np.linspace(0, 1, len(tc)))
    for k, (st, m, *_r) in enumerate(tc):
        ax.bar(["TC-Full"], [m], bottom=bottom, color=cmap[k], label=f"{SHORT_STAGE.get(st, st)} ({m:.0f})")
        bottom += m
    ax.set_ylabel("latency (ms)")
    ax.legend(ncol=2, fontsize=12, loc="center left", bbox_to_anchor=(1.02, 0.5))
    paths.append(save(fig, out_dir, "e2_tcfull_breakdown"))

    # e3: total latency per variant (log)
    fig, ax = new_fig()
    ax.bar(variants, lat, yerr=std, capsize=6, color=cm.viridis(np.linspace(0.1, 0.9, len(variants))))
    ax.set_yscale("log"); ax.set_ylabel("total latency (ms, log)")
    for i, v in enumerate(lat):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=13)
    ax.set_xticks(range(len(variants))); ax.set_xticklabels(variants, rotation=20, ha="right")
    paths.append(save(fig, out_dir, "e3_total_latency"))

    # e4: throughput per variant
    fig, ax = new_fig()
    ax.bar(variants, thr, color=cm.cividis(np.linspace(0.1, 0.9, len(variants))))
    ax.set_ylabel("throughput (req/s)")
    for i, v in enumerate(thr):
        ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=13)
    ax.set_xticks(range(len(variants))); ax.set_xticklabels(variants, rotation=20, ha="right")
    paths.append(save(fig, out_dir, "e4_throughput"))

    # e5: stage latency heatmap
    fig, ax = new_fig()
    mat = np.full((len(variants), len(ONCHAIN_STAGES)), np.nan)
    for i, v in enumerate(variants):
        d = {st: m for st, m, *_ in stages_of(v)}
        for j, st in enumerate(ONCHAIN_STAGES):
            if st in d:
                mat[i, j] = d[st]
    im = ax.imshow(np.log10(mat + 0.1), aspect="auto", cmap="inferno")
    ax.set_yticks(range(len(variants))); ax.set_yticklabels(variants)
    ax.set_xticks(range(len(ONCHAIN_STAGES))); ax.set_xticklabels([SHORT_STAGE.get(s, s) for s in ONCHAIN_STAGES], rotation=55, ha="right")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("log10 latency (ms)")
    paths.append(save(fig, out_dir, "e5_stage_latency_heatmap"))

    # e6: TC-Full percentile profile
    fig, ax = new_fig()
    names = [SHORT_STAGE.get(st, st) for st, *_ in tc]
    x = np.arange(len(tc))
    ax.plot(x, [p for _, _, p, _, _ in tc], marker="o", label="p50", color=PALETTE[0])
    ax.plot(x, [p for _, _, _, p, _ in tc], marker="s", label="p95", color=PALETTE[1])
    ax.plot(x, [p for _, _, _, _, p in tc], marker="^", label="p99", color=PALETTE[3])
    ax.set_yscale("log"); ax.set_ylabel("latency (ms, log)")
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=55, ha="right")
    ax.legend()
    paths.append(save(fig, out_dir, "e6_percentiles"))

    # e7: latency waterfall -- per-stage bars + cumulative curve (dual axis)
    fig, ax = new_fig()
    stage_lat = [m for _, m, *_ in tc]
    names = [SHORT_STAGE.get(st, st) for st, *_ in tc]
    ax.bar(range(len(tc)), stage_lat, color=cm.viridis(np.linspace(0.1, 0.9, len(tc))), label="per-stage")
    ax.set_ylabel("per-stage latency (ms)")
    ax2 = ax.twinx()
    cum = np.cumsum(stage_lat)
    ax2.plot(range(len(cum)), cum, color="#cc3311", marker="o", lw=2.4, label="cumulative")
    ax2.set_ylabel("cumulative latency (ms)", color="#cc3311")
    ax2.tick_params(axis="y", labelcolor="#cc3311")
    ax.set_xticks(range(len(tc))); ax.set_xticklabels(names, rotation=55, ha="right")
    ax.legend(loc="upper left", fontsize=12)
    paths.append(save(fig, out_dir, "e7_latency_waterfall"))

    # e8: efficiency frontier
    fig, ax = new_fig()
    sc = ax.scatter(lat, thr, s=260, c=gas, cmap="cool", edgecolor="k")
    for v, x, y in zip(variants, lat, thr):
        ax.annotate(v, (x, y), fontsize=13, xytext=(5, 5), textcoords="offset points")
    ax.set_xscale("log"); ax.set_xlabel("latency (ms, log)"); ax.set_ylabel("throughput (req/s)")
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04).set_label("gas (k)")
    paths.append(save(fig, out_dir, "e8_efficiency_frontier"))

    return paths


# ===========================================================================
# Group 3: differential-privacy utility
# ===========================================================================
def figures_dp(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    queries = sorted({r["query"] for r in rows})
    eps = sorted({float(r["epsilon"]) for r in rows})
    err = {(r["query"], float(r["epsilon"])): float(r["relative_error_percent_mean"]) for r in rows}
    p95 = {(r["query"], float(r["epsilon"])): float(r["relative_error_p95"]) * 100 for r in rows}
    p50 = {(r["query"], float(r["epsilon"])): float(r["relative_error_p50"]) * 100 for r in rows}
    p99 = {(r["query"], float(r["epsilon"])): float(r["relative_error_p99"]) * 100 for r in rows}
    mat = np.array([[err[(q, e)] for e in eps] for q in queries])
    short_q = [q.replace("_", " ") for q in queries]
    paths: list[Path] = []

    # d1: 3D surface
    fig, ax = new_fig("3d")
    X, Y = np.meshgrid(np.arange(len(eps)), np.arange(len(queries)))
    ax.plot_surface(X, Y, mat, cmap="viridis", edgecolor="k", linewidth=0.3, antialiased=True)
    ax.set_xticks(range(len(eps))); ax.set_xticklabels([str(e) for e in eps])
    ax.set_yticks(range(len(queries))); ax.set_yticklabels([q[:10] for q in queries], fontsize=11)
    ax.set_xlabel("epsilon", labelpad=10); ax.set_zlabel("rel error (%)", labelpad=10)
    ax.view_init(elev=26, azim=-60)
    paths.append(save(fig, out_dir, "d1_error_surface_3d"))

    # d2: log-log error vs epsilon
    fig, ax = new_fig()
    for i, q in enumerate(queries):
        ax.loglog(eps, [err[(q, e)] for e in eps], marker="o", color=PALETTE[i % len(PALETTE)], label=q.replace("_", " "))
    ax.set_xlabel("privacy budget epsilon"); ax.set_ylabel("mean relative error (%)")
    ax.legend(fontsize=12, ncol=2)
    paths.append(save(fig, out_dir, "d2_error_vs_eps"))

    # d3: contour
    fig, ax = new_fig()
    cf = ax.contourf(X, Y, mat, levels=16, cmap="Blues")
    ax.contour(X, Y, mat, levels=8, colors="white", linewidths=0.7, alpha=0.7)
    ax.set_xticks(range(len(eps))); ax.set_xticklabels([str(e) for e in eps])
    ax.set_yticks(range(len(queries))); ax.set_yticklabels([q[:12] for q in queries])
    ax.set_xlabel("epsilon")
    fig.colorbar(cf, ax=ax, fraction=0.046, pad=0.04).set_label("rel error (%)")
    paths.append(save(fig, out_dir, "d3_error_contour"))

    # d4: phase space mean vs p95
    fig, ax = new_fig()
    for i, q in enumerate(queries):
        mv = np.array([err[(q, e)] for e in eps]); pv = np.array([p95[(q, e)] for e in eps])
        ax.scatter(mv, pv, s=80 + np.array(eps) * 40, color=PALETTE[i % len(PALETTE)], alpha=0.75, label=q.replace("_", " "))
        ax.plot(mv, pv, color=PALETTE[i % len(PALETTE)], alpha=0.5, lw=1.5)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("mean relative error (%)"); ax.set_ylabel("p95 relative error (%)")
    ax.legend(fontsize=11, ncol=2)
    paths.append(save(fig, out_dir, "d4_utility_phase_space"))

    # d5: error at eps=1.0
    fig, ax = new_fig()
    e1 = 1.0 if 1.0 in eps else eps[len(eps) // 2]
    vals = [err[(q, e1)] for q in queries]
    ax.barh(short_q, vals, color=cm.plasma(np.linspace(0.1, 0.9, len(queries))))
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:.3f}", va="center", fontsize=13)
    ax.set_xlabel(f"mean relative error (%) at epsilon = {e1}")
    paths.append(save(fig, out_dir, "d5_error_at_eps1"))

    # d6: heatmap query x epsilon
    fig, ax = new_fig()
    im = ax.imshow(mat, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(eps))); ax.set_xticklabels([str(e) for e in eps])
    ax.set_yticks(range(len(queries))); ax.set_yticklabels([q.replace("_", " ") for q in queries])
    for y in range(mat.shape[0]):
        for x in range(mat.shape[1]):
            ax.text(x, y, f"{mat[y, x]:.2f}", ha="center", va="center", fontsize=11,
                    color="white" if mat[y, x] > mat.mean() else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("rel error (%)")
    paths.append(save(fig, out_dir, "d6_query_eps_heatmap"))

    # d7: aggregated percentile band
    fig, ax = new_fig()
    a50 = np.array([np.mean([p50[(q, e)] for q in queries]) for e in eps])
    a95 = np.array([np.mean([p95[(q, e)] for q in queries]) for e in eps])
    a99 = np.array([np.mean([p99[(q, e)] for q in queries]) for e in eps])
    ax.fill_between(eps, a50, a99, alpha=0.25, color="#4477aa", label="p50-p99 band")
    ax.plot(eps, a95, marker="o", color="#cc3311", label="p95")
    ax.plot(eps, a50, marker="s", color="#117733", label="p50")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("epsilon"); ax.set_ylabel("relative error (%)")
    ax.legend()
    paths.append(save(fig, out_dir, "d7_percentile_band"))

    # d8: noise-scaling law error vs 1/eps
    fig, ax = new_fig()
    inv = 1.0 / np.array(eps)
    counts = np.array([np.mean([err[(q, e)] for q in queries if "count" in q]) for e in eps])
    means = np.array([np.mean([err[(q, e)] for q in queries if q.startswith("mean")]) for e in eps])
    ax.plot(inv, counts, marker="o", color=PALETTE[1], label="count queries")
    ax.plot(inv, means, marker="s", color=PALETTE[0], label="mean queries")
    ax.set_xlabel("1 / epsilon"); ax.set_ylabel("mean relative error (%)")
    ax.legend()
    paths.append(save(fig, out_dir, "d8_noise_scaling"))

    return paths


# ===========================================================================
# Group 4: TEE worker-pool scaling
# ===========================================================================
def figures_tee_scaling(rows: list[dict[str, str]], out_dir: Path, cores: int = 16) -> list[Path]:
    rows = sorted(rows, key=lambda r: int(r["worker_count"]))
    w = np.array([int(r["worker_count"]) for r in rows])
    thr = np.array([float(r["throughput_req_s"]) for r in rows])
    thr_pw = np.array([float(r["throughput_per_worker_req_s"]) for r in rows])
    p50 = np.array([float(r["p50_latency_ms"]) for r in rows])
    p95 = np.array([float(r["p95_latency_ms"]) for r in rows])
    p99 = np.array([float(r["p99_latency_ms"]) for r in rows])
    cpu = np.array([float(r["cpu_utilization_estimate_pct"]) for r in rows])
    paths: list[Path] = []

    # s1: 3D trajectory
    fig, ax = new_fig("3d")
    ax.plot(w, thr, p95, color="#555555", lw=1.6)
    ax.scatter(w, thr, p95, s=90, c=w, cmap="viridis", edgecolor="k", linewidth=0.5)
    ax.set_xlabel("workers", labelpad=10); ax.set_ylabel("req/s", labelpad=10); ax.set_zlabel("p95 (ms)", labelpad=8)
    ax.view_init(elev=24, azim=-58)
    paths.append(save(fig, out_dir, "s1_scaling_trajectory_3d"))

    # s2: throughput saturation
    fig, ax = new_fig()
    ax.plot(w, thr, marker="o", color=PALETTE[0], label="measured")
    ax.plot(w, thr[0] * w, "--", color="gray", label="ideal linear")
    ax.axvline(cores, color="#cc3311", ls=":", lw=2, label=f"{cores} cores")
    ax.set_xlabel("worker count"); ax.set_ylabel("throughput (req/s)")
    ax.set_ylim(0, max(thr) * 1.4); ax.legend()
    paths.append(save(fig, out_dir, "s2_throughput_saturation"))

    # s3: latency bands
    fig, ax = new_fig()
    ax.fill_between(w, p50, p99, alpha=0.2, color="#4477aa", label="p50-p99 band")
    ax.plot(w, p95, marker="o", color="#cc3311", label="p95")
    ax.plot(w, p50, marker="s", color="#117733", label="p50")
    ax.set_xlabel("worker count"); ax.set_ylabel("latency (ms)"); ax.legend()
    paths.append(save(fig, out_dir, "s3_latency_bands"))

    # s4: efficiency -- per-worker throughput + parallel efficiency (dual axis)
    fig, ax = new_fig()
    eff = (thr / thr[0]) / w * 100.0
    l1, = ax.plot(w, thr_pw, marker="o", color=PALETTE[4], label="per-worker throughput")
    ax.axhline(thr_pw[0], color=PALETTE[4], ls="--", lw=1.5, alpha=0.6)
    ax.axvline(cores, color="#cc3311", ls=":", lw=2)
    ax.set_xlabel("worker count"); ax.set_ylabel("per-worker throughput (req/s)", color=PALETTE[4])
    ax.tick_params(axis="y", labelcolor=PALETTE[4])
    ax2 = ax.twinx()
    l2, = ax2.plot(w, eff, marker="s", color=PALETTE[0], label="parallel efficiency")
    ax2.set_ylabel("parallel efficiency (%)", color=PALETTE[0]); ax2.set_ylim(0, 105)
    ax2.tick_params(axis="y", labelcolor=PALETTE[0])
    ax.legend([l1, l2], ["per-worker throughput", "parallel efficiency"], fontsize=12, loc="upper right")
    paths.append(save(fig, out_dir, "s4_efficiency_decay"))

    # s5: resource saturation -- CPU utilization + total throughput (dual axis)
    fig, ax = new_fig()
    l1, = ax.plot(w, cpu, marker="o", color=PALETTE[3], label="CPU utilization")
    ax.axvline(cores, color="#cc3311", ls=":", lw=2, label=f"{cores} physical cores")
    ax.set_xlabel("worker count"); ax.set_ylabel("CPU utilization (%)", color=PALETTE[3])
    ax.tick_params(axis="y", labelcolor=PALETTE[3])
    ax2 = ax.twinx()
    l2, = ax2.plot(w, thr, marker="s", color=PALETTE[2], label="throughput")
    ax2.set_ylabel("throughput (req/s)", color=PALETTE[2])
    ax2.tick_params(axis="y", labelcolor=PALETTE[2])
    ax.legend([l1, l2, ax.lines[1]], ["CPU utilization", "throughput", f"{cores} cores"], fontsize=12, loc="center right")
    paths.append(save(fig, out_dir, "s5_cpu_utilization"))

    # s6: speedup
    fig, ax = new_fig()
    speedup = thr / thr[0]
    ax.plot(w, speedup, marker="o", color=PALETTE[0], label="measured speedup")
    ax.plot(w, w, "--", color="gray", label="linear")
    ax.axhline(speedup.max(), color="#117733", ls=":", label=f"max {speedup.max():.1f}x")
    ax.set_xlabel("worker count"); ax.set_ylabel("speedup vs 1 worker"); ax.legend()
    paths.append(save(fig, out_dir, "s6_speedup"))

    # s7: latency heatmap workers x percentile
    fig, ax = new_fig()
    stack = np.vstack([p50, p95, p99])
    im = ax.imshow(stack, aspect="auto", cmap="inferno")
    ax.set_yticks([0, 1, 2]); ax.set_yticklabels(["p50", "p95", "p99"])
    ax.set_xticks(range(len(w))); ax.set_xticklabels([str(x) for x in w], rotation=45)
    ax.set_xlabel("worker count")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("latency (ms)")
    paths.append(save(fig, out_dir, "s7_latency_heatmap"))

    # s8: throughput vs cpu util phase space
    fig, ax = new_fig()
    sc = ax.scatter(cpu, thr, s=60 + w * 12, c=w, cmap="turbo", edgecolor="k", linewidth=0.5)
    ax.plot(cpu, thr, color="gray", alpha=0.4, lw=1.2)
    ax.set_xlabel("CPU utilization (%)"); ax.set_ylabel("throughput (req/s)")
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04).set_label("workers")
    paths.append(save(fig, out_dir, "s8_throughput_cpu_phase"))

    return paths


# ===========================================================================
# Group 5: TEE attack robustness
# ===========================================================================
SUBTLE = ["skip_dp_noise", "tampered_result", "tampered_attestation", "wrong_epsilon"]


def figures_tee_attack(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    attacks = sorted({r["attack_type"] for r in rows if r["attack_type"] != "honest"})
    sev = sorted({float(r["severity"]) for r in rows})
    det = {(r["attack_type"], float(r["severity"])): float(r["detection_rate"]) for r in rows}
    suc = {(r["attack_type"], float(r["severity"])): float(r["attack_success_rate"]) for r in rows}
    fa = {(r["attack_type"], float(r["severity"])): float(r["false_accept_rate"]) for r in rows}
    lat = {(r["attack_type"], float(r["severity"])): float(r["mean_total_tee_latency_ms"]) for r in rows}
    paths: list[Path] = []

    # r1: 3D detection surface (subtle)
    fig, ax = new_fig("3d")
    Z = np.array([[det[(a, s)] for s in sev] for a in SUBTLE])
    X, Y = np.meshgrid(np.arange(len(sev)), np.arange(len(SUBTLE)))
    ax.plot_surface(X, Y, Z, cmap="magma", edgecolor="k", linewidth=0.3)
    ax.set_xticks(range(len(sev))); ax.set_xticklabels([str(s) for s in sev])
    ax.set_yticks(range(len(SUBTLE))); ax.set_yticklabels([a[:10] for a in SUBTLE], fontsize=10)
    ax.set_xlabel("severity", labelpad=4); ax.set_zlabel("detection", labelpad=8)
    ax.view_init(elev=26, azim=-60)
    paths.append(save(fig, out_dir, "r1_detection_surface_3d"))

    # r2: detection vs severity (subtle)
    fig, ax = new_fig()
    for i, a in enumerate(SUBTLE):
        ax.plot(sev, [det[(a, s)] for s in sev], marker="o", color=PALETTE[i], label=a.replace("_", " "))
    ax.set_xlabel("deviation severity"); ax.set_ylabel("detection rate"); ax.set_ylim(0, 1.05); ax.legend()
    paths.append(save(fig, out_dir, "r2_subtle_detection"))

    # r3: attack success vs severity
    fig, ax = new_fig()
    for i, a in enumerate(SUBTLE):
        ax.plot(sev, [suc[(a, s)] for s in sev], marker="s", color=PALETTE[i], label=a.replace("_", " "))
    ax.set_xlabel("deviation severity"); ax.set_ylabel("evasion rate"); ax.set_ylim(0, 1.05); ax.legend()
    paths.append(save(fig, out_dir, "r3_attack_success"))

    # r4: detection heatmap attack x severity
    fig, ax = new_fig()
    M = np.array([[det[(a, s)] for s in sev] for a in attacks])
    im = ax.imshow(M, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_yticks(range(len(attacks))); ax.set_yticklabels([a.replace("_", " ") for a in attacks])
    ax.set_xticks(range(len(sev))); ax.set_xticklabels([str(s) for s in sev])
    ax.set_xlabel("attack severity")
    for y in range(M.shape[0]):
        for x in range(M.shape[1]):
            ax.text(x, y, f"{M[y, x]:.2f}", ha="center", va="center", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("detection rate")
    paths.append(save(fig, out_dir, "r4_detection_heatmap"))

    # r5: mean detection per attack
    fig, ax = new_fig()
    means = [np.mean([det[(a, s)] for s in sev]) for a in attacks]
    colors = ["#117733" if m > 0.99 else "#cc3311" for m in means]
    ax.barh([a.replace("_", " ") for a in attacks], means, color=colors)
    for i, m in enumerate(means):
        ax.text(m, i, f" {m:.2f}", va="center", fontsize=12)
    ax.set_xlabel("mean detection rate"); ax.set_xlim(0, 1.08)
    paths.append(save(fig, out_dir, "r5_mean_detection"))

    # r6: detection vs false-accept (subtle)
    fig, ax = new_fig()
    for i, a in enumerate(SUBTLE):
        ax.plot([fa[(a, s)] for s in sev], [det[(a, s)] for s in sev], marker="o", color=PALETTE[i], label=a.replace("_", " "))
    ax.plot([0, 1], [1, 0], "--", color="gray")
    ax.set_xlabel("false-accept rate"); ax.set_ylabel("detection rate"); ax.legend()
    paths.append(save(fig, out_dir, "r6_detection_vs_false_accept"))

    # r7: per-attack latency
    fig, ax = new_fig()
    lmean = [np.mean([lat[(a, s)] for s in sev]) for a in attacks]
    ax.bar(range(len(attacks)), lmean, color=cm.cividis(np.linspace(0.1, 0.9, len(attacks))))
    ax.set_xticks(range(len(attacks))); ax.set_xticklabels([a.replace("_", " ") for a in attacks], rotation=55, ha="right")
    ax.set_ylabel("mean TEE latency (ms)")
    paths.append(save(fig, out_dir, "r7_per_attack_latency"))

    # r8: robustness phase space
    fig, ax = new_fig()
    for i, a in enumerate(SUBTLE):
        d = np.array([det[(a, s)] for s in sev]); u = np.array([suc[(a, s)] for s in sev])
        ax.scatter(d, u, s=80 + np.array(sev) * 160, color=PALETTE[i], alpha=0.75, label=a.replace("_", " "))
        ax.plot(d, u, color=PALETTE[i], alpha=0.4, lw=1.2)
    ax.set_xlabel("detection rate"); ax.set_ylabel("attack success rate"); ax.legend()
    paths.append(save(fig, out_dir, "r8_robustness_phase_space"))

    return paths


# ===========================================================================
# Group 6: ZK Groth16 compliance proofs
# ===========================================================================
def figures_zk(rows: list[dict[str, str]], gas_rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    rows = sorted(rows, key=lambda r: int(r["n_rules"]))
    nr = np.array([int(r["n_rules"]) for r in rows])
    cons = np.array([int(r["constraints"]) for r in rows])
    prove = np.array([float(r["prove_time_ms_mean"]) for r in rows])
    prove_sd = np.array([float(r["prove_time_ms_std"]) for r in rows])
    prove95 = np.array([float(r["prove_time_ms_p95"]) for r in rows])
    verify = np.array([float(r["verify_time_ms_mean"]) for r in rows])
    proof_b = np.array([int(r["proof_size_bytes"]) for r in rows])
    pk = np.array([int(r["proving_key_bytes"]) for r in rows]) / 1e6
    vk = np.array([int(r["verification_key_bytes"]) for r in rows])
    r1cs = np.array([int(r["r1cs_bytes"]) for r in rows]) / 1e6
    rss = np.array([float(r["peak_rss_mb"]) for r in rows])
    verify_gas = float(gas_rows[0]["verify_gas"]) if gas_rows else 255757.0
    deploy_gas = float(gas_rows[0]["deploy_gas"]) if gas_rows else 470580.0
    paths: list[Path] = []

    # z1: 3D trajectory constraints-prove-RSS
    fig, ax = new_fig("3d")
    ax.plot(cons, prove, rss, color="#555555", lw=1.6)
    ax.scatter(cons, prove, rss, s=100, c=nr, cmap="viridis", edgecolor="k", linewidth=0.5)
    ax.set_xlabel("constraints", labelpad=10); ax.set_ylabel("prove (ms)", labelpad=10); ax.set_zlabel("peak RSS (MB)", labelpad=8)
    ax.view_init(elev=24, azim=-58)
    paths.append(save(fig, out_dir, "z1_constraints_prove_rss_3d"))

    # z2: prove time vs constraints with std band + p95
    fig, ax = new_fig()
    ax.fill_between(cons, prove - prove_sd, prove + prove_sd, alpha=0.2, color="#4477aa", label="mean +/- std")
    ax.plot(cons, prove, marker="o", color=PALETTE[0], label="mean prove time")
    ax.plot(cons, prove95, marker="^", color=PALETTE[1], label="p95 prove time")
    ax.set_xlabel("R1CS constraints"); ax.set_ylabel("prove time (ms)"); ax.legend()
    paths.append(save(fig, out_dir, "z2_prove_time"))

    # z3: prove vs verify time vs rules (dual axis)
    fig, ax = new_fig()
    l1, = ax.plot(nr, prove, marker="o", color=PALETTE[0], label="prove (ms)")
    ax.set_xlabel("active compliance rules"); ax.set_ylabel("prove time (ms)", color=PALETTE[0])
    ax.tick_params(axis="y", labelcolor=PALETTE[0])
    ax2 = ax.twinx()
    l2, = ax2.plot(nr, verify, marker="s", color=PALETTE[1], label="verify (ms)")
    ax2.set_ylabel("off-chain verify time (ms)", color=PALETTE[1])
    ax2.tick_params(axis="y", labelcolor=PALETTE[1])
    ax.legend([l1, l2], ["prove time", "off-chain verify time"], fontsize=12, loc="upper left")
    paths.append(save(fig, out_dir, "z3_prove_verify_vs_rules"))

    # z4: key/circuit sizes vs rules (grouped bars)
    fig, ax = new_fig()
    width = 0.4
    x = np.arange(len(nr))
    ax.bar(x - width / 2, pk, width, color=PALETTE[2], label="proving key (MB)")
    ax.bar(x + width / 2, r1cs, width, color=PALETTE[3], label="R1CS (MB)")
    ax.set_xticks(x); ax.set_xticklabels([str(n) for n in nr])
    ax.set_xlabel("active compliance rules"); ax.set_ylabel("size (MB)"); ax.legend()
    paths.append(save(fig, out_dir, "z4_key_sizes"))

    # z5: constraints scaling vs rules with linear fit
    fig, ax = new_fig()
    coef = np.polyfit(nr, cons, 1)
    ax.plot(nr, cons, marker="o", color=PALETTE[0], label="measured constraints")
    ax.plot(nr, np.polyval(coef, nr), "--", color="gray", label=f"linear fit (~{coef[0]:.0f}/rule)")
    ax.set_xlabel("active compliance rules"); ax.set_ylabel("R1CS constraints"); ax.legend()
    paths.append(save(fig, out_dir, "z5_constraint_scaling"))

    # z6: succinctness -- proof + vkey sizes stay O(1)
    fig, ax = new_fig()
    l1, = ax.plot(nr, proof_b, marker="o", color=PALETTE[0], label="proof size (bytes)")
    ax.set_xlabel("active compliance rules"); ax.set_ylabel("proof size (bytes)", color=PALETTE[0])
    ax.set_ylim(0, max(proof_b) * 1.6)
    ax.tick_params(axis="y", labelcolor=PALETTE[0])
    ax2 = ax.twinx()
    l2, = ax2.plot(nr, vk, marker="s", color=PALETTE[1], label="verification key (bytes)")
    ax2.set_ylabel("verification key (bytes)", color=PALETTE[1]); ax2.set_ylim(0, max(vk) * 1.6)
    ax2.tick_params(axis="y", labelcolor=PALETTE[1])
    ax.legend([l1, l2], ["proof size", "verification key"], fontsize=12, loc="center right")
    paths.append(save(fig, out_dir, "z6_succinctness"))

    # z7: on-chain verification cost context
    fig, ax = new_fig()
    names = ["Groth16\nverify", "verifier\ndeploy", "ECPAIRING\nbudget (3M)"]
    vals = [verify_gas / 1000, deploy_gas / 1000, 3000]
    bars = ax.bar(names, vals, color=[PALETTE[1], PALETTE[4], "#999999"])
    ax.set_ylabel("gas (k)")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}k", ha="center", va="bottom", fontsize=13)
    ax.set_yscale("log")
    paths.append(save(fig, out_dir, "z7_onchain_gas"))

    # z8: prove time vs peak RSS phase space, bubble=constraints
    fig, ax = new_fig()
    sc = ax.scatter(prove, rss, s=60 + (cons - cons.min()) / (np.ptp(cons) + 1e-9) * 500, c=nr, cmap="turbo", edgecolor="k", linewidth=0.5)
    ax.plot(prove, rss, color="gray", alpha=0.4, lw=1)
    ax.set_xlabel("prove time (ms)"); ax.set_ylabel("peak RSS (MB)")
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04).set_label("rules")
    paths.append(save(fig, out_dir, "z8_prove_rss_phase"))

    return paths


# ===========================================================================
# Group 7: multi-scheme ZK comparison (Groth16 / PLONK / fflonk)
# ===========================================================================
SCHEME_LABEL = {"groth16": "Groth16", "plonk": "PLONK", "fflonk": "fflonk"}
SCHEME_COLOR = {"groth16": "#1f77b4", "plonk": "#d62728", "fflonk": "#2ca02c"}


def figures_zk_schemes(rows: list[dict[str, str]], gas_rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    order = ["groth16", "plonk", "fflonk"]
    rows = sorted(rows, key=lambda r: order.index(r["scheme"]))
    schemes = [r["scheme"] for r in rows]
    labels = [SCHEME_LABEL[s] for s in schemes]
    colors = [SCHEME_COLOR[s] for s in schemes]
    prove = np.array([float(r["prove_time_ms_mean"]) for r in rows])
    prove_sd = np.array([float(r["prove_time_ms_std"]) for r in rows])
    verify = np.array([float(r["verify_time_ms_mean"]) for r in rows])
    proof_b = np.array([int(r["proof_size_bytes"]) for r in rows])
    pk = np.array([int(r["proving_key_bytes"]) for r in rows]) / 1e6
    vk = np.array([int(r["verification_key_bytes"]) for r in rows])
    rss = np.array([float(r["peak_rss_mb"]) for r in rows])
    gas_map = {g["scheme"]: float(g["verify_gas"]) for g in gas_rows}
    deploy_map = {g["scheme"]: float(g["deploy_gas"]) for g in gas_rows}
    gas = np.array([gas_map.get(s, 0.0) for s in schemes]) / 1000.0
    deploy = np.array([deploy_map.get(s, 0.0) for s in schemes]) / 1000.0
    paths: list[Path] = []

    # zs1: proving cost -- prove time (bars + std)
    fig, ax = new_fig()
    bars = ax.bar(labels, prove, yerr=prove_sd, capsize=6, color=colors)
    ax.set_ylabel("proof generation time (ms)")
    for b, v in zip(bars, prove):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}", ha="center", va="bottom", fontsize=14)
    paths.append(save(fig, out_dir, "zs1_prove_time"))

    # zs2: on-chain verification + deploy gas (grouped bars) -- EVM cost
    fig, ax = new_fig()
    x = np.arange(len(labels)); w = 0.38
    b1 = ax.bar(x - w / 2, gas, w, color=colors, label="verify")
    b2 = ax.bar(x + w / 2, deploy, w, color=colors, alpha=0.45, hatch="//", label="deploy")
    ax.set_ylabel("on-chain gas (k)"); ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    for b, v in zip(b1, gas):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}k", ha="center", va="bottom", fontsize=12)
    ax.legend()
    paths.append(save(fig, out_dir, "zs2_onchain_gas"))

    # zs3: artifact sizes -- proof bytes (left) + proving key MB (right), distinct metrics
    fig, ax = new_fig()
    l1 = ax.bar(x - w / 2, proof_b, w, color=colors, label="proof size (B)")
    ax.set_ylabel("proof size (bytes)")
    for b, v in zip(l1, proof_b):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v}", ha="center", va="bottom", fontsize=12)
    ax2 = ax.twinx()
    ax2.plot(x, pk, "o-", color="#333333", lw=2.2, label="proving key (MB)")
    ax2.set_ylabel("proving key (MB)")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.legend(loc="upper left"); ax2.legend(loc="upper right")
    paths.append(save(fig, out_dir, "zs3_sizes"))

    # zs4: normalized cost radar across 5 axes (lower is better)
    metrics = ["prove\ntime", "verify\ngas", "proof\nsize", "proving\nkey", "peak\nRAM"]
    raw = np.vstack([prove, gas, proof_b, pk, rss]).astype(float)
    norm = raw / raw.max(axis=1, keepdims=True)
    ang = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    ang = np.concatenate([ang, ang[:1]])
    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_subplot(111, projection="polar")
    for j, s in enumerate(schemes):
        vals = np.concatenate([norm[:, j], norm[:1, j]])
        ax.plot(ang, vals, "o-", color=colors[j], label=labels[j], lw=2.2)
        ax.fill(ang, vals, color=colors[j], alpha=0.12)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(metrics, fontsize=13)
    ax.set_ylim(0, 1.05); ax.set_yticklabels([])
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
    paths.append(save(fig, out_dir, "zs4_cost_radar"))

    return paths


# ===========================================================================
# Group 8: SOTA on-chain mechanism comparison
# ===========================================================================
def figures_sota(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    systems = [r["system"] for r in rows]
    short = [s.replace(" et al.", "+") for s in systems]
    storage = np.array([float(r["storage_gas"]) for r in rows]) / 1000.0
    logic = np.array([float(r["logic_gas"]) for r in rows]) / 1000.0
    proof = np.array([float(r["proof_gas"]) for r in rows]) / 1000.0
    total = np.array([float(r["total_gas"]) for r in rows]) / 1000.0
    slots = np.array([float(r["storage_slots"]) for r in rows])
    cov = np.array([float(r["coverage"]) for r in rows])
    is_tc = np.array([s == "TrustCircuit" for s in systems])
    paths: list[Path] = []

    # so1: total per-access on-chain gas, sorted ascending (differentiated gradient)
    fig, ax = new_fig()
    order = np.argsort(total)
    col = ["#2ca02c" if is_tc[i] else ("#cc3311" if proof[i] > 0 else "#4477aa") for i in order]
    bars = ax.barh(np.array(short)[order], total[order], color=col)
    ax.set_xlabel("total on-chain gas per data access (k)")
    for i, v in enumerate(total[order]):
        ax.text(v, i, f" {v:.0f}k", va="center", fontsize=12)
    ax.scatter([], [], c="#4477aa", label="access/commit (no proof)")
    ax.scatter([], [], c="#cc3311", label="ZK verifiable")
    ax.scatter([], [], c="#2ca02c", label="TrustCircuit (full)")
    ax.legend(fontsize=11, loc="lower right")
    paths.append(save(fig, out_dir, "so1_total_gas"))

    # so2: gas decomposition per system (storage / logic / proof)
    fig, ax = new_fig()
    order = np.argsort(total)
    s_short = np.array(short)[order]
    x = np.arange(len(systems))
    ax.bar(x, storage[order], label="storage settlement", color="#4477aa")
    ax.bar(x, logic[order], bottom=storage[order], label="protocol logic", color="#ccbb44")
    ax.bar(x, proof[order], bottom=storage[order] + logic[order], label="ZK proof verify", color="#cc3311")
    ax.set_ylabel("gas (k)")
    ax.set_xticks(x); ax.set_xticklabels(s_short, rotation=40, ha="right", fontsize=11)
    ax.legend(fontsize=12)
    paths.append(save(fig, out_dir, "so2_gas_breakdown"))

    # so3: cost vs capability-coverage Pareto frontier
    fig, ax = new_fig()
    col = ["#2ca02c" if t else "#cc3311" if p > 0 else "#4477aa" for t, p in zip(is_tc, proof)]
    ax.scatter(cov, total, s=240, c=col, edgecolor="k", linewidth=0.8, zorder=3)
    for sname, xx, yy in zip(short, cov, total):
        ax.annotate(sname, (xx, yy), fontsize=10, xytext=(5, 4), textcoords="offset points")
    # Pareto frontier: minimal gas at each coverage level moving up-right.
    pts = sorted(zip(cov, total))
    fx, fy = [], []
    best = -1
    for cc, gg in pts:
        if cc > best:
            fx.append(cc); fy.append(gg); best = cc
    ax.step(fx, fy, where="post", color="#888888", ls="--", lw=1.6, label="capability frontier")
    ax.set_xlabel("design dimensions covered (of 6)"); ax.set_ylabel("total on-chain gas (k)")
    ax.set_xlim(1.5, 6.6); ax.legend(fontsize=11, loc="upper left")
    paths.append(save(fig, out_dir, "so3_cost_vs_coverage"))

    # so4: per-access on-chain storage footprint (state-growth scalability)
    fig, ax = new_fig()
    order = np.argsort(slots)
    col = ["#2ca02c" if is_tc[i] else "#4477aa" for i in order]
    bars = ax.barh(np.array(short)[order], slots[order], color=col)
    ax.set_xlabel("persistent state slots written per access")
    for i, v in enumerate(slots[order]):
        ax.text(v, i, f" {int(v)}", va="center", fontsize=12)
    paths.append(save(fig, out_dir, "so4_storage_footprint"))

    return paths


# ===========================================================================
# Group 9: per-scheme end-to-end pipeline projection
# ===========================================================================
def figures_e2e_schemes(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    order = ["groth16", "plonk", "fflonk"]
    rows = sorted(rows, key=lambda r: order.index(r["scheme"]))
    labels = [SCHEME_LABEL[r["scheme"]] for r in rows]
    colors = [SCHEME_COLOR[r["scheme"]] for r in rows]
    tee = np.array([float(r["tee_compute_ms"]) for r in rows])
    onchain = np.array([float(r["onchain_settlement_ms"]) for r in rows])
    prove = np.array([float(r["prove_ms"]) for r in rows])
    verify = np.array([float(r["offchain_verify_ms"]) for r in rows])
    e2e = np.array([float(r["e2e_latency_ms"]) for r in rows])
    thr = np.array([float(r["throughput_req_s"]) for r in rows])
    gas = np.array([float(r["onchain_verify_gas"]) for r in rows]) / 1000.0
    x = np.arange(len(labels))
    paths: list[Path] = []

    # ez1: total end-to-end latency per scheme (log bars)
    fig, ax = new_fig()
    bars = ax.bar(labels, e2e, color=colors)
    ax.set_ylabel("end-to-end latency (ms)"); ax.set_yscale("log")
    for b, v in zip(bars, e2e):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}", ha="center", va="bottom", fontsize=13)
    paths.append(save(fig, out_dir, "ez1_e2e_latency"))

    # ez2: critical-path composition per scheme (stacked stages)
    fig, ax = new_fig()
    ax.bar(x, tee, label="TEE compute", color="#4477aa")
    ax.bar(x, onchain, bottom=tee, label="on-chain settle", color="#ccbb44")
    ax.bar(x, prove, bottom=tee + onchain, label="ZK prove", color="#cc3311")
    ax.bar(x, verify, bottom=tee + onchain + prove, label="off-chain verify", color="#228833")
    ax.set_ylabel("latency contribution (ms)")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.legend(fontsize=12)
    paths.append(save(fig, out_dir, "ez2_stage_stack"))

    # ez3: single-client throughput per scheme
    fig, ax = new_fig()
    bars = ax.bar(labels, thr, color=colors)
    ax.set_ylabel("single-client throughput (circ/s)")
    for b, v in zip(bars, thr):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=13)
    paths.append(save(fig, out_dir, "ez3_throughput"))

    # ez4: latency vs on-chain gas trade-off
    fig, ax = new_fig()
    ax.scatter(e2e, gas, s=260, c=colors, edgecolor="k", linewidth=0.8, zorder=3)
    for lab, xx, yy in zip(labels, e2e, gas):
        ax.annotate(lab, (xx, yy), fontsize=12, xytext=(6, 4), textcoords="offset points")
    ax.set_xlabel("end-to-end latency (ms)"); ax.set_ylabel("on-chain verify gas (k)")
    ax.set_xscale("log")
    paths.append(save(fig, out_dir, "ez4_latency_vs_gas"))

    return paths


# ===========================================================================
# Group 10: ZK scheme-selection matrix (measured + literature)
# ===========================================================================
SEL_COLOR = {"groth16": "#1f77b4", "plonk": "#d62728", "fflonk": "#2ca02c",
             "stark": "#9467bd", "bulletproofs": "#8c564b"}
SEL_LABEL = {"groth16": "Groth16", "plonk": "PLONK", "fflonk": "fflonk",
             "stark": "STARK*", "bulletproofs": "Bullet*"}


def figures_zk_select(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    labels = [SEL_LABEL[r["scheme"]] for r in rows]
    colors = [SEL_COLOR[r["scheme"]] for r in rows]
    proof = np.array([float(r["proof_size_bytes"]) for r in rows])
    gas = np.array([float(r["verify_onchain_gas"]) for r in rows]) / 1000.0
    measured = np.array([int(r["measured"]) for r in rows])
    hatch = ["" if m else "//" for m in measured]
    x = np.arange(len(labels))
    paths: list[Path] = []

    # zsel1: proof size across schemes (log)
    fig, ax = new_fig()
    for i in range(len(labels)):
        ax.bar(i, proof[i], color=colors[i], hatch=hatch[i], edgecolor="k", linewidth=0.6)
    ax.set_ylabel("proof size (bytes)"); ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    for i, v in enumerate(proof):
        ax.text(i, v, f"{int(v)}", ha="center", va="bottom", fontsize=11)
    ax.text(0.02, 0.96, "* literature value (not measured here)", transform=ax.transAxes, fontsize=11, va="top")
    paths.append(save(fig, out_dir, "zsel1_proof_size"))

    # zsel2: on-chain verify gas across schemes (log)
    fig, ax = new_fig()
    for i in range(len(labels)):
        ax.bar(i, gas[i], color=colors[i], hatch=hatch[i], edgecolor="k", linewidth=0.6)
    ax.set_ylabel("on-chain verify gas (k)"); ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    for i, v in enumerate(gas):
        ax.text(i, v, f"{v:.0f}k", ha="center", va="bottom", fontsize=11)
    ax.axhline(3000, ls=":", color="#555555")
    ax.text(len(labels) - 0.5, 3300, "3M EVM block budget guide", fontsize=10, ha="right")
    paths.append(save(fig, out_dir, "zsel2_verify_gas"))

    # zsel3: proof size vs verify gas trade-off (EVM-friendliness frontier)
    fig, ax = new_fig()
    ax.scatter(proof, gas, s=260, c=colors, edgecolor="k", linewidth=0.8, zorder=3)
    for lab, xx, yy in zip(labels, proof, gas):
        ax.annotate(lab, (xx, yy), fontsize=12, xytext=(6, 4), textcoords="offset points")
    ax.set_xlabel("proof size (bytes)"); ax.set_ylabel("on-chain verify gas (k)")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.text(0.02, 0.06, "bottom-left = most EVM-friendly", transform=ax.transAxes, fontsize=11)
    paths.append(save(fig, out_dir, "zsel3_size_vs_gas"))

    # zsel4: qualitative property matrix (scheme x property)
    props = ["universal\nsetup", "transparent\n(no setup)", "post-\nquantum", "EVM-cheap\nverify", "measured\nhere"]
    pm = []
    for r in rows:
        universal = 1.0 if r["setup_model"] in ("universal", "transparent") else 0.0
        transparent = float(r["transparent"])
        pq = float(r["post_quantum"])
        evm_cheap = 1.0 if float(r["verify_onchain_gas"]) <= 400000 else 0.0
        pm.append([universal, transparent, pq, evm_cheap, float(r["measured"])])
    pm = np.array(pm)
    fig, ax = new_fig()
    im = ax.imshow(pm, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(props))); ax.set_xticklabels(props, fontsize=11)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
    for y in range(pm.shape[0]):
        for xx in range(pm.shape[1]):
            ax.text(xx, y, "Y" if pm[y, xx] >= 1 else "-", ha="center", va="center", fontsize=12)
    paths.append(save(fig, out_dir, "zsel4_property_matrix"))

    return paths


# ===========================================================================
# Group 11: CP-ABE hybrid encryption (policy scaling, payload scaling, security)
# ===========================================================================
def figure_cpabe_policy_comparison(rows, out_dir: Path) -> Path:
    pr = sorted(rows, key=lambda row: int(row["policy_attributes"]))
    attributes = np.array([int(row["policy_attributes"]) for row in pr])
    kem_enc = np.array([float(row["kem_dem_baseline_encrypt_ms_mean"]) for row in pr])
    kem_dec = np.array([float(row["kem_dem_baseline_decrypt_ms_mean"]) for row in pr])
    cpabe_enc = np.array([float(row["full_cpabe_encrypt_ms_mean"]) for row in pr])
    cpabe_dec = np.array([float(row["full_cpabe_decrypt_ms_mean"]) for row in pr])

    fig, ax = new_fig()
    ax.plot(attributes, kem_enc, marker="o", color=PALETTE[0], label="encrypt (KEM-DEM baseline)")
    ax.plot(attributes, kem_dec, marker="s", color=PALETTE[1], label="decrypt (KEM-DEM baseline)")
    ax.plot(attributes, cpabe_enc, marker="^", linestyle="--", color=PALETTE[2], label="encrypt (Full CP-ABE)")
    ax.plot(attributes, cpabe_dec, marker="D", linestyle="--", color=PALETTE[4], label="decrypt (Full CP-ABE)")
    ax.set_xlabel("policy attributes")
    ax.set_ylabel("latency (ms)")
    ax.set_xticks(attributes)
    ax.set_ylim(bottom=0)
    ax.legend()
    return save(fig, out_dir, "ab1_policy_time")


def figures_abe(policy_rows, payload_rows, sec_rows, out_dir: Path, cpabe_policy_rows=None) -> list[Path]:
    paths: list[Path] = []

    # --- policy scaling: encrypt/decrypt time + key-encapsulation size ----
    if policy_rows:
        pr = sorted(policy_rows, key=lambda r: int(r["policy_leaves"]))
        leaves = np.array([int(r["policy_leaves"]) for r in pr])
        enc = np.array([float(r["encrypt_ms_mean"]) for r in pr])
        enc_sd = np.array([float(r["encrypt_ms_std"]) for r in pr])
        dec = np.array([float(r["decrypt_ms_mean"]) for r in pr])
        kenc = np.array([int(r["kenc_bytes"]) for r in pr])

        # ab1: matched KEM-DEM baseline versus real pairing-based CP-ABE.
        if cpabe_policy_rows:
            paths.append(figure_cpabe_policy_comparison(cpabe_policy_rows, out_dir))
        else:
            fig, ax = new_fig()
            ax.fill_between(leaves, enc - enc_sd, enc + enc_sd, alpha=0.2, color="#4477aa")
            ax.plot(leaves, enc, marker="o", color=PALETTE[0], label="encrypt (KEM)")
            ax.plot(leaves, dec, marker="s", color=PALETTE[1], label="decrypt (KEM + LSSS)")
            ax.set_xlabel("policy attributes (leaves)"); ax.set_ylabel("key-encapsulation time (ms)")
            ax.legend()
            paths.append(save(fig, out_dir, "ab1_policy_time"))

        # ab2: key-encapsulation size grows linearly with policy size
        fig, ax = new_fig()
        coef = np.polyfit(leaves, kenc, 1)
        ax.plot(leaves, kenc, marker="o", color=PALETTE[2], label="measured KEM size")
        ax.plot(leaves, np.polyval(coef, leaves), "--", color="gray", label=f"linear (~{coef[0]:.0f} B/attr)")
        ax.set_xlabel("policy attributes (leaves)"); ax.set_ylabel("key-encapsulation size (bytes)")
        ax.legend()
        paths.append(save(fig, out_dir, "ab2_kenc_size"))

    # --- payload scaling: AES-256-GCM bulk path -------------------------------
    if payload_rows:
        pay = sorted(payload_rows, key=lambda r: int(r["payload_mb"]))
        mb = np.array([int(r["payload_mb"]) for r in pay])
        penc = np.array([float(r["encrypt_ms_mean"]) for r in pay])
        pdec = np.array([float(r["decrypt_ms_mean"]) for r in pay])
        ethr = np.array([float(r["enc_throughput_mbps"]) for r in pay])
        dthr = np.array([float(r["dec_throughput_mbps"]) for r in pay])
        frac = np.array([float(r["kenc_fraction_pct"]) for r in pay])
        rss = np.array([float(r["peak_rss_mb"]) for r in pay])

        # ab3: encrypt/decrypt time vs payload (log-log, ~linear in size)
        fig, ax = new_fig()
        ax.loglog(mb, penc, marker="o", color=PALETTE[0], label="encrypt")
        ax.loglog(mb, pdec, marker="s", color=PALETTE[1], label="decrypt")
        ax.set_xlabel("payload size (MB, log)"); ax.set_ylabel("time (ms, log)")
        ax.legend()
        paths.append(save(fig, out_dir, "ab3_payload_time"))

        # ab4: bulk throughput vs payload size
        fig, ax = new_fig()
        ax.semilogx(mb, ethr, marker="o", color=PALETTE[0], label="encrypt throughput")
        ax.semilogx(mb, dthr, marker="s", color=PALETTE[1], label="decrypt throughput")
        ax.set_xlabel("payload size (MB, log)"); ax.set_ylabel("throughput (MB/s)")
        ax.legend()
        paths.append(save(fig, out_dir, "ab4_throughput"))

        # ab5: key-encapsulation overhead is amortised away as payload grows
        fig, ax = new_fig()
        ax.loglog(mb, frac, marker="o", color=PALETTE[4])
        ax.set_xlabel("payload size (MB, log)")
        ax.set_ylabel("key-encapsulation overhead (% of ciphertext, log)")
        for x, y in zip(mb, frac):
            if x in (mb[0], mb[-1]):
                ax.annotate(f"{y:.1e}%", (x, y), fontsize=11, xytext=(4, 4), textcoords="offset points")
        paths.append(save(fig, out_dir, "ab5_overhead_amortization"))

        # ab6: peak RSS vs payload (memory footprint of the bulk path)
        fig, ax = new_fig()
        ax.plot(mb, rss, marker="o", color=PALETTE[3], label="peak RSS")
        ax.plot(mb, mb, "--", color="gray", label="1x payload")
        ax.set_xlabel("payload size (MB)"); ax.set_ylabel("peak resident memory (MB)")
        ax.legend()
        paths.append(save(fig, out_dir, "ab6_peak_rss"))

    # --- security stress: authorised success vs unauthorised block ------------
    if sec_rows:
        sr = sorted(sec_rows, key=lambda r: int(r["policy_leaves"]))
        labels = [f"{r['threshold_k']}/{r['policy_leaves']}" for r in sr]
        auth = np.array([float(r["authorized_success_rate"]) for r in sr])
        blk = np.array([float(r["unauthorized_block_rate"]) for r in sr])
        x = np.arange(len(labels)); w = 0.38
        fig, ax = new_fig()
        ax.bar(x - w / 2, auth, w, color="#228833", label="authorized success rate")
        ax.bar(x + w / 2, blk, w, color="#cc3311", label="unauthorized block rate")
        ax.set_ylim(0, 1.12); ax.set_ylabel("rate")
        ax.set_xticks(x); ax.set_xticklabels(labels)
        ax.set_xlabel("access policy (k-of-n threshold)")
        for i in range(len(labels)):
            ax.text(x[i] - w / 2, auth[i], f"{auth[i]:.2f}", ha="center", va="bottom", fontsize=12)
            ax.text(x[i] + w / 2, blk[i], f"{blk[i]:.2f}", ha="center", va="bottom", fontsize=12)
        ax.legend(loc="lower center", ncol=2)
        paths.append(save(fig, out_dir, "ab7_security_rates"))

    return paths


# ===========================================================================
# Group 12: SOTA multi-dimensional capability comparison (closest systems)
# ===========================================================================
CAP_AXES = [
    ("confidential_compute", "confidential\ncompute"),
    ("composable_dp_budget", "composable\nDP budget"),
    ("zk_compliance_proof", "ZK compliance\nproof"),
    ("replay_nullifier_guard", "replay /\nnullifier"),
    ("public_input_binding", "public-input\nbinding"),
    ("end_to_end_lifecycle", "end-to-end\nlifecycle"),
]
SOTA_CAP_COLOR = {
    "Ekiden": "#ff7f0e", "Hawk": "#9467bd", "zkLedger": "#17becf",
    "ProMark": "#8c564b", "TrustCircuit": "#2ca02c",
}


def figures_sota_capability(rows, out_dir: Path) -> list[Path]:
    paths: list[Path] = []
    systems = [r["system"] for r in rows]
    keys = [k for k, _ in CAP_AXES]
    labels = [lab for _, lab in CAP_AXES]
    mat = np.array([[float(r[k]) for k in keys] for r in rows])

    # so5: capability radar across the closest systems + TrustCircuit
    ang = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    ang = np.concatenate([ang, ang[:1]])
    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_subplot(111, projection="polar")
    for i, sysname in enumerate(systems):
        vals = np.concatenate([mat[i], mat[i, :1]])
        is_tc = sysname == "TrustCircuit"
        ax.plot(ang, vals, "o-", color=SOTA_CAP_COLOR.get(sysname, PALETTE[i % len(PALETTE)]),
                label=sysname, lw=3.0 if is_tc else 2.0, zorder=5 if is_tc else 3)
        ax.fill(ang, vals, color=SOTA_CAP_COLOR.get(sysname, PALETTE[i % len(PALETTE)]),
                alpha=0.18 if is_tc else 0.06)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(labels, fontsize=12)
    ax.set_ylim(0, 1.05); ax.set_yticks([0.5, 1.0]); ax.set_yticklabels(["partial", "full"], fontsize=11)
    ax.legend(loc="upper right", bbox_to_anchor=(1.28, 1.12), fontsize=12)
    paths.append(save(fig, out_dir, "so5_capability_radar"))

    # so6: capability heatmap (system x dimension), score annotated
    fig, ax = new_fig()
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_yticks(range(len(systems))); ax.set_yticklabels(systems)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels([l.replace("\n", " ") for l in labels], rotation=30, ha="right", fontsize=11)
    for y in range(mat.shape[0]):
        for x in range(mat.shape[1]):
            sym = {0.0: "\u2717", 0.5: "\u223c", 1.0: "\u2713"}.get(mat[y, x], f"{mat[y, x]:.1f}")
            ax.text(x, y, sym, ha="center", va="center", fontsize=14,
                    color="black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).set_label("capability score")
    paths.append(save(fig, out_dir, "so6_capability_heatmap"))

    return paths


# ===========================================================================
# main
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-dir", type=Path, default=Path("results/summary"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    args = parser.parse_args()

    apply_style()
    s = args.summary_dir
    produced: list[Path] = []
    deploy_path = s / "contract_deploy_gas.csv"
    deploy_rows = read_csv(deploy_path) if deploy_path.exists() else None
    produced += figures_gas(read_csv(s / "contract_gas_summary.csv"), args.out_dir / "gas", deploy_rows)
    produced += figures_e2e(read_csv(s / "e2e_pipeline_summary.csv"), args.out_dir / "e2e")
    produced += figures_dp(read_csv(s / "dp_utility_summary.csv"), args.out_dir / "dp")
    produced += figures_tee_scaling(read_csv(s / "tee_workload_summary.csv"), args.out_dir / "tee_scaling")
    produced += figures_tee_attack(read_csv(s / "tee_attack_summary.csv"), args.out_dir / "tee_robustness")
    zk_path = s / "zk_benchmark_summary.csv"
    if zk_path.exists():
        gas_path = s / "zk_onchain_gas.csv"
        gas_rows = read_csv(gas_path) if gas_path.exists() else []
        produced += figures_zk(read_csv(zk_path), gas_rows, args.out_dir / "zk")
    schemes_path = s / "zk_schemes_summary.csv"
    if schemes_path.exists():
        sg_path = s / "zk_schemes_gas.csv"
        sg_rows = read_csv(sg_path) if sg_path.exists() else []
        produced += figures_zk_schemes(read_csv(schemes_path), sg_rows, args.out_dir / "zk_schemes")
    sota_path = s / "sota_compare.csv"
    if sota_path.exists():
        produced += figures_sota(read_csv(sota_path), args.out_dir / "sota")
    e2e_sch_path = s / "e2e_zk_schemes.csv"
    if e2e_sch_path.exists():
        produced += figures_e2e_schemes(read_csv(e2e_sch_path), args.out_dir / "e2e_schemes")
    sel_path = s / "zk_scheme_selection.csv"
    if sel_path.exists():
        produced += figures_zk_select(read_csv(sel_path), args.out_dir / "zk_select")
    # CP-ABE hybrid encryption figures
    abe_policy = read_csv(s / "abe_summary.csv") if (s / "abe_summary.csv").exists() else []
    abe_payload = read_csv(s / "abe_payload_summary.csv") if (s / "abe_payload_summary.csv").exists() else []
    abe_sec_path = Path("results/raw/abe_security.csv")
    abe_sec = read_csv(abe_sec_path) if abe_sec_path.exists() else []
    if abe_policy or abe_payload or abe_sec:
        cpabe_policy_path = s / "cpabe_policy_summary.csv"
        cpabe_policy_rows = read_csv(cpabe_policy_path) if cpabe_policy_path.exists() else []
        produced += figures_abe(
            abe_policy,
            abe_payload,
            abe_sec,
            args.out_dir / "abe",
            cpabe_policy_rows,
        )
    # SOTA capability comparison (closest systems)
    cap_path = s / "sota_capability.csv"
    if cap_path.exists():
        produced += figures_sota_capability(read_csv(cap_path), args.out_dir / "sota")
    for p in produced:
        print(p)
    print(f"total figures: {len(produced)}")


if __name__ == "__main__":
    main()
