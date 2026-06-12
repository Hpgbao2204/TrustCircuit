"""Plot TEE attack simulation results as readable paper PDF figures."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from textwrap import fill

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.paper_plot_style import PALETTE, apply_paper_style, remove_png_figures, save_pdf


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def short(text: str, width: int = 14) -> str:
    return fill(text.replace("_", " "), width=width)


def plot_subtle_phase_plane(summary: list[dict[str, str]], out_dir: Path) -> None:
    subtle_attacks = ["tampered_result", "tampered_attestation", "skip_dp_noise", "wrong_epsilon"]
    rows = [r for r in summary if r["attack_type"] in subtle_attacks]

    fig, ax = plt.subplots()
    for i, attack in enumerate(subtle_attacks):
        items = sorted([r for r in rows if r["attack_type"] == attack], key=lambda r: float(r["severity"]))
        detection = np.array([float(r["detection_rate"]) * 100 for r in items])
        success = np.array([float(r["attack_success_rate"]) * 100 for r in items])
        severity = np.array([float(r["severity"]) for r in items])
        ax.scatter(detection, success, s=90 + severity * 110, color=PALETTE[i % len(PALETTE)], alpha=0.78, label=short(attack, 20))
        ax.plot(detection, success, color=PALETTE[i % len(PALETTE)], alpha=0.68)
    ax.set_xlabel("detection rate (%)")
    ax.set_ylabel("attack success rate (%)")
    ax.set_title("Subtle attack phase plane")
    ax.grid(True, alpha=0.25)
    ax.legend()
    save_pdf(fig, out_dir, "tee_attack_subtle_phase_plane")


def plot_resource_profile(summary: list[dict[str, str]], out_dir: Path) -> None:
    rows = [r for r in summary if r["severity"] == "1.00"]
    rows = sorted(rows, key=lambda r: float(r["mean_total_tee_latency_ms"]))
    attacks = [short(r["attack_type"], 18) for r in rows]
    latency = np.array([float(r["mean_total_tee_latency_ms"]) / 1000 for r in rows])
    cpu = np.array([float(r["mean_cpu_time_ms"]) / 1000 for r in rows])

    y = np.arange(len(attacks))
    fig, ax = plt.subplots()
    ax.hlines(y, cpu, latency, color="#b8b8b8", linewidth=2)
    ax.scatter(cpu, y, color=PALETTE[1], s=80, label="CPU time")
    ax.scatter(latency, y, color=PALETTE[0], s=80, label="wall latency")
    ax.set_yticks(y, attacks)
    ax.set_xlabel("seconds")
    ax.set_title("Attack resource profile at severity 1.00")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right")
    save_pdf(fig, out_dir, "tee_attack_resource_profile")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=Path("results/summary/tee_attack_summary.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    args = parser.parse_args()

    apply_paper_style()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    remove_png_figures(args.out_dir)
    summary = read_csv(args.summary)
    plot_subtle_phase_plane(summary, args.out_dir)
    plot_resource_profile(summary, args.out_dir)
    print(args.out_dir)


if __name__ == "__main__":
    main()
