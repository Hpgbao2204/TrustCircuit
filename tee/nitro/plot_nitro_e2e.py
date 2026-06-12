"""Update TrustCircuit E2E figures with measured Nitro TEE compute.

This keeps the original E2E blockchain/ZK stages unchanged and replaces only
the tee_compute stage with the measured AWS Nitro Enclaves worker latency.
It rewrites the two paper-facing E2E figures:

  results/figures/e2e/e4_throughput.pdf
  results/figures/e2e/e7_latency_waterfall.pdf
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmarks"))

try:
    from make_paper_figures import E2E_STAGE_ORDER, SHORT_STAGE, apply_style  # noqa: E402
except ModuleNotFoundError:
    E2E_STAGE_ORDER = [
        "registerAsset", "requestAccess", "approveRequest", "registerBudget", "reserveBudget",
        "tee_compute", "mock_prove", "submitProof", "consumeBudget", "recordAudit", "completeRequest",
        "register_offchain", "request_offchain", "compute_offchain", "audit_offchain",
    ]
    SHORT_STAGE = {
        "registerAsset": "register", "requestAccess": "request", "approveRequest": "approve",
        "registerBudget": "regBudget", "reserveBudget": "reserve", "tee_compute": "TEE",
        "mock_prove": "prove", "submitProof": "verify", "consumeBudget": "consume",
        "recordAudit": "audit", "completeRequest": "complete", "compute_offchain": "compute",
        "register_offchain": "register", "request_offchain": "request", "audit_offchain": "audit",
    }

    def apply_style() -> None:
        plt.rcParams.update(
            {
                "figure.figsize": (12.0, 6.0),
                "font.size": 16,
                "axes.titlesize": 16,
                "axes.labelsize": 16,
                "xtick.labelsize": 14,
                "ytick.labelsize": 14,
                "legend.fontsize": 14,
                "lines.linewidth": 2.4,
                "lines.markersize": 8,
                "axes.axisbelow": True,
                "savefig.format": "pdf",
                "pdf.fonttype": 42,
                "ps.fonttype": 42,
            }
        )


E2E_SUMMARY = REPO / "results" / "summary" / "e2e_pipeline_summary.csv"
NITRO_SUMMARY = REPO / "results" / "summary" / "nitro_latency_summary.csv"
NITRO_RAW = REPO / "results" / "raw" / "nitro_latency.csv"
OUT_DIR = REPO / "results" / "figures" / "e2e"
ADJUSTED_SUMMARY = REPO / "results" / "summary" / "e2e_pipeline_summary_nitro.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def nitro_tee_metrics(payload_mib: int = 1) -> dict[str, float]:
    if NITRO_RAW.exists():
        values = [
            float(row["end_to_end_latency_ms"])
            for row in read_csv(NITRO_RAW)
            if int(float(row["payload_mib"])) == payload_mib
        ]
        if values:
            return {
                "mean_latency_ms": statistics.mean(values),
                "std_latency_ms": statistics.stdev(values) if len(values) > 1 else 0.0,
                "p50_latency_ms": statistics.median(values),
                "p95_latency_ms": percentile(values, 0.95),
                "p99_latency_ms": percentile(values, 0.99),
            }

    for row in read_csv(NITRO_SUMMARY):
        if int(float(row["payload_mib"])) == payload_mib:
            return {
                "mean_latency_ms": float(row["e2e_mean_ms"]),
                "std_latency_ms": 0.0,
                "p50_latency_ms": float(row["e2e_median_ms"]),
                "p95_latency_ms": float(row["e2e_max_ms"]),
                "p99_latency_ms": float(row["e2e_max_ms"]),
            }
    raise ValueError(f"missing Nitro payload {payload_mib} MiB in {NITRO_SUMMARY}")


def adjusted_rows(rows: list[dict[str, str]], replacement: dict[str, float]) -> list[dict[str, str]]:
    out = [dict(row) for row in rows]
    original_tee_by_variant: dict[str, dict[str, float]] = {}
    variants_with_tee: set[str] = set()
    latency_fields = ("mean_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms")

    for row in out:
        if row["stage"] == "tee_compute":
            variants_with_tee.add(row["variant"])
            original_tee_by_variant[row["variant"]] = {
                field: float(row[field]) for field in latency_fields
            }
            for field in latency_fields:
                row[field] = f"{replacement[field]:.6f}"
            row["std_latency_ms"] = f"{replacement['std_latency_ms']:.6f}"
            row["throughput_req_s"] = ""

    for row in out:
        if row["stage"] == "TOTAL_PIPELINE" and row["variant"] in variants_with_tee:
            for field in latency_fields:
                delta = replacement[field] - original_tee_by_variant[row["variant"]][field]
                row[field] = f"{max(float(row[field]) + delta, 0.0):.6f}"
            row["std_latency_ms"] = f"{replacement['std_latency_ms']:.6f}"
            mean = float(row["mean_latency_ms"])
            row["throughput_req_s"] = f"{1000.0 / mean:.6f}" if mean > 0 else "0.000000"

    return out


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_throughput(rows: list[dict[str, str]]) -> Path:
    totals = {r["variant"]: r for r in rows if r["stage"] == "TOTAL_PIPELINE"}
    variants = sorted(totals)
    thr = np.array([float(totals[v]["throughput_req_s"]) for v in variants])

    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(variants, thr, color=cm.cividis(np.linspace(0.1, 0.9, len(variants))))
    ax.set_ylabel("throughput (req/s)")
    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(variants, rotation=20, ha="right")
    ax.set_ylim(0, max(thr) * 1.18)
    for bar, value in zip(bars, thr):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.1f}",
                ha="center", va="bottom", fontsize=13)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "e4_throughput.pdf"
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return out


def plot_waterfall(rows: list[dict[str, str]]) -> Path:
    tc = []
    for stage in E2E_STAGE_ORDER:
        for row in rows:
            if row["variant"] == "TC-Full" and row["stage"] == stage:
                tc.append((stage, float(row["mean_latency_ms"])))

    names = [SHORT_STAGE.get(stage, stage) for stage, _ in tc]
    stage_lat = np.array([ms for _, ms in tc])
    cum = np.cumsum(stage_lat)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = cm.viridis(np.linspace(0.1, 0.9, len(tc)))
    bars = ax.bar(range(len(tc)), stage_lat, color=colors, label="per-stage")
    for bar, value in zip(bars, stage_lat):
        if value >= max(stage_lat) * 0.08:
            ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.1f}",
                    ha="center", va="bottom", fontsize=11)
    ax.set_ylabel("per-stage latency (ms)")
    ax.set_xticks(range(len(tc)))
    ax.set_xticklabels(names, rotation=55, ha="right")
    ax.grid(True, axis="y", alpha=0.25)

    ax2 = ax.twinx()
    ax2.plot(range(len(cum)), cum, color="#cc3311", marker="o", lw=2.4, label="cumulative")
    ax2.set_ylabel("cumulative latency (ms)", color="#cc3311")
    ax2.tick_params(axis="y", labelcolor="#cc3311")
    ax.legend(loc="upper left", fontsize=12, frameon=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "e7_latency_waterfall.pdf"
    fig.savefig(out, dpi=300, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return out


def main() -> None:
    apply_style()
    rows = read_csv(E2E_SUMMARY)
    replacement = nitro_tee_metrics(payload_mib=1)
    adjusted = adjusted_rows(rows, replacement)
    write_csv(ADJUSTED_SUMMARY, adjusted)
    e4 = plot_throughput(adjusted)
    e7 = plot_waterfall(adjusted)
    print(f"TEE stage replaced with Nitro 1 MiB mean: {replacement['mean_latency_ms']:.3f} ms")
    print(f"wrote {ADJUSTED_SUMMARY}")
    print(f"wrote {e4}")
    print(f"wrote {e7}")


if __name__ == "__main__":
    main()
