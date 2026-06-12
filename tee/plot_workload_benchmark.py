"""Plot TEE workload benchmark outputs as paper-ready PDF figures."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.paper_plot_style import PALETTE, apply_paper_style, remove_png_figures, save_pdf


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plot_scaling_trajectory(rows: list[dict[str, str]], out_dir: Path) -> None:
    workers = np.array([int(r["worker_count"]) for r in rows])
    throughput = np.array([float(r["throughput_req_s"]) for r in rows])
    p95 = np.array([float(r["p95_latency_ms"]) / 1000 for r in rows])
    ram = np.array([float(r["estimated_active_ram_mb"]) / 1024 for r in rows])

    fig = plt.figure()
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(workers, throughput, p95, color=PALETTE[0], marker="o")
    scatter = ax.scatter(workers, throughput, p95, s=70 + ram * 8, c=ram, cmap="viridis", depthshade=True)
    for worker, x, y, z in zip(workers, workers, throughput, p95):
        ax.text(x, y, z, str(worker), fontsize=12)
    ax.set_xlabel("worker count")
    ax.set_ylabel("throughput (req/s)")
    ax.set_zlabel("p95 latency (s)")
    ax.set_title("TEE workload scaling trajectory")
    ax.view_init(elev=24, azim=-54)
    fig.colorbar(scatter, ax=ax, shrink=0.62, pad=0.08, label="active RAM (GB)")
    save_pdf(fig, out_dir, "tee_workload_scaling_trajectory")


def plot_latency_bands(rows: list[dict[str, str]], out_dir: Path) -> None:
    workers = np.array([int(r["worker_count"]) for r in rows])
    p50 = np.array([float(r["p50_latency_ms"]) / 1000 for r in rows])
    p95 = np.array([float(r["p95_latency_ms"]) / 1000 for r in rows])
    p99 = np.array([float(r["p99_latency_ms"]) / 1000 for r in rows])

    fig, ax = plt.subplots()
    ax.fill_between(workers, p50, p99, color=PALETTE[0], alpha=0.12, label="p50-p99 band")
    ax.fill_between(workers, p50, p95, color=PALETTE[0], alpha=0.22, label="p50-p95 band")
    ax.plot(workers, p50, color=PALETTE[0], marker="o", label="p50")
    ax.plot(workers, p95, color=PALETTE[3], marker="s", label="p95")
    ax.plot(workers, p99, color=PALETTE[1], marker="^", label="p99")
    ax.set_xlabel("worker count")
    ax.set_ylabel("latency (s)")
    ax.set_title("TEE latency percentile bands")
    ax.grid(True, alpha=0.25)
    ax.legend()
    save_pdf(fig, out_dir, "tee_workload_latency_bands")


def plot_resource_contour(rows: list[dict[str, str]], out_dir: Path) -> None:
    workers = np.array([int(r["worker_count"]) for r in rows])
    cpu = np.array([float(r["cpu_utilization_estimate_pct"]) for r in rows])
    ram = np.array([float(r["estimated_active_ram_mb"]) / 1024 for r in rows])
    throughput = np.array([float(r["throughput_req_s"]) for r in rows])

    fig, ax = plt.subplots()
    scatter = ax.scatter(cpu, ram, s=90 + throughput * 12, c=workers, cmap="plasma", alpha=0.78)
    ax.plot(cpu, ram, color=PALETTE[2], alpha=0.7)
    for worker, x, y in zip(workers, cpu, ram):
        ax.annotate(str(worker), (x, y), xytext=(6, 6), textcoords="offset points", fontsize=12)
    ax.set_xlabel("CPU utilization estimate (%)")
    ax.set_ylabel("estimated active RAM (GB)")
    ax.set_title("TEE resource pressure phase space")
    ax.grid(True, alpha=0.25)
    fig.colorbar(scatter, ax=ax, label="worker count")
    save_pdf(fig, out_dir, "tee_workload_resource_phase_space")


def plot_efficiency_phase_space(rows: list[dict[str, str]], out_dir: Path) -> None:
    workers = np.array([int(r["worker_count"]) for r in rows])
    throughput = np.array([float(r["throughput_req_s"]) for r in rows])
    baseline = throughput[0] if len(throughput) else 1.0
    speedup = throughput / baseline
    ideal = workers / workers[0]
    efficiency = np.divide(speedup, ideal, out=np.zeros_like(speedup), where=ideal != 0) * 100
    per_worker = np.array([float(r["throughput_per_worker_req_s"]) for r in rows])

    fig, ax = plt.subplots()
    scatter = ax.scatter(speedup, efficiency, s=90 + workers * 7, c=per_worker, cmap="cividis", alpha=0.78)
    ax.plot(speedup, efficiency, color=PALETTE[0], alpha=0.72)
    for worker, x, y in zip(workers, speedup, efficiency):
        ax.annotate(str(worker), (x, y), xytext=(6, 6), textcoords="offset points", fontsize=12)
    ax.set_xlabel("measured speedup")
    ax.set_ylabel("scaling efficiency (%)")
    ax.set_title("TEE efficiency phase space")
    ax.grid(True, alpha=0.25)
    fig.colorbar(scatter, ax=ax, label="throughput per worker (req/s)")
    save_pdf(fig, out_dir, "tee_workload_efficiency_phase_space")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=Path("results/summary/tee_workload_summary.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    args = parser.parse_args()

    apply_paper_style()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    remove_png_figures(args.out_dir)
    rows = sorted(read_csv(args.summary), key=lambda r: int(r["worker_count"]))
    plot_scaling_trajectory(rows, args.out_dir)
    plot_latency_bands(rows, args.out_dir)
    plot_resource_contour(rows, args.out_dir)
    plot_efficiency_phase_space(rows, args.out_dir)
    print(args.out_dir)


if __name__ == "__main__":
    main()
