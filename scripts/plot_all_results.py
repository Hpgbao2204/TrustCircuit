"""Publication figures for the Phase 8 result bundle.

The plotter intentionally performs no measurement.  It consumes the processed
CSV files and emits one independent, single-axis figure for each panel.  The
visual vocabulary is deliberately small: Matplotlib defaults, line charts,
dot/ECDF charts, and unannotated capability matrices.  This keeps the figures
readable when they are placed as separate panels in a manuscript.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
PANELS = ROOT / "Paper" / "figures" / "panels"
FIGURE_SIZE = (12, 8)
DPI = 600

# A restrained, colour-blind-friendly palette.  Font, font size, line width,
# and other typography remain Matplotlib defaults on purpose.
COLORS = {
    "Native": "#1f4e79",
    "VBS Enclave": "#c55a11",
    "Access Ledger": "#4472c4",
    "TEE-only": "#70ad47",
    "ZK Release": "#8064a2",
    "Local DP Ledger": "#ed7d31",
    "TrustCircuit": "#1f4e79",
    "access": "#4472c4",
    "budget": "#70ad47",
    "tee": "#c55a11",
    "proof": "#8064a2",
    "settlement": "#a5a5a5",
    "audit": "#ffc000",
    "decrypt": "#4472c4",
    "aggregate": "#70ad47",
    "dp_noise": "#ed7d31",
    "transcript": "#8064a2",
    "attestation_generation": "#c55a11",
}
VARIANT_ORDER = [
    "baseline_minimal",
    "access_only",
    "no_budget",
    "no_zk",
    "no_tee",
    "full_trustcircuit",
]
COMPARISON_ORDER = [
    "TEE-only",
    "Access Ledger",
    "ZK Release",
    "Local DP Ledger",
    "TrustCircuit",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        value = float(row.get(key, ""))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def retained(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("is_warmup", "0") != "1"]


def grouped(rows: Iterable[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    output: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        output.setdefault(row.get(key, ""), []).append(row)
    return output


def values(rows: Iterable[dict[str, str]], key: str) -> list[float]:
    result: list[float] = []
    for row in rows:
        value = f(row, key)
        if math.isfinite(value):
            result.append(value)
    return result


def quantile(data: Sequence[float], percentile: float) -> float:
    return float(np.percentile(data, percentile)) if data else math.nan


def style() -> None:
    # Reset any user/site matplotlibrc (including Times New Roman overrides).
    # No project-specific font is selected: the default Matplotlib font is
    # used consistently in PDF and PNG output.
    plt.rcdefaults()


def tidy(ax: plt.Axes, *, log_y: bool = False) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#d9e2f3", linewidth=0.55, alpha=0.8)
    if log_y:
        ax.set_yscale("log")


def save(fig: plt.Figure, stem: str) -> None:
    PANELS.mkdir(parents=True, exist_ok=True)
    # No tight bounding box: every panel has the same physical canvas and can
    # be dropped into a paper layout without an unpredictable crop.
    fig.savefig(PANELS / f"{stem}.pdf", format="pdf")
    fig.savefig(PANELS / f"{stem}.png", format="png", dpi=DPI)
    plt.close(fig)


def ecdf(ax: plt.Axes, data: Sequence[float], *, label: str, color: str) -> None:
    clean = np.sort(np.asarray([v for v in data if math.isfinite(v)], dtype=float))
    if clean.size:
        y = (np.arange(clean.size, dtype=float) + 1) / clean.size
        ax.plot(clean, y, color=color, linewidth=1.8, label=label)


def variant_label(value: str) -> str:
    return value.replace("_", " ").title().replace("No Tee", "No TEE")


def summary_line(
    ax: plt.Axes,
    rows: Sequence[dict[str, str]],
    x_field: str,
    y_field: str,
    *,
    label: str,
    color: str,
    marker: str = "o",
    sort_numeric: bool = True,
) -> None:
    ordered = sorted(rows, key=lambda row: f(row, x_field)) if sort_numeric else list(rows)
    x = np.asarray([f(row, x_field) for row in ordered])
    y = np.asarray([f(row, y_field) for row in ordered])
    mask = np.isfinite(x) & np.isfinite(y)
    if np.any(mask):
        ax.plot(x[mask], y[mask], marker=marker, linewidth=1.8, color=color, label=label)


def fig3() -> None:
    trials = retained(read_csv(PROCESSED / "e2e_ablation_trials.csv"))
    present = {row["variant"] for row in trials}
    order = [variant for variant in VARIANT_ORDER if variant in present]
    labels = [variant_label(value) for value in order]

    # 3a: a compact median/p95 line chart replaces the repeated boxplot motif.
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    medians = [quantile(values([r for r in trials if r["variant"] == v], "throughput_req_s"), 50) for v in order]
    p95 = [quantile(values([r for r in trials if r["variant"] == v], "throughput_req_s"), 95) for v in order]
    x = np.arange(len(order))
    ax.plot(x, medians, "o-", color="#4472c4", label="Median")
    ax.plot(x, p95, "s--", color="#c55a11", label="95th percentile")
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_title("Ablation throughput")
    ax.legend()
    tidy(ax, log_y=True)
    save(fig, "fig3a_ablation_throughput")

    # 3b: same visual grammar, with latency on a linear axis.
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    medians = [quantile(values([r for r in trials if r["variant"] == v], "total_latency_ms"), 50) for v in order]
    p95 = [quantile(values([r for r in trials if r["variant"] == v], "total_latency_ms"), 95) for v in order]
    ax.plot(x, medians, "o-", color="#4472c4", label="Median")
    ax.plot(x, p95, "s--", color="#c55a11", label="95th percentile")
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_ylabel("End-to-end latency (ms)")
    ax.set_title("Ablation end-to-end latency")
    ax.legend()
    tidy(ax)
    save(fig, "fig3b_ablation_latency")

    # 3c: one panel showing normalized stage shares as smooth lines.
    matrix = read_csv(PROCESSED / "e2e_stage_by_variant.csv")
    stages = ["access", "budget", "tee", "proof", "settlement", "audit"]
    stage_rows = {(row["variant"], row["stage"]): f(row, "mean_latency_ms") for row in matrix}
    x = np.arange(len(order))
    totals = np.asarray([sum(stage_rows.get((v, s), 0.0) for s in stages) for v in order])
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for stage in stages:
        share = np.asarray([stage_rows.get((v, stage), 0.0) for v in order])
        share = np.divide(share, totals, out=np.zeros_like(share), where=totals > 0) * 100
        ax.plot(x, share, "o-", color=COLORS.get(stage, "#777777"), label=stage.title())
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_ylabel("Share of total stage time (%)")
    ax.set_title("Stage-time composition across ablations")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig3c_stage_breakdown")

    # 3d: ordered cost profile; connecting observations prevents a sparse,
    # label-heavy cloud while preserving the measured values.
    summary = read_csv(PROCESSED / "e2e_ablation_summary.csv")
    summary = sorted(summary, key=lambda row: order.index(row["variant"]))
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.plot(
        np.arange(len(summary)),
        [f(row, "mean_total_gas") for row in summary],
        "o-",
        color="#8064a2",
        label="Mean local-Hardhat gas",
    )
    ax.set_xticks(np.arange(len(summary)), [variant_label(row["variant"]) for row in summary], rotation=25, ha="right")
    ax.set_ylabel("Mean local-Hardhat gas")
    ax.set_title("Gas cost across ablation configurations")
    ax.legend()
    tidy(ax)
    save(fig, "fig3d_cost_breakdown")


def fig4() -> None:
    scaling = sorted(read_csv(PROCESSED / "zk_scaling.csv"), key=lambda row: f(row, "n_rules"))
    rules = np.asarray([f(row, "n_rules") for row in scaling])

    # 4a: bubble/lollipop profile instead of a nearly diagonal dual-axis line.
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    constraints = np.asarray([f(row, "constraints") for row in scaling])
    witness_kib = np.asarray([f(row, "witness_size_bytes") / 1024 for row in scaling])
    sizes = 45 + 230 * witness_kib / max(float(np.nanmax(witness_kib)), 1.0)
    ax.scatter(rules, constraints, s=sizes, c=witness_kib, cmap="viridis", edgecolors="#222222", linewidths=0.6)
    ax.plot(rules, constraints, color="#4472c4", linewidth=1.2, alpha=0.55)
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("R1CS constraints")
    ax.set_title("Compliance circuit growth")
    tidy(ax)
    save(fig, "fig4a_constraints")

    # 4b: empirical CDFs are legible with many repeated measurements and do
    # not turn a distribution into a collection of box glyphs.
    trials = retained(read_csv(PROCESSED / "zk_scaling_trials.csv"))
    groups = sorted(grouped(trials, "n_rules").items(), key=lambda item: int(item[0]))
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for rule, rows in groups:
        ecdf(ax, values(rows, "prove_time_ms"), label=f"{rule} rules: prove", color="#4472c4")
        ecdf(ax, values(rows, "verify_time_ms"), label=f"{rule} rules: verify", color="#8064a2")
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Proof and verification latency distributions")
    ax.legend(ncol=2, fontsize=8)
    tidy(ax, log_y=False)
    save(fig, "fig4b_proving_time")

    # 4c: normalized footprint lines keep the three measures on one scale.
    distribution = {row["circuit"]: row for row in read_csv(PROCESSED / "zk_scaling_distribution.csv")}
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for field, label, color in (
        ("proof_size_bytes", "Proof", "#4472c4"),
        ("proving_key_bytes", "Proving key", "#c55a11"),
        ("peak_working_set_p95_bytes", "Prover working set", "#70ad47"),
    ):
        vals: list[float] = []
        for row in scaling:
            source = distribution.get(row["circuit"], row)
            vals.append(f(source, field))
        base = vals[0] if vals and vals[0] > 0 else 1.0
        ax.plot(rules, np.asarray(vals) / base, "o-", color=color, label=label)
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Size relative to one-rule circuit")
    ax.set_title("Normalized proof-system footprint")
    ax.legend()
    tidy(ax, log_y=True)
    save(fig, "fig4c_proof_key_size")

    # 4d: connect the three backend observations in a fixed, documented order.
    circulation = read_csv(PROCESSED / "zk_backend_circulation.csv")
    backend = {row["scheme"]: row for row in read_csv(PROCESSED / "zk_backend_distribution.csv")}
    schemes = [row["scheme"] for row in circulation]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.plot(
        schemes,
        [f(row, "full_circulation_throughput_req_s") for row in circulation],
        "o-",
        color="#4472c4",
        label="Full-circulation throughput",
    )
    ax.set_xlabel("Proof backend")
    ax.set_ylabel("Model-calibrated throughput (requests/s)")
    ax.set_title("Proof-backend throughput")
    ax.legend()
    tidy(ax)
    save(fig, "fig4d_backend_throughput")


def fig5() -> None:
    dp = retained(read_csv(PROCESSED / "dp_vbs_trials.csv"))
    epsilons = sorted({row["epsilon_requested"] for row in dp}, key=float)

    # 5a: ECDFs show utility across epsilon without overplotting 30-run boxes.
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for index, epsilon in enumerate(epsilons):
        data = values([row for row in dp if row["epsilon_requested"] == epsilon], "relative_error")
        ecdf(ax, data, label=f"epsilon={epsilon}", color=plt.cm.viridis((index + 1) / (len(epsilons) + 1)))
    ax.set_xlabel("Relative error")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Differential-privacy utility")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig5a_dp_relative_error")

    # 5b: analytical composition is drawn as an ordinary line chart, not a
    # staircase, because the underlying fixed-point values are already sampled
    # at release indices.
    composition = read_csv(PROCESSED / "dp_composition.csv")
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for index, epsilon in enumerate(epsilons):
        rows = sorted([row for row in composition if row["epsilon_requested"] == epsilon], key=lambda row: f(row, "releases"))
        ax.plot(
            [f(row, "releases") for row in rows],
            [f(row, "conservative_fixed_epsilon") for row in rows],
            "o-",
            color=plt.cm.viridis((index + 1) / (len(epsilons) + 1)),
            label=f"epsilon={epsilon}",
        )
    ax.set_xlabel("Release index")
    ax.set_ylabel("Cumulative conservative privacy loss")
    ax.set_title("Repeated-release privacy composition")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig5b_cumulative_privacy_loss")

    # 5c: continuous-looking ECDF of the conservative rounding margin.
    rounding = read_csv(PROCESSED / "dp_rounding_margin.csv")
    margins = values(rounding, "rounding_margin_micro_epsilon")
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ecdf(ax, margins, label="Observed margins", color="#4472c4")
    ax.axvline(0, color="#c55a11", linestyle="--", linewidth=1.2, label="Zero margin")
    ax.set_xlabel("Conservative rounding margin (micro-epsilon)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Fixed-point rounding margin")
    ax.legend()
    tidy(ax)
    save(fig, "fig5c_rounding_gap")

    # 5d: one trajectory per epsilon, with accepted releases represented by
    # the measured remaining budget only (the acceptance invariant is in CSV).
    budget = read_csv(PROCESSED / "budget_exhaustion_trajectory.csv")
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for index, epsilon in enumerate(sorted({row["epsilon_requested"] for row in budget}, key=float)):
        rows = sorted([row for row in budget if row["epsilon_requested"] == epsilon], key=lambda row: f(row, "request_index"))
        ax.plot(
            [f(row, "request_index") for row in rows],
            [f(row, "budget_remaining_fixed") / 1_000_000 for row in rows],
            "o-",
            color=plt.cm.viridis((index + 1) / (len(epsilons) + 1)),
            label=f"epsilon={epsilon}",
        )
    ax.set_xlabel("Request index")
    ax.set_ylabel("Remaining privacy budget")
    ax.set_title("Privacy-budget exhaustion trajectories")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig5d_budget_exhaustion")


def fig6() -> None:
    summary = sorted(read_csv(PROCESSED / "vbs_performance_summary.csv"), key=lambda row: f(row, "payload_bytes"))
    payload = np.asarray([f(row, "payload_bytes") for row in summary])

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for name, median_field, low_field, high_field, color in (
        ("Native", "native_p50_latency_ms", "native_latency_bootstrap_ci95_low_ms", "native_latency_bootstrap_ci95_high_ms", COLORS["Native"]),
        ("VBS Enclave", "vbs_p50_latency_ms", "vbs_latency_bootstrap_ci95_low_ms", "vbs_latency_bootstrap_ci95_high_ms", COLORS["VBS Enclave"]),
    ):
        y = np.asarray([f(row, median_field) for row in summary])
        lo = np.asarray([f(row, low_field) for row in summary])
        hi = np.asarray([f(row, high_field) for row in summary])
        ax.plot(payload, y, "o-", color=color, label=name)
        ax.fill_between(payload, lo, hi, color=color, alpha=0.16)
    ax.set_xscale("log")
    ax.set_xlabel("Plaintext payload (bytes)")
    ax.set_ylabel("Process latency (ms)")
    ax.set_title("Native and VBS Enclave latency")
    ax.legend()
    tidy(ax)
    save(fig, "fig6a_native_vs_vbs_latency")

    trials = retained(read_csv(PROCESSED / "native_vbs_trials.csv"))
    by_payload = grouped(trials, "payload_bytes")
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    medians = [quantile(values(by_payload.get(str(int(p)), []), "vbs_slowdown_vs_native"), 50) for p in payload]
    p95 = [quantile(values(by_payload.get(str(int(p)), []), "vbs_slowdown_vs_native"), 95) for p in payload]
    ax.plot(payload, medians, "o-", color="#c55a11", label="Median slowdown")
    ax.plot(payload, p95, "s--", color="#8064a2", label="95th percentile")
    ax.set_xscale("log")
    ax.set_xlabel("Plaintext payload (bytes)")
    ax.set_ylabel("VBS / Native latency")
    ax.set_title("VBS overhead scaling")
    ax.legend()
    tidy(ax)
    save(fig, "fig6b_vbs_slowdown")

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for name, field, color in (("Native", "native_payload_throughput_mib_s", COLORS["Native"]), ("VBS Enclave", "vbs_payload_throughput_mib_s", COLORS["VBS Enclave"])):
        medians = [quantile(values(by_payload.get(str(int(p)), []), field), 50) for p in payload]
        lows = [quantile(values(by_payload.get(str(int(p)), []), field), 2.5) for p in payload]
        highs = [quantile(values(by_payload.get(str(int(p)), []), field), 97.5) for p in payload]
        ax.plot(payload, medians, "o-", color=color, label=name)
        ax.fill_between(payload, lows, highs, color=color, alpha=0.15)
    ax.set_xscale("log")
    ax.set_xlabel("Plaintext payload (bytes)")
    ax.set_ylabel("Payload throughput (MiB/s)")
    ax.set_title("Payload throughput scaling")
    ax.legend()
    tidy(ax)
    save(fig, "fig6c_payload_throughput")

    stage_rows = read_csv(PROCESSED / "vbs_stage_breakdown.csv")
    stages = ["decrypt", "aggregate", "dp_noise", "transcript", "attestation_generation"]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for stage in stages:
        vals: list[float] = []
        for p in payload:
            candidates = [row for row in stage_rows if int(f(row, "payload_bytes")) == int(p) and row["stage"] == stage]
            vals.append(f(candidates[0], "mean_latency_us") / 1000 if candidates else 0.0)
        totals = np.zeros(len(payload))
        for item in stages:
            totals += np.asarray([
                f(next((row for row in stage_rows if int(f(row, "payload_bytes")) == int(p) and row["stage"] == item), {}), "mean_latency_us") / 1000
                for p in payload
            ])
        share = np.divide(np.asarray(vals), totals, out=np.zeros_like(totals), where=totals > 0) * 100
        ax.plot(payload, share, "o-", color=COLORS.get(stage, "#777777"), label=stage.replace("_", " ").title())
    ax.set_xscale("log")
    ax.set_xlabel("Plaintext payload (bytes)")
    ax.set_ylabel("Share of enclave stage time (%)")
    ax.set_title("VBS stage-time composition")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig6d_enclave_stage_breakdown")

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for configuration, prefix, marker, color in (("Native", "native", "o", COLORS["Native"]), ("VBS Enclave", "vbs", "s", COLORS["VBS Enclave"])):
        x_values = [f(row, f"{prefix}_normalized_peak_cpu_percent") for row in trials]
        y_values = [f(row, f"{prefix}_peak_rss_bytes") / (1024 * 1024) for row in trials]
        mask = np.isfinite(x_values) & np.isfinite(y_values)
        ax.scatter(np.asarray(x_values)[mask], np.asarray(y_values)[mask], marker=marker, color=color, alpha=0.32, label=configuration)
    ax.set_xlabel("Peak normalized process CPU (%)")
    ax.set_ylabel("Peak working set (MiB)")
    ax.set_title("Host-process resource footprint")
    ax.legend()
    tidy(ax)
    save(fig, "fig6e_memory_footprint")

    overhead = read_csv(PROCESSED / "vbs_attestation_overhead.csv")
    largest = max((f(row, "payload_bytes") for row in overhead), default=0)
    overhead = [row for row in overhead if f(row, "payload_bytes") == largest]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for stage, color in (("Transcript", "#8064a2"), ("Evidence generation", "#c55a11"), ("External validation", "#70ad47")):
        ecdf(ax, values([row for row in overhead if row["stage"] == stage], "latency_us"), label=stage, color=color)
    ax.set_xlabel("Latency (microseconds)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Transcript, evidence, and validation overhead")
    ax.legend()
    tidy(ax)
    save(fig, "fig6f_transcript_attestation_overhead")


def fig7() -> None:
    binding = read_csv(PROCESSED / "attack_binding_matrix.csv")
    attacks = [row["attack_case"] for row in binding]
    layers = ["enclave", "attestation_validator", "circuit_adapter", "solidity_settlement"]
    layer_labels = ["Enclave", "Attestation validator", "Circuit adapter", "Solidity settlement"]
    layer_index = {label: index for index, label in enumerate(layers)}
    matrix = np.zeros((len(attacks), len(layers)))
    for i, row in enumerate(binding):
        first = row.get("first_rejecting_layer", "")
        if first in layer_index:
            matrix[i, layer_index[first]] = 1
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.imshow(matrix, aspect="auto", cmap=matplotlib.colors.ListedColormap(["#f2f2f2", "#4472c4"]), vmin=0, vmax=1)
    ax.set_xticks(np.arange(len(layers)), layer_labels, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(attacks)), [attack.replace("_", " ") for attack in attacks])
    ax.set_xlabel("First rejecting layer")
    ax.set_ylabel("Attack case")
    ax.set_title("Binding-attack rejection layer")
    ax.grid(False)
    save(fig, "fig7a_context_substitution")

    attacks_raw = read_csv(PROCESSED / "protocol_attack_latency.csv")
    wanted = ["altered_transcript", "altered_attestation", "stale_attestation", "tampered_proof", "nullifier_replay"]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for index, case in enumerate([case for case in wanted if case in {row["attack_case"] for row in attacks_raw}]):
        ecdf(ax, values([row for row in attacks_raw if row["attack_case"] == case], "latency_ms"), label=case.replace("_", " "), color=plt.cm.plasma((index + 1) / 6))
    ax.set_xlabel("Rejection latency (ms)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Tampering and replay rejection latency")
    ax.legend(ncol=2)
    tidy(ax)
    save(fig, "fig7b_tampering_replay")

    concurrency = sorted(read_csv(PROCESSED / "settlement_concurrency_summary.csv"), key=lambda row: f(row, "concurrency"))
    x = np.asarray([f(row, "concurrency") for row in concurrency])
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.plot(x, [f(row, "mean_accepted") for row in concurrency], "o-", color="#70ad47", label="Accepted")
    ax.plot(x, [f(row, "mean_reverted") for row in concurrency], "s--", color="#c55a11", label="Reverted")
    ax.plot(x, [f(row, "mean_throughput_req_s") for row in concurrency], "^-", color="#1f4e79", label="Throughput")
    ax.set_xlabel("Same-block concurrency")
    ax.set_ylabel("Measured value")
    ax.set_title("Settlement outcomes under concurrency")
    ax.legend()
    tidy(ax)
    save(fig, "fig7c_concurrency_outcomes")

    trials = retained(read_csv(PROCESSED / "settlement_concurrency_trials.csv"))
    levels = sorted({row["concurrency"] for row in trials}, key=int)
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    medians = [quantile(values([row for row in trials if row["concurrency"] == level], "settlement_mean_latency_ms"), 50) for level in levels]
    p95 = [quantile(values([row for row in trials if row["concurrency"] == level], "settlement_mean_latency_ms"), 95) for level in levels]
    ax.plot([int(level) for level in levels], medians, "o-", color="#4472c4", label="Median latency")
    ax.plot([int(level) for level in levels], p95, "s--", color="#c55a11", label="95th percentile")
    ax.set_xlabel("Same-block concurrency")
    ax.set_ylabel("Settlement latency (ms)")
    ax.set_title("Settlement latency scaling")
    ax.legend()
    tidy(ax)
    save(fig, "fig7d_concurrency_invariants_latency")


def fig8() -> None:
    capabilities = read_csv(PROCESSED / "comparison_capabilities.csv")
    configurations = [name for name in COMPARISON_ORDER if name in {row["configuration"] for row in capabilities}]
    fields = [field for field in capabilities[0] if field not in {"measurement_type", "configuration", "security_coverage_score"}]
    matrix = np.asarray([[f(next(row for row in capabilities if row["configuration"] == configuration), field, 0) for field in fields] for configuration in configurations])
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.imshow(matrix, aspect="auto", cmap=matplotlib.colors.ListedColormap(["#f2f2f2", "#4472c4"]), vmin=0, vmax=1)
    ax.set_xticks(np.arange(len(fields)), [field.replace("_", " ").title() for field in fields], rotation=35, ha="right")
    ax.set_yticks(np.arange(len(configurations)), configurations)
    ax.set_xlabel("Capability")
    ax.set_ylabel("Configuration")
    ax.set_title("Lifecycle capability coverage")
    ax.grid(False)
    save(fig, "fig8a_lifecycle_capabilities")

    trials = retained(read_csv(PROCESSED / "comparison_trials.csv"))
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    x = np.arange(len(configurations))
    latency = [quantile(values([row for row in trials if row["configuration"] == configuration], "total_latency_ms"), 50) for configuration in configurations]
    throughput = [quantile(values([row for row in trials if row["configuration"] == configuration], "throughput_req_s"), 50) for configuration in configurations]
    # A single latency chart avoids the misleading visual comparison caused by
    # placing two differently-scaled panels beside each other.
    ax.plot(x, latency, "o-", color="#4472c4", label="Median latency")
    ax.set_xticks(x, configurations, rotation=28, ha="right")
    ax.set_ylabel("End-to-end latency (ms)")
    ax.set_title("Controlled comparison: latency")
    ax.legend()
    tidy(ax)
    save(fig, "fig8b_comparison_latency_throughput")

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    gas = [quantile(values([row for row in trials if row["configuration"] == configuration], "total_gas"), 50) for configuration in configurations]
    coverage = [f(next(row for row in capabilities if row["configuration"] == configuration), "security_coverage_score") for configuration in configurations]
    ax.plot(x, gas, "o-", color="#8064a2", label="Median local-Hardhat gas")
    ax.set_xticks(x, configurations, rotation=28, ha="right")
    ax.set_ylabel("Median local-Hardhat gas")
    ax.set_title("Controlled comparison: settlement cost")
    ax.legend()
    tidy(ax)
    save(fig, "fig8c_comparison_pareto")

    overhead = read_csv(PROCESSED / "comparison_overhead.csv")
    stages = ["proof_overhead_ms", "attestation_overhead_ms", "budget_overhead_ms", "other_lifecycle_ms"]
    stage_labels = ["Proof", "Attestation", "Budget", "Other lifecycle"]
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    for stage, label, color in zip(stages, stage_labels, ("#8064a2", "#c55a11", "#70ad47", "#a5a5a5")):
        rows = [row for row in overhead if row["stage"] == stage]
        ordered = [next((row for row in rows if row["configuration"] == configuration), {}) for configuration in configurations]
        ax.plot(x, [f(row, "mean_latency_ms", 0) for row in ordered], "o-", color=color, label=label)
    ax.set_xticks(x, configurations, rotation=28, ha="right")
    ax.set_ylabel("Latency contribution (ms)")
    ax.set_title("Lifecycle overhead by configuration")
    ax.legend()
    tidy(ax)
    save(fig, "fig8d_comparison_overhead")


def main() -> int:
    style()
    fig3()
    fig4()
    fig5()
    fig6()
    fig7()
    fig8()
    print("generated 26 independent Phase 8 panels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
