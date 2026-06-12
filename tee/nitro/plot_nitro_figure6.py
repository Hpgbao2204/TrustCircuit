"""Paper-ready Figure 6 plots from AWS Nitro Enclaves measurements.

This replaces the old SGX projection visuals with hardware measurements:

  n1  Stacked latency composition vs working set.
  n3  Throughput recovery when one Nitro attestation document is amortized
      across a batch of accepted requests.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from benchmarks.paper_plot_style import PALETTE  # noqa: E402
except ModuleNotFoundError:
    PALETTE = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]


LATENCY_CSV = REPO / "results" / "summary" / "nitro_latency_summary.csv"
ATTEST_CSV = REPO / "results" / "raw" / "nitro_attestation.csv"
OUT_DIR = REPO / "results" / "figures" / "nitro"


def save_nitro_fig(fig, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / f"{name}.pdf", dpi=300, bbox_inches="tight")
    plt.close(fig)


def apply_nitro_style() -> None:
    plt.rcdefaults()
    plt.rcParams.update(
        {
            "figure.figsize": (12, 6),
            "font.size": 18,
            "axes.titlesize": 18,
            "axes.labelsize": 18,
            "xtick.labelsize": 16,
            "ytick.labelsize": 16,
            "legend.fontsize": 14,
            "lines.linewidth": 2.4,
            "lines.markersize": 8,
            "axes.axisbelow": True,
            "savefig.format": "pdf",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_latency_summary() -> list[dict]:
    with LATENCY_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda r: float(r["payload_mib"]))


def read_attestation_latencies() -> list[float]:
    with ATTEST_CSV.open(newline="", encoding="utf-8") as f:
        return [float(r["attestation_latency_ms"]) for r in csv.DictReader(f)]


def fig_latency_composition_area() -> None:
    rows = read_latency_summary()
    measured_x = np.array([float(r["payload_mib"]) for r in rows])
    enclave_ms = np.array([float(r["enclave_mean_ms"]) for r in rows])
    e2e_ms = np.array([float(r["e2e_mean_ms"]) for r in rows])
    vsock_overhead = np.maximum(e2e_ms - enclave_ms, 0.0)

    attest_lat = read_attestation_latencies()
    attest_ms = statistics.median(attest_lat)

    # Interpolate measured points to make a smooth area chart while preserving
    # the actual measured endpoints.
    ws = np.linspace(measured_x.min(), measured_x.max(), 240)
    enclave_interp = np.interp(ws, measured_x, enclave_ms)
    vsock_interp = np.interp(ws, measured_x, vsock_overhead)

    # The current worker's dominant measured component is payload materialization
    # and hashing inside Nitro. Estimate fixed aggregate/DP cost from the 1 MiB
    # intercept and keep it non-negative.
    slope = (enclave_ms[-1] - enclave_ms[0]) / (measured_x[-1] - measured_x[0])
    fixed_compute = max(0.0, enclave_ms[0] - slope * measured_x[0])
    fixed_compute_layer = np.full_like(ws, fixed_compute)
    payload_layer = np.maximum(enclave_interp - fixed_compute_layer, 0.0)
    vsock_layer = vsock_interp
    attest_layer = np.full_like(ws, attest_ms)

    layers = [fixed_compute_layer, payload_layer, vsock_layer, attest_layer]
    labels = [
        "Aggregate + DP",
        "Payload + transcript hash",
        "VSOCK overhead",
        "NSM attestation",
    ]
    colors = [PALETTE[2], PALETTE[1], PALETTE[3], PALETTE[4]]

    total = fixed_compute_layer + payload_layer + vsock_layer + attest_layer

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.stackplot(ws, *layers, labels=labels, colors=colors, alpha=0.86)
    ax.scatter(measured_x, e2e_ms + attest_ms, color="black", s=22, zorder=5,
               label="measured request sizes")
    ax.annotate("flat enclave memory\n(no SGX EPC paging cliff)",
                xy=(92, float(np.interp(92, ws, payload_layer + fixed_compute_layer))),
                xytext=(35, max(e2e_ms) * 0.34),
                arrowprops=dict(arrowstyle="->", color=PALETTE[7], linewidth=1.2),
                color=PALETTE[7], fontsize=12,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.78))
    ax.set_ylabel("Latency (ms)")
    ax.set_xlim(0, 128)
    ax.set_ylim(0, None)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.92, ncol=2, columnspacing=0.9,
              handlelength=1.3)

    # Inset zoom: exposes the small fixed components that disappear on the
    # full 128 MiB scale.
    axins = inset_axes(ax, width="35%", height="38%", loc="lower right", borderpad=1.2)
    axins.stackplot(ws, *layers, colors=colors, alpha=0.9)
    axins.set_xlim(0, 8)
    axins.set_ylim(0, float(np.interp(8, ws, total)) * 1.08)
    axins.text(0.04, 0.92, "0--8 MiB zoom", transform=axins.transAxes,
               fontsize=12, va="top")
    axins.tick_params(labelsize=11)
    axins.grid(True, alpha=0.2)
    mark_inset(ax, axins, loc1=2, loc2=4, fc="none", ec=PALETTE[7], lw=0.8, alpha=0.8)

    save_nitro_fig(fig, "n1_latency_composition_area")


def fig_attestation_amortization() -> None:
    latency_rows = read_latency_summary()
    one_mib = next(r for r in latency_rows if int(float(r["payload_mib"])) == 1)
    base_median_ms = float(one_mib["e2e_median_ms"])
    att = np.array(read_attestation_latencies(), dtype=float)
    batch = np.arange(1, 65)

    overhead_samples = []
    throughput_samples = []
    for a in att:
        overhead_samples.append(a / batch)
        throughput_samples.append(1000.0 / (base_median_ms + a / batch))
    overhead = np.vstack(overhead_samples)
    thru = np.vstack(throughput_samples)
    overhead_p5 = np.percentile(overhead, 5, axis=0)
    overhead_p50 = np.percentile(overhead, 50, axis=0)
    overhead_p95 = np.percentile(overhead, 95, axis=0)
    thru_p50 = np.percentile(thru, 50, axis=0)
    thru_p5 = np.percentile(thru, 5, axis=0)
    thru_p95 = np.percentile(thru, 95, axis=0)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.fill_between(batch, overhead_p5, overhead_p95, color=PALETTE[4], alpha=0.24,
                    label="p5--p95 NSM")
    ax.plot(batch, overhead_p50, color=PALETTE[4], marker="o", markevery=6,
            linewidth=2.2, label="median overhead")
    ax.axhline(overhead_p50[0], color=PALETTE[1], linestyle="--", linewidth=1.5,
               label=f"per request ({overhead_p50[0]:.2f} ms)")
    ax.annotate("NSM document cost\namortized across batch",
                xy=(16, overhead_p50[15]), xytext=(27, overhead_p50[0] * 0.62),
                arrowprops=dict(arrowstyle="->", color=PALETTE[7], linewidth=1.2),
                fontsize=14, color=PALETTE[7],
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.78))
    ax.set_xlabel("attestation batch size (requests per Nitro document)")
    ax.set_ylabel("Attest. overhead (ms/req)")
    ax.set_xlim(1, 64)
    ax.set_ylim(0, overhead_p50[0] * 1.18)
    ax.grid(True, alpha=0.25)

    ax2 = ax.twinx()
    ax2.fill_between(batch, thru_p5, thru_p95, color=PALETTE[0], alpha=0.12)
    ax2.plot(batch, thru_p50, color=PALETTE[0], linewidth=2.0,
             label="throughput")
    ax2.set_ylabel("Throughput (req/s)")
    ax2.set_ylim(min(thru_p5) * 0.995, max(thru_p95) * 1.003)

    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="lower right",
              framealpha=0.92, fontsize=12)
    save_nitro_fig(fig, "n3_attestation_amortization")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    apply_nitro_style()
    fig_latency_composition_area()
    fig_attestation_amortization()
    print(f"wrote {OUT_DIR / 'n1_latency_composition_area.pdf'}")
    print(f"wrote {OUT_DIR / 'n3_attestation_amortization.pdf'}")


if __name__ == "__main__":
    main()
