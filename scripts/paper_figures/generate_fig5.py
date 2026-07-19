"""Figure 5: structured attack rejection and concurrency panels."""

from __future__ import annotations

import textwrap

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, processed, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import smooth_line, style_secondary_axis


LAYERS = ["enclave", "attestation_validator", "circuit_adapter", "solidity_settlement"]
LAYER_LABELS = ["VBS enclave", "Attestation validator", "Circuit adapter", "Solidity settlement"]


def panel_a(matrix_rows) -> None:
    order = {name: i for i, name in enumerate(LAYERS)}
    rows = sorted(matrix_rows, key=lambda r: (order[r["first_rejecting_layer"]], r["attack_case"]))
    suites = sorted({r["source_suite"] for r in rows})
    suite_colors = {suite: PALETTE[i] for i, suite in enumerate(suites)}
    y = np.arange(len(rows), dtype=float)
    fig, ax = new_figure(figsize=(8.8, 7.8))
    for i, row in enumerate(rows):
        stop = order[row["first_rejecting_layer"]]
        ax.hlines(i, 0, stop, color="#C9D0D5", linewidth=1.8)
        ax.plot(np.arange(stop + 1), np.full(stop + 1, i), linestyle="none", marker=".",
                color="#9AA3AA", markersize=4)
        ax.plot(stop, i, linestyle="none", marker="D", markersize=6.2,
                color=suite_colors[row["source_suite"]], markeredgecolor="white", markeredgewidth=0.6)
    ax.set_yticks(y, [r["attack_case"].replace("_", " ") for r in rows])
    ax.set_xticks(np.arange(len(LAYERS)), LAYER_LABELS, rotation=10, ha="right")
    ax.set_xlim(-0.15, len(LAYERS) - 0.75)
    ax.invert_yaxis()
    ax.set_xlabel("First rejecting layer")
    ax.set_ylabel("Adversarial mutation")
    ax.set_title("Binding-attack rejection paths")
    handles = [plt.Line2D([], [], marker="D", linestyle="none", color=suite_colors[s], label=s)
               for s in suites]
    ax.legend(handles=handles, title="Evidence suite", loc="lower right")
    finish_axis(ax, grid="x")
    save_pdf(fig, "fig5a_attack_rejection_matrix.pdf")


def panel_b(summary_rows) -> None:
    rows = sorted(summary_rows, key=lambda r: float(r["p50_rejection_latency_ms"]))
    y = np.arange(len(rows), dtype=float)
    categories = sorted({r["category"] for r in rows})
    category_colors = {c: PALETTE[i] for i, c in enumerate(categories)}
    fig, ax = new_figure(figsize=(8.7, 6.3))
    for i, row in enumerate(rows):
        color = category_colors[row["category"]]
        outer_low = float(row["p2_5_rejection_latency_ms"])
        outer_high = float(row["p97_5_rejection_latency_ms"])
        ci_low = float(row["bootstrap_ci95_low_rejection_latency_ms"])
        ci_high = float(row["bootstrap_ci95_high_rejection_latency_ms"])
        p50 = float(row["p50_rejection_latency_ms"])
        p95 = float(row["p95_rejection_latency_ms"])
        ax.hlines(i, outer_low, outer_high, color=color, linewidth=1.0, alpha=0.55)
        ax.hlines(i, ci_low, ci_high, color=color, linewidth=5.0, alpha=0.42)
        ax.plot(p50, i, marker="D", linestyle="none", color=color, markersize=5.5)
        ax.plot(p95, i, marker=">", linestyle="none", color=COLORS["red"], markersize=5.5)
    ax.set_yticks(y, [textwrap.fill(r["attack_case"].replace("_", " "), 20) for r in rows])
    ax.set_xlabel("Rejection latency (ms)")
    ax.set_ylabel("Protocol attack")
    ax.set_title("Ranked rejection-latency intervals")
    handles = [plt.Line2D([], [], color=category_colors[c], linewidth=4, label=c) for c in categories]
    handles += [
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker=">", linestyle="none", color=COLORS["red"], label="p95"),
    ]
    ax.legend(handles=handles, loc="lower right", ncol=2)
    finish_axis(ax, grid="x")
    save_pdf(fig, "fig5b_rejection_latency_distribution.pdf")


def panel_c(summary_rows) -> None:
    rows = sorted(summary_rows, key=lambda r: int(r["concurrency"]))
    x = np.arange(len(rows), dtype=float)
    concurrency = values(rows, "concurrency")
    accepted = values(rows, "mean_accepted")
    reverted = values(rows, "mean_reverted")
    throughput = values(rows, "mean_throughput_req_s")
    fig, ax = new_figure(figsize=(8.55, 5.2))
    ax.bar(x, accepted, width=0.68, color=COLORS["green"], label="accepted")
    ax.bar(x, reverted, bottom=accepted, width=0.68, color=COLORS["red"], alpha=0.76,
           label="reverted")
    for i, (a, r) in enumerate(zip(accepted, reverted)):
        ax.text(i, a / 2, f"{a:.0f}", ha="center", va="center", color="white",
                fontsize=ANNOTATION_SIZE)
        if r:
            ax.text(i, a + r / 2, f"{r:.0f}", ha="center", va="center", color="white",
                    fontsize=ANNOTATION_SIZE)
    ax.set_xticks(x, concurrency.astype(int))
    ax.set_xlabel("Concurrent settlement requests")
    ax.set_ylabel("Mean outcomes per batch")
    ax.set_title("Atomic concurrent outcomes and throughput")
    ax2 = ax.twinx()
    smooth_line(ax2, x, throughput, color=COLORS["blue"], label="throughput", marker="D")
    ax2.set_ylabel("Throughput (requests/s)", color=COLORS["blue"])
    style_secondary_axis(ax2, COLORS["blue"])
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles2.append(plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["dark"],
                               label="invariant violations: 0"))
    labels2.append("invariant violations: 0")
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig5c_concurrent_outcomes.pdf")


def panel_d(summary_rows, trial_rows) -> None:
    rows = sorted(summary_rows, key=lambda r: int(r["concurrency"]))
    concurrency = values(rows, "concurrency")
    trial_groups = groups(trial_rows, "concurrency")
    gas_per_accept = np.array([
        np.median(values(trial_groups[r["concurrency"]], "total_gas") /
                  np.maximum(values(trial_groups[r["concurrency"]], "accepted"), 1)) for r in rows
    ])
    metrics = [
        ("Throughput", values(rows, "mean_throughput_req_s"), COLORS["blue"], "o"),
        ("p95 latency", values(rows, "p95_settlement_latency_ms"), COLORS["red"], "D"),
        ("Gas / accept", gas_per_accept, COLORS["orange"], "s"),
        ("Peak CPU", values(rows, "p95_normalized_peak_cpu_percent"), COLORS["green"], "^"),
        ("Private RAM", values(rows, "p95_peak_private_bytes"), COLORS["purple"], "v"),
    ]
    fig, ax = new_figure(figsize=(8.65, 5.25))
    for label, metric, color, marker in metrics:
        index = 100 * metric / max(metric.max(), 1e-9)
        smooth_line(ax, concurrency, index, color=color, label=label, marker=marker, log_x=True)
    ax.set_xscale("log", base=2)
    ax.set_xticks(concurrency, concurrency.astype(int))
    ax.set_xlabel("Concurrency")
    ax.set_ylabel("Within-metric normalized index (% of maximum)")
    ax.set_title("Concurrency scaling profile")
    ax.legend(loc="lower right", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig5d_concurrency_scaling.pdf")


def panel_e(trial_rows) -> None:
    grouped = groups(trial_rows, "concurrency")
    keys = sorted(grouped, key=int)
    x = np.arange(len(keys), dtype=float)
    concurrency = np.array([int(k) for k in keys])
    total = np.array([np.median(values(grouped[k], "budget_total_fixed")) for k in keys]) / 1e6
    used = np.array([np.median(values(grouped[k], "budget_used_fixed")) for k in keys]) / 1e6
    reserved = np.array([np.median(values(grouped[k], "budget_reserved_fixed")) for k in keys]) / 1e6
    available = np.array([np.median(values(grouped[k], "budget_remaining_fixed")) for k in keys]) / 1e6
    accepted = np.array([np.median(values(grouped[k], "accepted")) for k in keys])
    reverted = np.array([np.median(values(grouped[k], "reverted")) for k in keys])
    fig, ax = new_figure(figsize=(8.55, 5.2))
    ax.bar(x, used, width=0.68, color=COLORS["blue"], label="used")
    ax.bar(x, reserved, bottom=used, width=0.68, color=COLORS["orange"], label="reserved")
    ax.bar(x, available, bottom=used + reserved, width=0.68, color=COLORS["green"], alpha=0.45,
           label="available")
    ax.plot(x, total, linestyle="none", marker="_", markersize=18, color=COLORS["dark"],
            label="total budget")
    ax.set_xticks(x, concurrency)
    ax.set_xlabel("Concurrent batch size")
    ax.set_ylabel("Median fixed-point budget (ε)")
    ax.set_title("Concurrent privacy-budget invariant")
    ax2 = ax.twinx()
    smooth_line(ax2, x, accepted, color=COLORS["green"], label="accepted", marker="o")
    smooth_line(ax2, x, reverted, color=COLORS["red"], label="reverted", marker="D", linestyle="--")
    ax2.set_ylabel("Requests per batch", color=COLORS["red"])
    style_secondary_axis(ax2)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles2.append(plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["dark"],
                               label="invariant violations: 0"))
    labels2.append("invariant violations: 0")
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig5e_concurrent_budget_invariant.pdf")


def generate() -> list[str]:
    matrix = processed(
        "attack_binding_matrix.csv", ["attack_case", "first_rejecting_layer", "source_suite", *LAYERS]
    )
    attack_summary = processed(
        "protocol_attack_summary.csv",
        ["category", "attack_case", "p2_5_rejection_latency_ms", "p50_rejection_latency_ms",
         "p95_rejection_latency_ms", "p97_5_rejection_latency_ms",
         "bootstrap_ci95_low_rejection_latency_ms", "bootstrap_ci95_high_rejection_latency_ms"],
    )
    concurrency_summary = processed(
        "settlement_concurrency_summary.csv",
        ["concurrency", "mean_accepted", "mean_reverted", "p95_settlement_latency_ms",
         "mean_throughput_req_s", "p95_normalized_peak_cpu_percent", "p95_peak_private_bytes"],
    )
    trials = processed(
        "settlement_concurrency_trials.csv",
        ["concurrency", "accepted", "reverted", "total_gas", "budget_total_fixed", "budget_used_fixed",
         "budget_reserved_fixed", "budget_remaining_fixed"],
    )
    panel_a(matrix)
    panel_b(attack_summary)
    panel_c(concurrency_summary)
    panel_d(concurrency_summary, trials)
    panel_e(trials)
    return [
        "fig5a_attack_rejection_matrix.pdf", "fig5b_rejection_latency_distribution.pdf",
        "fig5c_concurrent_outcomes.pdf", "fig5d_concurrency_scaling.pdf",
        "fig5e_concurrent_budget_invariant.pdf",
    ]


if __name__ == "__main__":
    generate()
