"""Render the paper-ready Nitro figures with enlarged typography.

The script reads the existing canonical Nitro CSV files and writes only the
six requested PDFs to ``Paper/Figure/figures/nitro_new``.  It does not create
PNG files and does not modify the benchmark data.
"""

from __future__ import annotations

from pathlib import Path

import plot_nitro_figure6 as figure6
import plot_nitro_results as results


REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "Paper" / "Figure" / "figures" / "nitro_new"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results.OUT_DIR = OUT_DIR
    results.SELECTED_OUTPUTS = {
        "nitro_pool_per_worker_throughput",
        "nitro_pool_parallel_efficiency",
        "nitro_payload_throughput",
        "nitro_latency_vs_payload",
    }
    results.apply_nitro_style(font_delta=4)
    latency_summary = results.summarize(results.read_rows())
    results.plot_latency(latency_summary)
    results.plot_throughput(latency_summary)
    results.plot_pool(results.read_csv(results.POOL_CSV))

    figure6.OUT_DIR = OUT_DIR
    figure6.apply_nitro_style(font_delta=1)
    figure6.fig_latency_composition_area()
    figure6.fig_attestation_amortization()

    for name in sorted(
        results.SELECTED_OUTPUTS
        | {"n1_latency_composition_area", "n3_attestation_amortization"}
    ):
        print(OUT_DIR / f"{name}.pdf")


if __name__ == "__main__":
    main()
