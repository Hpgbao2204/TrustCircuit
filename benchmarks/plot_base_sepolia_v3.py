"""Plot the two Base Sepolia panels from the latest full v3 campaign.

Same style as benchmarks/process_base_sepolia_vcp_v2.py. Reads
results/raw/testnet/base_sepolia_v3_full_*/{transactions.csv,run_summary.json}
and writes results/figures/figure_1a_deployment_resources.pdf and
figure_2a_settlement_latency.pdf.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "results" / "raw" / "testnet"
FIGURE_ROOT = ROOT / "results" / "figures"
PALETTE = ["#286F9E", "#E58C3B", "#3E9C76", "#C8514D", "#8064A2"]
SHORT = {
    "DataRegistry": "Data reg.", "AccessController": "Access", "BudgetLedger": "Budget",
    "AuditLedger": "Audit", "ValidatorRegistry": "Validator", "VCPv3Groth16Verifier": "VCP ver.",
    "ComplianceVerifier": "Adapter", "TrustCircuitSettlement": "Settlement", "TimelockMultisig": "Multisig",
}


def style() -> None:
    plt.rcdefaults()
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9.5, "axes.labelsize": 10.5, "xtick.labelsize": 8.5,
        "ytick.labelsize": 9.0, "legend.fontsize": 8.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.axisbelow": True, "grid.alpha": 0.28, "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def save(fig, name: str) -> None:
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.8)
    fig.savefig(FIGURE_ROOT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.04,
                metadata={"Creator": "TrustCircuit plotter", "CreationDate": None, "ModDate": None})
    plt.close(fig)


def main() -> None:
    runs = sorted(RAW_ROOT.glob("base_sepolia_v3_full_*"))
    if not runs:
        raise SystemExit("no full v3 campaign found")
    run = runs[-1]
    rows = list(csv.DictReader((run / "transactions.csv").open()))
    summary = json.loads((run / "run_summary.json").read_text())
    style()

    deploys = [r for r in rows if r["category"] == "deployment"]
    x = np.arange(len(deploys))
    gas = np.array([int(r["gas_used"]) / 1e6 for r in deploys])
    calldata = np.array([int(r["calldata_bytes"]) / 1024 for r in deploys])
    labels = [SHORT[r["operation"].replace("deploy_", "")] for r in deploys]
    fig, axis = plt.subplots(figsize=(4.6, 3.5))
    axis.bar(x, gas, width=0.55, color=PALETTE[0], alpha=0.88, label="Deployment gas")
    axis.set_ylabel("Gas used (millions)")
    axis.set_xticks(x, labels)
    axis.tick_params(axis="x", rotation=32, labelsize=7.8)
    for label in axis.get_xticklabels():
        label.set_horizontalalignment("right")
    twin = axis.twinx()
    twin.plot(x, calldata, color=PALETTE[1], marker="o", linewidth=1.7, label="Calldata")
    twin.set_ylabel("Calldata (KiB)")
    twin.grid(False)
    ha, la = axis.get_legend_handles_labels()
    hb, lb = twin.get_legend_handles_labels()
    axis.legend(ha + hb, la + lb, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    save(fig, "figure_1a_deployment_resources")

    settles = [float(r["inclusion_latency_ms"]) / 1000 for r in rows if r["category"] == "settlement"]
    p50 = summary["inclusion_latency_s"]["p50"]
    p95 = summary["inclusion_latency_s"]["p95"]
    fig, axis = plt.subplots(figsize=(4.6, 3.5))
    idx = np.arange(1, len(settles) + 1)
    axis.plot(idx, settles, color=PALETTE[0], marker="o", markersize=3.3, linewidth=1.25, label="Measured run")
    axis.axhline(p50, color=PALETTE[2], linestyle="--", linewidth=1.5, label=f"p50 = {p50:,.2f}")
    axis.axhline(p95, color=PALETTE[1], linestyle=":", linewidth=1.7, label=f"p95 = {p95:,.2f}")
    axis.set_xlabel("Accepted settlement index")
    axis.set_ylabel("Client-observed inclusion (s)")
    axis.set_xlim(1, len(settles))
    axis.set_ylim(bottom=0)
    axis.legend(frameon=False, loc="best")
    save(fig, "figure_2a_settlement_latency")
    print(json.dumps({"run": run.name, "settlements": len(settles), "figures": str(FIGURE_ROOT)}))


if __name__ == "__main__":
    main()
