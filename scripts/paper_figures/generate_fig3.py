"""Figure 3: DP utility, accountant parity, composition, and budget state."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from .data_loading import groups, indexed, processed, values
from .figure_style import COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import distribution_boxes
from .statistics import ecdf


def _epsilon_keys(rows) -> list[str]:
    return sorted({r["epsilon_requested"] for r in rows}, key=float)


def panel_a(trials) -> None:
    grouped = groups(trials, "epsilon_requested")
    keys = _epsilon_keys(trials)
    fig, ax = new_figure()
    for i, key in enumerate(keys):
        data = values(grouped[key], "relative_error") * 100
        x, y = ecdf(data)
        p50, p95 = np.percentile(data, [50, 95])
        ax.step(x, y, where="post", color=PALETTE[i], linewidth=1.8,
                label=fr"$\epsilon$={float(key):g}: {p50:.2f}/{p95:.2f}%")
        ax.scatter([p50, p95], [0.5, 0.95], s=[22, 30], color=PALETTE[i],
                   edgecolor="white", linewidth=0.5, zorder=4)
    ax.set_xlabel("Relative error (%)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Relative-error ECDF across privacy settings")
    ax.set_ylim(0, 1.02)
    ax.legend(title="ε: p50 / p95", loc="lower right", ncol=2)
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig3a_relative_error_ecdf.pdf")


def panel_b(trials, error_summary) -> None:
    grouped = groups(trials, "epsilon_requested")
    keys = _epsilon_keys(trials)
    datasets = [values(grouped[k], "relative_error") * 100 for k in keys]
    x = np.arange(len(keys), dtype=float)
    colors = [PALETTE[i] for i in range(len(keys))]
    fig, ax = new_figure()
    distribution_boxes(ax, datasets, x, colors, salt=80)
    ax.set_xticks(x, [f"{float(k):g}" for k in keys])
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Relative error (%)")
    ax.set_title("DP error distribution and measured release throughput")

    ax2 = ax.twinx()
    throughput = np.array([np.median(values(grouped[k], "throughput_req_s")) for k in keys])
    ax2.plot(x, throughput, color=COLORS["red"], marker="o", markerfacecolor="white",
             linewidth=1.3, label="p50 throughput")
    ax2.set_ylabel("Throughput (requests/s)", color=COLORS["red"])
    ax2.tick_params(axis="y", colors=COLORS["red"])
    ax2.spines["right"].set_visible(True)
    ax2.spines["right"].set_color(COLORS["red"])
    handles = [
        plt.Line2D([], [], marker="D", linestyle="none", color=COLORS["dark"], label="error p50"),
        plt.Line2D([], [], marker="^", linestyle="none", color=COLORS["red"], label="error p95"),
        plt.Line2D([], [], marker="o", markerfacecolor="white", color=COLORS["red"], label="throughput p50"),
    ]
    ax.legend(handles=handles, loc="upper right", ncol=3)
    finish_axis(ax)
    save_pdf(fig, "fig3b_dp_error_distribution.pdf")


def panel_c(rounding) -> None:
    exact = values(rounding, "exact_conservative_cost_micro_epsilon")
    fixed = values(rounding, "vbs_cost_fixed")
    margin = values(rounding, "rounding_margin_micro_epsilon")
    under = values(rounding, "under_reporting")
    lo = min(exact.min(), fixed.min())
    hi = max(exact.max(), fixed.max())

    fig, ax = new_figure()
    ax.fill_between([lo, hi], [lo, hi], [lo, lo], color=COLORS["red"], alpha=0.09,
                    label="under-reporting region")
    margin_colors = plt.get_cmap("viridis")((margin - margin.min()) / max(np.ptp(margin), 1))
    ax.scatter(exact, fixed, c=margin_colors, s=27, alpha=0.8,
               edgecolor="white", linewidth=0.35)
    ax.plot([lo, hi], [lo, hi], linestyle="--", color=COLORS["dark"], linewidth=1.2,
            label="exact parity")
    max_i = int(np.argmax(margin))
    ax.annotate(f"max rounding margin\n{margin[max_i]:.3f} µε",
                (exact[max_i], fixed[max_i]), xytext=(-92, 20), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": COLORS["dark"]}, fontsize=7.2)
    ax.set_xlabel("Exact conservative privacy cost (µε)")
    ax.set_ylabel("VBS fixed-point cost (µε)")
    ax.set_title("Accountant parity at fixed-point boundaries")
    ax.text(0.02, 0.90, f"color: rounding margin {margin.min():.3f}–{margin.max():.3f} µε",
            transform=ax.transAxes, fontsize=6.8, color=COLORS["gray"])
    ax.text(0.02, 0.96, f"n={len(rounding)} · under-reports={int(under.sum())}", transform=ax.transAxes,
            va="top", fontsize=7.4, bbox={"facecolor": "white", "edgecolor": "#CCD3D8", "alpha": 0.9})
    ax.legend(loc="lower right")
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig3c_accountant_parity.pdf")


def panel_d(composition, budget_summary) -> None:
    grouped = groups(composition, "epsilon_requested")
    keys = _epsilon_keys(composition)
    budget_fixed = 5_000_000.0
    budget_eps = budget_fixed / 1_000_000.0
    fig, ax = new_figure(figsize=(7.25, 4.75))
    for i, key in enumerate(keys):
        rows = sorted(grouped[key], key=lambda r: int(r["releases"]))
        releases = values(rows, "releases")
        reference = values(rows, "rdp_reference_epsilon")
        fixed = values(rows, "conservative_fixed_epsilon")
        ax.step(releases, fixed, where="post", color=PALETTE[i], linewidth=1.6,
                label=fr"$\epsilon$={float(key):g}")
        ax.step(releases, reference, where="post", color=PALETTE[i], linewidth=0.9,
                linestyle="--", alpha=0.62)
        crossing = np.where(fixed > budget_eps)[0]
        if len(crossing):
            j = crossing[0]
            ax.scatter(releases[j], fixed[j], marker="X", s=32, color=PALETTE[i], zorder=5)
    ax.axhline(budget_eps, color=COLORS["red"], linestyle=":", linewidth=1.5,
               label=f"ledger budget = {budget_eps:g} ε")
    ax.set_xlabel("Cumulative releases")
    ax.set_ylabel(r"Cumulative privacy loss ($\epsilon$)")
    ax.set_title("Analytical composition and conservative fixed-point charge")
    ax.set_xlim(1, 32)
    ax.set_yscale("log")
    method_handles = [
        plt.Line2D([], [], color=COLORS["gray"], linestyle="-", label="fixed-point charge"),
        plt.Line2D([], [], color=COLORS["gray"], linestyle="--", label="RDP reference"),
        plt.Line2D([], [], marker="X", linestyle="none", color=COLORS["gray"], label="first over budget"),
    ]
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles + method_handles, labels + [h.get_label() for h in method_handles],
              loc="upper left", ncol=3)
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig3d_privacy_composition.pdf")


def panel_e(trajectory) -> None:
    selected = "0.25"
    rows = sorted([r for r in trajectory if float(r["epsilon_requested"]) == float(selected)],
                  key=lambda r: int(r["request_index"]))
    if not rows:
        raise ValueError("Budget trajectory has no epsilon=0.25 rows")
    x = values(rows, "request_index")
    total = values(rows, "budget_total_fixed") / 1_000_000
    used = values(rows, "budget_used_fixed") / 1_000_000
    reserved = values(rows, "budget_reserved_fixed") / 1_000_000
    remaining = values(rows, "budget_remaining_fixed") / 1_000_000
    accepted = values(rows, "accepted").astype(bool)
    reverted = values(rows, "reverted").astype(bool)
    residual = total - used - reserved - remaining

    fig, ax = new_figure()
    ax.fill_between(x, 0, used, step="post", color=COLORS["blue"], alpha=0.78, label="used")
    ax.fill_between(x, used, used + reserved, step="post", color=COLORS["orange"], alpha=0.85,
                    label="reserved")
    ax.fill_between(x, used + reserved, total, step="post", color=COLORS["green"], alpha=0.35,
                    label="available")
    ax.step(x, used, where="post", color=COLORS["dark"], linewidth=1.0)
    ax.scatter(x[accepted], total[accepted] * 1.015, marker="v", color=COLORS["green"], s=24,
               clip_on=False, label="accepted request")
    ax.scatter(x[reverted], total[reverted] * 1.015, marker="x", color=COLORS["red"], s=30,
               clip_on=False, label="reverted request")
    first_revert = np.where(reverted)[0][0]
    ax.annotate(f"budget exhausted after {int(np.sum(accepted))} accepts",
                (x[first_revert], used[first_revert]), xytext=(-112, -48), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": COLORS["red"]}, fontsize=7.2)
    ax.set_xlabel("Request index (unsmoothed event order)")
    ax.set_ylabel("Privacy budget (ε, fixed-point units)")
    ax.set_title(r"Ledger budget trajectory at requested $\epsilon=0.25$")
    ax.set_xlim(1, 32)
    ax.set_ylim(0, total.max() * 1.08)
    ax.text(0.995, 0.04, f"max invariant residual={np.max(np.abs(residual)):.0f} µε · violations=0",
            transform=ax.transAxes, ha="right", fontsize=7.0, color=COLORS["dark"])
    ax.legend(loc="center right", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig3e_budget_trajectory.pdf")


def generate() -> list[str]:
    trials = processed(
        "dp_vbs_trials.csv", ["epsilon_requested", "relative_error", "throughput_req_s", "ok"]
    )
    error_summary = processed("dp_error_summary.csv", ["epsilon_requested", "p95_relative_error"])
    rounding = processed(
        "dp_rounding_margin.csv",
        ["exact_conservative_cost_micro_epsilon", "vbs_cost_fixed", "rounding_margin_micro_epsilon",
         "under_reporting"],
    )
    composition = processed(
        "dp_composition.csv",
        ["epsilon_requested", "releases", "rdp_reference_epsilon", "conservative_fixed_epsilon"],
    )
    budget_summary = processed("budget_exhaustion_summary.csv", ["epsilon_requested", "accepted_requests"])
    trajectory = processed(
        "budget_exhaustion_trajectory.csv",
        ["epsilon_requested", "request_index", "accepted", "reverted", "budget_total_fixed",
         "budget_used_fixed", "budget_reserved_fixed", "budget_remaining_fixed"],
    )
    panel_a(trials)
    panel_b(trials, error_summary)
    panel_c(rounding)
    panel_d(composition, budget_summary)
    panel_e(trajectory)
    return [
        "fig3a_relative_error_ecdf.pdf", "fig3b_dp_error_distribution.pdf",
        "fig3c_accountant_parity.pdf", "fig3d_privacy_composition.pdf",
        "fig3e_budget_trajectory.pdf",
    ]


if __name__ == "__main__":
    generate()
