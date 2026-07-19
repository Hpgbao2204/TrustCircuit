"""Figure 6: controlled capability/performance comparison."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, indexed, processed, values
from .figure_style import COLORS, PALETTE, finish_axis, human_number, new_figure, save_pdf
from .plot_helpers import distribution_boxes
from .statistics import area_sizes


CONFIGS = ["Access Ledger", "Local DP Ledger", "TEE-only", "ZK Release", "TrustCircuit"]
CAPABILITIES = [
    "access_authorization", "encrypted_confidential_execution", "native_attestation_validation",
    "differential_privacy_release", "cumulative_privacy_budget", "zero_knowledge_binding",
    "replay_protection", "atomic_audit_settlement",
]
CAP_LABELS = ["Access", "Encrypted\nexecution", "Native\nattestation", "DP\nrelease", "Budget", "ZK\nbinding", "Replay", "Atomic\naudit"]
OVERHEAD_STAGES = ["other_lifecycle_ms", "attestation_overhead_ms", "budget_overhead_ms", "proof_overhead_ms"]
OVERHEAD_LABELS = ["Other lifecycle", "Attestation", "Budget", "Proof"]


def panel_a(rows) -> None:
    rows = [indexed(rows, "configuration")[c] for c in CONFIGS]
    matrix = np.array([[int(float(r[c])) for c in CAPABILITIES] for r in rows], dtype=float)
    fig, ax = new_figure(figsize=(7.35, 4.45))
    ax.pcolormesh(np.arange(len(CAPABILITIES) + 1), np.arange(len(CONFIGS) + 1), matrix,
                  cmap="Blues", vmin=0, vmax=1, edgecolors="white", linewidth=1.0, shading="flat")
    ax.set_xticks(np.arange(len(CAPABILITIES)) + 0.5, CAP_LABELS)
    ax.set_yticks(np.arange(len(CONFIGS)) + 0.5, CONFIGS)
    ax.invert_yaxis()
    ax.set_xlabel("Control / guarantee")
    ax.set_ylabel("Controlled configuration")
    ax.set_title("Capability matrix used for the controlled comparison")
    for i in range(len(CONFIGS)):
        for j in range(len(CAPABILITIES)):
            value = matrix[i, j]
            ax.text(j + 0.5, i + 0.5, "✓" if value else "—", ha="center", va="center",
                    fontsize=9, color="white" if value else COLORS["gray"])
    ax.text(0.995, -0.13, "Security coverage score is the count of enabled controls (8 total)",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    save_pdf(fig, "fig6a_capability_matrix.pdf")


def panel_b(trials, summary) -> None:
    grouped = groups(trials, "configuration")
    datasets = [values(grouped[c], "total_latency_ms") for c in CONFIGS]
    x = np.arange(len(CONFIGS), dtype=float)
    colors = [PALETTE[i] for i in range(len(CONFIGS))]
    fig, ax = new_figure(figsize=(7.35, 4.75))
    distribution_boxes(ax, datasets, x, colors, salt=190)
    summary_map = indexed(summary, "configuration")
    success = np.array([100 * float(summary_map[c]["success_rate"]) for c in CONFIGS])
    ax.set_yscale("log")
    ax.set_xticks(x, CONFIGS, rotation=16, ha="right")
    ax.set_xlabel("Configuration")
    ax.set_ylabel("End-to-end latency (ms, log scale)")
    ax.set_title("Controlled performance distributions")
    ax2 = ax.twinx()
    throughput = np.array([float(summary_map[c]["median_throughput_req_s"]) for c in CONFIGS])
    ax2.scatter(x, throughput, marker="o", facecolors="white", edgecolors=COLORS["red"],
                linewidth=1.4, s=38, label="p50 throughput")
    ax2.set_yscale("log")
    ax2.set_ylabel("Throughput (requests/s, log scale)", color=COLORS["red"])
    ax2.tick_params(axis="y", colors=COLORS["red"])
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color(COLORS["red"])
    top = ax.get_ylim()[1]
    for i, value in enumerate(success):
        ax.text(i, top / 1.35, f"{value:.0f}% ok", ha="center", fontsize=6.8)
    ax.legend(handles=[
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50 latency"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95 latency"),
        plt.Line2D([], [], marker="o", markerfacecolor="white", color=COLORS["red"], label="p50 throughput"),
    ], loc="center left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig6b_controlled_performance.pdf")


def panel_c(overhead) -> None:
    lookup = {(r["configuration"], r["stage"]): r for r in overhead}
    x = np.arange(len(CONFIGS), dtype=float)
    fig, ax = new_figure(figsize=(7.35, 4.75))
    bottom = np.zeros(len(CONFIGS))
    p95_total = np.zeros(len(CONFIGS))
    for stage, label in zip(OVERHEAD_STAGES, OVERHEAD_LABELS):
        mean = np.array([float(lookup[(config, stage)]["mean_latency_ms"]) for config in CONFIGS])
        p95 = np.array([float(lookup[(config, stage)]["p95_latency_ms"]) for config in CONFIGS])
        p95_total += p95
        color = {"other_lifecycle_ms": COLORS["gray"], "attestation_overhead_ms": COLORS["purple"],
                 "budget_overhead_ms": COLORS["green"], "proof_overhead_ms": COLORS["orange"]}[stage]
        ax.bar(x, mean, bottom=bottom, width=0.68, color=color, label=label,
               edgecolor="white", linewidth=0.5)
        bottom += mean
    ax.scatter(x, p95_total, marker="D", s=34, color=COLORS["red"], zorder=5, label="sum of stage p95")
    for i, value in enumerate(bottom):
        ax.annotate(f"{value:.0f} ms", (i, value), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=6.8)
    ax.set_xticks(x, CONFIGS, rotation=16, ha="right")
    ax.set_xlabel("Configuration")
    ax.set_ylabel("Mean overhead (ms)")
    ax.set_title("Controlled overhead attribution")
    ax.legend(loc="upper left", ncol=3)
    ax.text(0.995, 0.02, "Other lifecycle is the measured remainder; diamond = sum of component p95 values",
            transform=ax.transAxes, ha="right", fontsize=6.7, color=COLORS["gray"])
    finish_axis(ax)
    save_pdf(fig, "fig6c_controlled_overhead.pdf")


def panel_d(summary, trials) -> None:
    summary_map = indexed(summary, "configuration")
    trial_groups = groups(trials, "configuration")
    latency = np.array([float(summary_map[c]["median_latency_ms"]) for c in CONFIGS])
    throughput = np.array([float(summary_map[c]["median_throughput_req_s"]) for c in CONFIGS])
    gas = np.array([float(summary_map[c]["mean_total_gas"]) for c in CONFIGS])
    coverage = np.array([float(summary_map[c]["security_coverage_score"]) for c in CONFIGS])
    private = np.array([np.median(values(trial_groups[c], "peak_private_bytes")) / 1024**2 for c in CONFIGS])
    sizes = area_sizes(gas, 100, 650)
    fig, ax = new_figure(figsize=(7.35, 4.75))
    coverage_colors = plt.get_cmap("viridis")((coverage - 1) / 7)
    ax.scatter(latency, throughput, s=sizes, c=coverage_colors,
               edgecolor=COLORS["dark"], linewidth=0.9, alpha=0.84)
    label_offsets = {
        "Access Ledger": (8, 8), "Local DP Ledger": (8, 5), "TEE-only": (15, 18),
        "ZK Release": (-76, 20), "TrustCircuit": (12, -31),
    }
    for x, y, config, score, mem, ok in zip(latency, throughput, CONFIGS, coverage, private,
                                             [summary_map[c]["success_rate"] for c in CONFIGS]):
        ax.annotate(f"{config}\ncoverage {score:.0f}/8 · {mem:.0f} MiB",
                    (x, y), xytext=label_offsets[config], textcoords="offset points", fontsize=6.6)
    tc = CONFIGS.index("TrustCircuit")
    ax.scatter(latency[tc], throughput[tc], s=sizes[tc] * 1.18, facecolors="none",
               edgecolors=COLORS["red"], linewidth=1.7, zorder=5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Median end-to-end latency (ms, log scale)")
    ax.set_ylabel("Median throughput (requests/s, log scale)")
    ax.set_title("Multiobjective controlled comparison")
    ax.text(0.98, 0.98, "color: security coverage 1/8 → 8/8",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.8, color=COLORS["gray"])
    ax.text(0.995, 0.02, "Bubble area ∝ mean gas; labels include median private memory; red ring = TrustCircuit",
            transform=ax.transAxes, ha="right", fontsize=6.6, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig6d_multiobjective_comparison.pdf")


def generate() -> list[str]:
    capabilities = processed(
        "comparison_capabilities.csv", ["configuration", *CAPABILITIES, "security_coverage_score"]
    )
    summary = processed(
        "comparison_summary.csv",
        ["configuration", "median_latency_ms", "p95_latency_ms", "median_throughput_req_s",
         "mean_total_gas", "security_coverage_score", "success_rate"],
    )
    trials = processed(
        "comparison_trials.csv",
        ["configuration", "total_latency_ms", "throughput_req_s", "peak_private_bytes", "success"],
    )
    overhead = processed(
        "comparison_overhead.csv", ["configuration", "stage", "mean_latency_ms", "p95_latency_ms"]
    )
    panel_a(capabilities)
    panel_b(trials, summary)
    panel_c(overhead)
    panel_d(summary, trials)
    return [
        "fig6a_capability_matrix.pdf", "fig6b_controlled_performance.pdf",
        "fig6c_controlled_overhead.pdf", "fig6d_multiobjective_comparison.pdf",
    ]


if __name__ == "__main__":
    generate()
