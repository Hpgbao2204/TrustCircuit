"""Plot the differential-privacy and access-control figures.

Reads the summaries in results/summary and writes the DP error contour, the
CP-ABE policy-size comparison, and the hybrid-encryption throughput and memory
panels to results/figures/offchain.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

FIG_SIZE = (12.0, 6.0)

FONT_SIZE = 16

PDF_DPI = 300

PALETTE = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
    "#8c564b",
    "#e377c2",
]


def apply_style(font_delta: int = 0) -> None:
    global FONT_SIZE
    FONT_SIZE = 16 + font_delta
    plt.rcParams.update(
        {
            "figure.figsize": FIG_SIZE,
            "font.size": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE - 2,
            "ytick.labelsize": FONT_SIZE - 2,
            "legend.fontsize": FONT_SIZE - 2,
            "lines.linewidth": 2.4,
            "lines.markersize": 8,
            "axes.axisbelow": True,
            "savefig.format": "pdf",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def new_fig(projection: str | None = None):
    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_subplot(111, projection=projection) if projection else fig.add_subplot(111)
    return fig, ax


def save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.pdf"
    fig.set_size_inches(*FIG_SIZE, forward=True)
    fig.savefig(out, dpi=PDF_DPI, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return out


def figure_dp_error_contour(rows: list[dict[str, str]], out_dir: Path) -> Path:
    """Render the DP contour panel with a wrapped, paper-sized colorbar label."""
    queries = sorted({r["query"] for r in rows})
    eps = sorted({float(r["epsilon"]) for r in rows})
    by_key = {
        (r["query"], float(r["epsilon"])): float(r["relative_error_percent_mean"])
        for r in rows
    }
    matrix = np.array([[by_key[(query, epsilon)] for epsilon in eps] for query in queries])
    x_grid, y_grid = np.meshgrid(np.arange(len(eps)), np.arange(len(queries)))

    fig, ax = new_fig()
    contour = ax.contourf(x_grid, y_grid, matrix, levels=16, cmap="Blues")
    ax.contour(x_grid, y_grid, matrix, levels=8, colors="white", linewidths=0.7, alpha=0.7)
    y_label_map = {
        "mean_systolic_bp": "mean systolic\nBP",
        "mean_cholesterol": "mean\ncholesterol",
        "high_cholesterol_count": "high cholesterol\ncount",
    }
    ax.set_xticks(range(len(eps))); ax.set_xticklabels([f"{e:g}" for e in eps])
    ax.set_yticks(range(len(queries))); ax.set_yticklabels([y_label_map.get(q, q.replace("_", " ")) for q in queries])
    ax.set_xlabel("epsilon")
    fig.subplots_adjust(left=0.20, right=0.85, bottom=0.16, top=0.96)
    colorbar = fig.colorbar(contour, ax=ax, fraction=0.046, pad=0.04)
    colorbar.set_label("relative error\n(%)", fontsize=FONT_SIZE)
    return save(fig, out_dir, "d3_error_contour")


def figure_cpabe_policy_comparison_revised(rows, out_dir: Path) -> Path:
    """Render the paper-facing CP-ABE policy benchmark without inline notes."""
    pr = sorted(rows, key=lambda row: int(row["policy_attributes"]))
    attributes = np.array([int(row["policy_attributes"]) for row in pr])
    repetitions = np.array([int(row["repetitions"]) for row in pr])
    if not np.all(repetitions == 30):
        raise ValueError("the revised Figure 5(b) requires 30 repetitions per point")

    series = [
        (
            "kem_dem_baseline_encrypt_ms",
            "KEM-DEM enc.",
            "o",
            "-",
            PALETTE[0],
        ),
        (
            "kem_dem_baseline_decrypt_ms",
            "KEM-DEM dec.",
            "s",
            "-",
            PALETTE[1],
        ),
        (
            "full_cpabe_encrypt_ms",
            "CP-ABE enc.",
            "^",
            "--",
            PALETTE[2],
        ),
        (
            "full_cpabe_decrypt_ms",
            "CP-ABE dec.",
            "D",
            "--",
            PALETTE[4],
        ),
    ]

    fig, ax = new_fig()
    for prefix, label, marker, linestyle, color in series:
        means = np.array([float(row[f"{prefix}_mean"]) for row in pr])
        stddevs = np.array([float(row[f"{prefix}_std"]) for row in pr])
        ci95 = 2.04523 * stddevs / np.sqrt(repetitions)
        ax.errorbar(
            attributes,
            means,
            yerr=ci95,
            marker=marker,
            linestyle=linestyle,
            color=color,
            capsize=4,
            elinewidth=1.5,
            label=label,
        )

    ax.set_xlabel("Policy leaves")
    ax.set_ylabel("Latency (ms)")
    ax.set_xticks(attributes)
    ax.set_ylim(bottom=0)
    ax.legend(ncol=2, fontsize=FONT_SIZE - 4)
    fig.tight_layout()
    return save(fig, out_dir, "ab1_policy_time_revised")


def figure_abe_throughput(rows, out_dir: Path) -> Path:
    pay = sorted(rows, key=lambda r: int(r["payload_mb"]))
    mb = np.array([int(r["payload_mb"]) for r in pay])
    ethr = np.array([float(r["enc_throughput_mbps"]) for r in pay])
    dthr = np.array([float(r["dec_throughput_mbps"]) for r in pay])

    fig, ax = new_fig()
    ax.semilogx(mb, ethr, marker="o", color=PALETTE[0], label="encrypt throughput")
    ax.semilogx(mb, dthr, marker="s", color=PALETTE[1], label="decrypt throughput")
    ax.set_xlabel("payload size (MB, log)"); ax.set_ylabel("throughput (MB/s)")
    ax.legend(fontsize=FONT_SIZE - 2)
    return save(fig, out_dir, "ab4_throughput")


def figure_abe_memory(rows, out_dir: Path) -> Path:
    pay = sorted(rows, key=lambda r: int(r["payload_mb"]))
    mb = np.array([int(r["payload_mb"]) for r in pay])
    rss = np.array([float(r["peak_rss_mb"]) for r in pay])

    fig, ax = new_fig()
    ax.plot(mb, rss, marker="o", color=PALETTE[3], label="peak RSS")
    ax.plot(mb, mb, "--", color="gray", label="1x payload")
    ax.set_xlabel("payload size (MB)"); ax.set_ylabel("peak resident memory (MB)")
    ax.legend(fontsize=FONT_SIZE - 2)
    return save(fig, out_dir, "ab6_peak_rss")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "figures" / "offchain")
    args = parser.parse_args()
    apply_style(font_delta=8)
    summary = ROOT / "results" / "summary"
    dp_rows = read_csv(summary / "dp_utility_summary.csv")
    cpabe_rows = read_csv(summary / "cpabe_policy_summary.csv")
    payload_rows = read_csv(summary / "abe_payload_summary.csv")
    outputs = [
        figure_dp_error_contour(dp_rows, args.out),
        figure_cpabe_policy_comparison_revised(cpabe_rows, args.out),
        figure_abe_throughput(payload_rows, args.out),
        figure_abe_memory(payload_rows, args.out),
    ]
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
