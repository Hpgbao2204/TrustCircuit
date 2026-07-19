"""Figure 4: smooth Native/VBS trends and Nitro-style composition areas."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, processed, values
from .figure_style import (
    ANNOTATION_SIZE,
    COLORS,
    STAGE_COLORS,
    finish_axis,
    payload_label,
    new_figure,
    save_pdf,
)
from .plot_helpers import annotate_bar_values, percentile_ribbon, smooth_line, style_secondary_axis
from .statistics import pchip


STAGES = ["decrypt", "aggregate", "dp_noise", "transcript", "attestation_generation"]
STAGE_LABELS = {
    "decrypt": "AES-GCM decrypt", "aggregate": "bounded aggregate", "dp_noise": "DP noise",
    "transcript": "transcript", "attestation_generation": "evidence generation",
    "host_residual": "host/process residual",
}


def _sources():
    trials = processed(
        "native_vbs_trials.csv",
        ["payload_bytes", "native_peak_rss_bytes", "vbs_peak_rss_bytes", "result_hash_match",
         "result_parity", "native_ok", "vbs_ok"],
    )
    summary = processed(
        "vbs_performance_summary.csv",
        ["payload_bytes", "native_p50_latency_ms", "native_p95_latency_ms", "vbs_p50_latency_ms",
         "vbs_p95_latency_ms", "native_latency_bootstrap_ci95_low_ms",
         "native_latency_bootstrap_ci95_high_ms", "vbs_latency_bootstrap_ci95_low_ms",
         "vbs_latency_bootstrap_ci95_high_ms", "slowdown_p50", "slowdown_p95",
         "native_throughput_p50_mib_s", "vbs_throughput_p50_mib_s", "native_rss_p50_mib",
         "vbs_rss_p50_mib", "result_parity_rate"],
    )
    stages = processed("vbs_stage_breakdown.csv", ["payload_bytes", "stage", "p50_latency_us"])
    attestation = processed(
        "vbs_attestation_overhead.csv",
        ["payload_bytes", "stage", "latency_us", "total_validated_vbs_us", "percent_of_total_vbs_latency"],
    )
    return trials, summary, stages, attestation


def panel_a(summary) -> None:
    rows = sorted(summary, key=lambda r: int(r["payload_bytes"]))
    payloads = values(rows, "payload_bytes")
    fig, ax = new_figure(figsize=(9.0, 5.55))
    for prefix, color, label in [("native", COLORS["blue"], "Native"), ("vbs", COLORS["purple"], "VBS")]:
        p50 = values(rows, f"{prefix}_p50_latency_ms")
        p95 = values(rows, f"{prefix}_p95_latency_ms")
        low = values(rows, f"{prefix}_latency_bootstrap_ci95_low_ms")
        high = values(rows, f"{prefix}_latency_bootstrap_ci95_high_ms")
        percentile_ribbon(ax, payloads, low, high, color=color, label=f"{label} 95% CI", log_x=True)
        smooth_line(ax, payloads, p50, color=color, label=f"{label} p50", marker="o", log_x=True)
        smooth_line(ax, payloads, p95, color=color, label=f"{label} p95", marker="D",
                    linestyle="--", log_x=True)
    ax.set_xscale("log", base=2)
    ax.set_xticks(payloads, [payload_label(p) for p in payloads])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Process wall latency (ms)")
    ax.set_title("Native and VBS latency trends")
    ax.legend(loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig4a_native_vbs_latency_distribution.pdf")


def panel_b(summary) -> None:
    rows = sorted(summary, key=lambda r: int(r["payload_bytes"]))
    x = np.arange(len(rows), dtype=float)
    native = values(rows, "native_throughput_p50_mib_s")
    vbs = values(rows, "vbs_throughput_p50_mib_s")
    slowdown50 = values(rows, "slowdown_p50")
    slowdown95 = values(rows, "slowdown_p95")
    width = 0.35
    fig, ax = new_figure(figsize=(8.9, 5.4))
    b1 = ax.bar(x - width / 2, native, width, color=COLORS["blue"], label="Native throughput p50")
    b2 = ax.bar(x + width / 2, vbs, width, color=COLORS["purple"], label="VBS throughput p50")
    annotate_bar_values(ax, b1, native, "{:.2g}")
    annotate_bar_values(ax, b2, vbs, "{:.2g}")
    ax.set_xticks(x, [payload_label(int(r["payload_bytes"])) for r in rows])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Payload throughput (MiB/s)")
    ax.set_title("Absolute throughput and VBS slowdown")
    ax2 = ax.twinx()
    smooth_line(ax2, x, slowdown50, color=COLORS["orange"], label="slowdown p50", marker="o")
    smooth_line(ax2, x, slowdown95, color=COLORS["red"], label="slowdown p95", marker="s",
                linestyle="--")
    ax2.set_ylabel("VBS / Native latency slowdown (×)", color=COLORS["red"])
    style_secondary_axis(ax2)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig4b_vbs_overhead_and_throughput.pdf")


def panel_c(summary, stages) -> None:
    rows = sorted(summary, key=lambda r: int(r["payload_bytes"]))
    payloads = values(rows, "payload_bytes")
    total_ms = values(rows, "vbs_p50_latency_ms")
    lookup = {(int(r["payload_bytes"]), r["stage"]): float(r["p50_latency_us"]) / 1000 for r in stages}
    measured = [np.array([lookup[(int(p), stage)] for p in payloads]) for stage in STAGES]
    residual = total_ms - np.sum(measured, axis=0)
    if np.any(residual < -1e-9):
        raise ValueError("Measured VBS stages exceed measured VBS process total")
    layers = measured + [np.maximum(residual, 0)]
    shares = np.vstack(layers)
    shares = np.divide(shares, total_ms, out=np.zeros_like(shares), where=total_ms > 0) * 100
    dense_layers = []
    dense_x = None
    for share in shares:
        dense_x, dense_share = pchip(payloads, share, log_x=True, clamp_min=0)
        dense_layers.append(dense_share)
    dense_stack = np.vstack(dense_layers)
    dense_stack = 100 * dense_stack / np.maximum(dense_stack.sum(axis=0), 1e-9)
    names = STAGES + ["host_residual"]
    colors = [STAGE_COLORS[name] for name in names]

    fig, ax = new_figure(figsize=(9.0, 5.6))
    ax.stackplot(dense_x, *dense_stack, colors=colors, alpha=0.88,
                 labels=[STAGE_LABELS[name] for name in names])
    cumulative = np.zeros_like(payloads)
    for share, color in zip(shares, colors):
        cumulative += share
        ax.plot(payloads, cumulative, linestyle="none", marker="o", markersize=3.2,
                color=color, markeredgecolor="white", markeredgewidth=0.4)
    ax.set_xscale("log", base=2)
    ax.set_xticks(payloads, [payload_label(p) for p in payloads])
    ax.set_xlim(payloads.min(), payloads.max())
    ax.set_ylim(0, 100)
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Share of p50 process latency (%)")
    ax.set_title("VBS latency composition across payload sizes")
    ax2 = ax.twinx()
    smooth_line(ax2, payloads, total_ms, color=COLORS["dark"], label="VBS process p50",
                marker="D", log_x=True, linewidth=1.5)
    ax2.set_ylabel("VBS process p50 latency (ms)", color=COLORS["dark"])
    style_secondary_axis(ax2, COLORS["dark"])
    largest = len(payloads) - 1
    ax.annotate(f"host/process {shares[-1, largest]:.0f}%", (payloads[largest], shares[-1, largest] / 2),
                xytext=(-110, -4), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": COLORS["gray"]},
                fontsize=ANNOTATION_SIZE)
    ax2.annotate("largest latency rise", (payloads[largest], total_ms[largest]), xytext=(-105, -35),
                 textcoords="offset points", arrowprops={"arrowstyle": "->", "color": COLORS["dark"]},
                 fontsize=ANNOTATION_SIZE)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig4c_vbs_latency_composition_area.pdf")


def panel_d(summary) -> None:
    rows = sorted(summary, key=lambda r: int(r["payload_bytes"]))
    x = np.arange(len(rows), dtype=float)
    native_rss = values(rows, "native_rss_p50_mib")
    vbs_rss = values(rows, "vbs_rss_p50_mib")
    native_latency = values(rows, "native_p50_latency_ms")
    vbs_latency = values(rows, "vbs_p50_latency_ms")
    width = 0.35
    fig, ax = new_figure(figsize=(8.9, 5.35))
    ax.bar(x - width / 2, native_rss, width, color=COLORS["blue"], label="Native RSS")
    ax.bar(x + width / 2, vbs_rss, width, color=COLORS["purple"], label="VBS RSS")
    ax.set_xticks(x, [payload_label(int(r["payload_bytes"])) for r in rows])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Median peak working set (MiB)")
    ax.set_title("Native/VBS memory and latency scaling")
    ax2 = ax.twinx()
    smooth_line(ax2, x, native_latency, color=COLORS["cyan"], label="Native latency p50", marker="o")
    smooth_line(ax2, x, vbs_latency, color=COLORS["red"], label="VBS latency p50", marker="D")
    ax2.set_ylabel("Process p50 latency (ms)", color=COLORS["red"])
    style_secondary_axis(ax2)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig4d_vbs_resource_scaling.pdf")


def panel_e(attestation, trials) -> None:
    payloads = sorted({int(r["payload_bytes"]) for r in attestation})
    stage_names = ["Transcript", "Evidence generation", "External validation"]
    grouped = groups(attestation, "payload_bytes")
    shares = []
    total_ms = []
    for payload in payloads:
        rows = grouped[str(payload)]
        stage_share = [np.median(values([r for r in rows if r["stage"] == stage],
                                        "percent_of_total_vbs_latency")) for stage in stage_names]
        stage_share = np.asarray(stage_share, dtype=float)
        shares.append(100 * stage_share / max(stage_share.sum(), 1e-9))
        total_ms.append(np.median(values(rows, "total_validated_vbs_us")) / 1000)
    shares = np.asarray(shares).T
    total_ms = np.asarray(total_ms)
    x = np.arange(len(payloads), dtype=float)
    colors = [COLORS["orange"], COLORS["purple"], COLORS["red"]]
    fig, ax = new_figure(figsize=(8.9, 5.35))
    bottom = np.zeros(len(payloads))
    for stage, share, color in zip(stage_names, shares, colors):
        ax.bar(x, share, bottom=bottom, width=0.7, color=color, edgecolor="white", linewidth=0.5,
               label=stage)
        bottom += share
    ax.set_xticks(x, [payload_label(p) for p in payloads])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Share of selected attestation phases (%)")
    ax.set_title("Attestation composition and validated latency")
    ax2 = ax.twinx()
    smooth_line(ax2, x, total_ms, color=COLORS["dark"], label="validated VBS p50", marker="D")
    ax2.set_ylabel("Total validated VBS latency (ms)", color=COLORS["dark"])
    style_secondary_axis(ax2, COLORS["dark"])
    parity = 100 * np.mean(values(trials, "result_parity"))
    hashes = 100 * np.mean(values(trials, "result_hash_match"))
    success = 100 * min(np.mean(values(trials, "native_ok")), np.mean(values(trials, "vbs_ok")))
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    handles2.append(plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["green"],
                               label=f"parity/hash/success {parity:.0f}/{hashes:.0f}/{success:.0f}%"))
    labels2.append(f"parity/hash/success {parity:.0f}/{hashes:.0f}/{success:.0f}%")
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig4e_vbs_attestation_and_parity.pdf")


def generate() -> list[str]:
    trials, summary, stages, attestation = _sources()
    panel_a(summary)
    panel_b(summary)
    panel_c(summary, stages)
    panel_d(summary)
    panel_e(attestation, trials)
    return [
        "fig4a_native_vbs_latency_distribution.pdf", "fig4b_vbs_overhead_and_throughput.pdf",
        "fig4c_vbs_latency_composition_area.pdf", "fig4d_vbs_resource_scaling.pdf",
        "fig4e_vbs_attestation_and_parity.pdf",
    ]


if __name__ == "__main__":
    generate()
