"""Plot four deployment-profile figures from the reused Phase 8 summaries."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "deployment_profiles" / "summary"
DEFAULT_OUTPUT = ROOT / "results" / "deployment_profiles" / "figures"
PROFILES = ["TC-Lite", "TC-Protected", "TC-Full"]
COLORS = {
    "TC-Lite": "#2A9D8F",
    "TC-Protected": "#E9C46A",
    "TC-Full": "#E76F51",
}
STAGE_COLORS = {
    "access": "#4C78A8",
    "budget": "#72B7B2",
    "tee": "#F2CF5B",
    "proof": "#E45756",
    "settlement": "#B279A2",
    "audit": "#59A14F",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {
                key.strip(): value.strip() if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def error_bounds(row: dict, metric: str) -> tuple[float, float]:
    mean = float(row[f"mean_{metric}"])
    return (
        mean - float(row[f"ci95_low_{metric}"]),
        float(row[f"ci95_high_{metric}"]) - mean,
    )


def save_figure(fig, output: Path, stem: str) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    pdf_path = output / f"{stem}.pdf"
    png_path = output / f"{stem}.png"
    fig.savefig(pdf_path, dpi=300, bbox_inches="tight")
    fig.savefig(png_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return pdf_path, png_path


def plot_latency(output: Path, stage_lookup: dict[tuple[str, str], float]) -> tuple[Path, Path]:
    fig, ax = plt.subplots(layout="constrained")
    x = np.arange(len(PROFILES))
    bottoms = np.zeros(len(PROFILES))
    for stage, color in STAGE_COLORS.items():
        values = np.array([stage_lookup[(profile, stage)] for profile in PROFILES])
        ax.bar(x, values, bottom=bottoms, width=0.62, color=color, label=stage.capitalize())
        bottoms += values
    for index, total in enumerate(bottoms):
        ax.text(index, total + max(bottoms) * 0.025, f"{total:.1f}", ha="center", va="bottom")
    ax.set_xticks(x, PROFILES)
    ax.set_ylabel("Latency (ms)")
    ax.set_ylim(0, max(bottoms) * 1.18)
    ax.legend(ncol=3, frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.22)
    return save_figure(fig, output, "deployment_profile_a_latency_reused")


def plot_throughput_gas(output: Path, by_profile: dict[str, dict]) -> tuple[Path, Path]:
    fig, (ax_throughput, ax_gas) = plt.subplots(
        2, 1, sharex=True, gridspec_kw={"height_ratios": [1, 1]}, layout="constrained"
    )
    x = np.arange(len(PROFILES))
    colors = [COLORS[profile] for profile in PROFILES]

    throughput = np.array(
        [float(by_profile[profile]["mean_throughput_req_s"]) for profile in PROFILES]
    )
    throughput_err = np.array(
        [error_bounds(by_profile[profile], "throughput_req_s") for profile in PROFILES]
    ).T
    ax_throughput.bar(x, throughput, color=colors, width=0.62)
    ax_throughput.errorbar(
        x, throughput, yerr=throughput_err, fmt="none", ecolor="#333333", capsize=3
    )
    for index, value in enumerate(throughput):
        ax_throughput.text(index, value + max(throughput) * 0.025, f"{value:.2f}", ha="center")
    ax_throughput.set_ylabel("Throughput (req/s)")
    ax_throughput.set_ylim(0, max(throughput) * 1.18)
    ax_throughput.grid(axis="y", alpha=0.22)

    gas = np.array(
        [float(by_profile[profile]["mean_total_gas"]) / 1_000_000 for profile in PROFILES]
    )
    gas_err = np.array(
        [
            tuple(value / 1_000_000 for value in error_bounds(by_profile[profile], "total_gas"))
            for profile in PROFILES
        ]
    ).T
    ax_gas.bar(x, gas, color=colors, width=0.62)
    ax_gas.errorbar(x, gas, yerr=gas_err, fmt="none", ecolor="#333333", capsize=3)
    for index, value in enumerate(gas):
        ax_gas.text(index, value + max(gas) * 0.025, f"{value:.2f}", ha="center")
    ax_gas.set_ylabel("Gas (million)")
    ax_gas.set_ylim(0, max(gas) * 1.18)
    ax_gas.set_xticks(x, PROFILES)
    ax_gas.grid(axis="y", alpha=0.22)
    return save_figure(fig, output, "deployment_profile_b_throughput_gas_reused")


def plot_cpu_ram(output: Path, by_profile: dict[str, dict]) -> tuple[Path, Path]:
    fig, (ax_cpu, ax_rss) = plt.subplots(
        2, 1, sharex=True, gridspec_kw={"height_ratios": [1, 1]}, layout="constrained"
    )
    x = np.arange(len(PROFILES))
    colors = [COLORS[profile] for profile in PROFILES]

    cpu = np.array(
        [
            float(by_profile[profile]["mean_normalized_peak_cpu_percent"])
            for profile in PROFILES
        ]
    )
    cpu_err = np.array(
        [
            error_bounds(by_profile[profile], "normalized_peak_cpu_percent")
            for profile in PROFILES
        ]
    ).T
    ax_cpu.bar(x, cpu, color=colors, width=0.62)
    ax_cpu.errorbar(x, cpu, yerr=cpu_err, fmt="none", ecolor="#333333", capsize=3)
    for index, value in enumerate(cpu):
        ax_cpu.text(index, value + max(cpu) * 0.025, f"{value:.1f}", ha="center")
    ax_cpu.set_ylabel("CPU (%)")
    ax_cpu.set_ylim(0, max(cpu + cpu_err[1]) * 1.12)
    ax_cpu.grid(axis="y", alpha=0.22)

    rss = np.array(
        [
            float(by_profile[profile]["mean_peak_working_set_bytes"]) / (1024**3)
            for profile in PROFILES
        ]
    )
    rss_err = np.array(
        [
            tuple(
                value / (1024**3)
                for value in error_bounds(by_profile[profile], "peak_working_set_bytes")
            )
            for profile in PROFILES
        ]
    ).T
    ax_rss.bar(x, rss, color=colors, width=0.62)
    ax_rss.errorbar(x, rss, yerr=rss_err, fmt="none", ecolor="#333333", capsize=3)
    for index, value in enumerate(rss):
        ax_rss.text(index, value + max(rss) * 0.025, f"{value:.2f}", ha="center")
    ax_rss.set_ylabel("Peak RSS (GiB)")
    ax_rss.set_ylim(0, max(rss + rss_err[1]) * 1.18)
    ax_rss.set_xticks(x, PROFILES)
    ax_rss.grid(axis="y", alpha=0.22)
    return save_figure(fig, output, "deployment_profile_c_cpu_ram_reused")


def plot_cost_guarantee(output: Path, by_profile: dict[str, dict]) -> tuple[Path, Path]:
    fig, ax = plt.subplots(layout="constrained")
    full_latency = float(by_profile["TC-Full"]["mean_total_latency_ms"])
    relative_latency = np.array(
        [
            100 * float(by_profile[profile]["mean_total_latency_ms"]) / full_latency
            for profile in PROFILES
        ]
    )
    relative_latency_err = np.array(
        [
            tuple(
                100 * value / full_latency
                for value in error_bounds(by_profile[profile], "total_latency_ms")
            )
            for profile in PROFILES
        ]
    ).T
    scores = np.array([float(by_profile[profile]["guarantee_score"]) for profile in PROFILES])

    ax.plot(relative_latency, scores, color="#777777", linestyle="--", zorder=1)
    for index, profile in enumerate(PROFILES):
        ax.errorbar(
            relative_latency[index],
            scores[index],
            xerr=np.array(
                [[relative_latency_err[0, index]], [relative_latency_err[1, index]]]
            ),
            fmt="o",
            markersize=10,
            capsize=3,
            color=COLORS[profile],
            zorder=2,
        )
        ax.annotate(profile, (relative_latency[index], scores[index]), xytext=(7, 5), textcoords="offset points")
    ax.set_xlabel("Latency relative to TC-Full (%)")
    ax.set_ylabel("Guarantees (0-4)")
    ax.set_xlim(0, 112)
    ax.set_ylim(0.7, 4.35)
    ax.set_yticks(range(1, 5))
    ax.grid(alpha=0.22)
    return save_figure(fig, output, "deployment_profile_d_cost_guarantee_reused")


def plot_compact_matrix(
    output: Path,
    by_profile: dict[str, dict],
    stage_lookup: dict[tuple[str, str], float],
    capabilities: dict[str, dict],
) -> tuple[Path, Path]:
    fig = plt.figure(figsize=(8.8, 3.0))
    grid = fig.add_gridspec(1, 2, width_ratios=[1.08, 1.92])
    ax_latency = fig.add_subplot(grid[0, 0])
    ax_matrix = fig.add_subplot(grid[0, 1], sharey=ax_latency)
    fig.subplots_adjust(left=0.09, right=0.99, bottom=0.23, top=0.78, wspace=0.08)

    y = np.arange(len(PROFILES))
    totals = np.array(
        [float(by_profile[profile]["mean_total_latency_ms"]) for profile in PROFILES]
    )
    left = np.zeros(len(PROFILES))
    for stage, color in STAGE_COLORS.items():
        values = np.array([stage_lookup[(profile, stage)] for profile in PROFILES])
        shares = 100 * values / totals
        ax_latency.barh(y, shares, left=left, height=0.56, color=color)
        left += shares
    for index, total in enumerate(totals):
        ax_latency.text(102.5, index, f"{total:.1f} ms", va="center")
    ax_latency.set_xlim(0, 132)
    ax_latency.set_xticks([0, 50, 100])
    ax_latency.set_xlabel("Latency composition (%)")
    ax_latency.set_yticks(y, PROFILES)
    ax_latency.set_ylim(len(PROFILES) - 0.5, -0.5)
    ax_latency.grid(axis="x", alpha=0.22)
    ax_latency.spines[["top", "right"]].set_visible(False)

    metric_specs = [
        ("mean_throughput_req_s", "Throughput ↑\n(req/s)", lambda value: f"{value:.1f}"),
        ("mean_total_gas", "Gas ↓\n(million)", lambda value: f"{value / 1_000_000:.2f}"),
        (
            "mean_normalized_peak_cpu_percent",
            "CPU ↓\n(%)",
            lambda value: f"{value:.1f}",
        ),
        (
            "mean_peak_working_set_bytes",
            "RSS ↓\n(GiB)",
            lambda value: f"{value / (1024**3):.2f}",
        ),
    ]
    capability_specs = [
        ("tee", "TEE"),
        ("dp_budget", "DP"),
        ("zkp", "ZKP"),
        ("on_chain_audit", "Audit"),
    ]

    for row_index in range(len(PROFILES)):
        for column_index in range(len(metric_specs) + len(capability_specs)):
            ax_matrix.add_patch(
                Rectangle(
                    (column_index - 0.48, row_index - 0.38),
                    0.96,
                    0.76,
                    facecolor="#F7F7F7" if row_index % 2 == 0 else "#FFFFFF",
                    edgecolor="#DDDDDD",
                    linewidth=0.7,
                    zorder=0,
                )
            )

    for column_index, (field, _, formatter) in enumerate(metric_specs):
        values = np.array([float(by_profile[profile][field]) for profile in PROFILES])
        if np.isclose(values.max(), values.min()):
            sizes = np.full(len(PROFILES), 900.0)
        else:
            sizes = 480 + 700 * (values - values.min()) / (values.max() - values.min())
        for row_index, profile in enumerate(PROFILES):
            ax_matrix.scatter(
                column_index,
                row_index,
                s=sizes[row_index],
                color=COLORS[profile],
                edgecolor="white",
                linewidth=1.2,
                zorder=2,
            )
            ax_matrix.text(
                column_index,
                row_index,
                formatter(values[row_index]),
                ha="center",
                va="center",
                zorder=3,
            )

    capability_offset = len(metric_specs)
    for capability_index, (field, _) in enumerate(capability_specs):
        column_index = capability_offset + capability_index
        for row_index, profile in enumerate(PROFILES):
            enabled = capabilities[profile][field] == "1"
            ax_matrix.add_patch(
                Rectangle(
                    (column_index - 0.31, row_index - 0.27),
                    0.62,
                    0.54,
                    facecolor="#DDF2E1" if enabled else "#EEEEEE",
                    edgecolor="#8FB996" if enabled else "#CCCCCC",
                    linewidth=0.8,
                    zorder=1,
                )
            )
            ax_matrix.text(
                column_index,
                row_index,
                "✓" if enabled else "—",
                ha="center",
                va="center",
                zorder=2,
            )

    labels = [spec[1] for spec in metric_specs] + [spec[1] for spec in capability_specs]
    ax_matrix.set_xticks(np.arange(len(labels)), labels)
    ax_matrix.xaxis.tick_top()
    ax_matrix.tick_params(axis="x", length=0, pad=7)
    ax_matrix.tick_params(axis="y", left=False, labelleft=False)
    ax_matrix.set_xlim(-0.55, len(labels) - 0.45)
    ax_matrix.set_ylim(len(PROFILES) - 0.5, -0.5)
    ax_matrix.axvline(capability_offset - 0.5, color="#888888", linewidth=1.0)
    ax_matrix.spines[:].set_visible(False)

    legend_handles = [
        Patch(facecolor=color, label=stage.capitalize())
        for stage, color in STAGE_COLORS.items()
    ]
    fig.legend(
        handles=legend_handles,
        ncol=len(legend_handles),
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.99),
    )
    return save_figure(fig, output, "deployment_profiles_compact_matrix_reused")


def main() -> None:
    args = parse_args()
    summary_rows = read_csv(args.input / "deployment_profile_summary.csv")
    stage_rows = read_csv(args.input / "deployment_profile_stage_summary.csv")
    capability_rows = read_csv(args.input / "deployment_profile_capabilities.csv")
    by_profile = {row["profile"]: row for row in summary_rows}
    capabilities = {row["profile"]: row for row in capability_rows}
    stage_lookup = {
        (row["profile"], row["stage"]): float(row["mean_latency_ms"])
        for row in stage_rows
    }

    paths = plot_compact_matrix(args.output, by_profile, stage_lookup, capabilities)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
