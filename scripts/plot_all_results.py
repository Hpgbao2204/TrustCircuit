from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
PANELS = ROOT / "Paper" / "figures" / "panels"
FIGSIZE = (12, 8)
PNG_DPI = 600
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
            "font.size": 17,
            "axes.labelsize": 19,
            "axes.titlesize": 19,
            "legend.fontsize": 15,
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linewidth": 0.8,
            "lines.linewidth": 2.4,
            "lines.markersize": 8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, stem: str) -> None:
    PANELS.mkdir(parents=True, exist_ok=True)
    fig.set_size_inches(*FIGSIZE, forward=True)
    fig.tight_layout(pad=1.2)
    fig.savefig(PANELS / f"{stem}.pdf")
    fig.savefig(PANELS / f"{stem}.png", dpi=PNG_DPI)
    plt.close(fig)


def short_payload(value: float) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):g} MiB"
    return f"{value / 1024:g} KiB"


def set_payload_ticks(ax: plt.Axes, payload: list[int]) -> None:
    ax.set_xscale("log", base=2)
    ax.set_xticks(payload, [short_payload(value) for value in payload])


def empirical_band(
    ax: plt.Axes,
    x: list[int],
    center: list[float],
    lower: list[float],
    upper: list[float],
    *,
    label: str,
    color: str,
    marker: str,
) -> None:
    ax.plot(x, center, marker=marker, label=label, color=color)
    ax.fill_between(x, lower, upper, color=color, alpha=0.16, linewidth=0)


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
    x = np.arange(len(ablation))
    xlabels = [labels[row["variant"]] for row in ablation]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    means = np.array([float(row["mean_throughput_req_s"]) for row in ablation])
    stds = np.array([float(row["std_throughput_req_s"]) for row in ablation])
    ax.errorbar(x, means, yerr=stds, fmt="o", capsize=7, color=COLORS[0])
    ax.set_xticks(x, xlabels, rotation=18, ha="right")
    ax.set_ylabel("Throughput (requests/s)")
    ax.set_yscale("log")
    ax.grid(axis="x", visible=False)
    save(fig, "fig3a_ablation_throughput")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    means = np.array([float(row["mean_latency_ms"]) for row in ablation])
    stds = np.array([float(row["std_latency_ms"]) for row in ablation])
    ax.errorbar(x, means, yerr=stds, fmt="o", capsize=7, color=COLORS[1])
    ax.set_xticks(x, xlabels, rotation=18, ha="right")
    ax.set_ylabel("End-to-end latency (ms)")
    ax.set_yscale("log")
    ax.grid(axis="x", visible=False)
    save(fig, "fig3b_ablation_latency")

    stages = rows("e2e_stage_breakdown.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    left = 0.0
    for index, row in enumerate(stages):
        value = float(row["mean_latency_ms"])
        label = {
            "tee": "VBS",
            "proof": "Proof",
            "settlement": "Settlement",
        }.get(row["stage"], row["stage"].title())
        ax.barh([0], [value], left=left, label=label, color=COLORS[index % len(COLORS)])
        if value > 0.04 * sum(float(item["mean_latency_ms"]) for item in stages):
            ax.text(left + value / 2, 0, f"{value:.1f}", ha="center", va="center", color="white")
        left += value
    ax.set_yticks([0], ["Full TrustCircuit"])
    ax.set_xlabel("Mean latency (ms)")
    ax.margins(y=0.9)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.04))
    ax.grid(axis="y", visible=False)
    save(fig, "fig3c_stage_breakdown")

    gas = rows("e2e_gas_breakdown.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    y = np.arange(len(gas))
    values = [float(row["mean_gas"]) for row in gas]
    gas_labels = [
        {"proof": "Proof setup", "settlement": "Atomic settlement"}.get(
            row["stage"], row["stage"].title()
        )
        for row in gas
    ]
    ax.hlines(y, 0, values, color=COLORS[3], linewidth=3)
    ax.scatter(values, y, color=COLORS[3], s=100, zorder=3)
    ax.set_yticks(y, gas_labels)
    ax.set_xlabel("Gas")
    ax.grid(axis="y", visible=False)
    save(fig, "fig3d_cost_breakdown")


def fig4() -> None:
    scaling = rows("zk_scaling.csv")
    rule_count = [int(row["n_rules"]) for row in scaling]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(rule_count, [float(row["constraints"]) for row in scaling], "o-", color=COLORS[0])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("R1CS constraints")
    save(fig, "fig4a_constraints")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    means = np.array([float(row["prove_time_ms_mean"]) for row in scaling])
    stds = np.array([float(row["prove_time_ms_std"]) for row in scaling])
    ax.errorbar(rule_count, means, yerr=stds, fmt="o-", capsize=7, color=COLORS[1])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Proving time (ms)")
    save(fig, "fig4b_proving_time")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    proof_kib = [float(row["proof_size_bytes"]) / 1024 for row in scaling]
    key_mib = [float(row["proving_key_bytes"]) / (1024 * 1024) for row in scaling]
    line1 = ax.plot(rule_count, proof_kib, "o", label="Proof bundle", color=COLORS[0])
    ax2 = ax.twinx()
    line2 = ax2.plot(rule_count, key_mib, "s--", label="Proving key", color=COLORS[1])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Proof bundle (KiB)")
    ax2.set_ylabel("Proving key (MiB)")
    lines = line1 + line2
    ax.legend(lines, [line.get_label() for line in lines], frameon=False, loc="upper left")
    save(fig, "fig4c_proof_key_size")

    circulation = rows("zk_backend_circulation.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    y = np.arange(len(circulation))
    values = [float(row["full_circulation_throughput_req_s"]) for row in circulation]
    names = [{"groth16": "Groth16", "plonk": "PLONK", "fflonk": "fflonk"}.get(row["scheme"], row["scheme"]) for row in circulation]
    ax.hlines(y, 0, values, linewidth=3, color=COLORS[2])
    ax.scatter(values, y, color=COLORS[2], s=110, zorder=3)
    ax.set_yticks(y, names)
    ax.set_xlabel("Full-circulation throughput (requests/s)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig4d_backend_throughput")


def fig5() -> None:
    error = rows("dp_error_summary.csv")
    eps = [float(row["epsilon_requested"]) for row in error]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    means = np.array([float(row["mean_relative_error"]) * 100 for row in error])
    stds = np.array([float(row["std_relative_error"]) * 100 for row in error])
    ax.errorbar(eps, means, yerr=stds, fmt="o-", capsize=7, color=COLORS[0])
    ax.set_xscale("log", base=2)
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Relative error (%)")
    save(fig, "fig5a_dp_relative_error")

    composition = rows("dp_composition.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    for index, epsilon in enumerate((0.05, 0.1, 0.5, 1.0)):
        subset = [row for row in composition if float(row["epsilon_requested"]) == epsilon]
        ax.step(
            [int(row["releases"]) for row in subset],
            [float(row["conservative_fixed_epsilon"]) for row in subset],
            where="post",
            label=rf"$\epsilon={epsilon:g}$",
            color=COLORS[index],
        )
    ax.set_xlabel("Repeated releases")
    ax.set_ylabel(r"Cumulative conservative $\epsilon$")
    ax.legend(frameon=False, ncol=2)
    save(fig, "fig5b_cumulative_privacy_loss")

    rounding = rows("dp_rounding_margin.csv")
    margins = np.sort(np.array([float(row["rounding_margin_micro_epsilon"]) for row in rounding]))
    ecdf = np.arange(1, len(margins) + 1) / len(margins)
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.step(margins, ecdf, where="post", color=COLORS[3])
    ax.set_xlabel(r"Conservative rounding margin ($10^{-6}$ epsilon)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1.02)
    save(fig, "fig5c_rounding_gap")

    trajectory = rows("budget_exhaustion_trajectory.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax2 = ax.twinx()
    selected = (0.05, 0.2, 0.5, 1.0)
    lines: list[Any] = []
    for index, epsilon in enumerate(selected):
        subset = [row for row in trajectory if float(row["epsilon_requested"]) == epsilon]
        request_index = [int(row["request_index"]) for row in subset]
        remaining = [float(row["budget_remaining_fixed"]) / 1_000_000 for row in subset]
        accepted = [int(row["cumulative_accepted_requests"]) for row in subset]
        line = ax.step(
            request_index,
            remaining,
            where="post",
            color=COLORS[index],
            label=rf"Remaining, $\epsilon={epsilon:g}$",
        )[0]
        lines.append(line)
        ax2.step(
            request_index,
            accepted,
            where="post",
            color=COLORS[index],
            linestyle="--",
            alpha=0.72,
        )
    ax.set_xlabel("Request index")
    ax.set_ylabel(r"Remaining budget ($\epsilon$)")
    ax2.set_ylabel("Cumulative accepted requests (dashed)")
    ax.legend(handles=lines, frameon=False, ncol=2, loc="upper center")
    save(fig, "fig5d_budget_exhaustion")


def fig6() -> None:
    performance = rows("vbs_performance_summary.csv")
    payload = [int(row["payload_bytes"]) for row in performance]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    empirical_band(
        ax,
        payload,
        [float(row["native_p50_latency_ms"]) for row in performance],
        [float(row["native_p2_5_latency_ms"]) for row in performance],
        [float(row["native_p97_5_latency_ms"]) for row in performance],
        label="Native",
        color=COLORS[1],
        marker="o",
    )
    empirical_band(
        ax,
        payload,
        [float(row["vbs_p50_latency_ms"]) for row in performance],
        [float(row["vbs_p2_5_latency_ms"]) for row in performance],
        [float(row["vbs_p97_5_latency_ms"]) for row in performance],
        label="VBS Enclave",
        color=COLORS[0],
        marker="s",
    )
    set_payload_ticks(ax, payload)
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Process latency (ms)")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    save(fig, "fig6a_native_vs_vbs_latency")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    empirical_band(
        ax,
        payload,
        [float(row["slowdown_p50"]) for row in performance],
        [float(row["slowdown_p2_5"]) for row in performance],
        [float(row["slowdown_p97_5"]) for row in performance],
        label="VBS Enclave / Native",
        color=COLORS[4],
        marker="o",
    )
    ax.axhline(1, color="#555555", linewidth=1.4, linestyle="--")
    set_payload_ticks(ax, payload)
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Slowdown relative to Native (×)")
    ax.legend(frameon=False)
    save(fig, "fig6b_vbs_slowdown")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    empirical_band(
        ax,
        payload,
        [float(row["native_throughput_p50_mib_s"]) for row in performance],
        [float(row["native_throughput_p2_5_mib_s"]) for row in performance],
        [float(row["native_throughput_p97_5_mib_s"]) for row in performance],
        label="Native",
        color=COLORS[1],
        marker="o",
    )
    empirical_band(
        ax,
        payload,
        [float(row["vbs_throughput_p50_mib_s"]) for row in performance],
        [float(row["vbs_throughput_p2_5_mib_s"]) for row in performance],
        [float(row["vbs_throughput_p97_5_mib_s"]) for row in performance],
        label="VBS Enclave",
        color=COLORS[0],
        marker="s",
    )
    set_payload_ticks(ax, payload)
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Payload throughput (MiB/s)")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    save(fig, "fig6c_payload_throughput")

    stage_rows = rows("vbs_stage_breakdown.csv")
    stage_names = ["decrypt", "aggregate", "dp_noise", "transcript", "attestation_generation"]
    x = np.arange(len(payload))
    fig, ax = plt.subplots(figsize=FIGSIZE)
    bottom = np.zeros(len(payload))
    for index, stage in enumerate(stage_names):
        values = np.array(
            [
                float(
                    next(
                        row["mean_latency_us"]
                        for row in stage_rows
                        if int(row["payload_bytes"]) == size and row["stage"] == stage
                    )
                )
                / 1000
                for size in payload
            ]
        )
        label = {
            "dp_noise": "DP noise",
            "attestation_generation": "Evidence generation",
        }.get(stage, stage.title())
        ax.bar(x, values, bottom=bottom, label=label, color=COLORS[index])
        bottom += values
    ax.set_xticks(x, [short_payload(value) for value in payload], rotation=18, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Enclave stage latency (ms)")
    ax.text(
        0.99,
        0.94,
        "DP noise = 0 (disabled in paired baseline)",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=COLORS[2],
        fontsize=14,
    )
    ax.legend(frameon=False, ncol=3)
    save(fig, "fig6d_enclave_stage_breakdown")

    fig, ax = plt.subplots(figsize=FIGSIZE)
    offsets = (-0.16, 0.16)
    for offset, prefix, label, color, marker in (
        (offsets[0], "native", "Native", COLORS[1], "o"),
        (offsets[1], "vbs", "VBS Enclave", COLORS[0], "s"),
    ):
        centers = np.arange(len(payload)) + offset
        medians = np.array([float(row[f"{prefix}_rss_p50_mib"]) for row in performance])
        lower = np.array([float(row[f"{prefix}_rss_p2_5_mib"]) for row in performance])
        upper = np.array([float(row[f"{prefix}_rss_p97_5_mib"]) for row in performance])
        ax.errorbar(
            centers,
            medians,
            yerr=np.vstack((medians - lower, upper - medians)),
            fmt=marker,
            capsize=7,
            label=label,
            color=color,
        )
    ax.set_xticks(np.arange(len(payload)), [short_payload(value) for value in payload], rotation=18, ha="right")
    ax.set_xlabel("Plaintext payload")
    ax.set_ylabel("Peak resident memory (MiB)")
    ax.legend(frameon=False)
    save(fig, "fig6e_memory_footprint")

    overhead = rows("vbs_attestation_overhead.csv")
    largest_payload = max(int(row["payload_bytes"]) for row in overhead)
    subset = [row for row in overhead if int(row["payload_bytes"]) == largest_payload]
    stage_names = ["Transcript", "Evidence generation", "External validation"]
    distributions = [
        [float(row["latency_us"]) / 1000 for row in subset if row["stage"] == stage]
        for stage in stage_names
    ]
    percentages = [
        np.mean(
            [
                float(row["percent_of_total_vbs_latency"])
                for row in subset
                if row["stage"] == stage
            ]
        )
        for stage in stage_names
    ]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    box = ax.boxplot(distributions, tick_labels=stage_names, patch_artist=True, showfliers=True)
    for patch, color in zip(box["boxes"], COLORS):
        patch.set_facecolor(color)
        patch.set_alpha(0.72)
    ymax = max(max(values) for values in distributions)
    for index, percentage in enumerate(percentages, start=1):
        formatted = f"{percentage:.2f}" if percentage < 0.1 else f"{percentage:.1f}"
        ax.text(index, ymax * 1.05, f"{formatted}% of total", ha="center", va="bottom")
    ax.set_ylim(top=ymax * 1.18)
    ax.set_ylabel("Latency (ms)")
    ax.set_xlabel(f"{short_payload(largest_payload)} payload; {len(distributions[0])} measured repetitions")
    save(fig, "fig6f_transcript_attestation_overhead")


def fig7() -> None:
    binding = rows("attack_binding_matrix.csv")
    desired_cases = [
        "aad_context_tampering",
        "request_id_substitution",
        "asset_id_substitution",
        "consumer_id_substitution",
        "policy_hash_substitution",
        "policy_version_substitution",
        "function_id_substitution",
        "result_hash_substitution",
        "transcript_substitution",
        "public_asset_mismatch",
        "public_consumer_mismatch",
        "public_policy_mismatch",
        "public_result_mismatch",
        "caller_substitution",
        "request_key_substitution",
    ]
    row_by_case = {row["attack_case"]: row for row in binding}
    selected = [row_by_case[case] for case in desired_cases]
    layer_fields = ["enclave", "attestation_validator", "circuit_adapter", "solidity_settlement"]
    layer_labels = ["Enclave", "Attestation validator", "Circuit adapter", "Solidity settlement"]
    case_labels = [
        "AAD context",
        "Request ID",
        "Asset ID",
        "Consumer ID",
        "Policy hash",
        "Policy version",
        "Function ID",
        "Result hash",
        "Transcript",
        "Circuit asset",
        "Circuit consumer",
        "Circuit policy",
        "Circuit result",
        "Caller address",
        "Request key",
    ]
    matrix = np.array([[int(row[field]) for field in layer_fields] for row in selected])
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.imshow(
        matrix,
        cmap=ListedColormap(["#f2f2f2", COLORS[4]]),
        vmin=0,
        vmax=1,
        interpolation="nearest",
        aspect="auto",
    )
    ax.set_xticks(np.arange(len(layer_labels)), layer_labels)
    ax.set_yticks(np.arange(len(case_labels)), case_labels)
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            if matrix[row_index, column_index] == 1:
                ax.text(column_index, row_index, "FIRST", ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    ax.set_xlabel("First rejecting layer confirmed by a passing test")
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
    save(fig, "fig7a_context_substitution")

    attacks = rows("protocol_attack_latency.csv")
    attack_cases = [
        "altered_transcript",
        "altered_attestation",
        "stale_attestation",
        "tampered_proof",
        "nullifier_replay",
    ]
    attack_labels = ["Transcript", "Evidence substitution", "Stale evidence", "Proof", "Replay"]
    distributions = [
        [float(row["latency_ms"]) for row in attacks if row["attack_case"] == attack_case]
        for attack_case in attack_cases
    ]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    box = ax.boxplot(distributions, tick_labels=attack_labels, patch_artist=True, showfliers=True)
    for patch, color in zip(box["boxes"], COLORS):
        patch.set_facecolor(color)
        patch.set_alpha(0.72)
    ax.scatter(
        np.arange(1, len(distributions) + 1),
        [np.mean(values) for values in distributions],
        marker="D",
        color="#202020",
        label="Mean",
        zorder=3,
    )
    ax.set_ylabel("Rejection latency (ms)")
    ax.legend(frameon=False)
    save(fig, "fig7b_tampering_replay")

    concurrency = rows("settlement_concurrency_summary.csv")
    levels = [int(row["concurrency"]) for row in concurrency]
    x = np.arange(len(levels))
    accepted = np.array([float(row["mean_accepted"]) for row in concurrency])
    reverted = np.array([float(row["mean_reverted"]) for row in concurrency])
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(x, accepted, label="Accepted", color=COLORS[2])
    ax.bar(x, reverted, bottom=accepted, label="Reverted", color=COLORS[4])
    ax.set_xticks(x, levels)
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Mean request count per trial")
    ax.legend(frameon=False)
    save(fig, "fig7c_concurrency_outcomes")

    trials = rows("settlement_concurrency_trials.csv")
    latency_distributions = [
        [float(row["settlement_mean_latency_ms"]) for row in trials if int(row["concurrency"]) == level]
        for level in levels
    ]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    box = ax.boxplot(latency_distributions, tick_labels=levels, patch_artist=True, showfliers=True)
    for patch in box["boxes"]:
        patch.set_facecolor(COLORS[0])
        patch.set_alpha(0.7)
    ax.scatter(
        np.arange(1, len(levels) + 1),
        [np.mean(values) for values in latency_distributions],
        marker="D",
        color=COLORS[1],
        label="Mean",
        zorder=3,
    )
    ax.set_xlabel("Concurrent requests")
    ax.set_ylabel("Mean settlement latency per accepted request (ms)")
    ax.legend(frameon=False)
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
        raise RuntimeError(
            f"expected 22 PDF and PNG panels, found {len(pdfs)} and {len(pngs)}"
        )
    print(
        f"generated {len(pdfs)} PDF and {len(pngs)} PNG panels "
        f"at {FIGSIZE[0]}x{FIGSIZE[1]} inches and {PNG_DPI} dpi in {PANELS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
