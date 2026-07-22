"""Summarize and plot the measured Base Sepolia settlement experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np
from scipy.interpolate import PchipInterpolator

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "results" / "raw" / "phase8" / "testnet"
PROCESSED_ROOT = ROOT / "results" / "processed" / "testnet"

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]
KEY_OPERATION_LABELS = {
    "atomic_settlement_valid": "Valid settlement",
    "attack_control_valid_settlement": "Valid control",
    "revert_context_mismatch": "Context mismatch",
    "revert_invalid_proof": "Tampered proof",
    "revert_replay": "Replay",
}


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def numeric(rows: list[dict[str, str]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field, "")
        if value not in ("", None):
            values.append(float(value))
    return values


def summarize_group(label: str, category: str, operation: str, rows: list[dict[str, str]]) -> dict[str, object]:
    gas = numeric(rows, "gas_used")
    calldata = numeric(rows, "calldata_bytes")
    inclusion = numeric(rows, "inclusion_latency_ms")
    confirm_5 = numeric(rows, "confirmation_5_latency_ms")
    confirm_12 = numeric(rows, "confirmation_12_latency_ms")
    total_fee = numeric(rows, "total_fee_wei")

    def mean(values: list[float]) -> float | None:
        return statistics.fmean(values) if values else None

    def median(values: list[float]) -> float | None:
        return statistics.median(values) if values else None

    def stddev(values: list[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0

    return {
        "label": label,
        "category": category,
        "operation": operation,
        "runs": len(rows),
        "successful": sum(int(row["success"]) for row in rows),
        "reverted": sum(1 - int(row["success"]) for row in rows),
        "rollback_pass_rate": (
            statistics.fmean(float(row["rollback_verified"]) for row in rows if row["rollback_verified"] != "")
            if any(row["rollback_verified"] != "" for row in rows)
            else None
        ),
        "mean_gas_used": mean(gas),
        "median_gas_used": median(gas),
        "std_gas_used": stddev(gas),
        "p95_gas_used": percentile(gas, 0.95),
        "mean_calldata_bytes": mean(calldata),
        "median_calldata_bytes": median(calldata),
        "mean_inclusion_ms": mean(inclusion),
        "median_inclusion_ms": median(inclusion),
        "std_inclusion_ms": stddev(inclusion),
        "p95_inclusion_ms": percentile(inclusion, 0.95),
        "median_confirmation_5_ms": median(confirm_5),
        "p95_confirmation_5_ms": percentile(confirm_5, 0.95),
        "median_confirmation_12_ms": median(confirm_12),
        "p95_confirmation_12_ms": percentile(confirm_12, 0.95),
        "mean_total_fee_wei": mean(total_fee),
    }


def finite(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def save_figure(fig: plt.Figure, output_dir: Path, name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.9)
    fig.savefig(output_dir / f"{name}.pdf", dpi=300)
    plt.close(fig)


def clean_figure_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("base_sepolia_*"):
        if path.is_file() and path.suffix.lower() in {".pdf", ".png", ".svg"}:
            path.unlink()


def selected_groups(rows: list[dict[str, str]], operations: list[str]) -> list[list[dict[str, str]]]:
    return [[row for row in rows if row["operation"] == operation] for operation in operations]


def add_violin_jitter(
    axis: plt.Axes,
    datasets: list[list[float]],
    labels: list[str],
    colors: list[str],
    seed: int,
) -> None:
    positions = np.arange(1, len(datasets) + 1)
    parts = axis.violinplot(datasets, positions=positions, widths=0.78, showextrema=False)
    for body, color in zip(parts["bodies"], colors):
        body.set_facecolor(color)
        body.set_edgecolor("none")
        body.set_alpha(0.28)
    rng = np.random.default_rng(seed)
    for position, values, color in zip(positions, datasets, colors):
        jitter = rng.uniform(-0.17, 0.17, len(values))
        axis.scatter(
            np.full(len(values), position) + jitter,
            values,
            s=26,
            color=color,
            alpha=0.72,
            edgecolors="white",
            linewidths=0.35,
            zorder=3,
        )
        axis.scatter(
            [position],
            [statistics.median(values)],
            marker="D",
            s=58,
            color="white",
            edgecolors="#222222",
            linewidths=1.0,
            zorder=4,
        )
    axis.set_xticks(positions, labels)


def plot_deployments(rows: list[dict[str, str]], output_dir: Path) -> None:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["category"] == "deployment":
            groups[row["operation"].removeprefix("deploy_")].append(row)
    names = list(groups)
    gas = np.array([statistics.median(numeric(groups[name], "gas_used")) / 1e6 for name in names])
    calldata = np.array([statistics.median(numeric(groups[name], "calldata_bytes")) / 1024 for name in names])
    inclusion = np.array([statistics.median(numeric(groups[name], "inclusion_latency_ms")) / 1000 for name in names])
    fig, axis = plt.subplots(figsize=(10.5, 6.8))
    points = axis.scatter(
        calldata,
        gas,
        c=inclusion,
        s=165,
        cmap="viridis",
        edgecolors="#202020",
        linewidths=0.8,
    )
    short_names = {
        "Phase7Groth16Verifier": "Groth16 verifier",
        "ComplianceVerifier": "Compliance adapter",
        "TrustCircuitSettlement": "Settlement",
    }
    label_offsets = {
        "AuditLedger": (9, 7, "left"),
        "DataRegistry": (9, 7, "left"),
        "BudgetLedger": (-10, -20, "right"),
        "Phase7Groth16Verifier": (10, 11, "left"),
        "AccessController": (-10, 8, "right"),
        "ComplianceVerifier": (-10, 8, "right"),
        "TrustCircuitSettlement": (-10, 8, "right"),
    }
    for index, name in enumerate(names):
        dx, dy, ha = label_offsets[name]
        axis.annotate(
            short_names.get(name, name),
            (calldata[index], gas[index]),
            xytext=(dx, dy),
            textcoords="offset points",
            ha=ha,
            fontsize=8.5,
        )
    colorbar = fig.colorbar(points, ax=axis, pad=0.02)
    colorbar.set_label("Median inclusion latency (s)")
    axis.set_xlabel("Deployment calldata (KiB)")
    axis.set_ylabel("Deployment gas (millions)")
    axis.set_title("Deployment resource fingerprint (10 repetitions per contract)")
    axis.grid(alpha=0.18)
    save_figure(fig, output_dir, "base_sepolia_deployments")


def plot_settlement_costs(rows: list[dict[str, str]], output_dir: Path) -> None:
    operations = [
        "atomic_settlement_valid",
        "revert_context_mismatch",
        "revert_invalid_proof",
        "revert_replay",
    ]
    labels = ["Valid settlement", "Context mismatch", "Tampered proof", "Replay"]
    grouped = selected_groups(rows, operations)
    colors = [PALETTE[0], PALETTE[1], PALETTE[3], PALETTE[4]]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.4))
    add_violin_jitter(axes[0], [numeric(group, "gas_used") for group in grouped], labels, colors, seed=84532)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Gas used (log scale)")
    axes[0].set_title("Gas distribution: raw trials + median diamond")
    axes[0].tick_params(axis="x", rotation=24)
    axes[0].grid(axis="y", alpha=0.18)
    markers = ["o", "s", "^", "D"]
    for group, label, color, marker in zip(grouped, labels, colors, markers):
        axes[1].scatter(
            numeric(group, "calldata_nonzero_bytes"),
            np.array(numeric(group, "total_fee_wei")) / 1e9,
            label=label,
            color=color,
            marker=marker,
            s=44,
            alpha=0.72,
            edgecolors="white",
            linewidths=0.4,
        )
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Non-zero calldata bytes")
    axes[1].set_ylabel("Total transaction fee (Gwei, log scale)")
    axes[1].set_title("Calldata density versus total transaction fee")
    axes[1].legend(fontsize=8, frameon=False)
    axes[1].grid(alpha=0.18)
    save_figure(fig, output_dir, "base_sepolia_settlement_costs")


def plot_latencies(rows: list[dict[str, str]], output_dir: Path) -> None:
    valid = [row for row in rows if row["operation"] == "atomic_settlement_valid"]
    metrics = [
        ("inclusion_latency_ms", "L2 inclusion"),
        ("confirmation_5_latency_ms", "5 confirmations"),
        ("confirmation_12_latency_ms", "12 confirmations"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.3))
    data = [[value / 1000 for value in numeric(valid, field)] for field, _ in metrics]
    add_violin_jitter(
        axes[0],
        data,
        [label for _, label in metrics],
        [PALETTE[0], PALETTE[2], PALETTE[3]],
        seed=84533,
    )
    axes[0].set_ylabel("Client-observed latency (s)")
    axes[0].set_title("Valid-settlement milestone distributions (n=30)")
    axes[0].tick_params(axis="x", rotation=18)
    axes[0].grid(axis="y", alpha=0.18)
    relevant = [row for row in rows if row["operation"] in KEY_OPERATION_LABELS]
    x = np.array(numeric(relevant, "inclusion_latency_ms")) / 1000
    y = np.array(numeric(relevant, "post_inclusion_confirmation_12_ms")) / 1000
    bins = axes[1].hexbin(x, y, gridsize=11, mincnt=1, cmap="magma", linewidths=0.25)
    colorbar = fig.colorbar(bins, ax=axes[1], pad=0.02)
    colorbar.set_label("Transactions per hexagon")
    axes[1].set_xlabel("Inclusion latency (s)")
    axes[1].set_ylabel("Additional time to 12 confirmations (s)")
    axes[1].set_title("Joint confirmation-latency density (n=70)")
    axes[1].grid(alpha=0.12)
    save_figure(fig, output_dir, "base_sepolia_settlement_latency")


def plot_operation_latencies(rows: list[dict[str, str]], output_dir: Path) -> None:
    operations = list(KEY_OPERATION_LABELS)
    groups = selected_groups(rows, operations)
    datasets = [[value / 1000 for value in numeric(group, "inclusion_latency_ms")] for group in groups]
    fig, axis = plt.subplots(figsize=(11, 6.4))
    add_violin_jitter(axis, datasets, [KEY_OPERATION_LABELS[item] for item in operations], PALETTE[:5], seed=84534)
    axis.set_ylabel("Inclusion latency (s)")
    axis.set_title("Inclusion-latency distributions by settlement outcome")
    axis.tick_params(axis="x", rotation=20)
    axis.grid(axis="y", alpha=0.18)
    save_figure(fig, output_dir, "base_sepolia_operation_latency")


def plot_fee_landscape(rows: list[dict[str, str]], output_dir: Path) -> None:
    operations = list(KEY_OPERATION_LABELS)
    groups = selected_groups(rows, operations)
    fig, axis = plt.subplots(figsize=(10.5, 6.8))
    markers = ["o", "P", "s", "^", "D"]
    for operation, group, color, marker in zip(operations, groups, PALETTE[:5], markers):
        axis.scatter(
            np.array(numeric(group, "l1_fee_wei")) / 1e9,
            np.array(numeric(group, "l2_execution_fee_wei")) / 1e9,
            label=KEY_OPERATION_LABELS[operation],
            color=color,
            marker=marker,
            s=48,
            alpha=0.72,
            edgecolors="white",
            linewidths=0.45,
        )
    axis.set_yscale("log")
    axis.set_xlabel("L1 data fee (Gwei)")
    axis.set_ylabel("L2 execution fee (Gwei, log scale)")
    axis.set_title("Base Sepolia fee landscape by settlement outcome")
    axis.legend(fontsize=8.5, frameon=False)
    axis.grid(alpha=0.18)
    save_figure(fig, output_dir, "base_sepolia_fee_landscape")


def rank_values(values: np.ndarray) -> np.ndarray:
    unique, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    del unique
    ends = np.cumsum(counts)
    starts = ends - counts
    average_ranks = (starts + ends - 1) / 2
    return average_ranks[inverse]


def plot_metric_correlation(rows: list[dict[str, str]], output_dir: Path) -> None:
    fields = [
        ("submit_ack_ms", "Submit ack"),
        ("inclusion_latency_ms", "Inclusion"),
        ("post_inclusion_confirmation_5_ms", "+5 conf."),
        ("post_inclusion_confirmation_12_ms", "+12 conf."),
        ("gas_used", "Gas"),
        ("calldata_nonzero_bytes", "Non-zero calldata"),
        ("l1_fee_wei", "L1 fee"),
        ("l2_execution_fee_wei", "L2 fee"),
    ]
    relevant = [row for row in rows if row["operation"] in KEY_OPERATION_LABELS]
    complete = [row for row in relevant if all(row.get(field, "") != "" for field, _ in fields)]
    matrix = np.array([[float(row[field]) for field, _ in fields] for row in complete])
    ranked = np.column_stack([rank_values(matrix[:, index]) for index in range(matrix.shape[1])])
    correlation = np.corrcoef(ranked, rowvar=False)
    fig, axis = plt.subplots(figsize=(9.3, 7.8))
    image = axis.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
    labels = [label for _, label in fields]
    axis.set_xticks(np.arange(len(labels)), labels, rotation=38, ha="right")
    axis.set_yticks(np.arange(len(labels)), labels)
    for row_index in range(len(labels)):
        for column_index in range(len(labels)):
            value = correlation[row_index, column_index]
            axis.text(
                column_index,
                row_index,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if abs(value) > 0.58 else "#202020",
            )
    colorbar = fig.colorbar(image, ax=axis, pad=0.02)
    colorbar.set_label("Spearman rank correlation")
    axis.set_title(f"Metric dependence across settlement transactions (n={len(complete)})")
    save_figure(fig, output_dir, "base_sepolia_metric_correlation")


def plot_temporal_stability(rows: list[dict[str, str]], output_dir: Path) -> None:
    operations = list(KEY_OPERATION_LABELS)
    groups = selected_groups(rows, operations)
    fig, axis = plt.subplots(figsize=(11, 6.6))
    markers = ["o", "P", "s", "^", "D"]
    for operation, group, color, marker in zip(operations, groups, PALETTE[:5], markers):
        axis.scatter(
            numeric(group, "block_number"),
            np.array(numeric(group, "inclusion_latency_ms")) / 1000,
            label=KEY_OPERATION_LABELS[operation],
            color=color,
            marker=marker,
            s=42,
            alpha=0.74,
            edgecolors="white",
            linewidths=0.4,
        )
    axis.ticklabel_format(style="plain", axis="x", useOffset=False)
    axis.set_xlabel("Base Sepolia block number")
    axis.set_ylabel("Inclusion latency (s)")
    axis.set_title("Inclusion latency across the canonical experiment blocks")
    axis.legend(fontsize=8.5, frameon=False, ncols=2)
    axis.grid(alpha=0.18)
    save_figure(fig, output_dir, "base_sepolia_temporal_stability")


def describe_distributions(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    metrics = {
        "submit_ack_ms": "ms",
        "inclusion_latency_ms": "ms",
        "confirmation_5_latency_ms": "ms",
        "confirmation_12_latency_ms": "ms",
        "post_inclusion_confirmation_5_ms": "ms",
        "post_inclusion_confirmation_12_ms": "ms",
        "gas_used": "gas",
        "total_fee_wei": "wei",
        "calldata_bytes": "bytes",
        "calldata_zero_bytes": "bytes",
        "calldata_nonzero_bytes": "bytes",
    }
    by_operation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_operation[row["operation"]].append(row)
    output: list[dict[str, object]] = []
    for operation, operation_rows in sorted(by_operation.items()):
        for metric, unit in metrics.items():
            values = numeric(operation_rows, metric)
            if not values:
                continue
            output.append(
                {
                    "operation": operation,
                    "category": operation_rows[0]["category"],
                    "metric": metric,
                    "unit": unit,
                    "count": len(values),
                    "min": min(values),
                    "p25": percentile(values, 0.25),
                    "median": statistics.median(values),
                    "mean": statistics.fmean(values),
                    "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "p75": percentile(values, 0.75),
                    "p95": percentile(values, 0.95),
                    "p99": percentile(values, 0.99),
                    "max": max(values),
                }
            )
    return output


def group_stat(rows: list[dict[str, str]], field: str, probability: float = 0.5) -> float:
    value = percentile(numeric(rows, field), probability)
    if value is None:
        raise ValueError(f"Missing {field} values")
    return value


def annotate_bars(axis: plt.Axes, bars: object, values: list[float], fmt: str, fontsize: float = 7.5) -> None:
    for rectangle, value in zip(bars, values):
        axis.annotate(
            fmt.format(value),
            (rectangle.get_x() + rectangle.get_width() / 2, rectangle.get_height()),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=fontsize,
        )


def plot_cost_and_data_evidence(rows: list[dict[str, str]], output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.2))
    fig.suptitle("Base Sepolia public-testnet settlement: on-chain cost and data footprint", fontsize=16)

    deployment_operations = [
        "deploy_DataRegistry",
        "deploy_AccessController",
        "deploy_BudgetLedger",
        "deploy_AuditLedger",
        "deploy_Phase7Groth16Verifier",
        "deploy_ComplianceVerifier",
        "deploy_TrustCircuitSettlement",
    ]
    deployment_labels = ["Registry", "Access", "Budget", "Audit", "Groth16", "Adapter", "Settlement"]
    deployment_groups = selected_groups(rows, deployment_operations)
    x = np.arange(len(deployment_labels))
    gas_millions = [group_stat(group, "gas_used") / 1e6 for group in deployment_groups]
    calldata_kib = [group_stat(group, "calldata_bytes") / 1024 for group in deployment_groups]
    axis = axes[0, 0]
    bars = axis.bar(x, gas_millions, color=PALETTE[0], alpha=0.82, label="Median gas")
    annotate_bars(axis, bars, gas_millions, "{:.2f}")
    twin = axis.twinx()
    twin.plot(x, calldata_kib, color=PALETTE[1], marker="o", linewidth=2.0, label="Median calldata")
    for position, value in zip(x, calldata_kib):
        offset = -15 if position >= 5 else 7
        twin.annotate(f"{value:.2f}", (position, value), xytext=(0, offset), textcoords="offset points", ha="center", fontsize=7.5)
    axis.set_xticks(x, deployment_labels, rotation=24, ha="right")
    axis.set_ylabel("Deployment gas (millions)")
    twin.set_ylabel("Deployment calldata (KiB)")
    axis.set_title("(a) Contract deployment medians (n=10 per contract)")
    axis.grid(axis="y", alpha=0.18)
    handles_a, labels_a = axis.get_legend_handles_labels()
    handles_b, labels_b = twin.get_legend_handles_labels()
    axis.legend(handles_a + handles_b, labels_a + labels_b, loc="upper left", frameon=False, fontsize=8)

    operations = list(KEY_OPERATION_LABELS)
    labels = [KEY_OPERATION_LABELS[item] for item in operations]
    groups = selected_groups(rows, operations)
    colors = PALETTE[:5]
    x = np.arange(len(labels))
    gas_p50 = [group_stat(group, "gas_used", 0.50) / 1000 for group in groups]
    gas_p95 = [group_stat(group, "gas_used", 0.95) / 1000 for group in groups]
    axis = axes[0, 1]
    bars = axis.bar(x, gas_p50, color=colors, alpha=0.82, label="p50 gas")
    axis.plot(x, gas_p95, color="#222222", marker="D", linewidth=1.8, label="p95 gas")
    annotate_bars(axis, bars, gas_p50, "{:.0f}")
    axis.set_yscale("log")
    axis.set_xticks(x, labels, rotation=24, ha="right")
    axis.set_ylabel("Gas used (thousands, log scale)")
    axis.set_title("(b) Settlement and mined-revert gas")
    axis.legend(frameon=False, fontsize=8)
    axis.grid(axis="y", alpha=0.18)

    l1_fee = [group_stat(group, "l1_fee_wei") / 1e12 for group in groups]
    l2_fee = [group_stat(group, "l2_execution_fee_wei") / 1e12 for group in groups]
    fee_p95 = [group_stat(group, "total_fee_wei", 0.95) / 1e12 for group in groups]
    axis = axes[1, 0]
    l1_bars = axis.bar(x, l1_fee, color=PALETTE[2], alpha=0.86, label="Median L1 data fee")
    axis.bar(x, l2_fee, bottom=l1_fee, color=PALETTE[0], alpha=0.82, label="Median L2 execution fee")
    axis.plot(x, fee_p95, color=PALETTE[1], marker="o", linewidth=1.9, label="p95 total fee")
    for position, value in zip(x, fee_p95):
        axis.annotate(f"{value:.3f}", (position, value), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7.3)
    axis.set_xticks(x, labels, rotation=24, ha="right")
    axis.set_ylabel("Fee (micro-ETH; 1 micro-ETH = 10^12 wei)")
    axis.set_title("(c) L1/L2 fee decomposition and p95 total")
    axis.legend(frameon=False, fontsize=8)
    axis.grid(axis="y", alpha=0.18)

    zero_bytes = [group_stat(group, "calldata_zero_bytes") for group in groups]
    nonzero_bytes = [group_stat(group, "calldata_nonzero_bytes") for group in groups]
    gas_density = [gas * 1000 / nonzero for gas, nonzero in zip(gas_p50, nonzero_bytes)]
    axis = axes[1, 1]
    axis.bar(x, zero_bytes, color="#BBBBBB", alpha=0.92, label="Median zero bytes")
    axis.bar(x, nonzero_bytes, bottom=zero_bytes, color=PALETTE[3], alpha=0.78, label="Median non-zero bytes")
    for position, zero, nonzero in zip(x, zero_bytes, nonzero_bytes):
        axis.annotate(f"{zero + nonzero:.0f} B", (position, zero + nonzero), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.5)
    twin = axis.twinx()
    twin.plot(x, gas_density, color=PALETTE[4], marker="s", linewidth=1.9, label="Gas / non-zero byte")
    twin.set_yscale("log")
    axis.set_xticks(x, labels, rotation=24, ha="right")
    axis.set_ylabel("Calldata bytes")
    twin.set_ylabel("Gas per non-zero byte (log scale)")
    axis.set_title("(d) Calldata composition and compute density")
    handles_a, labels_a = axis.get_legend_handles_labels()
    handles_b, labels_b = twin.get_legend_handles_labels()
    axis.legend(handles_a + handles_b, labels_a + labels_b, loc="upper left", frameon=False, fontsize=8)
    axis.grid(axis="y", alpha=0.18)

    fig.text(
        0.01,
        0.012,
        "Measured public-testnet data only. The tampered-proof revert uses an explicit 2,000,000 gas limit, so its gas/fee values are cap-conditional.",
        fontsize=8.5,
    )
    save_figure(fig, output_dir, "base_sepolia_cost_and_data_evidence")


def plot_latency_and_reliability_evidence(rows: list[dict[str, str]], output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.2))
    fig.suptitle("Base Sepolia public-testnet settlement: latency, confirmations, and expected outcomes", fontsize=16)
    operations = list(KEY_OPERATION_LABELS)
    labels = [KEY_OPERATION_LABELS[item] for item in operations]
    groups = selected_groups(rows, operations)
    colors = PALETTE[:5]
    x = np.arange(len(labels))

    p50 = [group_stat(group, "inclusion_latency_ms", 0.50) / 1000 for group in groups]
    p95 = [group_stat(group, "inclusion_latency_ms", 0.95) / 1000 for group in groups]
    p99 = [group_stat(group, "inclusion_latency_ms", 0.99) / 1000 for group in groups]
    axis = axes[0, 0]
    bars = axis.bar(x, p50, color=colors, alpha=0.82, label="p50")
    axis.plot(x, p95, color="#222222", marker="o", linewidth=1.8, label="p95")
    axis.plot(x, p99, color=PALETTE[1], marker="D", linestyle="--", linewidth=1.6, label="p99")
    annotate_bars(axis, bars, p50, "{:.2f}")
    axis.set_xticks(x, labels, rotation=24, ha="right")
    axis.set_ylabel("Inclusion latency (s)")
    axis.set_title("(a) Inclusion latency percentiles (30/10/10/10/10 trials)")
    axis.legend(frameon=False, fontsize=8, ncols=3)
    axis.grid(axis="y", alpha=0.18)

    valid = [row for row in rows if row["operation"] == "atomic_settlement_valid"]
    milestone_fields = ["inclusion_latency_ms", "confirmation_5_latency_ms", "confirmation_12_latency_ms"]
    milestone_labels = ["L2 inclusion", "5 confirmations", "12 confirmations"]
    milestone_x = np.arange(len(milestone_labels))
    milestone_p50 = [group_stat(valid, field, 0.50) / 1000 for field in milestone_fields]
    milestone_p95 = [group_stat(valid, field, 0.95) / 1000 for field in milestone_fields]
    milestone_p99 = [group_stat(valid, field, 0.99) / 1000 for field in milestone_fields]
    axis = axes[0, 1]
    bars = axis.bar(milestone_x, milestone_p50, color=[PALETTE[0], PALETTE[2], PALETTE[3]], alpha=0.82, label="p50")
    axis.plot(milestone_x, milestone_p95, color="#222222", marker="o", linewidth=1.8, label="p95")
    axis.plot(milestone_x, milestone_p99, color=PALETTE[1], marker="D", linestyle="--", linewidth=1.6, label="p99")
    annotate_bars(axis, bars, milestone_p50, "{:.2f}")
    axis.set_xticks(milestone_x, milestone_labels)
    axis.set_ylabel("Client-observed latency (s)")
    axis.set_title("(b) Valid-settlement confirmation milestones (n=30)")
    axis.legend(frameon=False, fontsize=8, ncols=3)
    axis.grid(axis="y", alpha=0.18)

    relevant = [row for row in rows if row["operation"] in KEY_OPERATION_LABELS]
    relevant.sort(key=lambda row: int(row["block_number"]))
    sequence = np.arange(1, len(relevant) + 1)
    sequence_latency = np.array(numeric(relevant, "inclusion_latency_ms")) / 1000
    axis = axes[1, 0]
    axis.plot(sequence, sequence_latency, color="#777777", linewidth=0.9, alpha=0.75, label="Measured sequence")
    for operation, color, marker in zip(operations, colors, ["o", "P", "s", "^", "D"]):
        indexes = [index + 1 for index, row in enumerate(relevant) if row["operation"] == operation]
        values = [float(row["inclusion_latency_ms"]) / 1000 for row in relevant if row["operation"] == operation]
        axis.scatter(indexes, values, color=color, marker=marker, s=32, label=KEY_OPERATION_LABELS[operation], zorder=3)
    axis.set_xlabel("Settlement-related transaction order")
    axis.set_ylabel("Inclusion latency (s)")
    axis.set_title("(c) All 70 settlement outcomes in measured order")
    axis.legend(frameon=False, fontsize=7.2, ncols=2)
    axis.grid(alpha=0.18)

    pass_rates: list[float] = []
    sample_counts: list[int] = []
    for operation, group in zip(operations, groups):
        if operation.startswith("revert_"):
            passes = [int(row["success"]) == 0 and row["rollback_verified"] == "1" for row in group]
        else:
            passes = [int(row["success"]) == 1 for row in group]
        pass_rates.append(100 * statistics.fmean(passes))
        sample_counts.append(len(group))
    axis = axes[1, 1]
    bars = axis.bar(x, pass_rates, color=colors, alpha=0.82, label="Expected-outcome pass rate")
    annotate_bars(axis, bars, pass_rates, "{:.0f}%")
    axis.set_ylim(0, 108)
    axis.set_xticks(x, labels, rotation=24, ha="right")
    axis.set_ylabel("Expected outcome + rollback pass rate (%)")
    twin = axis.twinx()
    twin.plot(x, sample_counts, color="#222222", marker="o", linewidth=1.8, label="Observed trials")
    for position, count in zip(x, sample_counts):
        twin.annotate(f"n={count}", (position, count), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7.5)
    twin.set_ylim(0, max(sample_counts) * 1.35)
    twin.set_ylabel("Observed trials")
    axis.set_title("(d) Expected behavior and state-preserving reverts")
    handles_a, labels_a = axis.get_legend_handles_labels()
    handles_b, labels_b = twin.get_legend_handles_labels()
    axis.legend(handles_a + handles_b, labels_a + labels_b, loc="lower left", frameon=False, fontsize=8)
    axis.grid(axis="y", alpha=0.18)

    fig.text(
        0.01,
        0.012,
        "Scope: 302 Base Sepolia transactions. This supports public-testnet operational feasibility; it is not a direct Ethereum/mainnet measurement. Panel (c) is descriptive because operation type and execution order are partially confounded.",
        fontsize=8.5,
    )
    save_figure(fig, output_dir, "base_sepolia_latency_and_reliability_evidence")


def horizontal_y_label(axis: plt.Axes, text: str, side: str = "left") -> None:
    axis.set_ylabel(text, rotation=0, fontsize=10.5)
    if side == "right":
        axis.yaxis.set_label_coords(1.0, 1.025)
        axis.yaxis.label.set_horizontalalignment("right")
    else:
        axis.yaxis.set_label_coords(0.0, 1.025)
        axis.yaxis.label.set_horizontalalignment("left")


def style_standalone_axis(axis: plt.Axes) -> None:
    axis.tick_params(axis="both", labelsize=10)
    axis.tick_params(axis="x", rotation=0)
    axis.grid(axis="y", alpha=0.18)


def smooth_guide(
    axis: plt.Axes,
    x: np.ndarray,
    y: list[float],
    *,
    color: str,
    label: str,
    marker: str = "o",
    linestyle: str = "-",
) -> None:
    dense_x = np.linspace(float(x.min()), float(x.max()), 240)
    dense_y = PchipInterpolator(x, np.asarray(y))(dense_x)
    axis.plot(dense_x, dense_y, color=color, linewidth=2.0, linestyle=linestyle, label=label)
    axis.scatter(x, y, color=color, marker=marker, s=42, zorder=4)


def standalone_operation_groups(rows: list[dict[str, str]]) -> tuple[list[str], list[str], list[list[dict[str, str]]]]:
    operations = [
        "atomic_settlement_valid",
        "revert_context_mismatch",
        "revert_invalid_proof",
        "revert_replay",
    ]
    labels = ["Valid\nsettlement", "Context\nmismatch", "Tampered\nproof", "Replay"]
    return operations, labels, selected_groups(rows, operations)


def plot_figure_1a(rows: list[dict[str, str]], output_dir: Path) -> None:
    operations = [
        "deploy_DataRegistry",
        "deploy_AccessController",
        "deploy_BudgetLedger",
        "deploy_AuditLedger",
        "deploy_Phase7Groth16Verifier",
        "deploy_ComplianceVerifier",
        "deploy_TrustCircuitSettlement",
    ]
    labels = ["Data\nReg.", "Access\nCtrl.", "Budget\nLedger", "Audit\nLedger", "Groth16\nVer.", "Comp.\nAdpt.", "Settle.\nCtr."]
    groups = selected_groups(rows, operations)
    x = np.arange(len(labels), dtype=float)
    gas = [group_stat(group, "gas_used") / 1e6 for group in groups]
    calldata = [group_stat(group, "calldata_bytes") / 1024 for group in groups]
    fig, axis = plt.subplots(figsize=(4, 4))
    axis.bar(x, gas, width=0.48, color=PALETTE[0], alpha=0.84, label="Median deployment gas")
    twin = axis.twinx()
    smooth_guide(twin, x, calldata, color=PALETTE[1], label="Median calldata (KiB)", marker="o")
    axis.set_xticks(x, labels)
    horizontal_y_label(axis, "Gas (millions)")
    twin.set_ylabel("")
    axis.set_ylim(0, max(gas) * 1.18)
    twin.set_ylim(0, max(calldata) * 1.22)
    style_standalone_axis(axis)
    axis.tick_params(axis="x", labelsize=8.0)
    twin.tick_params(axis="y", labelsize=10)
    handles_a, labels_a = axis.get_legend_handles_labels()
    handles_b, labels_b = twin.get_legend_handles_labels()
    axis.legend(handles_a + handles_b, labels_a + labels_b, fontsize=10, frameon=False, loc="upper left")
    save_figure(fig, output_dir, "figure_1a_deployment_resources")


def plot_figure_1b(rows: list[dict[str, str]], output_dir: Path) -> None:
    _, labels, groups = standalone_operation_groups(rows)
    x = np.arange(len(labels), dtype=float)
    p50 = [group_stat(group, "gas_used", 0.50) / 1000 for group in groups]
    p95 = [group_stat(group, "gas_used", 0.95) / 1000 for group in groups]
    fig, axis = plt.subplots(figsize=(4, 4))
    axis.bar(x, p50, width=0.48, color=[PALETTE[0], PALETTE[2], PALETTE[3], PALETTE[4]], alpha=0.84, label="p50 gas")
    smooth_guide(axis, x, p95, color="#222222", label="p95 gas", marker="D")
    axis.set_yscale("log")
    axis.set_xticks(x, labels)
    horizontal_y_label(axis, "Gas used (thousands, log scale)")
    style_standalone_axis(axis)
    axis.legend(fontsize=10, frameon=False, loc="upper left")
    save_figure(fig, output_dir, "figure_1b_settlement_gas")


def plot_figure_1c(rows: list[dict[str, str]], output_dir: Path) -> None:
    _, labels, groups = standalone_operation_groups(rows)
    x = np.arange(len(labels), dtype=float)
    l1_fee = [group_stat(group, "l1_fee_wei") / 1e12 for group in groups]
    l2_fee = [group_stat(group, "l2_execution_fee_wei") / 1e12 for group in groups]
    p95_total = [group_stat(group, "total_fee_wei", 0.95) / 1e12 for group in groups]
    fig, axis = plt.subplots(figsize=(4, 4))
    axis.bar(x, l1_fee, width=0.48, color=PALETTE[2], alpha=0.88, label="Median L1 data fee")
    axis.bar(x, l2_fee, width=0.48, bottom=l1_fee, color=PALETTE[0], alpha=0.84, label="Median L2 execution fee")
    smooth_guide(axis, x, p95_total, color=PALETTE[1], label="p95 total fee", marker="o")
    axis.set_xticks(x, labels)
    horizontal_y_label(axis, "Fee (micro-ETH; 10^12 wei)")
    style_standalone_axis(axis)
    axis.legend(fontsize=10, frameon=False, loc="upper left")
    save_figure(fig, output_dir, "figure_1c_settlement_fees")


def plot_figure_2a(rows: list[dict[str, str]], output_dir: Path) -> None:
    _, base_labels, groups = standalone_operation_groups(rows)
    valid = groups[0]
    fields = [
        "inclusion_latency_ms",
        "inclusion_latency_ms",
        "inclusion_latency_ms",
        "inclusion_latency_ms",
        "confirmation_5_latency_ms",
        "confirmation_12_latency_ms",
    ]
    metric_groups = groups + [valid, valid]
    labels = ["Valid", "Context", "Tampered", "Replay", "5 conf.", "12 conf."]
    x = np.arange(len(labels), dtype=float)
    p50 = [group_stat(group, field, 0.50) / 1000 for group, field in zip(metric_groups, fields)]
    p95 = [group_stat(group, field, 0.95) / 1000 for group, field in zip(metric_groups, fields)]
    fig, axis = plt.subplots(figsize=(4, 4))
    axis.bar(x, p50, width=0.48, color=[PALETTE[0], PALETTE[2], PALETTE[3], PALETTE[4], PALETTE[2], PALETTE[3]], alpha=0.82, label="p50")
    smooth_guide(axis, x, p95, color="#222222", label="p95", marker="o")
    axis.set_xticks(x, labels)
    horizontal_y_label(axis, "Client-observed latency (s)")
    style_standalone_axis(axis)
    axis.tick_params(axis="x", labelsize=8.5)
    axis.legend(fontsize=10, frameon=False, loc="upper left", ncols=2)
    save_figure(fig, output_dir, "figure_2a_settlement_latency")


def build_figure_tables(rows: list[dict[str, str]], config: dict[str, object]) -> str:
    deployment_operations = [
        ("deploy_DataRegistry", "Data registry"),
        ("deploy_AccessController", "Access controller"),
        ("deploy_BudgetLedger", "Budget ledger"),
        ("deploy_AuditLedger", "Audit ledger"),
        ("deploy_Phase7Groth16Verifier", "Groth16 verifier"),
        ("deploy_ComplianceVerifier", "Compliance adapter"),
        ("deploy_TrustCircuitSettlement", "Settlement"),
    ]
    operation_entries = [
        ("atomic_settlement_valid", "Valid settlement", "success"),
        ("attack_control_valid_settlement", "Valid control", "success"),
        ("revert_context_mismatch", "Context mismatch", "expected revert"),
        ("revert_invalid_proof", "Tampered proof", "expected revert"),
        ("revert_replay", "Replay", "expected revert"),
    ]
    lines = [
        "# Base Sepolia Figure Tables",
        "",
        f"Run: `{config['run_id']}`; measured on Base Sepolia (`{config['chain_id']}`). Exact values below come from `transactions.csv`; figures contain no synthetic observations.",
        "",
        "## Table for Figure 1a — deployment resources",
        "",
        "| Contract | n | Gas p50 | Gas p95 | Calldata p50 (B) | Inclusion p50 (ms) | Inclusion p95 (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for operation, label in deployment_operations:
        group = [row for row in rows if row["operation"] == operation]
        lines.append(
            f"| {label} | {len(group)} | {group_stat(group, 'gas_used', 0.50):,.0f} | {group_stat(group, 'gas_used', 0.95):,.0f} | "
            f"{group_stat(group, 'calldata_bytes', 0.50):,.0f} | {group_stat(group, 'inclusion_latency_ms', 0.50):,.1f} | {group_stat(group, 'inclusion_latency_ms', 0.95):,.1f} |"
        )
    lines.extend(
        [
            "",
            "## Table for Figure 1b — settlement and revert gas",
            "",
            "| Operation | n | Observed outcome | Gas p50 | Gas p95 | Gas p99 | Calldata p50 (B) |",
            "|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for operation, label, outcome in operation_entries:
        group = [row for row in rows if row["operation"] == operation]
        lines.append(
            f"| {label} | {len(group)} | {outcome} | {group_stat(group, 'gas_used', 0.50):,.0f} | "
            f"{group_stat(group, 'gas_used', 0.95):,.0f} | {group_stat(group, 'gas_used', 0.99):,.0f} | {group_stat(group, 'calldata_bytes', 0.50):,.0f} |"
        )
    lines.extend(
        [
            "",
            "## Table for Figure 1c — fee decomposition",
            "",
            "All fee values are micro-ETH (`10^12 wei`).",
            "",
            "| Operation | n | L1 fee p50 | L2 fee p50 | Total fee p50 | Total fee p95 | Total fee p99 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for operation, label, _ in operation_entries:
        group = [row for row in rows if row["operation"] == operation]
        lines.append(
            f"| {label} | {len(group)} | {group_stat(group, 'l1_fee_wei', 0.50) / 1e12:.4f} | "
            f"{group_stat(group, 'l2_execution_fee_wei', 0.50) / 1e12:.4f} | {group_stat(group, 'total_fee_wei', 0.50) / 1e12:.4f} | "
            f"{group_stat(group, 'total_fee_wei', 0.95) / 1e12:.4f} | {group_stat(group, 'total_fee_wei', 0.99) / 1e12:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Table for Figure 2a — latency and confirmations",
            "",
            "| Operation | n | Inclusion p50 | p95 | p99 | 5-conf p50 | p95 | p99 | 12-conf p50 | p95 | p99 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for operation, label, _ in operation_entries:
        group = [row for row in rows if row["operation"] == operation]
        values = []
        for field in ["inclusion_latency_ms", "confirmation_5_latency_ms", "confirmation_12_latency_ms"]:
            values.extend(group_stat(group, field, probability) for probability in [0.50, 0.95, 0.99])
        lines.append(f"| {label} | {len(group)} | " + " | ".join(f"{value:,.1f}" for value in values) + " |")
    lines.extend(
        [
            "",
            "All latency values are milliseconds and are client-observed from submission through the stated milestone.",
            "",
            "## Interpretation notes",
            "",
            "- `Valid control` intentionally invokes the same successful settlement path as `Valid settlement`. It is interleaved with attack trials to show that a valid proof/context still succeeds around the revert probes; near-identical gas and fee values are expected, not duplicate fabricated measurements.",
            "- The valid-control row remains in the tables for traceability but is omitted from the figures to avoid a visually redundant category.",
            "- The calldata/compute-density panel was removed because every settlement input is 772 bytes, so the calldata bars add no discriminating evidence.",
            "- The 100% expected-outcome panel was removed because all tested outcomes passed and the flat visualization added little information; raw pass/revert and rollback fields remain in `transactions.csv`.",
            "- The execution-order trace was removed because operation class and run order are partially confounded.",
            "- Smooth curves are PCHIP visual guides through the measured summary markers. They add no samples and should not be interpreted as continuous measurements between categorical operations.",
            "- Figure 2a shows p50 bars and a single p95 guide to avoid overlapping percentile curves; p99 remains available in the table above.",
            "- The tampered-proof revert uses an explicit 2,000,000 gas limit; its gas and fee values are conditional on that cap.",
            "- These results support public-testnet settlement feasibility, not a direct mainnet-performance claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.run_dir:
        run_dir = args.run_dir.resolve()
    else:
        latest = json.loads((RAW_ROOT / "full_latest.json").read_text(encoding="utf-8"))
        run_dir = ROOT / latest["raw_directory"]

    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    with (run_dir / "transactions.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    groups: list[tuple[str, str, str, list[dict[str, str]]]] = []
    operation_labels = {
        "deploy_Phase7Groth16Verifier": "Groth16 verifier deployment",
        "atomic_settlement_valid": "Valid atomic settlement",
        "attack_control_valid_settlement": "Attack-control valid settlement",
        "revert_context_mismatch": "Context-mismatch revert",
        "revert_invalid_proof": "Tampered-proof revert (2M gas cap)",
        "revert_replay": "Replay revert",
    }
    for operation, label in operation_labels.items():
        selected = [row for row in rows if row["operation"] == operation]
        if selected:
            groups.append((label, selected[0]["category"], operation, selected))

    suite_rows: list[dict[str, str]] = []
    by_suite: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["category"] == "deployment":
            by_suite[row["suite_iteration"]].append(row)
    for suite, items in sorted(by_suite.items(), key=lambda pair: int(pair[0])):
        verifier = [item for item in items if item["operation"] == "deploy_Phase7Groth16Verifier"]
        application = [item for item in items if item not in verifier]
        template = dict(items[0])
        template.update(
            {
                "operation": "deploy_application_contract_suite",
                "gas_used": str(sum(int(item["gas_used"]) for item in application)),
                "calldata_bytes": str(sum(int(item["calldata_bytes"]) for item in application)),
                "inclusion_latency_ms": str(sum(float(item["inclusion_latency_ms"]) for item in application)),
                "confirmation_5_latency_ms": "",
                "confirmation_12_latency_ms": "",
                "total_fee_wei": str(sum(int(item["total_fee_wei"]) for item in application)),
                "success": "1",
            }
        )
        suite_rows.append(template)
    groups.insert(0, ("Application contract suite deployment", "deployment", "deploy_application_contract_suite", suite_rows))

    summary = [summarize_group(*group) for group in groups]
    processed_dir = PROCESSED_ROOT / config["run_id"]
    figures_dir = processed_dir / "figures"
    processed_dir.mkdir(parents=True, exist_ok=True)
    headers = list(summary[0])
    with (processed_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(summary)
    (processed_dir / "summary.json").write_text(
        json.dumps({"config": config, "run_result": run_result, "summary": summary}, indent=2) + "\n",
        encoding="utf-8",
    )

    distribution_summary = describe_distributions(rows)
    distribution_headers = list(distribution_summary[0])
    with (processed_dir / "distribution_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=distribution_headers)
        writer.writeheader()
        writer.writerows(distribution_summary)
    (processed_dir / "distribution_summary.json").write_text(
        json.dumps(distribution_summary, indent=2) + "\n",
        encoding="utf-8",
    )

    clean_figure_outputs(figures_dir)
    plot_figure_1a(rows, figures_dir)
    plot_figure_1b(rows, figures_dir)
    plot_figure_1c(rows, figures_dir)
    plot_figure_2a(rows, figures_dir)
    (processed_dir / "FIGURE_TABLES.md").write_text(build_figure_tables(rows, config), encoding="utf-8")

    table_lines = [
        "# Base Sepolia Public-Testnet Settlement Results",
        "",
        f"- Run: `{config['run_id']}`",
        f"- Chain: Base Sepolia (`{config['chain_id']}`)",
        f"- Transactions: {run_result['transaction_count']} ({run_result['successful_transactions']} successful, {run_result['reverted_transactions']} reverted as intended)",
        f"- Deployer: `{run_result['deployer_address']}`",
        f"- Settlement contract: `{run_result['canonical_addresses']['settlement']}`",
        f"- Groth16 verifier: `{run_result['canonical_addresses']['groth16_verifier']}`",
        f"- Test ETH spent: {int(config['balance_spent_wei']) / 1e18:.9f} ETH",
        "- Scope: blockchain deployment and settlement only; proof preparation and VBS/Nitro are excluded from measured chain latency.",
        "",
        "| Operation | Runs | Success/revert | Median gas | Median calldata (B) | Inclusion p50 / p95 (ms) | 5-conf p50 (ms) | 12-conf p50 (ms) | Rollback pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        success_revert = f"{item['successful']}/{item['reverted']}"
        rollback = finite(item["rollback_pass_rate"])
        table_lines.append(
            f"| {item['label']} | {item['runs']} | {success_revert} | "
            f"{float(item['median_gas_used']):,.0f} | {float(item['median_calldata_bytes']):,.0f} | "
            f"{float(item['median_inclusion_ms']):,.1f} / {float(item['p95_inclusion_ms']):,.1f} | "
            f"{finite(item['median_confirmation_5_ms'])} | {finite(item['median_confirmation_12_ms'])} | {rollback} |"
        )
    table_lines.extend(
        [
            "",
            "The tampered-proof trials flip a Groth16 curve coordinate and are submitted with an explicit 2,000,000 gas limit. They measure mined malformed-proof revert behavior; their gas is conditional on that cap and is not a normal successful-verifier cost.",
            "",
            "## Canonical deployment",
            "",
            "| Contract | Address |",
            "|---|---|",
        ]
    )
    for name, address in config["canonical_addresses"].items():
        table_lines.append(f"| {name} | [`{address}`](https://sepolia-explorer.base.org/address/{address}) |")
    table_lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `summary.csv` and `summary.json`: calculated statistics.",
            "- `distribution_summary.csv` and `distribution_summary.json`: tidy per-operation distributions with min, p25, median, mean, standard deviation, p75, p95, p99, and max.",
            "- `FIGURE_TABLES.md`: exact values used by the four standalone figures, plus interpretation notes.",
            "- Figures are exported as PDF only.",
            "",
            "## Figure guide",
            "",
            "| Figure | Visual form | Research question |",
            "|---|---|---|",
            "| `figure_1a_deployment_resources.pdf` | Bar + smoothed measured-point guide | Deployment gas and calldata by contract. |",
            "| `figure_1b_settlement_gas.pdf` | Bar + smoothed measured-point guide | Settlement and mined-revert gas p50/p95. |",
            "| `figure_1c_settlement_fees.pdf` | Stacked bar + smoothed measured-point guide | L1/L2 median fees and p95 total fee. |",
            "| `figure_2a_settlement_latency.pdf` | Bar + one smoothed measured-point guide | Inclusion and valid-settlement confirmation p50/p95; p99 remains in `FIGURE_TABLES.md`. |",
            "",
            "These figures establish public-testnet settlement feasibility. They do not constitute a direct mainnet measurement; mainnet claims require mainnet or multi-regime validation.",
        ]
    )
    (processed_dir / "RESULTS.md").write_text("\n".join(table_lines) + "\n", encoding="utf-8")

    (processed_dir / "FIGURES.md").unlink(missing_ok=True)

    latest_path = RAW_ROOT / "full_latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["processed_directory"] = str(processed_dir.relative_to(ROOT)).replace("\\", "/")
    latest_path.write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "processed_directory": str(processed_dir)}))


if __name__ == "__main__":
    main()
