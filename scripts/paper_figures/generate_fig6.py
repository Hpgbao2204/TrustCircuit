"""Figure 6: controlled configuration performance and overhead."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, indexed, processed, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import style_secondary_axis


CONFIGS = ["Access Ledger", "Local DP Ledger", "ZK Release", "TEE-only", "TrustCircuit"]
OVERHEAD_STAGES = ["other_lifecycle_ms", "attestation_overhead_ms", "budget_overhead_ms", "proof_overhead_ms"]
OVERHEAD_LABELS = ["Other lifecycle", "Attestation", "Budget", "Proof"]


def panel_b(summary) -> None:
    rows = indexed(summary, "configuration")
    x = np.arange(len(CONFIGS), dtype=float)
    p50 = np.array([float(rows[c]["median_latency_ms"]) for c in CONFIGS])
    p95 = np.array([float(rows[c]["p95_latency_ms"]) for c in CONFIGS])
    throughput = np.array([float(rows[c]["median_throughput_req_s"]) for c in CONFIGS])
    success = np.array([100 * float(rows[c]["success_rate"]) for c in CONFIGS])
    width = 0.35
    fig, ax = new_figure(figsize=(8.8, 5.35))
    ax.bar(x - width / 2, p50, width, color=COLORS["blue"], label="latency p50")
    ax.bar(x + width / 2, p95, width, color=COLORS["cyan"], alpha=0.72, label="latency p95")
    ax.set_yscale("log")
    ax.set_xticks(x, CONFIGS, rotation=14, ha="right")
    ax.set_xlabel("Controlled configuration")
    ax.set_ylabel("End-to-end latency (ms, log scale)")
    ax.set_title("Controlled latency, throughput, and success")
    ax2 = ax.twinx()
    ax2.plot(x, throughput, linestyle="none", marker="D", markersize=6,
             color=COLORS["red"], markeredgecolor="white", markeredgewidth=0.6,
             label="throughput p50")
    ax2.set_yscale("log")
    ax2.set_ylabel("Throughput (requests/s, log scale)", color=COLORS["red"])
    style_secondary_axis(ax2)
    for i, value in enumerate(success):
        ax.annotate(f"{value:.0f}%", (i + width / 2, p95[i]), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=ANNOTATION_SIZE, color=COLORS["green"])
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles2.append(plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["green"], label="success"))
    labels2.append("success above bars")
    ax.legend(handles1 + handles2, labels1 + labels2, loc="center left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig6b_controlled_performance.pdf")


def panel_c(overhead) -> None:
    lookup = {(r["configuration"], r["stage"]): r for r in overhead}
    x = np.arange(len(CONFIGS), dtype=float)
    bottom = np.zeros(len(CONFIGS))
    p95_total = np.zeros(len(CONFIGS))
    fig, ax = new_figure(figsize=(8.8, 5.35))
    colors = [COLORS["gray"], COLORS["purple"], COLORS["green"], COLORS["orange"]]
    for stage, label, color in zip(OVERHEAD_STAGES, OVERHEAD_LABELS, colors):
        mean = np.array([float(lookup[(config, stage)]["mean_latency_ms"]) for config in CONFIGS])
        p95_total += np.array([float(lookup[(config, stage)]["p95_latency_ms"]) for config in CONFIGS])
        ax.bar(x, mean, bottom=bottom, width=0.68, color=color, edgecolor="white", linewidth=0.5,
               label=label)
        bottom += mean
    ax.plot(x, p95_total, linestyle="none", marker="D", color=COLORS["red"], markersize=6,
            label="sum of stage p95")
    for i, total in enumerate(bottom):
        ax.annotate(f"{total:.0f}", (i, total), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=ANNOTATION_SIZE)
    ax.set_xticks(x, CONFIGS, rotation=14, ha="right")
    ax.set_xlabel("Controlled configuration")
    ax.set_ylabel("Mean overhead (ms)")
    ax.set_title("Controlled overhead attribution")
    ax.legend(loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig6c_controlled_overhead.pdf")


def panel_d(summary, trials) -> None:
    summary_map = indexed(summary, "configuration")
    trial_groups = groups(trials, "configuration")
    raw = np.array([
        [float(summary_map[c]["median_latency_ms"]) for c in CONFIGS],
        [float(summary_map[c]["median_throughput_req_s"]) for c in CONFIGS],
        [float(summary_map[c]["mean_total_gas"]) for c in CONFIGS],
        [np.percentile(values(trial_groups[c], "normalized_peak_cpu_percent"), 95) for c in CONFIGS],
        [np.median(values(trial_groups[c], "peak_private_bytes")) for c in CONFIGS],
        [float(summary_map[c]["security_coverage_score"]) for c in CONFIGS],
    ], dtype=float)
    normalized = 100 * raw / np.maximum(raw.max(axis=1, keepdims=True), 1e-9)
    metric_labels = ["Latency", "Throughput", "Gas", "Peak CPU", "Private RAM", "Coverage"]
    grid_x, grid_y = np.meshgrid(
        np.arange(len(metric_labels), dtype=float),
        np.arange(len(CONFIGS), dtype=float),
    )
    heights = normalized.T
    xpos = grid_x.ravel()
    ypos = grid_y.ravel()
    zpos = np.zeros_like(xpos)
    dx = np.full_like(xpos, 0.58)
    dy = np.full_like(ypos, 0.55)
    dz = heights.ravel()
    bar_colors = [PALETTE[int(index)] for index in ypos]

    fig, ax = new_figure(figsize=(9.6, 6.35), projection="3d")
    ax.bar3d(xpos, ypos, zpos, dx, dy, dz, color=bar_colors, alpha=0.86,
             edgecolor="white", linewidth=0.45, shade=True)
    ax.scatter(xpos + dx / 2, ypos + dy / 2, dz, c=bar_colors, s=18,
               edgecolors=COLORS["dark"], linewidths=0.35, depthshade=False)
    ax.set_xticks(
        np.arange(len(metric_labels)) + 0.29,
        ["Latency", "Throughput", "Gas", "CPU", "RAM", "Coverage"],
        rotation=10,
        ha="right",
    )
    ax.set_yticks(np.arange(len(CONFIGS)) + 0.275,
                  ["Access", "Local DP", "ZK", "TEE", "Trust"])
    ax.set_zlim(0, 108)
    ax.set_ylabel("Configuration", labelpad=12)
    ax.set_zlabel("Index relative to metric maximum (%)", labelpad=10)
    ax.set_title("Controlled multiobjective metric grid")
    ax.view_init(elev=27, azim=-58)
    ax.set_box_aspect((1.65, 1.15, 0.9))
    handles = [plt.Rectangle((0, 0), 1, 1, color=PALETTE[i], label=config)
               for i, config in enumerate(CONFIGS)]
    ax.legend(handles=handles, loc="upper left", ncol=2)
    save_pdf(fig, "fig6d_multiobjective_profile.pdf")


def generate() -> list[str]:
    summary = processed(
        "comparison_summary.csv",
        ["configuration", "median_latency_ms", "p95_latency_ms", "median_throughput_req_s",
         "mean_total_gas", "security_coverage_score", "success_rate"],
    )
    trials = processed(
        "comparison_trials.csv", ["configuration", "normalized_peak_cpu_percent", "peak_private_bytes"]
    )
    overhead = processed(
        "comparison_overhead.csv", ["configuration", "stage", "mean_latency_ms", "p95_latency_ms"]
    )
    panel_b(summary)
    panel_c(overhead)
    panel_d(summary, trials)
    return [
        "fig6b_controlled_performance.pdf", "fig6c_controlled_overhead.pdf",
        "fig6d_multiobjective_profile.pdf",
    ]


if __name__ == "__main__":
    generate()
