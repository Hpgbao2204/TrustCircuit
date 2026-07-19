"""Figure 2: smooth ZK scaling trends and dense backend comparisons."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, indexed, processed, summary, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import percentile_ribbon, smooth_line
from .statistics import fit_line, normalized_to_first


def _scaling_sources():
    scaling = processed(
        "zk_scaling.csv",
        ["n_rules", "constraints", "witness_size_bytes", "proof_size_bytes", "proving_key_bytes",
         "peak_private_mb"],
    )
    distribution = processed(
        "zk_scaling_distribution.csv",
        ["n_rules", "prove_median_ms", "prove_p95_ms", "prove_bootstrap_ci95_low_ms",
         "prove_bootstrap_ci95_high_ms", "verify_median_ms", "verify_p95_ms",
         "verify_bootstrap_ci95_low_ms", "verify_bootstrap_ci95_high_ms"],
    )
    trials = processed("zk_scaling_trials.csv", ["n_rules", "normalized_peak_cpu_percent"])
    return scaling, distribution, trials


def panel_a(scaling) -> None:
    rows = sorted(scaling, key=lambda r: int(r["n_rules"]))
    rules = values(rows, "n_rules")
    total = values(rows, "constraints")
    base = np.full_like(total, total[0])
    incremental = total - base
    slope, _, r2 = fit_line(rules, total)

    fig, ax = new_figure(figsize=(8.4, 5.2))
    ax.bar(rules, base, width=0.72, color=COLORS["blue"], label="base circuit")
    ax.bar(rules, incremental, bottom=base, width=0.72, color=COLORS["orange"],
           label="rule-dependent increment")
    smooth_line(ax, rules, total, color=COLORS["dark"], marker="D",
                label=f"total: {slope:.0f} constraints/rule, $R^2$={r2:.4f}")
    for x, y in zip(rules, total):
        ax.annotate(f"{int(y):,}", (x, y), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=ANNOTATION_SIZE)
    ax.set_xticks(rules.astype(int))
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("R1CS constraints")
    ax.set_title("Base and incremental constraint growth")
    ax.legend(loc="upper left")
    finish_axis(ax)
    save_pdf(fig, "fig2a_constraint_growth.pdf")


def _trend_panel(distribution, *, metric: str, filename: str, title: str, ylabel: str) -> None:
    rows = sorted(distribution, key=lambda r: int(r["n_rules"]))
    rules = values(rows, "n_rules")
    median = values(rows, f"{metric}_median_ms")
    p95 = values(rows, f"{metric}_p95_ms")
    low = values(rows, f"{metric}_bootstrap_ci95_low_ms")
    high = values(rows, f"{metric}_bootstrap_ci95_high_ms")
    fig, ax = new_figure(figsize=(8.35, 5.15))
    percentile_ribbon(ax, rules, low, high, color=COLORS["blue"], label="95% CI")
    smooth_line(ax, rules, median, color=COLORS["blue"], label="p50", marker="o")
    smooth_line(ax, rules, p95, color=COLORS["red"], label="p95", marker="D", linestyle="--")
    ax.set_xticks(rules.astype(int))
    ax.set_xlabel("Policy rules")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="upper left")
    finish_axis(ax)
    save_pdf(fig, filename)


def panel_d(scaling, trials) -> None:
    rows = sorted(scaling, key=lambda r: int(r["n_rules"]))
    rules = values(rows, "n_rules")
    trial_groups = groups(trials, "n_rules")
    cpu = np.array([np.median(values(trial_groups[str(int(r))], "normalized_peak_cpu_percent")) for r in rules])
    series = [
        ("Witness", normalized_to_first(values(rows, "witness_size_bytes")), COLORS["blue"], "o"),
        ("Proving key", normalized_to_first(values(rows, "proving_key_bytes")), COLORS["orange"], "s"),
        ("Proof", normalized_to_first(values(rows, "proof_size_bytes")), COLORS["green"], "D"),
        ("Private RAM", normalized_to_first(values(rows, "peak_private_mb")), COLORS["purple"], "^"),
        ("Peak CPU", normalized_to_first(cpu), COLORS["red"], "v"),
    ]
    fig, ax = new_figure(figsize=(8.55, 5.25))
    for label, data, color, marker in series:
        smooth_line(ax, rules, data, color=color, label=label, marker=marker)
    ax.axhline(1, color=COLORS["gray"], linestyle=":", linewidth=1.0)
    ax.set_xticks(rules.astype(int))
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Resource index relative to 1-rule circuit (×)")
    ax.set_title("ZK resource scaling profile")
    ax.legend(loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig2d_resource_scaling.pdf")


def panel_e() -> None:
    dist = processed(
        "zk_backend_distribution.csv",
        ["scheme", "setup_model", "prove_median_ms", "verify_median_ms", "proof_size_bytes",
         "proving_key_bytes"],
    )
    circulation = indexed(processed(
        "zk_backend_circulation.csv", ["scheme", "full_circulation_throughput_req_s"]
    ), "scheme")
    gas = indexed(summary("zk_schemes_gas.csv", ["scheme", "verify_gas"]), "scheme")
    rows = sorted(dist, key=lambda r: r["scheme"])
    schemes = [r["scheme"] for r in rows]
    raw_metrics = np.array([
        values(rows, "prove_median_ms"),
        values(rows, "verify_median_ms"),
        np.array([float(gas[s]["verify_gas"]) for s in schemes]),
        values(rows, "proving_key_bytes"),
        values(rows, "proof_size_bytes"),
        np.array([1 / float(circulation[s]["full_circulation_throughput_req_s"]) for s in schemes]),
    ])
    ratios = raw_metrics / raw_metrics.min(axis=1, keepdims=True)
    metric_labels = ["Prove", "Verify", "Verifier gas", "Proving key", "Proof", "Circulation cost"]
    x = np.arange(len(metric_labels), dtype=float)
    width = 0.23
    fig, ax = new_figure(figsize=(8.7, 5.25))
    for i, row in enumerate(rows):
        label = f"{row['scheme'].upper()} ({row['setup_model']})"
        ax.bar(x + (i - 1) * width, ratios[:, i], width, color=PALETTE[i], label=label)
    ax.axhline(1, color=COLORS["dark"], linestyle=":", linewidth=1.0)
    ax.set_yscale("log")
    ax.set_xticks(x, metric_labels, rotation=12, ha="right")
    ax.set_xlabel("Backend metric")
    ax.set_ylabel("Cost multiple relative to best backend (×, log scale)")
    ax.set_title("ZK backend comparison")
    ax.legend(loc="upper left")
    finish_axis(ax)
    save_pdf(fig, "fig2e_backend_comparison.pdf")


def generate() -> list[str]:
    scaling, distribution, trials = _scaling_sources()
    panel_a(scaling)
    _trend_panel(distribution, metric="prove", filename="fig2b_proving_trend.pdf",
                 title="Groth16 proving-time trend", ylabel="Proving time (ms)")
    _trend_panel(distribution, metric="verify", filename="fig2c_verification_trend.pdf",
                 title="Groth16 verification-time trend", ylabel="Verification time (ms)")
    panel_d(scaling, trials)
    panel_e()
    return [
        "fig2a_constraint_growth.pdf", "fig2b_proving_trend.pdf", "fig2c_verification_trend.pdf",
        "fig2d_resource_scaling.pdf", "fig2e_backend_comparison.pdf",
    ]


if __name__ == "__main__":
    generate()
