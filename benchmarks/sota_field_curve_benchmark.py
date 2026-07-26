#!/usr/bin/env python3
"""Field-scale curve comparison for TrustCircuit and Related Work profiles.

External profiles are minimal feature-contract emulations.  The experiment
expands the common request/evidence/state interface into 48 protocol fields and
measures structural enforcement work under field-order and compound-mutation
workloads.  It is not a source-system performance reproduction.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "results" / "raw" / "phase8" / "sota_profiles"
PROCESSED_DIR = ROOT / "results" / "processed" / "sota_profiles"
FIGURE_DIR = ROOT / "Paper" / "figures" / "sota_profiles"

SEED = 20260723
ORDER_TRIALS = 600
MUTATION_BATCH_TRIALS = 100
REQUESTS_PER_BATCH = 1_000
MUTATION_ATTEMPTS = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128)

FIELD_GROUPS = {
    "identity_provenance": (
        "request_id", "asset_id", "consumer_id", "producer_id", "data_version", "request_timestamp",
    ),
    "policy_authorization": (
        "policy_hash", "policy_version", "consent_id", "access_scope", "deadline", "function_id",
    ),
    "input_integrity": (
        "data_hash", "ciphertext_hash", "nonce", "authentication_tag", "aad_hash", "input_signature",
    ),
    "execution_evidence": (
        "runtime_id", "enclave_measurement", "attestation_nonce", "attestation_time", "transcript_hash", "execution_key_id",
    ),
    "privacy_accounting": (
        "epsilon", "delta", "sensitivity", "clipping_bound", "mechanism_id", "actual_privacy_cost",
    ),
    "proof_context": (
        "public_input_hash", "proof_context", "verifier_id", "circuit_version", "proof_digest", "relation_tag",
    ),
    "state_settlement": (
        "request_status", "budget_before", "budget_after", "nullifier", "replay_key", "settlement_id",
    ),
    "audit_receipt": (
        "result_hash", "audit_digest", "receipt_id", "block_height", "settlement_time", "evidence_chain_hash",
    ),
}

FIELDS = tuple(field for group in FIELD_GROUPS.values() for field in group)
assert len(FIELDS) == 48 and len(set(FIELDS)) == 48

LAYERS = {
    "authorization": "authorization or policy validation",
    "commitment": "canonical transcript or commitment binding",
    "execution": "isolated-execution evidence",
    "proof": "proof-relation enforcement",
    "state": "stateful transition or replay enforcement",
}


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    year: int
    category: str
    source: str
    source_url: str
    protections: dict[str, frozenset[str]]
    emulated_slice: str
    omissions: str

    def depth(self, field: str) -> int:
        return len(self.protections.get(field, frozenset()))


def expand_tiers(spec: dict[str, tuple[tuple[int, str], ...]]) -> dict[str, frozenset[str]]:
    protections: dict[str, frozenset[str]] = {}
    for group, tiers in spec.items():
        fields = FIELD_GROUPS[group]
        cursor = 0
        for count, encoded in tiers:
            if cursor + count > len(fields):
                raise ValueError(f"too many fields assigned in {group}")
            layer_set = frozenset(encoded.split())
            unknown = layer_set.difference(LAYERS)
            if unknown:
                raise ValueError(f"unknown layers: {unknown}")
            for field in fields[cursor : cursor + count]:
                protections[field] = layer_set
            cursor += count
    return protections


PROFILES = (
    Profile(
        "promark", "ProMark", 2024, "Related Work emulation",
        "Hoang et al., IEEE TDSC", "https://doi.org/10.1109/TDSC.2024.3478049",
        expand_tiers({
            "identity_provenance": ((3, "authorization commitment proof state"), (2, "commitment state")),
            "policy_authorization": ((4, "authorization commitment state"), (2, "commitment proof")),
            "input_integrity": ((3, "commitment proof"),),
            "proof_context": ((4, "commitment proof"), (2, "proof")),
            "state_settlement": ((4, "commitment state"), (1, "state")),
            "audit_receipt": ((5, "commitment state"), (1, "state")),
        }),
        "campaign policy, participant binding, PoC relation, replay token, ledger audit",
        "Fabric deployment, Pedersen/ECIES/MPC workflow, original PoC implementation",
    ),
    Profile(
        "veracruz", "Veracruz", 2023, "Related Work emulation",
        "Brossard et al., IEEE TCC", "https://arxiv.org/abs/2205.03322",
        expand_tiers({
            "identity_provenance": ((4, "authorization commitment execution"), (2, "commitment execution")),
            "policy_authorization": ((5, "authorization commitment execution"), (1, "commitment")),
            "input_integrity": ((6, "commitment execution"),),
            "execution_evidence": ((6, "commitment execution"),),
            "audit_receipt": ((2, "commitment execution"),),
        }),
        "global policy, principals, transcript integrity, isolated-runtime attestation",
        "Nitro/CCA/seL4 runtimes, TLS provisioning, proxy attestation service",
    ),
    Profile(
        "vldp", "VLDP", 2025, "Related Work emulation",
        "Bontekoe et al., PoPETs", "https://petsymposium.org/popets/2025/popets-2025-0076.php",
        expand_tiers({
            "identity_provenance": ((2, "authorization commitment proof"),),
            "policy_authorization": ((1, "proof"),),
            "input_integrity": ((5, "authorization commitment proof"), (1, "commitment proof")),
            "privacy_accounting": ((6, "commitment proof"),),
            "proof_context": ((5, "commitment proof"),),
            "audit_receipt": ((1, "commitment proof"),),
        }),
        "authenticated LDP input, mechanism parameters, randomized output relation",
        "Groth16 circuit, shuffle deployment, original cryptographic implementation",
    ),
    Profile(
        "verifbfl", "VerifBFL", 2025, "Related Work emulation",
        "Bellachia et al.", "https://arxiv.org/abs/2501.04319",
        expand_tiers({
            "identity_provenance": ((5, "authorization commitment proof state"), (1, "commitment state")),
            "policy_authorization": ((2, "authorization commitment"),),
            "input_integrity": ((6, "commitment proof"),),
            "privacy_accounting": ((3, "commitment proof"),),
            "proof_context": ((6, "commitment proof"),),
            "state_settlement": ((5, "proof state"),),
            "audit_receipt": ((6, "commitment state"),),
        }),
        "training-task identity, model-update proof, round state, blockchain audit",
        "federated training, Nova/IVC execution, Chainlink, IPFS and PBFT network",
    ),
    Profile(
        "vprivkv", "VPrivKV", 2026, "Related Work emulation",
        "Zhou et al., IEEE TIFS", "https://doi.org/10.1109/TIFS.2025.3639964",
        expand_tiers({
            "identity_provenance": ((3, "authorization commitment proof"), (1, "commitment")),
            "policy_authorization": ((2, "authorization commitment"),),
            "input_integrity": ((6, "authorization commitment proof"),),
            "privacy_accounting": ((6, "commitment proof"),),
            "proof_context": ((5, "commitment proof"),),
            "state_settlement": ((2, "proof state"),),
            "audit_receipt": ((2, "commitment proof"),),
        }),
        "joint key sampling, interactive perturbation verification, enhanced ZK relation",
        "coin-flipping transport, full PrivKV analytics and original ZK implementation",
    ),
    Profile(
        "tc_lite", "TC-Lite", 2026, "TrustCircuit profile",
        "TrustCircuit deployment profile", "local:Paper/main-new.tex",
        expand_tiers({
            "identity_provenance": ((6, "authorization commitment state"),),
            "policy_authorization": ((6, "authorization commitment state"),),
            "input_integrity": ((6, "commitment"),),
            "state_settlement": ((5, "commitment state"), (1, "state")),
            "audit_receipt": ((6, "commitment state"),),
        }),
        "encrypted authorization, canonical request fields, request state and audit",
        "confidential execution, DP accounting and VCP proof",
    ),
    Profile(
        "tc_protected", "TC-Protected", 2026, "TrustCircuit profile",
        "TrustCircuit deployment profile", "local:Paper/main-new.tex",
        expand_tiers({
            "identity_provenance": ((6, "authorization commitment execution state"),),
            "policy_authorization": ((6, "authorization commitment execution state"),),
            "input_integrity": ((6, "commitment execution"),),
            "execution_evidence": ((6, "commitment execution"),),
            "privacy_accounting": ((6, "commitment execution state"),),
            "state_settlement": ((6, "commitment state"),),
            "audit_receipt": ((6, "commitment execution state"),),
        }),
        "TC-Lite plus attested computation, conservative privacy cost and budget state",
        "VCP proof and proof-bound nullifier",
    ),
    Profile(
        "tc_full", "TC-Full", 2026, "TrustCircuit profile",
        "TrustCircuit deployment profile", "local:Paper/main-new.tex",
        expand_tiers({
            "identity_provenance": ((6, "authorization commitment execution proof state"),),
            "policy_authorization": ((6, "authorization commitment execution proof state"),),
            "input_integrity": ((6, "commitment execution proof"),),
            "execution_evidence": ((6, "commitment execution proof state"),),
            "privacy_accounting": ((6, "commitment execution proof state"),),
            "proof_context": ((6, "commitment proof state"),),
            "state_settlement": ((6, "commitment proof state"),),
            "audit_receipt": ((6, "commitment proof state"),),
        }),
        "request, attestation and proof binding with cumulative budget and atomic settlement",
        "this emulator does not execute the real VBS, Groth16 or Solidity stack",
    ),
)


COLORS = {
    "ProMark": "#7f7f7f", "Veracruz": "#8c564b", "VLDP": "#9467bd",
    "VerifBFL": "#17becf", "VPrivKV": "#2ca02c", "TC-Lite": "#6baed6",
    "TC-Protected": "#1f77b4", "TC-Full": "#d62728",
}
LINESTYLES = {
    "ProMark": (0, (1, 1)), "Veracruz": (0, (5, 2)), "VLDP": (0, (3, 2, 1, 2)),
    "VerifBFL": (0, (5, 1, 1, 1)), "VPrivKV": (0, (7, 2)),
    "TC-Lite": (0, (2, 2)), "TC-Protected": (0, (6, 2)), "TC-Full": "-",
}
MARKERS = {
    "ProMark": "o", "Veracruz": "s", "VLDP": "^", "VerifBFL": "D",
    "VPrivKV": "v", "TC-Lite": "P", "TC-Protected": "X", "TC-Full": "*",
}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def field_order_trials() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile_index, profile in enumerate(PROFILES):
        rng = random.Random(SEED + profile_index * 997)
        for trial in range(ORDER_TRIALS):
            ordered: list[str] = []
            for fields in FIELD_GROUPS.values():
                shuffled = list(fields)
                rng.shuffle(shuffled)
                ordered.extend(shuffled)
            cumulative = 0
            for field_count, field in enumerate(ordered, start=1):
                cumulative += profile.depth(field)
                rows.append({
                    "measurement_type": "seeded_field_order_emulation",
                    "profile": profile.label,
                    "profile_key": profile.key,
                    "trial": trial,
                    "validated_fields_per_request": field_count,
                    "cumulative_checks_per_request": cumulative,
                    "seed": SEED + profile_index * 997,
                })
    return rows


def summarize_field_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for profile in PROFILES:
        for field_count in range(1, len(FIELDS) + 1):
            values = [row["cumulative_checks_per_request"] for row in rows if row["profile_key"] == profile.key and row["validated_fields_per_request"] == field_count]
            output.append({
                "measurement_type": "seeded_field_order_emulation",
                "profile": profile.label,
                "profile_key": profile.key,
                "validated_fields_per_request": field_count,
                "median_checks_per_request": round(statistics.median(values), 3),
                "p10_checks_per_request": round(percentile(values, 10), 3),
                "p90_checks_per_request": round(percentile(values, 90), 3),
                "trials": len(values),
            })
    return output


def mutation_batch_trials() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    request_rows = np.arange(REQUESTS_PER_BATCH, dtype=np.int32)[:, None]
    for profile_index, profile in enumerate(PROFILES):
        depths = np.array([profile.depth(field) for field in FIELDS], dtype=np.int32)
        rng = np.random.default_rng(SEED + profile_index * 1013)
        for attempt_count in MUTATION_ATTEMPTS:
            for trial in range(MUTATION_BATCH_TRIALS):
                selected = rng.integers(0, len(FIELDS), size=(REQUESTS_PER_BATCH, attempt_count))
                seen = np.zeros((REQUESTS_PER_BATCH, len(FIELDS)), dtype=bool)
                seen[request_rows, selected] = True
                unique_field_layer_controls = int((seen * depths).sum())
                unique_mutated_fields = int(seen.sum())
                rows.append({
                    "measurement_type": "seeded_compound_field_emulation",
                    "profile": profile.label,
                    "profile_key": profile.key,
                    "mutation_attempts_per_request": attempt_count,
                    "trial": trial,
                    "batch_requests": REQUESTS_PER_BATCH,
                    "unique_activated_field_layer_controls": unique_field_layer_controls,
                    "unique_mutated_fields": unique_mutated_fields,
                    "seed": SEED + profile_index * 1013,
                })
    return rows


def summarize_mutation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for profile in PROFILES:
        for count in MUTATION_ATTEMPTS:
            values = [row["unique_activated_field_layer_controls"] for row in rows if row["profile_key"] == profile.key and row["mutation_attempts_per_request"] == count]
            output.append({
                "measurement_type": "seeded_compound_field_emulation",
                "profile": profile.label,
                "profile_key": profile.key,
                "mutation_attempts_per_request": count,
                "median_unique_control_events_per_1000_requests": round(statistics.median(values), 3),
                "p10_unique_control_events_per_1000_requests": round(percentile(values, 10), 3),
                "p90_unique_control_events_per_1000_requests": round(percentile(values, 90), 3),
                "batch_trials": len(values),
                "requests_per_batch": REQUESTS_PER_BATCH,
            })
    return output


def profile_summary(order_summary: list[dict[str, Any]], mutation_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for profile in PROFILES:
        depths = [profile.depth(field) for field in FIELDS]
        order_final = next(row for row in order_summary if row["profile_key"] == profile.key and row["validated_fields_per_request"] == 48)
        mutation_mid = next(row for row in mutation_summary if row["profile_key"] == profile.key and row["mutation_attempts_per_request"] == 64)
        output.append({
            "profile": profile.label,
            "year": profile.year,
            "category": profile.category,
            "bound_fields": sum(depth > 0 for depth in depths),
            "total_enforcement_checks_per_request": int(order_final["median_checks_per_request"]),
            "median_layers_per_bound_field": round(statistics.median([depth for depth in depths if depth > 0]), 3),
            "unique_control_events_per_1000_requests_at_64_attempts": mutation_mid["median_unique_control_events_per_1000_requests"],
        })
    return output


def monotone_curve(x: np.ndarray, y: np.ndarray, samples: int = 600) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    h = np.diff(x)
    delta = np.diff(y) / h
    slopes = np.zeros_like(y)
    for index in range(1, len(y) - 1):
        if delta[index - 1] * delta[index] > 0:
            wa = 2 * h[index] + h[index - 1]
            wb = h[index] + 2 * h[index - 1]
            slopes[index] = (wa + wb) / (wa / delta[index - 1] + wb / delta[index])
    slopes[0] = delta[0]
    slopes[-1] = delta[-1]
    dense_x = np.linspace(x[0], x[-1], samples)
    dense_y = np.empty_like(dense_x)
    for position, value in enumerate(dense_x):
        segment = min(max(np.searchsorted(x, value, side="right") - 1, 0), len(x) - 2)
        t = (value - x[segment]) / h[segment]
        dense_y[position] = (
            (2*t**3 - 3*t**2 + 1) * y[segment]
            + (t**3 - 2*t**2 + t) * h[segment] * slopes[segment]
            + (-2*t**3 + 3*t**2) * y[segment + 1]
            + (t**3 - t**2) * h[segment] * slopes[segment + 1]
        )
    return dense_x, dense_y


def legend_label(profile: Profile) -> str:
    short = {"tc_lite": "TC-L", "tc_protected": "TC-P", "tc_full": "TC-F"}
    if profile.key in short:
        return short[profile.key]
    return profile.label


def setup_axes(ax: plt.Axes, xlabel: str, ylabel: str) -> None:
    ax.set_xlabel(xlabel, fontsize=22)
    ax.set_ylabel(ylabel, fontsize=22, rotation=90, labelpad=8)
    ax.tick_params(axis="both", labelsize=20)
    ax.grid(True, alpha=0.20, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def draw_profile_curve(ax: plt.Axes, profile: Profile, x: np.ndarray, median: np.ndarray, low: np.ndarray, high: np.ndarray) -> None:
    sx, sy = monotone_curve(x, median)
    _, slow = monotone_curve(x, low)
    _, shigh = monotone_curve(x, high)
    width = 3.5 if profile.key == "tc_full" else (2.8 if profile.category == "TrustCircuit profile" else 2.2)
    ax.fill_between(sx, slow, shigh, color=COLORS[profile.label], alpha=0.08)
    ax.plot(sx, sy, color=COLORS[profile.label], linestyle=LINESTYLES[profile.label], linewidth=width, label=legend_label(profile))
    marker_indices = np.linspace(0, len(x) - 1, 9, dtype=int)
    ax.plot(x[marker_indices], median[marker_indices], linestyle="none", marker=MARKERS[profile.label], markersize=7 if profile.key != "tc_full" else 10, color=COLORS[profile.label], markeredgecolor="white", markeredgewidth=0.6)


def plot_field_work(order_summary: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.subplots_adjust(left=0.18, right=0.97, bottom=0.15, top=0.96)
    for profile in PROFILES:
        rows = [row for row in order_summary if row["profile_key"] == profile.key]
        x = np.array([row["validated_fields_per_request"] for row in rows], dtype=float)
        median = np.array([row["median_checks_per_request"] for row in rows], dtype=float)
        low = np.array([row["p10_checks_per_request"] for row in rows], dtype=float)
        high = np.array([row["p90_checks_per_request"] for row in rows], dtype=float)
        draw_profile_curve(ax, profile, x, median, low, high)
    ax.set_xlim(0, 48)
    ax.set_ylim(0, 190)
    ax.set_xticks(range(0, 49, 6))
    ax.set_yticks(range(0, 181, 20))
    setup_axes(ax, "Validated fields · fields/request", "Enforcement workload\nchecks per request")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(0.02, 0.98),
        ncol=2,
        fontsize=20,
        frameon=True,
        framealpha=0.88,
        columnspacing=0.9,
        handletextpad=0.45,
        borderpad=0.45,
        labelspacing=0.35,
    )
    fig.savefig(path, format="pdf")
    plt.close(fig)


def plot_mutation_work(mutation_summary: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.subplots_adjust(left=0.19, right=0.97, bottom=0.15, top=0.96)
    for profile in PROFILES:
        rows = [row for row in mutation_summary if row["profile_key"] == profile.key]
        x = np.array([row["mutation_attempts_per_request"] for row in rows], dtype=float)
        median = np.array([row["median_unique_control_events_per_1000_requests"] for row in rows], dtype=float)
        low = np.array([row["p10_unique_control_events_per_1000_requests"] for row in rows], dtype=float)
        high = np.array([row["p90_unique_control_events_per_1000_requests"] for row in rows], dtype=float)
        draw_profile_curve(ax, profile, x, median, low, high)
    ax.set_xlim(0, 128)
    ax.set_ylim(0, 190_000)
    ax.set_xticks((0, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128))
    ax.set_yticks(range(0, 180_001, 20_000))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{int(value):,}"))
    setup_axes(ax, "Mutation attempts · attempts/request", "Unique control activations\nevents per 1,000 requests")
    ax.legend(
        loc="lower right",
        bbox_to_anchor=(0.98, 0.01),
        ncol=4,
        fontsize=20,
        frameon=True,
        framealpha=0.88,
        columnspacing=0.75,
        handletextpad=0.4,
        borderpad=0.4,
        labelspacing=0.3,
    )
    fig.savefig(path, format="pdf")
    plt.close(fig)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return "\n".join(lines)


def write_markdown(path: Path, summaries: list[dict[str, Any]]) -> None:
    source_rows = []
    for profile in PROFILES:
        source = f"[{profile.source}]({profile.source_url})" if profile.source_url.startswith("http") else profile.source
        source_rows.append([profile.label, profile.year, source, profile.emulated_slice, profile.omissions])
    text = [
        "# Field-scale SOTA curve tables", "",
        "The five external systems are minimal emulations of features described in the paper's Related Work table. Values measure this common 48-field contract, not the source implementations' runtime or security.", "",
        "## Units", "",
        "- `fields/request`: distinct protocol fields evaluated or mutated in one request.",
        "- `checks/request`: field-layer enforcement checks accumulated in one request.",
        "- `events/1,000 requests`: unique field-layer controls activated across a batch of 1,000 requests with repeated mutation attempts; repeated hits to the same field are deduplicated per request.",
        "- Ribbons in both figures show the 10th-90th percentile across seeded field orders or mutation batches.", "",
        "## Summary", "",
        markdown_table(
            ["Profile", "Year", "Bound fields", "Checks/request", "Median layers/bound field", "Unique control events/1,000 requests at 64 attempts"],
            [[row["profile"], row["year"], row["bound_fields"], row["total_enforcement_checks_per_request"], f'{row["median_layers_per_bound_field"]:.1f}', f'{row["unique_control_events_per_1000_requests_at_64_attempts"]:,.0f}'] for row in summaries],
        ), "", "## Reconstruction boundary", "",
        markdown_table(["Profile", "Year", "Source", "Emulated slice", "Explicit omissions"], source_rows), "",
        "Interpretation boundary: a larger value means that the common emulator invokes more independent enforcement layers over the selected fields. It is not a normalized security score and must not be presented as source-system throughput, proof cost, or cryptographic strength.", "",
    ]
    path.write_text("\n".join(text), encoding="utf-8")


def deployment_profile_measurements() -> dict[str, dict[str, float]]:
    path = ROOT / "results" / "deployment_profiles" / "summary" / "deployment_profile_summary.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            {key.strip(): value for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    return {
        row["profile"]: {
            "mean_latency_ms": float(row["mean_total_latency_ms"]),
            "mean_throughput_req_s": float(row["mean_throughput_req_s"]),
            "mean_total_gas": float(row["mean_total_gas"]),
        }
        for row in rows
    }


def write_paper_notes(path: Path, summaries: list[dict[str, Any]], mutation_summary: list[dict[str, Any]]) -> None:
    structural = {row["profile"]: row for row in summaries}
    endpoint = {
        row["profile"]: row["median_unique_control_events_per_1000_requests"]
        for row in mutation_summary
        if row["mutation_attempts_per_request"] == 128
    }
    deployment = deployment_profile_measurements()
    external_peak_name = max(
        (profile.label for profile in PROFILES if profile.category == "Related Work emulation"),
        key=lambda name: endpoint[name],
    )
    external_peak = endpoint[external_peak_name]
    content = f"""# Paper-ready SOTA comparison notes

## Core interpretation

- **TC-Full provides the broadest integrated lifecycle enforcement.** In the common 48-field contract, TC-Full binds {structural['TC-Full']['bound_fields']} fields using {structural['TC-Full']['total_enforcement_checks_per_request']} field-layer checks per request. At 128 repeated mutation attempts, it activates {endpoint['TC-Full']:,.0f} unique field-layer controls per 1,000 requests, compared with {external_peak:,.0f} for the strongest external profile in this experiment, {external_peak_name}.
- **TC-Protected is the middle assurance point.** Removing the VCP relation and proof-bound nullifier reduces the endpoint to {endpoint['TC-Protected']:,.0f} control activations, but it retains attested execution, privacy-cost accounting, cumulative budget state, and audit binding.
- **TC-Lite is intentionally comparable to narrower ledger or mechanism-specific profiles.** Its endpoint is {endpoint['TC-Lite']:,.0f}, between VPrivKV ({endpoint['VPrivKV']:,.0f}) and ProMark ({endpoint['ProMark']:,.0f}). This is expected because TC-Lite omits confidential execution, privacy accounting, and zero-knowledge compliance.

## Assurance-cost trade-off using measured deployment-profile data

| Profile | Mean latency | Mean throughput | Mean gas | Unique controls at 128 attempts |
| --- | ---: | ---: | ---: | ---: |
| TC-Lite | {deployment['TC-Lite']['mean_latency_ms']:.1f} ms | {deployment['TC-Lite']['mean_throughput_req_s']:.2f} req/s | {deployment['TC-Lite']['mean_total_gas']:,.0f} gas | {endpoint['TC-Lite']:,.0f} |
| TC-Protected | {deployment['TC-Protected']['mean_latency_ms']:.1f} ms | {deployment['TC-Protected']['mean_throughput_req_s']:.2f} req/s | {deployment['TC-Protected']['mean_total_gas']:,.0f} gas | {endpoint['TC-Protected']:,.0f} |
| TC-Full | {deployment['TC-Full']['mean_latency_ms']:.1f} ms | {deployment['TC-Full']['mean_throughput_req_s']:.2f} req/s | {deployment['TC-Full']['mean_total_gas']:,.0f} gas | {endpoint['TC-Full']:,.0f} |

The correct argument is therefore not that TC-Full is faster. TC-Lite is the fastest and cheapest profile, whereas TC-Full trades latency, throughput, and gas for broader cross-stage binding. TC-Protected occupies the practical middle point when confidential computation and cumulative privacy-budget enforcement are required but on-chain VCP verification is not.

## Candidate paragraph for the paper

> Under the common 48-field feature contract, TrustCircuit's deployment profiles expose a clear assurance-cost frontier. TC-Lite activates a number of unique field-layer controls comparable to specialized ledger and verifiable-privacy profiles, while retaining the lowest measured latency and gas envelope. TC-Protected adds attested execution and cumulative privacy-budget state, substantially increasing cross-stage mutation coverage without incurring proof-generation cost. TC-Full provides the broadest integrated binding across request identity, policy, execution evidence, privacy cost, proof context, nullifier state, and audit settlement; this additional assurance is accompanied by higher latency and gas, with the measured overhead concentrated in proof generation. These results support configurable deployment rather than a claim that every application should use the complete stack.

## Claims to avoid

- Do not call the control-activation curves runtime, throughput, or cryptographic-security measurements of the original related systems.
- Do not claim that TrustCircuit subsumes the mechanism-specific proof guarantees of VLDP, VPrivKV, or VerifBFL.
- Do not say TC-Full is faster; say it offers broader integrated enforcement at higher measured cost.
- Always describe the external curves as minimal feature-contract emulations derived from the cited systems' published contributions.
"""
    path.write_text(content, encoding="utf-8")


def clean_stale(raw: Path, processed: Path, figures: Path) -> None:
    for path in list(raw.glob("*.csv")) + list(processed.glob("*.csv")) + list(figures.glob("*.pdf")):
        path.unlink(missing_ok=True)
    for name in ("SOTA_CURVE_TABLES.md", "study_bundle.json"):
        (processed / name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--figure-dir", type=Path, default=FIGURE_DIR)
    args = parser.parse_args()
    raw, processed, figures = args.raw_dir.resolve(), args.processed_dir.resolve(), args.figure_dir.resolve()
    for directory in (raw, processed, figures):
        directory.mkdir(parents=True, exist_ok=True)
    clean_stale(raw, processed, figures)

    metadata = {
        "schema": "trustcircuit-sota-field-curves/v3",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(), "seed": SEED,
        "field_order_trials": ORDER_TRIALS,
        "mutation_batch_trials": MUTATION_BATCH_TRIALS,
        "requests_per_mutation_batch": REQUESTS_PER_BATCH,
        "python": sys.version, "platform": platform.platform(),
        "measurement_boundary": "48-field feature-contract emulation",
        "non_claim": "not source-system performance or cryptographic reproduction",
    }
    config = {
        "metadata": metadata, "field_groups": FIELD_GROUPS, "enforcement_layers": LAYERS,
        "profiles": [{
            "key": p.key, "label": p.label, "year": p.year, "category": p.category,
            "source": p.source, "source_url": p.source_url,
            "protections": {field: sorted(values) for field, values in p.protections.items()},
            "emulated_slice": p.emulated_slice, "omissions": p.omissions,
        } for p in PROFILES],
    }
    write_json(raw / "config.json", config)

    order_trials = field_order_trials()
    order_summary = summarize_field_order(order_trials)
    mutation_trials = mutation_batch_trials()
    mutation_summary = summarize_mutation(mutation_trials)
    summaries = profile_summary(order_summary, mutation_summary)

    write_csv(raw / "field_order_trials.csv", order_trials)
    write_csv(raw / "compound_field_batch_trials.csv", mutation_trials)
    write_csv(processed / "field_work_curve.csv", order_summary)
    write_csv(processed / "compound_field_curve.csv", mutation_summary)
    write_csv(processed / "profile_summary.csv", summaries)
    write_csv(processed / "reconstruction_scope.csv", [{
        "profile": p.label, "year": p.year, "category": p.category, "source": p.source,
        "source_url": p.source_url, "emulated_slice": p.emulated_slice, "explicit_omissions": p.omissions,
    } for p in PROFILES])
    write_json(processed / "study_bundle.json", {
        "metadata": metadata, "profile_summary": summaries,
        "field_work_curve": order_summary, "compound_field_curve": mutation_summary,
    })
    write_markdown(processed / "SOTA_FIELD_CURVE_TABLES.md", summaries)
    write_paper_notes(processed / "PAPER_SOTA_NOTES.md", summaries, mutation_summary)

    plot_field_work(order_summary, figures / "sota_field_curve_1_enforcement_work.pdf")
    plot_mutation_work(mutation_summary, figures / "sota_field_curve_2_mutation_events.pdf")
    print(json.dumps({
        "systems": len(PROFILES), "external_related_work": 5,
        "field_order_rows": len(order_trials), "mutation_batch_rows": len(mutation_trials),
        "represented_mutated_requests": len(mutation_trials) * REQUESTS_PER_BATCH,
        "figures": 2, "figure_dir": str(figures),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
