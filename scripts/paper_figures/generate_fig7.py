"""Supplementary security, budget, and concurrency panels."""

from __future__ import annotations

from collections import Counter

import numpy as np

from .data_loading import groups, processed, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import annotate_bar_values, smooth_line, style_secondary_axis


LAYER_LABELS = {
    "enclave": "Enclave",
    "attestation_validator": "Attestation",
    "circuit_adapter": "VCP adapter",
    "solidity_settlement": "Settlement",
}


def panel_a():
    rows = processed(
        "attack_binding_matrix.csv",
        ("first_rejecting_layer", "source_suite", "test_passed"),
    )
    layers = [key for key in LAYER_LABELS if any(r["first_rejecting_layer"] == key for r in rows)]
    suites = sorted({r["source_suite"] for r in rows})
    counts = Counter((r["first_rejecting_layer"], r["source_suite"]) for r in rows if r["test_passed"] == "1")

    fig, ax = new_figure(figsize=(8.4, 5.1))
    x = np.arange(len(layers))
    bottom = np.zeros(len(layers))
    for index, suite in enumerate(suites):
        data = np.asarray([counts[(layer, suite)] for layer in layers], dtype=float)
        bars = ax.bar(x, data, bottom=bottom, color=PALETTE[index], label=suite.title())
        for bar, value, base in zip(bars, data, bottom):
            if value:
                ax.text(bar.get_x() + bar.get_width() / 2, base + value / 2, f"{int(value)}",
                        ha="center", va="center", color="white", fontsize=ANNOTATION_SIZE)
        bottom += data
    ax.set_title("Binding attacks are rejected at distinct trust layers")
    ax.set_ylabel("Passing rejection tests")
    ax.set_xticks(x, [LAYER_LABELS[layer] for layer in layers])
    ax.set_ylim(0, max(bottom) * 1.2)
    ax.legend(title="Evidence suite", ncols=min(4, len(suites)), loc="upper right")
    finish_axis(ax)
    return save_pdf(fig, "fig7a_rejection_layer_coverage.pdf")


def panel_b():
    rows = processed(
        "protocol_attack_latency.csv",
        ("category", "latency_ms", "rejected", "is_warmup"),
    )
    measured = [r for r in rows if r["is_warmup"] == "0"]
    by_category = groups(measured, "category")
    categories = sorted(by_category)
    p50 = np.asarray([np.percentile(values(by_category[c], "latency_ms"), 50) for c in categories])
    p95 = np.asarray([np.percentile(values(by_category[c], "latency_ms"), 95) for c in categories])
    rejected = np.asarray([100 * np.mean(values(by_category[c], "rejected")) for c in categories])

    fig, ax = new_figure(figsize=(8.4, 5.1))
    x = np.arange(len(categories))
    width = 0.34
    left = ax.bar(x - width / 2, p50, width, color=COLORS["blue"], label="p50 latency")
    right = ax.bar(x + width / 2, p95, width, color=COLORS["orange"], label="p95 latency")
    annotate_bar_values(ax, left, p50, "{:.0f}")
    annotate_bar_values(ax, right, p95, "{:.0f}")
    ax.set_title("Attack rejection latency remains consistent across categories")
    ax.set_ylabel("Rejection latency (ms)")
    ax.set_xticks(x, [c.replace("_", " ").title() for c in categories])
    ax.set_ylim(0, max(p95) * 1.25)

    ax2 = ax.twinx()
    ax2.plot(x, rejected, color=COLORS["red"], marker="D", linestyle="none", label="Rejected")
    ax2.set_ylabel("Rejected attacks (%)", color=COLORS["red"])
    ax2.set_ylim(0, 112)
    style_secondary_axis(ax2)
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, ncols=3, loc="upper right")
    finish_axis(ax)
    return save_pdf(fig, "fig7b_attack_category_latency.pdf")


def panel_c():
    rows = processed(
        "budget_exhaustion_summary.csv",
        ("epsilon_requested", "privacy_cost_fixed", "accepted_requests", "reverted_requests"),
    )
    rows.sort(key=lambda row: float(row["epsilon_requested"]))
    epsilon = values(rows, "epsilon_requested")
    accepted = values(rows, "accepted_requests")
    reverted = values(rows, "reverted_requests")
    cost = values(rows, "privacy_cost_fixed") / 1_000_000

    fig, ax = new_figure(figsize=(8.3, 5.1))
    x = np.arange(len(rows))
    bars_a = ax.bar(x, accepted, color=COLORS["green"], label="Accepted")
    ax.bar(x, reverted, bottom=accepted, color=COLORS["red"], label="Reverted")
    for bar, value in zip(bars_a, accepted):
        ax.text(bar.get_x() + bar.get_width() / 2, value / 2, f"{int(value)}",
                ha="center", va="center", color="white", fontsize=ANNOTATION_SIZE)
    ax.set_title("Higher requested privacy cost exhausts the fixed budget sooner")
    ax.set_xlabel("Requested epsilon")
    ax.set_ylabel("Requests")
    ax.set_xticks(x, [f"{v:g}" for v in epsilon])
    ax.set_ylim(0, max(accepted + reverted) * 1.18)

    ax2 = ax.twinx()
    smooth_line(ax2, x, cost, color=COLORS["purple"], label="Fixed privacy cost", marker="D")
    ax2.set_ylabel("Privacy cost (fixed-point millions)", color=COLORS["purple"])
    style_secondary_axis(ax2, COLORS["purple"])
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, ncols=3, loc="upper left")
    finish_axis(ax)
    return save_pdf(fig, "fig7c_budget_exhaustion_by_epsilon.pdf")


def panel_d():
    rows = processed(
        "settlement_concurrency_summary.csv",
        ("concurrency", "p50_settlement_latency_ms", "p95_settlement_latency_ms", "mean_throughput_req_s"),
    )
    rows.sort(key=lambda row: float(row["concurrency"]))
    concurrency = values(rows, "concurrency")
    p50 = values(rows, "p50_settlement_latency_ms")
    p95 = values(rows, "p95_settlement_latency_ms")
    throughput = values(rows, "mean_throughput_req_s")

    fig, ax = new_figure(figsize=(8.4, 5.1))
    x = np.arange(len(rows))
    width = 0.34
    bars_1 = ax.bar(x - width / 2, p50, width, color=COLORS["blue"], label="p50 latency")
    bars_2 = ax.bar(x + width / 2, p95, width, color=COLORS["orange"], label="p95 latency")
    annotate_bar_values(ax, bars_1, p50, "{:.2f}")
    annotate_bar_values(ax, bars_2, p95, "{:.2f}")
    ax.set_title("Settlement latency and throughput across concurrent requests")
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Settlement latency (ms)")
    ax.set_xticks(x, [f"{int(v)}" for v in concurrency])
    ax.set_ylim(0, max(p95) * 1.28)

    ax2 = ax.twinx()
    smooth_line(ax2, x, throughput, color=COLORS["red"], label="Mean throughput", marker="D")
    ax2.set_ylabel("Throughput (requests/s)", color=COLORS["red"])
    style_secondary_axis(ax2)
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, ncols=3, loc="lower right")
    finish_axis(ax)
    return save_pdf(fig, "fig7d_concurrency_latency_throughput.pdf")


def generate():
    return [panel_a(), panel_b(), panel_c(), panel_d()]
