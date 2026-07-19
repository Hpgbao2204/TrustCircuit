"""Figure 3: smooth DP utility, parity, composition, and budget panels."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import BoundaryNorm

from .data_loading import groups, indexed, processed, values
from .figure_style import ANNOTATION_SIZE, COLORS, PALETTE, finish_axis, new_figure, save_pdf
from .plot_helpers import percentile_ribbon, smooth_line, style_secondary_axis
from .statistics import pchip, smooth_empirical_cdf


def _epsilon_keys(rows) -> list[str]:
    return sorted({r["epsilon_requested"] for r in rows}, key=float)


def panel_a(trials) -> None:
    grouped = groups(trials, "epsilon_requested")
    keys = _epsilon_keys(trials)
    fig, ax = new_figure(figsize=(8.45, 5.25))
    for i, key in enumerate(keys):
        data = np.sort(values(grouped[key], "relative_error") * 100)
        empirical_y = np.arange(1, len(data) + 1) / len(data)
        guide_x, guide_y = smooth_empirical_cdf(data)
        p50, p95 = np.percentile(data, [50, 95])
        ax.plot(guide_x, guide_y, color=PALETTE[i], linewidth=1.8,
                label=fr"$\epsilon$={float(key):g} ({p50:.2f}/{p95:.2f}%)")
        ax.plot(data, empirical_y, linestyle="none", marker=".", markersize=3.2,
                color=PALETTE[i], alpha=0.65)
        ax.plot([p50, p95], [0.5, 0.95], linestyle="none", marker="D", markersize=4,
                color=PALETTE[i], markeredgecolor="white", markeredgewidth=0.5)
    ax.set_xlabel("Relative error (%)")
    ax.set_ylabel("Empirical cumulative probability")
    ax.set_title("Relative-error empirical distributions")
    ax.set_ylim(0, 1.02)
    ax.legend(title="ε: p50 / p95", loc="lower right", ncol=2)
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig3a_relative_error_ecdf.pdf")


def panel_b(trials, error_summary) -> None:
    rows = sorted(error_summary, key=lambda r: float(r["epsilon_requested"]))
    epsilon = values(rows, "epsilon_requested")
    p50 = values(rows, "median_relative_error") * 100
    p95 = values(rows, "p95_relative_error") * 100
    low = values(rows, "bootstrap_ci95_low_relative_error") * 100
    high = values(rows, "bootstrap_ci95_high_relative_error") * 100
    trial_groups = groups(trials, "epsilon_requested")
    throughput = np.array([
        np.median(values(trial_groups[r["epsilon_requested"]], "throughput_req_s")) for r in rows
    ])

    fig, ax = new_figure(figsize=(8.45, 5.2))
    percentile_ribbon(ax, epsilon, low, high, color=COLORS["blue"], label="95% CI",
                      log_x=True)
    smooth_line(ax, epsilon, p50, color=COLORS["blue"], label="relative error p50", log_x=True)
    smooth_line(ax, epsilon, p95, color=COLORS["red"], label="relative error p95", marker="D",
                linestyle="--", log_x=True)
    ax.set_xscale("log")
    ax.set_xticks(epsilon, [f"{v:g}" for v in epsilon])
    ax.set_xlabel(r"Requested $\epsilon$")
    ax.set_ylabel("Relative error (%)")
    ax.set_title("DP utility and release throughput")
    ax2 = ax.twinx()
    smooth_line(ax2, epsilon, throughput, color=COLORS["green"], label="throughput p50",
                marker="s", log_x=True)
    ax2.set_ylabel("Throughput (requests/s)", color=COLORS["green"])
    style_secondary_axis(ax2, COLORS["green"])
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper right")
    finish_axis(ax)
    save_pdf(fig, "fig3b_dp_error_trend.pdf")


def panel_c(rounding) -> None:
    exact = values(rounding, "exact_conservative_cost_micro_epsilon") / 1e6
    margin = values(rounding, "rounding_margin_micro_epsilon")
    offsets = values(rounding, "offset_micro_epsilon")
    under = values(rounding, "under_reporting")
    q50, q95 = np.percentile(margin, [50, 95])
    bins = np.digitize(margin, [1 / 3, 2 / 3])
    colors = np.array([COLORS["blue"], COLORS["orange"], COLORS["red"]])[bins]

    fig, ax = new_figure(figsize=(8.45, 5.2))
    ax.axhspan(-0.12, 0, color=COLORS["red"], alpha=0.12, label="under-reporting region")
    ax.vlines(exact, 0, margin, colors=colors, linewidth=0.7, alpha=0.45)
    ax.scatter(exact, margin, c=colors, s=22, edgecolor="white", linewidth=0.35, zorder=4)
    ax.axhline(0, color=COLORS["dark"], linestyle="--", linewidth=1.2, label="exact parity")
    ax.axhline(q50, color=COLORS["blue"], linestyle=":", linewidth=1.2, label=f"margin p50={q50:.3f} µε")
    ax.axhline(q95, color=COLORS["red"], linestyle=":", linewidth=1.2, label=f"margin p95={q95:.3f} µε")
    max_i = int(np.argmax(margin))
    ax.annotate(f"maximum {margin[max_i]:.3f} µε", (exact[max_i], margin[max_i]),
                xytext=(-80, -34), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": COLORS["dark"]},
                fontsize=ANNOTATION_SIZE)
    ax.set_xlabel("Exact conservative privacy cost (ε)")
    ax.set_ylabel("VBS conservative margin (µε)")
    ax.set_ylim(-0.12, 1.08)
    ax.set_title("Fixed-point accountant parity residuals")
    handles, labels = ax.get_legend_handles_labels()
    handles.append(plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["green"],
                              label=f"under-reports: {int(under.sum())}"))
    labels.append(f"under-reports: {int(under.sum())}")
    ax.legend(handles, labels, loc="lower right", ncol=2)
    finish_axis(ax, grid="both")
    save_pdf(fig, "fig3c_accountant_parity.pdf")


def panel_d(composition) -> None:
    grouped = groups(composition, "epsilon_requested")
    keys = _epsilon_keys(composition)
    budget = 5.0
    epsilon = np.asarray([float(key) for key in keys])
    release_axis = np.asarray(sorted({int(r["releases"]) for r in composition}), dtype=float)
    fixed = np.vstack([
        values(sorted(grouped[key], key=lambda r: int(r["releases"])),
               "conservative_fixed_epsilon")
        for key in keys
    ])
    reference = np.vstack([
        values(sorted(grouped[key], key=lambda r: int(r["releases"])),
               "rdp_reference_epsilon")
        for key in keys
    ])
    gap = fixed - reference
    epsilon_position = np.log10(epsilon)
    release_grid, epsilon_grid = np.meshgrid(release_axis, epsilon_position)
    color_bounds = np.linspace(float(gap.min()), float(gap.max()), 9)
    cmap = plt.get_cmap("coolwarm", len(color_bounds) - 1)
    norm = BoundaryNorm(color_bounds, cmap.N, clip=True)

    fig, ax = new_figure(figsize=(9.4, 6.25), projection="3d")
    ax.plot_surface(
        release_grid,
        epsilon_grid,
        fixed,
        facecolors=cmap(norm(gap)),
        edgecolor="#455A64",
        linewidth=0.32,
        antialiased=True,
        shade=False,
        alpha=0.88,
    )
    ax.scatter(
        release_grid.ravel(), epsilon_grid.ravel(), fixed.ravel(),
        c=gap.ravel(), cmap=cmap, norm=norm, s=14, edgecolors="white", linewidths=0.35,
        depthshade=False,
    )
    budget_plane = np.full_like(fixed, budget)
    ax.plot_surface(release_grid, epsilon_grid, budget_plane, color=COLORS["red"],
                    alpha=0.10, linewidth=0)
    ax.plot_wireframe(release_grid, epsilon_grid, budget_plane, color=COLORS["red"],
                      linewidth=0.55, alpha=0.45, rstride=1, cstride=5)
    ax.set_xlabel("Cumulative releases", labelpad=10)
    ax.set_ylabel(r"Requested $\epsilon$", labelpad=12)
    ax.set_zlabel(r"Conservative cumulative loss ($\epsilon$)", labelpad=10)
    ax.set_yticks(epsilon_position, [f"{value:g}" for value in epsilon])
    ax.set_xticks([1, 8, 16, 24, 32])
    ax.set_zlim(0, float(fixed.max()) * 1.03)
    ax.set_title(r"Privacy-composition surface across requested $\epsilon$ and releases")
    ax.view_init(elev=27, azim=-58)
    ax.set_box_aspect((1.55, 1.0, 0.88))
    colorbar = fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap),
        ax=ax,
        boundaries=color_bounds,
        ticks=color_bounds[::2],
        pad=0.12,
        shrink=0.66,
        aspect=18,
    )
    colorbar.set_label(r"Fixed charge $-$ RDP reference ($\epsilon$)")
    handles = [
        plt.Line2D([], [], marker="o", linestyle="none", color=COLORS["dark"],
                   markerfacecolor="white", label="stored observations"),
        plt.Line2D([], [], color=COLORS["red"], linestyle="-", label=r"ledger budget $\epsilon=5$"),
    ]
    ax.legend(handles=handles, loc="upper left")
    save_pdf(fig, "fig3d_privacy_composition.pdf")


def panel_e(trajectory) -> None:
    rows = sorted([r for r in trajectory if float(r["epsilon_requested"]) == 0.25],
                  key=lambda r: int(r["request_index"]))
    if not rows:
        raise ValueError("Budget trajectory has no epsilon=0.25 rows")
    x = values(rows, "request_index")
    total = values(rows, "budget_total_fixed") / 1e6
    used = values(rows, "budget_used_fixed") / 1e6
    reserved = values(rows, "budget_reserved_fixed") / 1e6
    accepted = values(rows, "accepted").astype(bool)
    reverted = values(rows, "reverted").astype(bool)
    dense_x, dense_used = pchip(x, used, clamp_min=0)
    _, dense_reserved = pchip(x, reserved, clamp_min=0)
    dense_total = np.full_like(dense_x, total[0])
    dense_available = np.maximum(dense_total - dense_used - dense_reserved, 0)

    fig, ax = new_figure(figsize=(8.5, 5.25))
    ax.fill_between(dense_x, 0, dense_used, color=COLORS["blue"], alpha=0.78, label="used")
    ax.fill_between(dense_x, dense_used, dense_used + dense_reserved, color=COLORS["orange"],
                    alpha=0.82, label="reserved")
    ax.fill_between(dense_x, dense_used + dense_reserved, dense_total, color=COLORS["green"],
                    alpha=0.35, label="available")
    ax.plot(x, used, linestyle="none", marker="o", color=COLORS["dark"], markersize=3.6)
    ax.plot(x[accepted], total[accepted] * 1.015, linestyle="none", marker="v", color=COLORS["green"],
            markersize=5, clip_on=False, label="accepted")
    ax.plot(x[reverted], total[reverted] * 1.015, linestyle="none", marker="x", color=COLORS["red"],
            markersize=5, clip_on=False, label="reverted")
    first_revert = np.where(reverted)[0][0]
    ax.annotate("exhaustion boundary", (x[first_revert], used[first_revert]), xytext=(-92, -42),
                textcoords="offset points", arrowprops={"arrowstyle": "->", "color": COLORS["red"]},
                fontsize=ANNOTATION_SIZE)
    ax.set_xlim(1, 32)
    ax.set_ylim(0, total.max() * 1.08)
    ax.set_xlabel("Request index")
    ax.set_ylabel("Privacy budget (ε)")
    ax.set_title(r"Budget trajectory at requested $\epsilon=0.25$")
    ax.legend(loc="center right", ncol=2)
    finish_axis(ax)
    save_pdf(fig, "fig3e_budget_trajectory.pdf")


def generate() -> list[str]:
    trials = processed("dp_vbs_trials.csv", ["epsilon_requested", "relative_error", "throughput_req_s"])
    error_summary = processed(
        "dp_error_summary.csv",
        ["epsilon_requested", "median_relative_error", "p95_relative_error",
         "bootstrap_ci95_low_relative_error", "bootstrap_ci95_high_relative_error"],
    )
    rounding = processed(
        "dp_rounding_margin.csv",
        ["exact_conservative_cost_micro_epsilon", "rounding_margin_micro_epsilon",
         "offset_micro_epsilon", "under_reporting"],
    )
    composition = processed(
        "dp_composition.csv",
        ["epsilon_requested", "releases", "rdp_reference_epsilon", "conservative_fixed_epsilon"],
    )
    trajectory = processed(
        "budget_exhaustion_trajectory.csv",
        ["epsilon_requested", "request_index", "accepted", "reverted", "budget_total_fixed",
         "budget_used_fixed", "budget_reserved_fixed"],
    )
    panel_a(trials)
    panel_b(trials, error_summary)
    panel_c(rounding)
    panel_d(composition)
    panel_e(trajectory)
    return [
        "fig3a_relative_error_ecdf.pdf", "fig3b_dp_error_trend.pdf", "fig3c_accountant_parity.pdf",
        "fig3d_privacy_composition.pdf", "fig3e_budget_trajectory.pdf",
    ]


if __name__ == "__main__":
    generate()
