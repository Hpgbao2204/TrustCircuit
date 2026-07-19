"""Figure 1: dense end-to-end ablation and cost comparisons."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import indexed, processed
from .figure_style import (
    ANNOTATION_SIZE,
    COLORS,
    PALETTE,
    STAGE_COLORS,
    finish_axis,
    human_number,
    new_figure,
    save_pdf,
    short_variant,
)
from .plot_helpers import annotate_bar_values, smooth_line, style_secondary_axis


VARIANTS = ["baseline_minimal", "access_only", "no_zk", "no_tee", "no_budget", "full_trustcircuit"]
STAGES = ["access", "budget", "tee", "proof", "settlement", "audit"]


def _sources():
    summary = processed(
        "e2e_ablation_summary.csv",
        ["variant", "p50_latency_ms", "p95_latency_ms", "p50_throughput_req_s", "mean_total_gas",
         "success_rate", "measurement_type"],
    )
    stages = processed(
        "e2e_stage_by_variant.csv", ["variant", "stage", "mean_latency_ms", "p95_latency_ms"]
    )
    gas = processed("e2e_gas_by_variant.csv", ["variant", "stage", "mean_gas"])
    return summary, stages, gas


def panel_a(summary) -> None:
    rows = indexed(summary, "variant")
    x = np.arange(len(VARIANTS), dtype=float)
    p50 = np.array([float(rows[v]["p50_latency_ms"]) for v in VARIANTS])
    p95 = np.array([float(rows[v]["p95_latency_ms"]) for v in VARIANTS])
    throughput = np.array([float(rows[v]["p50_throughput_req_s"]) for v in VARIANTS])
    success = np.array([100 * float(rows[v]["success_rate"]) for v in VARIANTS])

    fig, ax = new_figure(figsize=(8.8, 5.4))
    width = 0.35
    b50 = ax.bar(x - width / 2, p50, width, color=COLORS["blue"], label="latency p50")
    b95 = ax.bar(x + width / 2, p95, width, color=COLORS["cyan"], alpha=0.72, label="latency p95")
    ax.set_yscale("log")
    ax.set_ylabel("End-to-end latency (ms, log scale)")
    ax.set_xticks(x, [short_variant(v) for v in VARIANTS], rotation=15, ha="right")
    ax.set_xlabel("Configuration ordered by lifecycle depth")
    ax.set_title("Ablation latency, throughput, and success")

    ax2 = ax.twinx()
    smooth_line(ax2, x, throughput, color=COLORS["red"], label="throughput p50", marker="D")
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
    save_pdf(fig, "fig1a_ablation_overview.pdf")


def panel_b(stage_rows) -> None:
    lookup = {(r["variant"], r["stage"]): r for r in stage_rows}
    x = np.arange(len(VARIANTS), dtype=float)
    fig, ax = new_figure(figsize=(8.7, 5.25))
    means = np.vstack([
        [float(lookup[(variant, stage)]["mean_latency_ms"]) for variant in VARIANTS]
        for stage in STAGES
    ])
    colors = [STAGE_COLORS[stage] for stage in STAGES]
    ax.stackplot(x, *means, colors=colors, alpha=0.90,
                 labels=[stage.title() for stage in STAGES])
    cumulative = np.cumsum(means, axis=0)
    for boundary, color in zip(cumulative, colors):
        ax.plot(x, boundary, linestyle="none", marker="o", color=color,
                markeredgecolor="white", markeredgewidth=0.8, markersize=5.8)
    p95_total = np.array([
        sum(float(lookup[(v, stage)]["p95_latency_ms"]) for stage in STAGES) for v in VARIANTS
    ])
    smooth_line(ax, x, p95_total, color=COLORS["dark"], label="sum of stage p95", marker="D",
                linestyle="--")
    for xpos, total in zip(x, p95_total):
        if total > 1:
            ax.annotate(f"{total:.0f}", (xpos, total), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=ANNOTATION_SIZE)
    ax.set_xticks(x, [short_variant(v) for v in VARIANTS], rotation=15, ha="right")
    ax.set_xlabel("Configuration ordered by lifecycle depth")
    ax.set_ylabel("Stage latency (ms)")
    ax.set_title("Ablation latency composition across lifecycle depth")
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(0, max(p95_total) * 1.14)
    ax.legend(loc="upper left", ncol=4)
    finish_axis(ax)
    save_pdf(fig, "fig1b_stage_latency_composition.pdf")


def panel_c(gas_rows) -> None:
    lookup = {(r["variant"], r["stage"]): float(r["mean_gas"]) for r in gas_rows}
    x = np.arange(len(VARIANTS), dtype=float)
    fig, ax = new_figure(figsize=(8.7, 5.25))
    bottom = np.zeros(len(VARIANTS))
    for stage in ["access", "budget", "proof", "settlement", "audit"]:
        stage_values = np.array([lookup[(v, stage)] for v in VARIANTS])
        ax.bar(x, stage_values, bottom=bottom, width=0.68, color=STAGE_COLORS[stage],
               edgecolor="white", linewidth=0.5, label=stage.title())
        bottom += stage_values
    for i, total in enumerate(bottom):
        if total > 0:
            ax.annotate(human_number(total), (i, total), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=ANNOTATION_SIZE)
    ax.set_ylabel("Mean gas per request")
    ax.set_xticks(x, [short_variant(v) for v in VARIANTS], rotation=15, ha="right")
    ax.set_xlabel("Configuration ordered by lifecycle depth")
    ax.set_title("On-chain gas attribution")
    ax.set_ylim(0, max(bottom) * 1.2)
    ax2 = ax.twinx()
    baseline = bottom[VARIANTS.index("access_only")]
    ratios = np.divide(bottom, baseline, out=np.zeros_like(bottom), where=baseline > 0)
    smooth_line(ax2, x, ratios, color=COLORS["dark"], label="relative gas", marker="D")
    ax2.set_ylabel("Gas relative to access-only (×)", color=COLORS["dark"])
    style_secondary_axis(ax2, COLORS["dark"])
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig1c_gas_attribution.pdf")


def _log_index(data: np.ndarray) -> np.ndarray:
    logged = np.log10(np.maximum(data, 1e-6))
    span = np.ptp(logged)
    return np.zeros_like(logged) if span == 0 else 100 * (logged - logged.min()) / span


def panel_d(summary, stage_rows) -> None:
    rows = indexed(summary, "variant")
    latency = np.array([float(rows[v]["p50_latency_ms"]) for v in VARIANTS])
    throughput = np.array([float(rows[v]["p50_throughput_req_s"]) for v in VARIANTS])
    gas = np.array([float(rows[v]["mean_total_gas"]) for v in VARIANTS])
    active = np.array([
        sum(float(r["mean_latency_ms"]) > 0.01 for r in stage_rows if r["variant"] == v)
        for v in VARIANTS
    ], dtype=float)
    profiles = np.vstack([
        _log_index(latency), _log_index(throughput), 100 * gas / max(gas.max(), 1),
        100 * active / max(active.max(), 1),
    ])
    metric_labels = ["Latency cost", "Throughput", "Gas cost", "Active stages"]
    colors = [COLORS["blue"], COLORS["green"], COLORS["orange"], COLORS["purple"]]
    y = np.arange(len(VARIANTS), dtype=float)
    height = 0.18
    fig, ax = new_figure(figsize=(8.6, 5.35))
    for j, (metric, color) in enumerate(zip(metric_labels, colors)):
        ax.barh(y + (j - 1.5) * height, profiles[j], height, color=color, label=metric)
    ax.set_yticks(y, [short_variant(v) for v in VARIANTS])
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    ax.set_xlabel("Within-metric normalized index (0–100)")
    ax.set_ylabel("Configuration")
    ax.set_title("Ranked ablation metric profile")
    ax.legend(loc="lower right", ncol=2)
    finish_axis(ax, grid="x")
    save_pdf(fig, "fig1d_ablation_metric_profile.pdf")


def generate() -> list[str]:
    summary, stages, gas = _sources()
    panel_a(summary)
    panel_b(stages)
    panel_c(gas)
    panel_d(summary, stages)
    return [
        "fig1a_ablation_overview.pdf", "fig1b_stage_latency_composition.pdf",
        "fig1c_gas_attribution.pdf", "fig1d_ablation_metric_profile.pdf",
    ]


if __name__ == "__main__":
    generate()
