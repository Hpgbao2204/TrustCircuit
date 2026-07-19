from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
PANELS = ROOT / "Paper" / "figures" / "panels"

COLORS = ("#1f5a94", "#e07a2d", "#2f855a", "#8b5fbf", "#b23a48", "#607d8b")


def rows(name: str) -> list[dict[str, str]]:
    path = PROCESSED / name
    if not path.is_file():
        raise FileNotFoundError(f"missing processed data: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 9,
            "legend.fontsize": 6.8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linewidth": 0.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, stem: str) -> None:
    PANELS.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=0.6)
    fig.savefig(PANELS / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(PANELS / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def short_payload(value: float) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):g} MiB"
    return f"{value / 1024:g} KiB"


def bar_panel(
    data: list[dict[str, str]],
    *,
    stem: str,
    key: str,
    value: str,
    ylabel: str,
    labels: dict[str, str] | None = None,
    color: str = COLORS[0],
    yscale: str | None = None,
) -> None:
    xlabels = [labels.get(row[key], row[key]) if labels else row[key] for row in data]
    values = [float(row[value]) for row in data]
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    x = np.arange(len(data))
    ax.bar(x, values, color=color, width=0.68)
    ax.set_xticks(x, xlabels, rotation=25, ha="right")
    ax.set_ylabel(ylabel)
    if yscale:
        ax.set_yscale(yscale)
    ax.set_axisbelow(True)
    save(fig, stem)


def fig3() -> None:
    ablation = rows("e2e_ablation_summary.csv")
    labels = {
        "baseline_minimal": "Baseline",
        "access_only": "Access only",
        "no_budget": "No budget",
        "no_zk": "No ZK",
        "no_tee": "No TEE*",
        "full_trustcircuit": "Full",
    }
    bar_panel(
        ablation,
        stem="fig3a_ablation_throughput",
        key="variant",
        value="mean_throughput_req_s",
        ylabel="Throughput (requests/s)",
        labels=labels,
        yscale="log",
    )
    bar_panel(
        ablation,
        stem="fig3b_ablation_latency",
        key="variant",
        value="mean_latency_ms",
        ylabel="End-to-end latency (ms)",
        labels=labels,
        color=COLORS[1],
        yscale="log",
    )
    stages = rows("e2e_stage_breakdown.csv")
    bar_panel(
        stages,
        stem="fig3c_stage_breakdown",
        key="stage",
        value="mean_latency_ms",
        ylabel="Mean latency (ms)",
        labels={"tee": "VBS", "proof": "Proof", "settlement": "Settle"},
        color=COLORS[2],
    )
    gas = rows("e2e_gas_breakdown.csv")
    bar_panel(
        gas,
        stem="fig3d_cost_breakdown",
        key="stage",
        value="mean_gas",
        ylabel="Gas",
        labels={"proof": "Proof setup", "settlement": "Atomic settle"},
        color=COLORS[3],
    )


def fig4() -> None:
    scaling = rows("zk_scaling.csv")
    rule_count = [int(row["n_rules"]) for row in scaling]
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    ax.plot(rule_count, [float(row["constraints"]) for row in scaling], "o-", color=COLORS[0])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("R1CS constraints")
    save(fig, "fig4a_constraints")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    means = np.array([float(row["prove_time_ms_mean"]) for row in scaling])
    stds = np.array([float(row["prove_time_ms_std"]) for row in scaling])
    ax.errorbar(rule_count, means, yerr=stds, fmt="o-", capsize=2, color=COLORS[1])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Proving time (ms)")
    save(fig, "fig4b_proving_time")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    x = np.arange(len(scaling))
    proof_kib = [float(row["proof_size_bytes"]) / 1024 for row in scaling]
    key_mib = [float(row["proving_key_bytes"]) / (1024 * 1024) for row in scaling]
    width = 0.36
    ax.bar(x - width / 2, proof_kib, width, label="Proof bundle (KiB)", color=COLORS[0])
    ax2 = ax.twinx()
    ax2.bar(x + width / 2, key_mib, width, label="Proving key (MiB)", color=COLORS[1])
    ax.set_xticks(x, rule_count)
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Proof bundle (KiB)")
    ax2.set_ylabel("Proving key (MiB)")
    ax.grid(axis="x", visible=False)
    handles = ax.containers + ax2.containers
    ax.legend(handles, ["Proof bundle", "Proving key"], loc="upper left", frameon=False)
    save(fig, "fig4c_proof_key_size")

    circulation = rows("zk_backend_circulation.csv")
    bar_panel(
        circulation,
        stem="fig4d_backend_throughput",
        key="scheme",
        value="full_circulation_throughput_req_s",
        ylabel="Full-circulation throughput (req/s)",
        labels={"groth16": "Groth16", "plonk": "PLONK", "fflonk": "fflonk"},
        color=COLORS[2],
    )


def fig5() -> None:
    error = rows("dp_error_summary.csv")
    eps = [float(row["epsilon_requested"]) for row in error]
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    means = np.array([float(row["mean_relative_error"]) * 100 for row in error])
    stds = np.array([float(row["std_relative_error"]) * 100 for row in error])
    ax.errorbar(eps, means, yerr=stds, fmt="o-", capsize=2, color=COLORS[0])
    ax.set_xscale("log", base=2)
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Relative error (%)")
    save(fig, "fig5a_dp_relative_error")

    composition = rows("dp_composition.csv")
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    for index, epsilon in enumerate(("0.05", "0.1", "0.5", "1.0")):
        subset = [row for row in composition if row["epsilon_requested"] == epsilon]
        if not subset:
            subset = [row for row in composition if float(row["epsilon_requested"]) == float(epsilon)]
        ax.plot(
            [int(row["releases"]) for row in subset],
            [float(row["conservative_fixed_epsilon"]) for row in subset],
            label=rf"$\epsilon={epsilon}$",
            color=COLORS[index],
        )
    ax.set_xlabel("Repeated releases")
    ax.set_ylabel(r"Cumulative conservative $\epsilon$")
    ax.legend(frameon=False, ncol=2)
    save(fig, "fig5b_cumulative_privacy_loss")

    rounding = rows("dp_rounding_summary.csv")
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    rounding_x = np.arange(len(rounding))
    rounding_values = [float(row["max_rounding_gap_fixed"]) for row in rounding]
    ax.axhline(0, color="#555555", linewidth=0.8)
    ax.scatter(rounding_x, rounding_values, color=COLORS[3], s=28, zorder=3)
    for x_value, gap in zip(rounding_x, rounding_values):
        ax.annotate(f"{gap:g}", (x_value, gap), xytext=(0, 5), textcoords="offset points", ha="center")
    ax.set_xticks(rounding_x, [str(row["epsilon_requested"]) for row in rounding])
    if max(rounding_values) == min(rounding_values) == 0:
        ax.set_ylim(-0.1, 0.5)
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Max fixed-point gap (units of $10^{-6}$)")
    save(fig, "fig5c_rounding_gap")

    exhaustion = rows("budget_exhaustion_summary.csv")
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    x = np.arange(len(exhaustion))
    accepted = [int(row["accepted_requests"]) for row in exhaustion]
    reverted = [int(row["reverted_requests"]) for row in exhaustion]
    ax.bar(x, accepted, label="Accepted", color=COLORS[2])
    ax.bar(x, reverted, bottom=accepted, label="Reverted", color=COLORS[4])
    ax.set_xticks(x, [row["epsilon_requested"] for row in exhaustion])
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Requests")
    ax.legend(frameon=False)
    save(fig, "fig5d_budget_exhaustion")


def fig6() -> None:
    performance = rows("vbs_performance_summary.csv")
    payload = [int(row["payload_bytes"]) for row in performance]
    labels = [short_payload(value) for value in payload]
    x = np.arange(len(payload))

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    ax.plot(x, [float(row["reference_mean_latency_ms"]) for row in performance], "o-", label="Python reference*", color=COLORS[1])
    ax.plot(x, [float(row["vbs_mean_latency_ms"]) for row in performance], "s-", label="VBS process", color=COLORS[0])
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Latency (ms)")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    save(fig, "fig6a_native_vs_vbs_latency")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    ax.plot(x, [float(row["slowdown_vs_python_reference"]) for row in performance], "o-", color=COLORS[4])
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Slowdown vs Python reference (×)")
    ax.set_yscale("log")
    save(fig, "fig6b_vbs_slowdown")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    ax.plot(x, [float(row["reference_throughput_mib_s"]) for row in performance], "o-", label="Python reference*", color=COLORS[1])
    ax.plot(x, [float(row["vbs_throughput_mib_s"]) for row in performance], "s-", label="VBS process", color=COLORS[0])
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Throughput (MiB/s)")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    save(fig, "fig6c_payload_throughput")

    stage_rows = rows("vbs_stage_breakdown.csv")
    stage_names = ["decrypt", "aggregate", "dp_noise", "transcript", "attestation_generation"]
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    bottom = np.zeros(len(payload))
    for index, stage in enumerate(stage_names):
        values = [
            float(next(row["mean_latency_us"] for row in stage_rows if int(row["payload_bytes"]) == size and row["stage"] == stage)) / 1000
            for size in payload
        ]
        stage_label = {
            "dp_noise": "DP noise",
            "attestation_generation": "attest. generation",
        }.get(stage, stage)
        ax.bar(x, values, bottom=bottom, label=stage_label, color=COLORS[index])
        bottom += np.array(values)
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Enclave stage latency (ms)")
    ax.legend(frameon=False, ncol=2)
    save(fig, "fig6d_enclave_stage_breakdown")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    width = 0.36
    ax.bar(x - width / 2, [float(row["reference_rss_mib"]) for row in performance], width, label="Python process*", color=COLORS[1])
    ax.bar(x + width / 2, [float(row["host_peak_rss_mib"]) for row in performance], width, label="VBS host", color=COLORS[0])
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Resident memory (MiB)")
    ax.legend(frameon=False)
    save(fig, "fig6e_memory_footprint")

    overhead = rows("vbs_attestation_overhead.csv")
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    bottom = np.zeros(len(overhead))
    for index, (field, label) in enumerate((
        ("transcript_us", "Transcript"),
        ("attestation_generation_us", "Evidence generation"),
        ("attestation_validation_host_us", "External validation"),
    )):
        values = np.array([float(row[field]) / 1000 for row in overhead])
        ax.bar(x, values, bottom=bottom, label=label, color=COLORS[index])
        bottom += values
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Transcript/attestation overhead (ms)")
    ax.legend(frameon=False)
    save(fig, "fig6f_transcript_attestation_overhead")


def fig7() -> None:
    attacks = rows("protocol_attack_summary.csv")
    context = [row for row in attacks if row["category"] == "context"]
    tampering = [row for row in attacks if row["category"] != "context"]
    labels = {
        "wrong_request": "Request",
        "wrong_asset": "Asset",
        "wrong_consumer_id": "Consumer ID",
        "wrong_consumer_address": "Caller",
        "wrong_policy": "Policy",
        "wrong_function": "Function",
        "wrong_result": "Result",
        "altered_transcript": "Transcript",
        "altered_attestation": "Attestation",
        "stale_attestation": "Stale",
        "tampered_proof": "Proof",
        "nullifier_replay": "Replay",
    }
    bar_panel(
        context,
        stem="fig7a_context_substitution",
        key="attack_case",
        value="rejected",
        ylabel="Rejected (1=yes)",
        labels=labels,
        color=COLORS[2],
    )
    bar_panel(
        tampering,
        stem="fig7b_tampering_replay",
        key="attack_case",
        value="rejected",
        ylabel="Rejected (1=yes)",
        labels=labels,
        color=COLORS[4],
    )

    concurrency = rows("settlement_concurrency_summary.csv")
    levels = [int(row["concurrency"]) for row in concurrency]
    x = np.arange(len(levels))
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    accepted = np.array([int(row["accepted"]) for row in concurrency])
    reverted = np.array([int(row["reverted"]) for row in concurrency])
    ax.bar(x, accepted, label="Accepted", color=COLORS[2])
    ax.bar(x, reverted, bottom=accepted, label="Reverted", color=COLORS[4])
    ax.set_xticks(x, levels)
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Requests")
    ax.legend(frameon=False)
    save(fig, "fig7c_concurrency_outcomes")

    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    violations = [int(row["budget_invariant_violations"]) for row in concurrency]
    ax.plot(x, violations, "o-", color=COLORS[4], label="Invariant violations")
    ax.set_xticks(x, levels)
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Invariant violations")
    ax.set_ylim(-0.05, max(1.0, max(violations) + 0.2))
    ax2 = ax.twinx()
    ax2.plot(x, [float(row["settlement_mean_latency_ms"]) for row in concurrency], "s--", color=COLORS[0], label="Settlement latency")
    ax2.set_ylabel("Mean settlement latency (ms)")
    lines = ax.lines + ax2.lines
    ax.legend(lines, [line.get_label() for line in lines], frameon=False, loc="upper left")
    save(fig, "fig7d_concurrency_invariants_latency")


def main() -> int:
    style()
    fig3()
    fig4()
    fig5()
    fig6()
    fig7()
    pdfs = sorted(PANELS.glob("*.pdf"))
    pngs = sorted(PANELS.glob("*.png"))
    if len(pdfs) != 22 or len(pngs) != 22:
        raise RuntimeError(f"expected 22 PDF and PNG panels, found {len(pdfs)} and {len(pngs)}")
    print(f"generated {len(pdfs)} PDF and {len(pngs)} PNG panels in {PANELS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
