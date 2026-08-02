"""Validate, summarize, and plot the canonical Base Sepolia VCP v2 campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import time
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "results" / "raw" / "phase8" / "testnet"
SUMMARY_ROOT = ROOT / "results" / "summary"
FIGURE_ROOT = ROOT / "Paper" / "Figure" / "figures" / "base-sepolia"
EXPECTED_CHAIN_ID = 84532
PALETTE = ["#286F9E", "#E58C3B", "#3E9C76", "#C8514D", "#8064A2"]


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("cannot summarize an empty measurement set")
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def rpc_call(url: str, method: str, params: list[object]) -> object:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "TrustCircuit-VCPv2-Evidence/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            return payload.get("result")
        except Exception as error:  # pragma: no cover - network retry branch
            last_error = error
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"RPC {method} failed after three attempts: {last_error}")


def latest_full_run() -> Path:
    candidates = sorted(RAW_ROOT.glob("base_sepolia_vcp_v2_full_*"))
    if not candidates:
        raise FileNotFoundError("no full Base Sepolia VCP v2 run found")
    return candidates[-1]


def short_contract(operation: str) -> str:
    return {
        "deploy_DataRegistry": "Data reg.",
        "deploy_AccessController": "Access",
        "deploy_BudgetLedger": "Budget",
        "deploy_AuditLedger": "Audit",
        "deploy_ValidatorRegistry": "Validator",
        "deploy_VCPGroth16Verifier": "VCP ver.",
        "deploy_ComplianceVerifier": "Adapter",
        "deploy_TrustCircuitSettlement": "Settlement",
    }[operation]


def apply_style() -> None:
    plt.rcdefaults()
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 9.0,
            "legend.fontsize": 8.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.28,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, name: str) -> None:
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.8)
    fig.savefig(
        FIGURE_ROOT / f"{name}.pdf",
        bbox_inches="tight",
        pad_inches=0.04,
        metadata={"Creator": "TrustCircuit VCP v2 processor", "CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def plot_deployments(deployments: list[dict[str, object]]) -> None:
    x = np.arange(len(deployments))
    gas = np.array([float(item["gas_used"]) / 1e6 for item in deployments])
    calldata = np.array([float(item["calldata_bytes"]) / 1024 for item in deployments])
    labels = [short_contract(str(item["operation"])) for item in deployments]
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
    handles_a, labels_a = axis.get_legend_handles_labels()
    handles_b, labels_b = twin.get_legend_handles_labels()
    axis.legend(handles_a + handles_b, labels_a + labels_b, frameon=False, loc="upper left")
    save(fig, "figure_1a_deployment_resources")


def plot_series(
    values: list[float],
    metric: dict[str, float],
    ylabel: str,
    name: str,
    scale: float = 1.0,
) -> None:
    x = np.arange(1, len(values) + 1)
    y = np.array(values) / scale
    p50 = metric["p50"] / scale
    p95 = metric["p95"] / scale
    fig, axis = plt.subplots(figsize=(4.6, 3.5))
    axis.plot(x, y, color=PALETTE[0], marker="o", markersize=3.3, linewidth=1.25, label="Measured run")
    axis.axhline(p50, color=PALETTE[2], linestyle="--", linewidth=1.5, label=f"p50 = {p50:,.2f}")
    axis.axhline(p95, color=PALETTE[1], linestyle=":", linewidth=1.7, label=f"p95 = {p95:,.2f}")
    axis.set_xlabel("Accepted settlement index")
    axis.set_ylabel(ylabel)
    axis.set_xlim(1, len(values))
    axis.legend(frameon=False, loc="best")
    save(fig, name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=None)
    args = parser.parse_args()
    run_dir = (args.run_dir or latest_full_run()).resolve()
    transactions_path = run_dir / "transactions.csv"
    proofs_path = run_dir / "proof_preparation.csv"
    config_path = run_dir / "config.json"
    result_path = run_dir / "run_result.json"
    for path in (transactions_path, proofs_path, config_path, result_path):
        if not path.exists():
            raise FileNotFoundError(path)

    rows = read_csv(transactions_path)
    proof_rows = read_csv(proofs_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if int(config["chain_id"]) != EXPECTED_CHAIN_ID or int(config["public_inputs"]) != 24:
        raise AssertionError("campaign is not the canonical Base Sepolia/24-input run")
    if len(rows) != 135 or len(proof_rows) != 30 or result["atomic_settlements"] != 30:
        raise AssertionError("expected 135 transactions, 30 proofs, and 30 settlements")
    if any(row["status"] != "1" for row in rows) or any(row["verified"] != "1" for row in proof_rows):
        raise AssertionError("campaign contains a failed transaction or proof")

    rpc_url = f"https://{config['rpc_host']}"
    chain_id_hex = rpc_call(rpc_url, "eth_chainId", [])
    if int(str(chain_id_hex), 16) != EXPECTED_CHAIN_ID:
        raise AssertionError("RPC endpoint no longer reports Base Sepolia")

    deployment_rows = [row for row in rows if row["category"] == "deployment"]
    settlement_rows = [row for row in rows if re.fullmatch(r"request_\d+_settle_vcp_v2", row["operation"])]
    if len(deployment_rows) != 8 or len(settlement_rows) != 30:
        raise AssertionError("unexpected deployment or settlement row count")

    deployments: list[dict[str, object]] = []
    for row in deployment_rows:
        transaction = rpc_call(rpc_url, "eth_getTransactionByHash", [row["tx_hash"]])
        if not isinstance(transaction, dict) or transaction.get("hash") != row["tx_hash"]:
            raise AssertionError(f"could not bind deployment transaction {row['tx_hash']}")
        calldata_bytes = (len(str(transaction["input"])) - 2) // 2
        deployments.append(
            {
                "operation": row["operation"],
                "contract": row["operation"].removeprefix("deploy_"),
                "gas_used": int(row["gas_used"]),
                "calldata_bytes": calldata_bytes,
                "fee_wei": int(row["fee_wei"]),
                "tx_hash": row["tx_hash"],
            }
        )

    gas = [float(row["gas_used"]) for row in settlement_rows]
    fee_micro_eth = [float(row["fee_wei"]) / 1e12 for row in settlement_rows]
    inclusion_ms = [float(row["inclusion_latency_ms"]) for row in settlement_rows]
    prove_ms = [float(row["prove_time_ms"]) for row in proof_rows]
    verify_ms = [float(row["verify_time_ms"]) for row in proof_rows]
    summary = {
        "schema": "TrustCircuit.BaseSepoliaVCPv2Summary.v1",
        "measurement_type": "measured_public_testnet",
        "run_id": result["run_id"],
        "chain_id": EXPECTED_CHAIN_ID,
        "public_inputs": 24,
        "contract_count": 8,
        "transaction_count": len(rows),
        "atomic_settlements": len(settlement_rows),
        "final_budget_used": int(result["final_budget_used"]),
        "deployment_total_gas": sum(int(item["gas_used"]) for item in deployments),
        "deployment_total_calldata_bytes": sum(int(item["calldata_bytes"]) for item in deployments),
        "settlement_gas": stats(gas),
        "settlement_fee_micro_eth": stats(fee_micro_eth),
        "settlement_inclusion_ms": stats(inclusion_ms),
        "offchain_prove_ms": stats(prove_ms),
        "offchain_verify_ms": stats(verify_ms),
        "raw_sha256": {
            "transactions.csv": sha256(transactions_path),
            "proof_preparation.csv": sha256(proofs_path),
            "config.json": sha256(config_path),
            "run_result.json": sha256(result_path),
        },
    }

    SUMMARY_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_ROOT / "base_sepolia_vcp_v2_summary.json"
    deployments_path = SUMMARY_ROOT / "base_sepolia_vcp_v2_deployments.csv"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with deployments_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(deployments[0]))
        writer.writeheader()
        writer.writerows(deployments)

    apply_style()
    plot_deployments(deployments)
    plot_series(
        inclusion_ms,
        summary["settlement_inclusion_ms"],
        "Client-observed inclusion (s)",
        "figure_2a_settlement_latency",
        1000,
    )
    print(json.dumps({"ok": True, "summary": str(summary_path), "figures": str(FIGURE_ROOT)}))


if __name__ == "__main__":
    main()
