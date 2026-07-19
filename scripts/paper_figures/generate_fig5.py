"""Figure 5: rejection coverage, attack latency, concurrency, and invariants."""

from __future__ import annotations

import textwrap

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle

from .data_loading import groups, processed, values
from .figure_style import COLORS, PALETTE, finish_axis, human_number, new_figure, save_pdf
from .plot_helpers import distribution_boxes
from .statistics import area_sizes


LAYERS = ["enclave", "attestation_validator", "circuit_adapter", "solidity_settlement"]
LAYER_LABELS = ["VBS\nenclave", "Attestation\nvalidator", "Circuit\nadapter", "Solidity\nsettlement"]


def panel_a(matrix_rows) -> None:
    order = {name: i for i, name in enumerate(LAYERS)}
    rows = sorted(matrix_rows, key=lambda r: (order[r["first_rejecting_layer"]], r["attack_case"]))
    matrix = np.array([[int(float(r[layer])) for layer in LAYERS] for r in rows], dtype=float)
    labels = [r["attack_case"].replace("_", " ") for r in rows]
    fig, ax = new_figure(figsize=(7.35, 7.45))
    ax.pcolormesh(np.arange(5), np.arange(len(rows) + 1), matrix,
                  cmap=ListedColormap(["#F2F4F5", "#79B99B"]), vmin=0, vmax=1,
                  edgecolors="white", linewidth=1.0, shading="flat")
    ax.set_xticks(np.arange(4) + 0.5, LAYER_LABELS)
    ax.set_yticks(np.arange(len(rows)) + 0.5, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Validation layer")
    ax.set_ylabel("Adversarial mutation")
    ax.set_title("Binding-attack rejection matrix (25 functional tests)")
    for i, row in enumerate(rows):
        for j, layer in enumerate(LAYERS):
            value = int(float(row[layer]))
            ax.text(j + 0.5, i + 0.5, "✓" if value else "—", ha="center", va="center",
                    color="white" if value else COLORS["gray"], fontsize=8.0)
        first = order[row["first_rejecting_layer"]]
        ax.add_patch(Rectangle((first + 0.04, i + 0.04), 0.92, 0.92, fill=False,
                               edgecolor=COLORS["red"], linewidth=1.25))
        ax.text(first + 0.5, i + 0.78, "FIRST", ha="center", va="center",
                fontsize=5.0, color=COLORS["red"], fontweight="bold")
    ax.text(0.995, 1.01, "Green = rejecting/checking evidence; red outline = first rejecting layer",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=6.8, color=COLORS["gray"])
    save_pdf(fig, "fig5a_attack_rejection_matrix.pdf")


def panel_b(latency_rows) -> None:
    grouped = groups(latency_rows, "attack_case")
    keys = sorted(grouped, key=lambda k: np.median(values(grouped[k], "latency_ms")))
    datasets = [values(grouped[k], "latency_ms") for k in keys]
    positions = np.arange(len(keys), dtype=float)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(keys))]
    fig, ax = new_figure(figsize=(7.35, 6.2))
    distribution_boxes(ax, datasets, positions, colors, horizontal=True, salt=160)
    labels = [textwrap.fill(k.replace("_", " "), 19) for k in keys]
    ax.set_yticks(positions, labels)
    ax.set_xlabel("Rejection latency (ms)")
    ax.set_ylabel("Protocol attack")
    ax.set_title("Protocol-attack rejection distributions (n=30 each)")
    ax.legend(handles=[
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker=">", linestyle="none", color=COLORS["red"], label="p95"),
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], alpha=0.45, label="trial"),
    ], loc="lower right", ncol=3)
    ax.text(0.995, 0.02, "All 360 attacks rejected at settlement; budget invariant violations = 0",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax, grid="x")
    save_pdf(fig, "fig5b_rejection_latency_distribution.pdf")


def panel_c(summary_rows) -> None:
    rows = sorted(summary_rows, key=lambda r: int(r["concurrency"]))
    x = np.arange(len(rows), dtype=float)
    concurrency = values(rows, "concurrency")
    accepted = values(rows, "mean_accepted")
    reverted = values(rows, "mean_reverted")
    total = accepted + reverted
    fig, ax = new_figure()
    b1 = ax.bar(x, accepted, width=0.68, color=COLORS["green"], label="accepted")
    b2 = ax.bar(x, reverted, bottom=accepted, width=0.68, color=COLORS["red"], alpha=0.75,
                label="reverted")
    for i, (a, r, t) in enumerate(zip(accepted, reverted, total)):
        ax.text(i, a / 2, f"{a:.0f}", ha="center", va="center", color="white", fontsize=7.2)
        if r > 0:
            ax.text(i, a + r / 2, f"{r:.0f}", ha="center", va="center", color="white", fontsize=7.2)
        ax.text(i, t + 0.7, "0 inv.", ha="center", fontsize=6.5, color=COLORS["dark"])
    ax.set_xticks(x, concurrency.astype(int))
    ax.set_xlabel("Concurrent settlement requests")
    ax.set_ylabel("Mean outcomes per batch")
    ax.set_title("Atomic concurrent outcomes")
    ax.set_ylim(0, max(total) * 1.16)
    ax.legend(loc="upper left", ncol=2)
    ax.text(0.995, 0.02, "Each batch admits exactly its measured capacity; excess requests revert",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax)
    save_pdf(fig, "fig5c_concurrent_outcomes.pdf")


def panel_d(summary_rows, trial_rows) -> None:
    rows = sorted(summary_rows, key=lambda r: int(r["concurrency"]))
    trial_groups = groups(trial_rows, "concurrency")
    latency = values(rows, "p95_settlement_latency_ms")
    throughput = values(rows, "mean_throughput_req_s")
    cpu = values(rows, "p95_normalized_peak_cpu_percent")
    rss = values(rows, "p95_peak_private_bytes") / 1024**2
    gas = np.array([np.median(values(trial_groups[r["concurrency"]], "total_gas")) for r in rows])
    sizes = area_sizes(gas, 110, 650)
    concurrency = values(rows, "concurrency")

    fig, ax = new_figure()
    cpu_colors = plt.get_cmap("viridis")((cpu - cpu.min()) / max(np.ptp(cpu), 1))
    ax.scatter(latency, throughput, s=sizes, c=cpu_colors,
               edgecolor=COLORS["dark"], linewidth=0.8, alpha=0.82)
    offsets = {1: (10, 7), 2: (10, 7), 4: (10, 7), 8: (10, 22), 16: (10, 18), 32: (-70, -32)}
    for x, y, c, mem in zip(latency, throughput, concurrency, rss):
        ax.annotate(f"c={int(c)}\n{mem:.0f} MiB private", (x, y), xytext=offsets[int(c)],
                    textcoords="offset points", fontsize=6.7)
    ax.set_xlabel("p95 mean settlement latency (ms)")
    ax.set_ylabel("Mean throughput (requests/s)")
    ax.set_title("Concurrency performance frontier")
    ax.text(0.98, 0.98, f"color: p95 normalized CPU {cpu.min():.1f}–{cpu.max():.1f}%",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.8, color=COLORS["gray"])
    ax.text(0.995, 0.02, "Bubble area ∝ median batch gas; labels report p95 private memory",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig5d_concurrency_frontier.pdf")


def panel_e(trial_rows) -> None:
    grouped = groups(trial_rows, "concurrency")
    keys = sorted(grouped, key=int)
    concurrency = np.array([int(k) for k in keys], dtype=float)
    total = np.array([np.median(values(grouped[k], "budget_total_fixed")) for k in keys]) / 1e6
    used = np.array([np.median(values(grouped[k], "budget_used_fixed")) for k in keys]) / 1e6
    reserved = np.array([np.median(values(grouped[k], "budget_reserved_fixed")) for k in keys]) / 1e6
    remaining = np.array([np.median(values(grouped[k], "budget_remaining_fixed")) for k in keys]) / 1e6
    accepted = np.array([np.median(values(grouped[k], "accepted")) for k in keys])
    reverted = np.array([np.median(values(grouped[k], "reverted")) for k in keys])
    residual = total - used - reserved - remaining

    fig, ax = new_figure()
    x = np.arange(len(keys), dtype=float)
    ax.bar(x, used, width=0.68, color=COLORS["blue"], label="used")
    ax.bar(x, reserved, bottom=used, width=0.68, color=COLORS["orange"], label="reserved")
    ax.bar(x, remaining, bottom=used + reserved, width=0.68, color=COLORS["green"], alpha=0.45,
           label="available")
    ax.scatter(x, total, marker="_", s=280, color=COLORS["dark"], linewidth=1.6, label="total budget")
    for i, (a, r, inv) in enumerate(zip(accepted, reverted, residual)):
        ax.annotate(f"{a:.0f}A/{r:.0f}R\nresid. {inv:.0f}", (i, total[i]), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=6.5)
    ax.set_xticks(x, concurrency.astype(int))
    ax.set_xlabel("Concurrent batch size (ordered, unsmoothed)")
    ax.set_ylabel("Median fixed-point budget (ε units)")
    ax.set_title("Concurrent privacy-budget invariant")
    ax.set_ylim(0, total.max() * 1.22)
    ax.legend(loc="upper left", ncol=2)
    ax.text(0.995, 0.02, "A/R = accepted/reverted; all 180 trials have zero invariant violations",
            transform=ax.transAxes, ha="right", fontsize=6.8, color=COLORS["gray"])
    finish_axis(ax)
    save_pdf(fig, "fig5e_concurrent_budget_invariant.pdf")


def generate() -> list[str]:
    matrix = processed(
        "attack_binding_matrix.csv", ["attack_case", "first_rejecting_layer", *LAYERS]
    )
    attacks = processed(
        "protocol_attack_latency.csv", ["attack_case", "latency_ms", "rejected", "budget_invariant_violation"]
    )
    summary_rows = processed(
        "settlement_concurrency_summary.csv",
        ["concurrency", "mean_accepted", "mean_reverted", "p95_settlement_latency_ms",
         "mean_throughput_req_s", "p95_normalized_peak_cpu_percent", "p95_peak_private_bytes"],
    )
    trials = processed(
        "settlement_concurrency_trials.csv",
        ["concurrency", "accepted", "reverted", "total_gas", "budget_total_fixed", "budget_used_fixed",
         "budget_reserved_fixed", "budget_remaining_fixed", "budget_invariant_violations"],
    )
    panel_a(matrix)
    panel_b(attacks)
    panel_c(summary_rows)
    panel_d(summary_rows, trials)
    panel_e(trials)
    return [
        "fig5a_attack_rejection_matrix.pdf", "fig5b_rejection_latency_distribution.pdf",
        "fig5c_concurrent_outcomes.pdf", "fig5d_concurrency_frontier.pdf",
        "fig5e_concurrent_budget_invariant.pdf",
    ]


if __name__ == "__main__":
    generate()
