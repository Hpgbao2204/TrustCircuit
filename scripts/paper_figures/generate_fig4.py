"""Figure 4: paired Native/VBS performance, composition, resources, parity."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, indexed, processed, values
from .figure_style import (
    COLORS, STAGE_COLORS, finish_axis, payload_label, new_figure, save_pdf,
)
from .plot_helpers import distribution_boxes
from .statistics import area_sizes, pchip_logx


STAGES = ["decrypt", "aggregate", "dp_noise", "transcript", "attestation_generation"]
STAGE_LABELS = {
    "decrypt": "AES-GCM decrypt",
    "aggregate": "bounded aggregate",
    "dp_noise": "DP noise",
    "transcript": "transcript",
    "attestation_generation": "evidence generation",
    "host_residual": "host/process + uninstrumented residual",
}


def _sources():
    trials = processed(
        "native_vbs_trials.csv",
        ["payload_bytes", "native_process_wall_us", "vbs_process_wall_us",
         "native_process_cpu_time_ms", "vbs_process_cpu_time_ms", "native_peak_rss_bytes",
         "vbs_peak_rss_bytes", "native_payload_throughput_mib_s", "vbs_payload_throughput_mib_s",
         "result_hash_match", "result_parity", "native_ok", "vbs_ok"],
    )
    summary = processed(
        "vbs_performance_summary.csv",
        ["payload_bytes", "native_p50_latency_ms", "native_p95_latency_ms", "vbs_p50_latency_ms",
         "vbs_p95_latency_ms", "slowdown_p50", "slowdown_p95", "native_throughput_p50_mib_s",
         "vbs_throughput_p50_mib_s", "result_parity_rate"],
    )
    stages = processed(
        "vbs_stage_breakdown.csv", ["payload_bytes", "stage", "p50_latency_us", "p95_latency_us"]
    )
    attest = processed(
        "vbs_attestation_overhead.csv",
        ["payload_bytes", "stage", "latency_us", "percent_of_total_vbs_latency"],
    )
    return trials, summary, stages, attest


def panel_a(trials) -> None:
    grouped = groups(trials, "payload_bytes")
    payloads = sorted(grouped, key=int)
    base = np.arange(len(payloads), dtype=float)
    native_data = [values(grouped[p], "native_process_wall_us") / 1000 for p in payloads]
    vbs_data = [values(grouped[p], "vbs_process_wall_us") / 1000 for p in payloads]

    fig, ax = new_figure(figsize=(7.35, 4.75))
    for i, (native, vbs) in enumerate(zip(native_data, vbs_data)):
        for n, v in zip(native, vbs):
            ax.plot([base[i] - 0.18, base[i] + 0.18], [n, v], color="#B8BEC3",
                    linewidth=0.35, alpha=0.25, zorder=1)
    datasets, positions, colors = [], [], []
    for i in range(len(payloads)):
        datasets.extend([native_data[i], vbs_data[i]])
        positions.extend([base[i] - 0.18, base[i] + 0.18])
        colors.extend([COLORS["blue"], COLORS["purple"]])
    distribution_boxes(ax, datasets, positions, colors, widths=0.27, raw_alpha=0.2, salt=100)
    ax.set_xticks(base, [payload_label(int(p)) for p in payloads])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Process wall latency (ms)")
    ax.set_title("Paired Native and VBS latency distributions")
    ax.legend(handles=[
        plt.Rectangle((0, 0), 1, 1, color=COLORS["blue"], alpha=0.45, label="Native"),
        plt.Rectangle((0, 0), 1, 1, color=COLORS["purple"], alpha=0.45, label="VBS"),
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95"),
        plt.Line2D([], [], color="#B8BEC3", linewidth=0.8, label="paired trial"),
    ], loc="upper left", ncol=3)
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

    fig, ax = new_figure(figsize=(7.35, 4.75))
    b1 = ax.bar(x - width / 2, native, width, color=COLORS["blue"], label="Native p50")
    b2 = ax.bar(x + width / 2, vbs, width, color=COLORS["purple"], label="VBS p50")
    for bars, vals in [(b1, native), (b2, vbs)]:
        for bar, val in zip(bars, vals):
            ax.annotate(f"{val:.2g}", (bar.get_x() + bar.get_width() / 2, val), xytext=(0, 2),
                        textcoords="offset points", ha="center", fontsize=6.4)
    ax.set_xticks(x, [payload_label(int(r["payload_bytes"])) for r in rows])
    ax.set_xlabel("Encrypted payload")
    ax.set_ylabel("Payload throughput (MiB/s)")
    ax.set_title("Absolute throughput and VBS slowdown")

    ax2 = ax.twinx()
    ax2.plot(x, slowdown50, color=COLORS["orange"], marker="o", markerfacecolor="white",
             label="slowdown p50")
    ax2.plot(x, slowdown95, color=COLORS["red"], marker="s", markerfacecolor="white",
             linestyle="--", label="slowdown p95")
    ax2.set_ylabel("VBS / Native latency slowdown (×)", color=COLORS["red"])
    ax2.tick_params(axis="y", colors=COLORS["red"])
    ax2.spines["right"].set_visible(True)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig4b_vbs_overhead_and_throughput.pdf")


def panel_c(summary, stages) -> None:
    rows = sorted(summary, key=lambda r: int(r["payload_bytes"]))
    payloads = values(rows, "payload_bytes")
    total = values(rows, "vbs_p50_latency_ms")
    lookup = {(int(r["payload_bytes"]), r["stage"]): float(r["p50_latency_us"]) / 1000 for r in stages}
    measured_layers = [np.array([lookup[(int(p), stage)] for p in payloads]) for stage in STAGES]
    residual = total - np.sum(measured_layers, axis=0)
    if np.any(residual < -1e-9):
        raise ValueError("Measured VBS stages exceed measured process total; cannot form an additive stack")
    residual = np.maximum(residual, 0)
    layer_names = STAGES + ["host_residual"]
    layers = measured_layers + [residual]
    dense_x = None
    dense_layers = []
    for layer in layers:
        guide_x, guide_y = pchip_logx(payloads, layer)
        dense_x = guide_x
        dense_layers.append(np.maximum(guide_y, 0))

    fig, ax = new_figure(figsize=(7.45, 4.85))
    colors = [STAGE_COLORS[name] for name in layer_names]
    ax.stackplot(dense_x, *dense_layers, colors=colors, alpha=0.86,
                 labels=[STAGE_LABELS[name] for name in layer_names])
    cumulative = np.zeros_like(payloads)
    for layer, color in zip(layers, colors):
        cumulative += layer
        ax.scatter(payloads, cumulative, s=12, color=color, edgecolor="white", linewidth=0.35, zorder=4)
    ax.scatter(payloads, total, s=34, color="black", edgecolor="white", linewidth=0.7,
               zorder=6, label="measured VBS process p50")
    ax.plot(payloads, total, color="black", linewidth=0.8, linestyle="--", alpha=0.75)
    transition = int(np.argmax(np.diff(total)) + 1)
    ax.annotate(
        f"largest measured rise\n{payload_label(payloads[transition])}: {total[transition]:.1f} ms",
        (payloads[transition], total[transition]), xytext=(-118, -42), textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": COLORS["dark"]}, fontsize=7.2,
    )
    dominant_share = 100 * residual[-1] / total[-1]
    ax.annotate(
        f"host/process residual dominates\n{dominant_share:.0f}% at largest payload",
        (payloads[-1], residual[-1] * 0.55), xytext=(-150, -8), textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": COLORS["gray"]}, fontsize=7.2,
    )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Encrypted payload (log scale)")
    ax.set_ylabel("Additive p50 latency (ms)")
    ax.set_title("VBS latency composition across payload sizes")
    ax.set_xticks(payloads, [payload_label(p) for p in payloads])
    ax.set_xlim(payloads.min(), payloads.max())
    ax.set_ylim(0, total.max() * 1.16)
    ax.legend(loc="upper left", ncol=2)
    ax.text(
        0.995, 0.015,
        "PCHIP guides in log-payload space; dots are measured. Residual = process p50 − measured enclave-stage p50 sum.",
        transform=ax.transAxes, ha="right", fontsize=6.4, color=COLORS["dark"],
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.5},
    )
    finish_axis(ax)
    save_pdf(fig, "fig4c_vbs_latency_composition_area.pdf")


def panel_d(trials) -> None:
    grouped = groups(trials, "payload_bytes")
    payloads = sorted(grouped, key=int)
    points = []
    for p in payloads:
        rows = grouped[p]
        for mode, prefix in [("Native", "native"), ("VBS", "vbs")]:
            points.append(
                {
                    "payload": int(p),
                    "mode": mode,
                    "cpu_ms": float(np.median(values(rows, f"{prefix}_process_cpu_time_ms"))),
                    "rss_mib": float(np.median(values(rows, f"{prefix}_peak_rss_bytes")) / 1024**2),
                    "latency_ms": float(np.median(values(rows, f"{prefix}_process_wall_us")) / 1000),
                    "throughput": float(np.median(values(rows, f"{prefix}_payload_throughput_mib_s"))),
                }
            )
    payload_arr = np.array([p["payload"] for p in points], dtype=float)
    sizes = area_sizes(np.log2(payload_arr), 90, 590)
    latency = np.array([p["latency_ms"] for p in points])
    norm = plt.Normalize(latency.min(), latency.max())
    latency_colors = plt.get_cmap("plasma")(norm(latency))

    fig, ax = new_figure()
    for i, point in enumerate(points):
        marker = "o" if point["mode"] == "Native" else "s"
        ax.scatter(point["cpu_ms"], point["rss_mib"], s=sizes[i], c=[latency_colors[i]],
                   marker=marker, edgecolor=COLORS["dark"],
                   linewidth=0.8, alpha=0.82)
        if point["payload"] in (1024, 800000):
            ax.annotate(f"{point['mode']} · {payload_label(point['payload'])}\n{point['throughput']:.2g} MiB/s",
                        (point["cpu_ms"], point["rss_mib"]), xytext=(5, 5),
                        textcoords="offset points", fontsize=6.5)
    for p in payloads:
        pair = [q for q in points if q["payload"] == int(p)]
        ax.plot([q["cpu_ms"] for q in pair], [q["rss_mib"] for q in pair], color="#AAB1B6",
                linestyle=":", linewidth=0.8, zorder=0)
    ax.text(0.02, 0.98, f"color: median process latency {latency.min():.1f}–{latency.max():.1f} ms",
            transform=ax.transAxes, va="top", fontsize=6.8, color=COLORS["gray"])
    ax.set_xlabel("Median process CPU time (ms)")
    ax.set_ylabel("Median peak working set (MiB)")
    ax.set_title("Native/VBS resource phase space")
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], label="Native"),
        plt.Line2D([], [], marker="s", linestyle="none", color=COLORS["gray"], label="VBS"),
    ], loc="upper left")
    ax.text(0.995, 0.02, "Bubble area ∝ log₂(payload); dotted segments pair the same payload",
            transform=ax.transAxes, ha="right", fontsize=6.7, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig4d_vbs_resource_phase_space.pdf")


def panel_e(attest, trials, summary) -> None:
    grouped = groups(attest, "stage")
    stages = ["Transcript", "Evidence generation", "External validation"]
    datasets = [values(grouped[s], "latency_us") / 1000 for s in stages]
    shares = [np.median(values(grouped[s], "percent_of_total_vbs_latency")) for s in stages]
    x = np.arange(len(stages), dtype=float)
    colors = [COLORS["orange"], COLORS["purple"], COLORS["red"]]
    fig, ax = new_figure()
    distribution_boxes(ax, datasets, x, colors, salt=130)
    ax.set_yscale("log")
    ax.set_xticks(x, [f"{s}\n(n={len(grouped[s])})" for s in stages])
    ax.set_ylabel("Latency (ms, log scale)")
    ax.set_title("Attestation overhead and correctness parity")

    ax2 = ax.twinx()
    ax2.scatter(x, shares, marker="D", s=35, facecolors="white", edgecolors=COLORS["blue"],
                linewidths=1.3, label="p50 share of VBS total")
    ax2.set_ylabel("Median share of VBS latency (%)", color=COLORS["blue"])
    ax2.tick_params(axis="y", colors=COLORS["blue"])
    ax2.spines["right"].set_visible(True)
    parity = 100 * np.mean(values(trials, "result_parity"))
    hash_match = 100 * np.mean(values(trials, "result_hash_match"))
    success = 100 * min(np.mean(values(trials, "native_ok")), np.mean(values(trials, "vbs_ok")))
    ax.text(0.02, 0.96, f"result parity {parity:.0f}% · hash match {hash_match:.0f}% · success {success:.0f}%",
            transform=ax.transAxes, va="top", fontsize=7.4,
            bbox={"facecolor": "white", "edgecolor": "#CCD3D8", "alpha": 0.92})
    handles = [
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="latency p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="latency p95"),
        plt.Line2D([], [], marker="D", markerfacecolor="white", color=COLORS["blue"],
                   linestyle="none", label="p50 total share"),
    ]
    ax.legend(handles=handles, loc="lower right", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig4e_vbs_attestation_and_parity.pdf")


def generate() -> list[str]:
    trials, summary, stages, attest = _sources()
    panel_a(trials)
    panel_b(summary)
    panel_c(summary, stages)
    panel_d(trials)
    panel_e(attest, trials, summary)
    return [
        "fig4a_native_vbs_latency_distribution.pdf", "fig4b_vbs_overhead_and_throughput.pdf",
        "fig4c_vbs_latency_composition_area.pdf", "fig4d_vbs_resource_phase_space.pdf",
        "fig4e_vbs_attestation_and_parity.pdf",
    ]


if __name__ == "__main__":
    generate()
