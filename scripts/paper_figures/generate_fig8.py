"""Supplementary controlled-comparison panels."""

from __future__ import annotations

import numpy as np

from .data_loading import groups, indexed, processed, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import annotate_bar_values, smooth_line, style_secondary_axis


ORDER = ["Access Ledger", "Local DP Ledger", "ZK Release", "TEE-only", "TrustCircuit"]
SHORT = ["Access", "Local DP", "ZK", "TEE", "Trust"]


def panel_a():
    rows = indexed(
        processed("comparison_capabilities.csv", ("configuration", "security_coverage_score")),
        "configuration",
    )
    coverage = np.asarray([float(rows[name]["security_coverage_score"]) for name in ORDER])
    total = max(float(rows[name].get("security_coverage_score", 0)) for name in ORDER)
    total = max(total, 8.0)
    missing = total - coverage

    fig, ax = new_figure(figsize=(8.2, 5.0))
    y = np.arange(len(ORDER))
    enabled = ax.barh(y, coverage, color=COLORS["green"], label="Enabled capabilities")
    ax.barh(y, missing, left=coverage, color=COLORS["light"], edgecolor="#BCC5CB", label="Not included")
    for bar, value in zip(enabled, coverage):
        ax.text(value / 2, bar.get_y() + bar.get_height() / 2, f"{int(value)}/{int(total)}",
                ha="center", va="center", color="white", fontsize=ANNOTATION_SIZE)
    ax.set_title("Security capability coverage in controlled configurations")
    ax.set_xlabel("Capability count")
    ax.set_yticks(y, SHORT)
    ax.set_xlim(0, total * 1.05)
    ax.legend(ncols=2, loc="lower right")
    finish_axis(ax, grid="x")
    return save_pdf(fig, "fig8a_capability_coverage.pdf")


def panel_b():
    rows = processed(
        "comparison_trials.csv",
        ("configuration", "normalized_peak_cpu_percent", "peak_private_bytes", "is_warmup"),
    )
    rows = [row for row in rows if row["is_warmup"] == "0"]
    by_config = groups(rows, "configuration")
    cpu = np.asarray([np.percentile(values(by_config[name], "normalized_peak_cpu_percent"), 95) for name in ORDER])
    ram = np.asarray([np.percentile(values(by_config[name], "peak_private_bytes"), 95) / 1024**3 for name in ORDER])
    cpu_index = 100 * cpu / max(cpu)
    ram_index = 100 * ram / max(ram)

    fig, ax = new_figure(figsize=(8.5, 5.25))
    y = np.arange(len(ORDER))
    lower = np.minimum(cpu_index, ram_index)
    upper = np.maximum(cpu_index, ram_index)
    ax.hlines(y, lower, upper, color="#BCC5CB", linewidth=4.5, zorder=1)
    ax.scatter(cpu_index, y, color=COLORS["orange"], marker="D", s=78,
               edgecolor="white", linewidth=0.8, label="p95 CPU", zorder=3)
    ax.scatter(ram_index, y, color=COLORS["blue"], marker="o", s=78,
               edgecolor="white", linewidth=0.8, label="p95 private RAM", zorder=3)
    for row, (cpu_value, ram_value) in enumerate(zip(cpu_index, ram_index)):
        if abs(cpu_value - ram_value) < 1:
            ax.annotate(f"both {cpu_value:.0f}", (cpu_value, row), xytext=(0, 10),
                        textcoords="offset points", ha="center", fontsize=ANNOTATION_SIZE,
                        clip_on=False)
            continue
        ax.annotate(f"{cpu_value:.0f}", (cpu_value, row), xytext=(0, 9),
                    textcoords="offset points", ha="center", fontsize=ANNOTATION_SIZE,
                    clip_on=False)
        ax.annotate(f"{ram_value:.0f}", (ram_value, row), xytext=(0, -16),
                    textcoords="offset points", ha="center", fontsize=ANNOTATION_SIZE,
                    clip_on=False)
    ax.set_title("Controlled CPU and private-memory demand")
    ax.set_xlabel("Demand normalized to each resource maximum (%)")
    ax.set_yticks(y, SHORT)
    ax.set_xlim(-4, 108)
    ax.set_ylim(len(ORDER) - 0.65, -0.65)
    ax.legend(ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    finish_axis(ax, grid="x")
    return save_pdf(fig, "fig8b_controlled_resource_profile.pdf")


def panel_c():
    rows = indexed(
        processed("comparison_summary.csv", ("configuration", "mean_total_gas", "security_coverage_score", "p95_latency_ms")),
        "configuration",
    )
    gas = np.asarray([float(rows[name]["mean_total_gas"]) / 1_000_000 for name in ORDER])
    coverage = np.asarray([float(rows[name]["security_coverage_score"]) for name in ORDER])
    latency = np.asarray([float(rows[name]["p95_latency_ms"]) for name in ORDER])

    fig, ax = new_figure(figsize=(8.4, 5.15))
    x = np.arange(len(ORDER))
    bars = ax.bar(x, gas, color=COLORS["gold"], alpha=0.9, label="Mean gas")
    annotate_bar_values(ax, bars, gas, "{:.2f}")
    ax.set_title("Cost and security coverage of controlled configurations")
    ax.set_ylabel("Mean gas (millions)")
    ax.set_xticks(x, SHORT)
    ax.set_ylim(0, max(gas) * 1.27)

    ax2 = ax.twinx()
    smooth_line(ax2, x, coverage, color=COLORS["green"], label="Coverage", marker="D")
    ax2.plot(x, latency / max(latency) * 8, color=COLORS["red"], marker="o", linestyle="--",
             label="p95 latency (indexed to 8)")
    ax2.set_ylabel("Coverage / normalized latency index", color=COLORS["green"])
    ax2.set_ylim(0, 9.4)
    style_secondary_axis(ax2, COLORS["green"])
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, ncols=3, loc="upper left")
    finish_axis(ax)
    return save_pdf(fig, "fig8c_cost_coverage_tradeoff.pdf")


def panel_d():
    rows = processed(
        "comparison_overhead.csv",
        ("configuration", "stage", "median_latency_ms"),
    )
    by_config = groups(rows, "configuration")
    stages = ["proof_overhead_ms", "attestation_overhead_ms", "budget_overhead_ms", "other_lifecycle_ms"]
    labels = ["Proof", "Attestation", "Budget", "Other lifecycle"]
    colors = [COLORS["orange"], COLORS["purple"], COLORS["green"], COLORS["gray"]]
    matrix = np.asarray([
        [float(indexed(by_config[name], "stage")[stage]["median_latency_ms"]) for stage in stages]
        for name in ORDER
    ])
    totals = matrix.sum(axis=1)
    shares = np.divide(matrix, totals[:, None], out=np.zeros_like(matrix), where=totals[:, None] > 0) * 100

    fig, ax = new_figure(figsize=(8.4, 5.15))
    x = np.arange(len(ORDER))
    bottom = np.zeros(len(ORDER))
    for column, (label, color) in enumerate(zip(labels, colors)):
        data = shares[:, column]
        ax.bar(x, data, bottom=bottom, color=color, label=label)
        bottom += data
    ax.set_title("Latency composition separates dominant controlled overheads")
    ax.set_ylabel("Share of median latency (%)")
    ax.set_xticks(x, SHORT)
    ax.set_ylim(0, 112)

    ax2 = ax.twinx()
    ax2.plot(x, totals, color=COLORS["red"], marker="D", linestyle="none", label="Median total")
    ax2.set_ylabel("Median latency (ms)", color=COLORS["red"])
    style_secondary_axis(ax2)
    handles, legend_labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, legend_labels + labels2, ncols=3, loc="upper left")
    finish_axis(ax)
    return save_pdf(fig, "fig8d_overhead_composition.pdf")


def generate():
    return [panel_a(), panel_b(), panel_c(), panel_d()]
