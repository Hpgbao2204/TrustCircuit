"""Generate readable paper-style PDF figures from TrustCircuit result CSVs."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from textwrap import fill

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from paper_plot_style import PALETTE, apply_paper_style, remove_png_figures, save_pdf


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def label(text: str, width: int = 13) -> str:
    return fill(text.replace("_", " "), width=width)


def annotate_heatmap(ax, matrix: np.ndarray, fmt: str = ".1f", color_threshold: float | None = None) -> None:
    threshold = float(np.nanmean(matrix)) if color_threshold is None else color_threshold
    for y in range(matrix.shape[0]):
        for x in range(matrix.shape[1]):
            value = matrix[y, x]
            color = "white" if value > threshold else "#111111"
            ax.text(x, y, format(value, fmt), ha="center", va="center", fontsize=11, color=color)


def heatmap_figure(
    matrix: np.ndarray,
    x_labels: list[str],
    y_labels: list[str],
    title: str,
    colorbar_label: str,
    out_dir: Path,
    name: str,
    cmap: str = "viridis",
    fmt: str = ".1f",
) -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(matrix, cmap=cmap, aspect="auto")
    ax.set_xticks(np.arange(len(x_labels)), [label(x, 10) for x in x_labels])
    ax.set_yticks(np.arange(len(y_labels)), [label(y, 16) for y in y_labels])
    ax.set_title(title)
    annotate_heatmap(ax, matrix, fmt=fmt)
    fig.colorbar(image, ax=ax, label=colorbar_label)
    save_pdf(fig, out_dir, name)


def plot_e2e_trajectory(summary: list[dict[str, str]], out_dir: Path) -> None:
    rows = [r for r in summary if r["stage"] == "TOTAL_PIPELINE"]
    variants = [r["variant"] for r in rows]
    latency = np.array([float(r["mean_latency_ms"]) for r in rows])
    gas = np.array([float(r["mean_gas_used"]) / 1000 for r in rows])
    throughput = np.array([float(r["throughput_req_s"]) for r in rows])

    fig = plt.figure()
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(latency, gas, throughput, color=PALETTE[0], marker="o")
    scatter = ax.scatter(latency, gas, throughput, s=120, c=throughput, cmap="plasma", depthshade=True)
    for variant, x, y, z in zip(variants, latency, gas, throughput):
        ax.text(x, y, z, variant, fontsize=12)
    ax.set_xlabel("latency (ms)")
    ax.set_ylabel("gas (k)")
    ax.set_zlabel("throughput (req/s)")
    ax.set_title("End-to-end performance trajectory")
    ax.view_init(elev=22, azim=-48)
    fig.colorbar(scatter, ax=ax, shrink=0.62, pad=0.08, label="throughput (req/s)")
    save_pdf(fig, out_dir, "e2e_latency_gas_throughput_trajectory")


def plot_dp_contour(dp_summary: list[dict[str, str]], out_dir: Path) -> None:
    queries = sorted({r["query"] for r in dp_summary})
    eps = sorted({float(r["epsilon"]) for r in dp_summary})
    by_key = {(r["query"], float(r["epsilon"])): float(r["relative_error_percent_mean"]) for r in dp_summary}
    matrix = np.array([[by_key[(query, epsilon)] for epsilon in eps] for query in queries])

    fig, ax = plt.subplots()
    x_grid, y_grid = np.meshgrid(np.arange(len(eps)), np.arange(len(queries)))
    contour = ax.contourf(x_grid, y_grid, matrix, levels=16, cmap="Blues")
    ax.contour(x_grid, y_grid, matrix, levels=8, colors="white", linewidths=0.7, alpha=0.75)
    ax.set_xticks(np.arange(len(eps)), [str(epsilon) for epsilon in eps])
    ax.set_yticks(np.arange(len(queries)), [label(query, 16) for query in queries])
    ax.set_xlabel("epsilon")
    ax.set_title("DP relative error contour")
    fig.colorbar(contour, ax=ax, label="relative error (%)")
    save_pdf(fig, out_dir, "dp_error_contour")


def plot_dp_phase_space(dp_summary: list[dict[str, str]], out_dir: Path) -> None:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in dp_summary:
        grouped[row["query"]].append(row)

    fig, ax = plt.subplots()
    for i, (query, rows) in enumerate(sorted(grouped.items())):
        rows = sorted(rows, key=lambda r: float(r["epsilon"]))
        eps = np.array([float(r["epsilon"]) for r in rows])
        p95 = np.array([float(r["relative_error_p95"]) * 100 for r in rows])
        mean_err = np.array([float(r["relative_error_percent_mean"]) for r in rows])
        ax.scatter(mean_err, p95, s=70 + eps * 24, color=PALETTE[i % len(PALETTE)], alpha=0.78, label=label(query, 18))
        ax.plot(mean_err, p95, color=PALETTE[i % len(PALETTE)], alpha=0.58)
    ax.set_xlabel("mean relative error (%)")
    ax.set_ylabel("p95 relative error (%)")
    ax.set_title("DP utility phase space")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, fontsize=11)
    save_pdf(fig, out_dir, "dp_utility_phase_space")


def plot_tee_pool_heatmap(tee_summary: list[dict[str, str]], out_dir: Path) -> None:
    modes = sorted({r["mode"] for r in tee_summary})
    pools = sorted({int(r["pool_size"]) for r in tee_summary})
    by_key = {(r["mode"], int(r["pool_size"])): float(r["compute_latency_p95_ms"]) for r in tee_summary}
    matrix = np.array([[by_key.get((mode, pool), 0.0) for pool in pools] for mode in modes])
    heatmap_figure(matrix, [str(pool) for pool in pools], modes, "TEE pool p95 latency", "p95 latency (ms)", out_dir, "tee_pool_latency_heatmap", "YlGnBu", ".2f")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    parser.add_argument("--e2e-summary", type=Path, default=Path("results/summary/e2e_pipeline_summary.csv"))
    parser.add_argument("--gas-summary", type=Path, default=Path("results/summary/contract_gas_summary.csv"))
    parser.add_argument("--dp-summary", type=Path, default=Path("results/summary/dp_utility_summary.csv"))
    parser.add_argument("--tee-summary", type=Path, default=Path("results/summary/tee_pool_summary.csv"))
    args = parser.parse_args()

    apply_paper_style()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    remove_png_figures(args.out_dir)
    e2e_summary = read_csv(args.e2e_summary)
    dp_summary = read_csv(args.dp_summary)
    tee_summary = read_csv(args.tee_summary)

    plot_e2e_trajectory(e2e_summary, args.out_dir)
    plot_dp_contour(dp_summary, args.out_dir)
    plot_dp_phase_space(dp_summary, args.out_dir)
    plot_tee_pool_heatmap(tee_summary, args.out_dir)
    print(args.out_dir)


if __name__ == "__main__":
    main()
