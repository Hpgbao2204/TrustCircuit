"""Figure 1: end-to-end ablation, stage composition, gas, and frontier."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle

from .data_loading import groups, indexed, processed, values
from .figure_style import (
    COLORS, PALETTE, STAGE_COLORS, finish_axis, human_number, new_figure,
    save_pdf, short_variant,
)
from .plot_helpers import distribution_boxes
from .statistics import area_sizes


VARIANTS = ["baseline_minimal", "access_only", "no_budget", "no_zk", "no_tee", "full_trustcircuit"]
STAGES = ["access", "budget", "tee", "proof", "settlement", "audit"]


def _sources():
    trials = processed(
        "e2e_ablation_trials.csv",
        ["variant", "total_latency_ms", "throughput_req_s", "success", "measurement_type"],
    )
    summary = processed(
        "e2e_ablation_summary.csv",
        ["variant", "p50_latency_ms", "p95_latency_ms", "latency_bootstrap_ci95_low_ms",
         "latency_bootstrap_ci95_high_ms", "p50_throughput_req_s", "mean_total_gas",
         "success_rate", "p95_normalized_peak_cpu_percent", "measurement_type"],
    )
    stage = processed("e2e_stage_by_variant.csv", ["variant", "stage", "mean_latency_ms", "measurement_type"])
    gas = processed("e2e_gas_by_variant.csv", ["variant", "stage", "mean_gas", "measurement_type"])
    return trials, summary, stage, gas


def panel_a(trials, summary) -> None:
    grouped = groups(trials, "variant")
    summaries = indexed(summary, "variant")
    datasets = [values(grouped[v], "total_latency_ms") for v in VARIANTS]
    x = np.arange(len(VARIANTS), dtype=float)
    colors = [PALETTE[i] for i in range(len(VARIANTS))]

    fig, ax = new_figure(figsize=(7.25, 4.65))
    distribution_boxes(ax, datasets, x, colors, salt=10)
    means = np.array([float(summaries[v]["mean_latency_ms"]) for v in VARIANTS])
    ci_lo = np.array([float(summaries[v]["latency_bootstrap_ci95_low_ms"]) for v in VARIANTS])
    ci_hi = np.array([float(summaries[v]["latency_bootstrap_ci95_high_ms"]) for v in VARIANTS])
    ax.errorbar(
        x, means, yerr=[means - ci_lo, ci_hi - means], fmt="s", ms=4.0,
        color=COLORS["blue"], ecolor=COLORS["blue"], capsize=3, zorder=5,
        label="mean + 95% bootstrap CI",
    )
    ax.set_yscale("log")
    ax.set_ylabel("End-to-end latency (ms, log scale)")
    ax.set_xticks(x, [short_variant(v) for v in VARIANTS], rotation=18, ha="right")
    ax.set_title("Ablation performance: 30 measured trials per configuration")

    ax2 = ax.twinx()
    throughput = np.array([float(summaries[v]["p50_throughput_req_s"]) for v in VARIANTS])
    ax2.scatter(x, throughput, marker="o", facecolors="white", edgecolors=COLORS["red"],
                linewidths=1.4, s=38, zorder=6, label="p50 throughput")
    ax2.set_yscale("log")
    ax2.set_ylabel("Throughput (requests/s, log scale)", color=COLORS["red"])
    ax2.tick_params(axis="y", colors=COLORS["red"])
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color(COLORS["red"])

    top = ax.get_ylim()[1]
    for i, variant in enumerate(VARIANTS):
        success = 100 * float(summaries[variant]["success_rate"])
        ax.text(i, top / 1.35, f"{success:.0f}% ok", ha="center", va="top", fontsize=6.8)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles1.extend([
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95"),
    ])
    labels1.extend(["p50", "p95"])
    ax.legend(handles1 + handles2, labels1 + labels2, loc="center left", ncol=2)
    ax.text(0.995, 0.02, "* model-calibrated from measured components", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax)
    save_pdf(fig, "fig1a_ablation_performance.pdf")


def panel_b(stage_rows, summary) -> None:
    summaries = indexed(summary, "variant")
    lookup = {(r["variant"], r["stage"]): float(r["mean_latency_ms"]) for r in stage_rows}
    matrix = np.array([[lookup[(v, s)] for s in STAGES] for v in VARIANTS], dtype=float)
    totals = np.array([float(summaries[v]["mean_latency_ms"]) for v in VARIANTS])
    shares = np.divide(matrix, totals[:, None], out=np.zeros_like(matrix), where=totals[:, None] > 0) * 100

    fig, ax = new_figure(figsize=(7.35, 4.55))
    positive = matrix[matrix > 0]
    norm = LogNorm(vmin=max(positive.min(), 1e-3), vmax=positive.max())
    cmap = plt.get_cmap("YlGnBu")
    for i in range(len(VARIANTS)):
        for j in range(len(STAGES)):
            value = matrix[i, j]
            color = "#F1F3F4" if value == 0 else cmap(norm(value))
            ax.add_patch(Rectangle((j, i), 1, 1, facecolor=color, edgecolor="white", linewidth=1.1))
    ax.set_xticks(np.arange(len(STAGES)) + 0.5, [s.title() for s in STAGES])
    ax.set_yticks(np.arange(len(VARIANTS)) + 0.5, [short_variant(v) for v in VARIANTS])
    ax.invert_yaxis()
    ax.set_title("Stage latency by ablation variant")
    ax.set_xlabel("Lifecycle stage")
    ax.set_ylabel("Configuration")
    threshold = np.sqrt(positive.min() * positive.max())
    for i in range(len(VARIANTS)):
        for j in range(len(STAGES)):
            value = matrix[i, j]
            text = "—" if value == 0 else f"{value:.1f} ms\n{shares[i, j]:.0f}%"
            color = "white" if value >= threshold else COLORS["dark"]
            ax.text(j + 0.5, i + 0.5, text, ha="center", va="center", fontsize=6.9, color=color)
    ax.text(0.995, 1.02, f"color = mean latency (log); {positive.min():.1f}–{positive.max():.0f} ms",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=6.8, color=COLORS["gray"])
    ax.text(0.995, -0.17, "Cell text: absolute latency / share of configuration total",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    save_pdf(fig, "fig1b_stage_latency_heatmap.pdf")


def panel_c(gas_rows, summary) -> None:
    summaries = indexed(summary, "variant")
    lookup = {(r["variant"], r["stage"]): float(r["mean_gas"]) for r in gas_rows}
    x = np.arange(len(VARIANTS))
    fig, ax = new_figure(figsize=(7.25, 4.65))
    bottom = np.zeros(len(VARIANTS))
    for stage in ["access", "budget", "proof", "settlement", "audit"]:
        vals = np.array([lookup[(v, stage)] for v in VARIANTS])
        ax.bar(x, vals, bottom=bottom, width=0.68, color=STAGE_COLORS[stage],
               edgecolor="white", label=stage.title())
        bottom += vals
    for i, total in enumerate(bottom):
        ax.text(i, total + max(bottom) * 0.025, human_number(total), ha="center", fontsize=7.0)
    ax.set_ylabel("Mean gas per request")
    ax.set_xticks(x, [short_variant(v) for v in VARIANTS], rotation=18, ha="right")
    ax.set_title("On-chain gas attribution")
    ax.set_ylim(0, max(bottom) * 1.22)
    ax.legend(loc="upper left", ncol=3)

    ax2 = ax.twinx()
    baseline = bottom[VARIANTS.index("access_only")]
    ratios = np.divide(bottom, baseline, out=np.zeros_like(bottom), where=baseline > 0)
    ax2.scatter(x, ratios, marker="D", s=30, facecolors="white", edgecolors=COLORS["dark"], zorder=5)
    ax2.set_ylabel("Gas relative to access-only", color=COLORS["dark"])
    ax2.set_ylim(0, max(ratios) * 1.25)
    ax2.spines["right"].set_visible(True)
    for i, ratio in enumerate(ratios):
        if ratio > 0:
            ax2.annotate(f"{ratio:.2f}×", (i, ratio), xytext=(4, -10), textcoords="offset points", fontsize=6.7)
    ax.text(0.995, 0.02, "No-TEE values are model-calibrated; all others are measured",
            transform=ax.transAxes, ha="right", fontsize=6.7, color=COLORS["gray"])
    finish_axis(ax)
    save_pdf(fig, "fig1c_gas_attribution.pdf")


def panel_d(stage_rows, summary) -> None:
    summaries = indexed(summary, "variant")
    active = {
        v: sum(float(r["mean_latency_ms"]) > 0.01 for r in stage_rows if r["variant"] == v)
        for v in VARIANTS
    }
    latency = np.array([float(summaries[v]["p50_latency_ms"]) for v in VARIANTS])
    throughput = np.array([float(summaries[v]["p50_throughput_req_s"]) for v in VARIANTS])
    gas = np.array([float(summaries[v]["mean_total_gas"]) for v in VARIANTS])
    controls = np.array([active[v] for v in VARIANTS], dtype=float)
    sizes = area_sizes(gas, 80, 620)

    fig, ax = new_figure(figsize=(7.15, 4.75))
    measured = np.array([summaries[v]["measurement_type"] == "measured" for v in VARIANTS])
    color_scale = plt.get_cmap("viridis")((controls - controls.min()) / max(np.ptp(controls), 1))
    for flag, marker, label in [(True, "o", "measured"), (False, "^", "model-calibrated")]:
        idx = np.where(measured == flag)[0]
        if len(idx):
            ax.scatter(latency[idx], throughput[idx], s=sizes[idx], c=color_scale[idx],
                       marker=marker, alpha=0.82,
                       edgecolor=COLORS["dark"], linewidth=0.8, label=label)
    label_offsets = {
        "baseline_minimal": (8, -16), "access_only": (8, 8), "no_budget": (10, 18),
        "no_zk": (10, 12), "no_tee": (-48, 12), "full_trustcircuit": (10, -35),
    }
    for i, variant in enumerate(VARIANTS):
        offset = label_offsets[variant]
        ax.annotate(short_variant(variant), (latency[i], throughput[i]), xytext=offset,
                    textcoords="offset points", fontsize=7.2)
    full = VARIANTS.index("full_trustcircuit")
    ax.scatter(latency[full], throughput[full], s=sizes[full] * 1.22, facecolors="none",
               edgecolors=COLORS["red"], linewidths=1.7, zorder=5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("p50 end-to-end latency (ms)")
    ax.set_ylabel("p50 throughput (requests/s)")
    ax.set_title("Cost–guarantee design space")
    ax.text(0.98, 0.98, f"color: active stages {int(controls.min())}–{int(controls.max())}",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.8, color=COLORS["gray"])
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], label="measured"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["gray"], label="model-calibrated"),
    ], loc="upper right")
    ax.text(0.995, 0.02, "Bubble area ∝ mean gas; red ring = full TrustCircuit",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig1d_cost_guarantee_frontier.pdf")


def generate() -> list[str]:
    trials, summary, stage, gas = _sources()
    panel_a(trials, summary)
    panel_b(stage, summary)
    panel_c(gas, summary)
    panel_d(stage, summary)
    return [
        "fig1a_ablation_performance.pdf", "fig1b_stage_latency_heatmap.pdf",
        "fig1c_gas_attribution.pdf", "fig1d_cost_guarantee_frontier.pdf",
    ]


if __name__ == "__main__":
    generate()
