"""Figure 2: ZK scaling, distributions, resources, and backend Pareto space."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from .data_loading import groups, indexed, processed, summary, values
from .figure_style import COLORS, PALETTE, finish_axis, human_number, new_figure, save_pdf
from .plot_helpers import distribution_boxes
from .statistics import area_sizes, fit_line


def _scaling_sources():
    scaling = processed(
        "zk_scaling.csv",
        ["n_rules", "constraints", "witness_size_bytes", "proof_size_bytes", "proving_key_bytes",
         "peak_rss_mb", "peak_private_mb"],
    )
    dist = processed(
        "zk_scaling_distribution.csv",
        ["n_rules", "samples", "prove_median_ms", "prove_p95_ms", "verify_median_ms",
         "verify_p95_ms", "prove_bootstrap_ci95_low_ms", "prove_bootstrap_ci95_high_ms"],
    )
    trials = processed(
        "zk_scaling_trials.csv", ["n_rules", "prove_time_ms", "verify_time_ms", "verified"],
    )
    return scaling, dist, trials


def panel_a(scaling) -> None:
    rows = sorted(scaling, key=lambda r: int(r["n_rules"]))
    rules = values(rows, "n_rules")
    constraints = values(rows, "constraints")
    slope, intercept, r2 = fit_line(rules, constraints)
    dense = np.linspace(rules.min(), rules.max(), 160)
    marginal = np.r_[constraints[0], np.diff(constraints) / np.diff(rules)]

    fig, ax = new_figure()
    ax.plot(dense, slope * dense + intercept, color=COLORS["blue"], linestyle="--",
            label=f"linear fit: {slope:.0f} constraints/rule, $R^2$={r2:.4f}")
    ax.scatter(rules, constraints, s=48, color=COLORS["blue"], edgecolor="white",
               linewidth=0.8, zorder=4, label="measured circuits")
    for x, y in zip(rules, constraints):
        ax.annotate(f"{int(y):,}", (x, y), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=7.0)
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("R1CS constraints")
    ax.set_title("Constraint growth and marginal circuit cost")
    ax.set_xticks(rules.astype(int))

    ax2 = ax.twinx()
    ax2.bar(rules, marginal, width=0.65, color=COLORS["orange"], alpha=0.25,
            edgecolor=COLORS["orange"], label="marginal constraints / rule")
    ax2.set_ylabel("Marginal constraints per rule", color=COLORS["orange"])
    ax2.tick_params(axis="y", colors=COLORS["orange"])
    ax2.spines["right"].set_visible(True)
    ax2.set_ylim(0, max(marginal) * 1.7)
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    finish_axis(ax)
    save_pdf(fig, "fig2a_constraint_growth.pdf")


def panel_b(trials, dist) -> None:
    grouped = groups(trials, "n_rules")
    summary_map = indexed(dist, "n_rules")
    keys = sorted(grouped, key=int)
    datasets = [values(grouped[k], "prove_time_ms") for k in keys]
    x = np.arange(len(keys), dtype=float)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(keys))]
    fig, ax = new_figure()
    distribution_boxes(ax, datasets, x, colors, salt=40)
    means = np.array([np.mean(d) for d in datasets])
    ci_lo = np.array([float(summary_map[k]["prove_bootstrap_ci95_low_ms"]) for k in keys])
    ci_hi = np.array([float(summary_map[k]["prove_bootstrap_ci95_high_ms"]) for k in keys])
    ax.errorbar(x, means, yerr=[means - ci_lo, ci_hi - means], fmt="s", color=COLORS["blue"],
                ecolor=COLORS["blue"], capsize=3, ms=3.7, label="mean + 95% bootstrap CI")
    ax.set_xticks(x, [f"{k}\n(n={len(grouped[k])})" for k in keys])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Groth16 proving time (ms)")
    ax.set_title("Proving-time distribution")
    handles, labels = ax.get_legend_handles_labels()
    handles += [
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95"),
    ]
    labels += ["p50", "p95"]
    ax.legend(handles, labels, loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig2b_proving_distribution.pdf")


def panel_c(trials, dist) -> None:
    grouped = groups(trials, "n_rules")
    keys = sorted(grouped, key=int)
    datasets = [values(grouped[k], "verify_time_ms") for k in keys]
    x = np.arange(len(keys), dtype=float)
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(keys))]
    fig, ax = new_figure()
    distribution_boxes(ax, datasets, x, colors, salt=60)
    ax.set_xticks(x, [f"{k}\n(n={len(grouped[k])})" for k in keys])
    ax.set_xlabel("Policy rules")
    ax.set_ylabel("Groth16 verification time (ms)")
    ax.set_title("Verification-time distribution")
    ax.legend(handles=[
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="p95"),
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], alpha=0.5, label="trial"),
    ], loc="upper left", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig2c_verification_distribution.pdf")


def panel_d(scaling) -> None:
    rows = sorted(scaling, key=lambda r: int(r["n_rules"]))
    witness_kib = values(rows, "witness_size_bytes") / 1024
    private_mib = values(rows, "peak_private_mb")
    key_mib = values(rows, "proving_key_bytes") / 1024**2
    proof_bytes = values(rows, "proof_size_bytes")
    rules = values(rows, "n_rules")
    sizes = area_sizes(key_mib, 110, 650)

    fig, ax = new_figure()
    rule_colors = plt.get_cmap("viridis")((rules - rules.min()) / max(np.ptp(rules), 1))
    ax.scatter(witness_kib, private_mib, s=sizes, c=rule_colors,
               edgecolor=COLORS["dark"], linewidth=0.8, alpha=0.82)
    for x, y, r, proof, key in zip(witness_kib, private_mib, rules, proof_bytes, key_mib):
        ax.annotate(f"{int(r)} rules\n{proof:.0f} B proof", (x, y), xytext=(5, 5),
                    textcoords="offset points", fontsize=6.8)
    ax.set_xlabel("Witness size (KiB)")
    ax.set_ylabel("Peak private memory (MiB)")
    ax.set_title("Proof-resource design space")
    ax.text(0.02, 0.98, f"color: policy rules {int(rules.min())}–{int(rules.max())}",
            transform=ax.transAxes, va="top", fontsize=6.8, color=COLORS["gray"])
    ax.text(0.995, 0.02, "Bubble area ∝ proving-key size (1.26–3.12 MiB); CPU counter = 100% for all trials",
            transform=ax.transAxes, ha="right", fontsize=6.6, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig2d_proof_resource_design_space.pdf")


def panel_e() -> None:
    dist = processed(
        "zk_backend_distribution.csv",
        ["scheme", "setup_model", "prove_median_ms", "verify_median_ms", "proof_size_bytes",
         "proving_key_bytes", "peak_working_set_p95_bytes"],
    )
    circulation = indexed(processed(
        "zk_backend_circulation.csv", ["scheme", "full_circulation_throughput_req_s", "measurement_type"]
    ), "scheme")
    gas = indexed(summary("zk_schemes_gas.csv", ["scheme", "verify_gas", "verified"]), "scheme")
    rows = sorted(dist, key=lambda r: float(r["prove_median_ms"]))
    x = values(rows, "prove_median_ms")
    y = np.array([float(circulation[r["scheme"]]["full_circulation_throughput_req_s"]) for r in rows])
    verify_gas = np.array([float(gas[r["scheme"]]["verify_gas"]) for r in rows])
    key_mib = values(rows, "proving_key_bytes") / 1024**2
    sizes = area_sizes(verify_gas, 170, 630)
    markers = {"per-circuit": "o", "universal": "s"}

    fig, ax = new_figure()
    backend_colors = plt.get_cmap("plasma")((key_mib - key_mib.min()) / max(np.ptp(key_mib), 1))
    backend_offsets = {"groth16": (8, 8), "plonk": (-70, 15), "fflonk": (13, -28)}
    for i, row in enumerate(rows):
        ax.scatter(x[i], y[i], s=sizes[i], c=[backend_colors[i]], marker=markers[row["setup_model"]],
                   edgecolor=COLORS["dark"], linewidth=0.9, alpha=0.84)
        ax.annotate(
            f"{row['scheme'].upper()}\n{float(row['verify_median_ms']):.1f} ms verify · {int(float(row['proof_size_bytes']))} B",
            (x[i], y[i]), xytext=backend_offsets[row["scheme"]], textcoords="offset points", fontsize=6.8,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Median proving time (ms, log scale)")
    ax.set_ylabel("Full-circulation throughput (requests/s, log scale)")
    ax.set_title("ZK backend Pareto space")
    ax.text(0.98, 0.98, f"color: proving key {key_mib.min():.1f}–{key_mib.max():.1f} MiB",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.8, color=COLORS["gray"])
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["gray"], label="per-circuit setup"),
        plt.Line2D([], [], marker="s", linestyle="none", color=COLORS["gray"], label="universal setup"),
    ], loc="lower left")
    ax.text(0.995, 0.02, "Bubble area ∝ measured verifier gas; circulation throughput is model-calibrated",
            transform=ax.transAxes, ha="right", fontsize=6.6, color=COLORS["gray"])
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig2e_backend_pareto.pdf")


def generate() -> list[str]:
    scaling, dist, trials = _scaling_sources()
    panel_a(scaling)
    panel_b(trials, dist)
    panel_c(trials, dist)
    panel_d(scaling)
    panel_e()
    return [
        "fig2a_constraint_growth.pdf", "fig2b_proving_distribution.pdf",
        "fig2c_verification_distribution.pdf", "fig2d_proof_resource_design_space.pdf",
        "fig2e_backend_pareto.pdf",
    ]


if __name__ == "__main__":
    generate()
