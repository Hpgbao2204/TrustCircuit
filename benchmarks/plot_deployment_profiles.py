"""Render the two deployment-profile parallel-coordinate paper panels."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "deployment_profiles" / "summary"
DEFAULT_OUTPUT = ROOT / "results" / "deployment_profiles" / "figures"
DEFAULT_PAPER_OUTPUT = (
    ROOT / "Paper" / "Figure" / "figures" / "deployment-profiles"
)
PROFILES = ["TC-Lite", "TC-Protected", "TC-Full"]
PROFILE_STYLES = {
    "TC-Lite": {"color": "#287F76", "marker": "o", "linestyle": "-"},
    "TC-Protected": {"color": "#6266A8", "marker": "D", "linestyle": "--"},
    "TC-Full": {"color": "#C65D57", "marker": "s", "linestyle": "-"},
}
VALUE_LABEL_STYLE = {
    "TC-Lite": {"xytext": (-5, 7), "ha": "right"},
    "TC-Protected": {"xytext": (5, -9), "ha": "left"},
    "TC-Full": {"xytext": (5, 7), "ha": "left"},
}


@dataclass(frozen=True)
class AxisSpec:
    label: str
    minimum: float
    maximum: float
    ticks: tuple[float, ...]
    tick_formatter: Callable[[float], str]
    value_formatter: Callable[[float], str]
    lower_is_better: bool = True

    def normalize(self, value: float) -> float:
        scaled = (value - self.minimum) / (self.maximum - self.minimum)
        return 1.0 - scaled if self.lower_is_better else scaled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--paper-output", type=Path, default=DEFAULT_PAPER_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {
                key.strip(): value.strip() if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def draw_parallel_coordinates(
    axes: list[AxisSpec],
    values: dict[str, list[float | None]],
    ci_low: dict[str, list[float | None]],
    ci_high: dict[str, list[float | None]],
    legend_labels: dict[str, str],
    *,
    shared_value_axes: set[int] | None = None,
) -> plt.Figure:
    shared_value_axes = shared_value_axes or set()
    fig, ax = plt.subplots(figsize=(4.7, 2.95))
    fig.subplots_adjust(left=0.035, right=0.985, bottom=0.285, top=0.77)
    x_values = np.arange(len(axes), dtype=float)

    for y_value in (0.25, 0.5, 0.75):
        ax.hlines(
            y_value,
            x_values[0],
            x_values[-1],
            color="#D8DEE6",
            linewidth=0.55,
            linestyle=(0, (2, 3)),
            zorder=0,
        )

    for axis_index, spec in enumerate(axes):
        ax.vlines(axis_index, 0, 1, color="#566372", linewidth=0.9, zorder=1)
        for tick in spec.ticks:
            normalized_tick = spec.normalize(tick)
            ax.hlines(
                normalized_tick,
                axis_index - 0.025,
                axis_index + 0.025,
                color="#566372",
                linewidth=0.75,
                zorder=2,
            )
            ax.text(
                axis_index - 0.04,
                normalized_tick,
                spec.tick_formatter(tick),
                ha="right",
                va="center",
                fontsize=7.2,
                color="#566372",
            )
        ax.text(
            axis_index,
            -0.255,
            spec.label,
            ha="center",
            va="top",
            fontsize=9.0,
            fontweight="semibold",
            color="#273444",
        )

    missing_by_axis: dict[int, list[str]] = {}
    for profile in PROFILES:
        for axis_index, value in enumerate(values[profile]):
            if value is None:
                missing_by_axis.setdefault(axis_index, []).append(profile)

    for profile in reversed(PROFILES):
        style = PROFILE_STYLES[profile]
        normalized = np.array(
            [
                np.nan if value is None else spec.normalize(value)
                for spec, value in zip(axes, values[profile])
            ],
            dtype=float,
        )
        ax.plot(
            x_values,
            normalized,
            color=style["color"],
            linewidth=1.35,
            linestyle=style["linestyle"],
            solid_capstyle="round",
            zorder=3,
        )

        for axis_index, spec in enumerate(axes):
            value = values[profile][axis_index]
            if value is None:
                continue
            low_value = ci_low[profile][axis_index]
            high_value = ci_high[profile][axis_index]
            if low_value is not None and high_value is not None:
                low = spec.normalize(low_value)
                high = spec.normalize(high_value)
                interval_low, interval_high = sorted((low, high))
                ax.vlines(
                    axis_index,
                    interval_low,
                    interval_high,
                    color=style["color"],
                    linewidth=1.15,
                    alpha=0.65,
                    zorder=3,
                )
                ax.hlines(
                    (interval_low, interval_high),
                    axis_index - 0.018,
                    axis_index + 0.018,
                    color=style["color"],
                    linewidth=0.85,
                    alpha=0.65,
                    zorder=3,
                )
            if axis_index not in shared_value_axes:
                ax.scatter(
                    axis_index,
                    normalized[axis_index],
                    s=20,
                    marker=style["marker"],
                    facecolor=style["color"],
                    edgecolor="white",
                    linewidth=0.65,
                    zorder=4,
                )
                label_style = VALUE_LABEL_STYLE[profile]
                ax.annotate(
                    spec.value_formatter(value),
                    (axis_index, normalized[axis_index]),
                    xytext=label_style["xytext"],
                    textcoords="offset points",
                    ha=label_style["ha"],
                    va="center",
                    fontsize=6.8,
                    color=style["color"],
                    clip_on=False,
                    zorder=5,
                )

    profile_offsets = {"TC-Lite": -0.035, "TC-Protected": 0.0, "TC-Full": 0.035}
    for axis_index, missing_profiles in missing_by_axis.items():
        for profile in missing_profiles:
            style = PROFILE_STYLES[profile]
            ax.scatter(
                axis_index + profile_offsets[profile],
                -0.085,
                s=18,
                marker=style["marker"],
                facecolor="white",
                edgecolor=style["color"],
                linewidth=1.0,
                zorder=4,
            )
        ax.text(
            axis_index,
            -0.16,
            "N/A",
            ha="center",
            va="center",
            fontsize=6.8,
            color="#7A8490",
        )

    for axis_index in shared_value_axes:
        active = [
            (profile, values[profile][axis_index])
            for profile in PROFILES
            if values[profile][axis_index] is not None
        ]
        if not active:
            continue
        shared_value = float(active[0][1])
        shared_y = axes[axis_index].normalize(shared_value)
        for profile, size in zip(reversed(PROFILES), (42, 29, 15)):
            style = PROFILE_STYLES[profile]
            ax.scatter(
                axis_index,
                shared_y,
                s=size,
                marker=style["marker"],
                facecolor="white" if profile != "TC-Lite" else style["color"],
                edgecolor=style["color"],
                linewidth=1.0,
                zorder=4,
            )
        ax.annotate(
            f"{axes[axis_index].value_formatter(shared_value)} (all)",
            (axis_index, shared_y),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=6.8,
            color="#46515D",
            clip_on=False,
            zorder=5,
        )

    legend_handles = [
        Line2D(
            [0],
            [0],
            color=PROFILE_STYLES[profile]["color"],
            marker=PROFILE_STYLES[profile]["marker"],
            linestyle=PROFILE_STYLES[profile]["linestyle"],
            linewidth=1.35,
            markersize=4.6,
            markeredgecolor="white",
            label=legend_labels[profile],
        )
        for profile in PROFILES
    ]
    ax.legend(
        handles=legend_handles,
        ncol=3,
        frameon=False,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.045),
        columnspacing=1.1,
        handlelength=1.65,
        handletextpad=0.35,
        fontsize=7.6,
    )
    ax.set_xlim(-0.18, len(axes) - 0.82)
    ax.set_ylim(-0.32, 1.04)
    ax.axis("off")
    fig.text(
        0.985,
        0.025,
        "Independent axis scales; preferable direction is upward.",
        ha="right",
        va="bottom",
        fontsize=6.2,
        color="#6F7882",
    )
    return fig


def save_pdf(fig: plt.Figure, output_dirs: tuple[Path, ...], stem: str) -> list[Path]:
    paths: list[Path] = []
    metadata = {
        "Creator": "TrustCircuit benchmark pipeline",
        "Producer": "Matplotlib",
        "CreationDate": None,
        "ModDate": None,
    }
    for output_dir in output_dirs:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{stem}.pdf"
        fig.savefig(
            path,
            format="pdf",
            bbox_inches="tight",
            pad_inches=0.02,
            metadata=metadata,
        )
        paths.append(path)
    plt.close(fig)
    return paths


def plot_latency(
    output_dirs: tuple[Path, ...],
    by_profile: dict[str, dict[str, str]],
    stage_rows: dict[tuple[str, str], dict[str, str]],
) -> list[Path]:
    stages = ["access", "budget", "tee", "proof", "settlement", "audit"]
    axes = [
        AxisSpec("Access\n(ms ↓)", 0, 6, (0, 3, 6), lambda value: f"{value:.0f}", lambda value: f"{value:.2f}"),
        AxisSpec("Budget\n(ms ↓)", 0, 4, (0, 2, 4), lambda value: f"{value:.0f}", lambda value: f"{value:.2f}"),
        AxisSpec("TEE\n(ms ↓)", 0, 150, (0, 75, 150), lambda value: f"{value:.0f}", lambda value: f"{value:.2f}"),
        AxisSpec("Proof\n(ms ↓)", 0, 250, (0, 125, 250), lambda value: f"{value:.0f}", lambda value: f"{value:.2f}"),
        AxisSpec("Settlement\n(ms ↓)", 0, 6, (0, 3, 6), lambda value: f"{value:.0f}", lambda value: f"{value:.2f}"),
        AxisSpec("Audit\n(ms ↓)", 0, 1.5, (0, 0.75, 1.5), lambda value: f"{value:g}", lambda value: f"{value:.2f}"),
    ]

    def stage_value(profile: str, stage: str, field: str) -> float | None:
        mean = float(stage_rows[(profile, stage)]["mean_latency_ms"])
        if mean == 0.0:
            return None
        return float(stage_rows[(profile, stage)][field])

    values = {
        profile: [stage_value(profile, stage, "mean_latency_ms") for stage in stages]
        for profile in PROFILES
    }
    ci_low = {
        profile: [stage_value(profile, stage, "ci95_low_latency_ms") for stage in stages]
        for profile in PROFILES
    }
    ci_high = {
        profile: [stage_value(profile, stage, "ci95_high_latency_ms") for stage in stages]
        for profile in PROFILES
    }
    legend_labels = {
        profile: f"{profile} ({float(by_profile[profile]['mean_total_latency_ms']):.1f} ms)"
        for profile in PROFILES
    }
    fig = draw_parallel_coordinates(axes, values, ci_low, ci_high, legend_labels)
    return save_pdf(fig, output_dirs, "deployment_profile_a_latency_reused")


def plot_cost_resource(
    output_dirs: tuple[Path, ...], by_profile: dict[str, dict[str, str]]
) -> list[Path]:
    axes = [
        AxisSpec(
            "Capacity\n(req/s ↑)",
            0,
            180,
            (0, 90, 180),
            lambda value: f"{value:.0f}",
            lambda value: f"{value:.2f} req/s",
            lower_is_better=False,
        ),
        AxisSpec(
            "Gas\n(Mgas ↓)",
            0.4,
            1.4,
            (0.4, 0.9, 1.4),
            lambda value: f"{value:.1f}",
            lambda value: f"{value:.2f} Mgas",
        ),
        AxisSpec(
            "CPU\n(% ↓)",
            20,
            50,
            (20, 35, 50),
            lambda value: f"{value:.0f}",
            lambda value: f"{value:.2f}%",
        ),
        AxisSpec(
            "Peak RSS\n(GiB ↓)",
            1.0,
            1.3,
            (1.0, 1.15, 1.3),
            lambda value: f"{value:.2f}",
            lambda value: f"{value:.2f} GiB",
        ),
    ]
    field_specs = [
        ("mean_throughput_req_s", 1.0),
        ("mean_total_gas", 1 / 1_000_000),
        ("mean_normalized_peak_cpu_percent", 1.0),
        ("mean_peak_working_set_bytes", 1 / (1024**3)),
    ]
    values = {
        profile: [float(by_profile[profile][field]) * scale for field, scale in field_specs]
        for profile in PROFILES
    }
    ci_low = {
        profile: [
            float(by_profile[profile][field.replace("mean_", "ci95_low_")]) * scale
            for field, scale in field_specs
        ]
        for profile in PROFILES
    }
    ci_high = {
        profile: [
            float(by_profile[profile][field.replace("mean_", "ci95_high_")]) * scale
            for field, scale in field_specs
        ]
        for profile in PROFILES
    }
    legend_labels = {profile: profile for profile in PROFILES}
    fig = draw_parallel_coordinates(
        axes,
        values,
        ci_low,
        ci_high,
        legend_labels,
        shared_value_axes={3},
    )
    return save_pdf(fig, output_dirs, "deployment_profile_b_cost_resource_reused")


def main() -> None:
    args = parse_args()
    summary_rows = read_csv(args.input / "deployment_profile_summary.csv")
    stage_summary_rows = read_csv(args.input / "deployment_profile_stage_summary.csv")
    by_profile = {row["profile"]: row for row in summary_rows}
    stage_rows = {
        (row["profile"], row["stage"]): row for row in stage_summary_rows
    }
    output_dirs = tuple(dict.fromkeys((args.output, args.paper_output)))

    paths = [
        *plot_latency(output_dirs, by_profile, stage_rows),
        *plot_cost_resource(output_dirs, by_profile),
    ]
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
