"""Paper figures for the measurement-calibrated SGX cost model.

Produces three visually and conceptually distinct figures from
tee/sgx_cost_model.py:

  g1  Stacked AREA chart  : per-request latency composition as the encrypted
                            working set grows, exposing the EPC-paging cliff.
  g2  Distribution chart  : Monte-Carlo per-request latency distributions for
                            the three deployment regimes (log scale, violin).
  g3  Operational curve   : single-worker throughput recovery as the DCAP
                            attestation quote is amortized over a request batch.

All transferable CPU costs come from real host measurements; SGX-specific
overheads come from cited microbenchmarks (see sgx_cost_model.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from benchmarks.paper_plot_style import PALETTE, apply_paper_style, save_pdf  # noqa: E402
from tee.sgx_cost_model import (  # noqa: E402
    EPC_USABLE_MIB, N_TRANSITIONS, PAGE_KIB,
    HostMeasurements, SgxRanges, cycles_to_ms, monte_carlo_latency,
    run_host_measurements,
)

OUT_DIR = REPO / "results" / "figures" / "sgx_model"
SGX_FONT_SIZE = 18
SGX_ANNOTATION_SIZE = 16


def apply_sgx_style() -> None:
    apply_paper_style()
    plt.rcParams.update(
        {
            "font.size": SGX_FONT_SIZE,
            "axes.titlesize": SGX_FONT_SIZE,
            "axes.labelsize": SGX_FONT_SIZE,
            "xtick.labelsize": SGX_FONT_SIZE - 1,
            "ytick.labelsize": SGX_FONT_SIZE - 1,
            "legend.fontsize": SGX_FONT_SIZE - 3,
        }
    )


def _mid(rng_pair) -> float:
    return 0.5 * (rng_pair[0] + rng_pair[1])


# --------------------------------------------------------------------------- #
# g1: stacked AREA chart of latency composition vs encrypted working set       #
# --------------------------------------------------------------------------- #
def fig_latency_composition_area(host: HostMeasurements, r: SgxRanges) -> None:
    ws = np.linspace(8.0, 1024.0, 400)  # encrypted working set (MiB)

    # measured symmetric-crypto bandwidth proxy -> ms per MiB
    rate_ms_per_mib = host.symmetric_crypto_fits_ms / 32.0
    mee = _mid(r.mee_slowdown)

    # component 1: in-EPC compute + payload decryption under MEE slowdown
    base_cpu = host.aggregate_compute_ms + host.dp_noise_ms + host.attest_hash_ms
    comp_compute = mee * (base_cpu + rate_ms_per_mib * ws)

    # component 2: enclave transitions (constant, additive)
    comp_transitions = np.full_like(
        ws, N_TRANSITIONS * cycles_to_ms(_mid(r.transition_cycles), r.clock_hz))

    # component 3: EPC paging (zero until working set exceeds usable EPC)
    overflow = np.clip(ws - EPC_USABLE_MIB, 0.0, None)
    n_pages = overflow * 1024.0 / PAGE_KIB
    page_ms = cycles_to_ms(_mid(r.page_cycles), r.clock_hz) + host.dram_random_access_ns * 1e-6
    comp_paging = n_pages * page_ms

    # component 4: DCAP attestation quote (per request)
    comp_attest = np.full_like(ws, _mid(r.attest_ms))

    layers = [comp_compute, comp_transitions, comp_attest, comp_paging]
    labels = [
        "Compute + payload decrypt (MEE $1.15\\times$)",
        "Enclave transitions (ECALL/OCALL)",
        "Remote attestation (DCAP quote)",
        "EPC protected paging (EWB/ELDU)",
    ]
    colors = [PALETTE[2], PALETTE[3], PALETTE[4], PALETTE[1]]

    fig, ax = plt.subplots()
    ax.stackplot(ws, *layers, labels=labels, colors=colors, alpha=0.85)
    ax.axvline(EPC_USABLE_MIB, color=PALETTE[7], linestyle="--", linewidth=1.6)
    ax.annotate("usable EPC\n($\\approx$93 MiB)",
                xy=(EPC_USABLE_MIB, ax.get_ylim()[1] * 0.55),
                xytext=(EPC_USABLE_MIB + 95, ax.get_ylim()[1] * 0.48),
                fontsize=SGX_ANNOTATION_SIZE, color=PALETTE[7],
                arrowprops=dict(arrowstyle="->", color=PALETTE[7]))
    ax.set_xlabel("encrypted working set (MiB)")
    ax.set_ylabel("projected per-request latency (ms)")
    ax.set_title("SGX per-request latency composition vs working set")
    ax.set_xlim(ws.min(), ws.max())
    ax.set_ylim(0, None)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", framealpha=0.9)
    save_pdf(fig, OUT_DIR, "g1_latency_composition_area")


# --------------------------------------------------------------------------- #
# g2: Monte-Carlo latency distribution per deployment regime (violin, log)     #
# --------------------------------------------------------------------------- #
def fig_latency_distribution(host: HostMeasurements, r: SgxRanges) -> None:
    regimes = [
        ("Fits EPC\namortized attest.", 32.0, False, False, PALETTE[0]),
        ("Fits EPC\nper-request quote", 32.0, True, False, PALETTE[3]),
        ("Exceeds EPC\n(512 MiB) + quote", 512.0, True, True, PALETTE[1]),
    ]
    dists = [monte_carlo_latency(host, ws, att, lg, r) for _, ws, att, lg, _ in regimes]

    fig, ax = plt.subplots()
    parts = ax.violinplot(dists, showmedians=True, showextrema=False, widths=0.8)
    for body, (_, _, _, _, color) in zip(parts["bodies"], regimes):
        body.set_facecolor(color)
        body.set_edgecolor("black")
        body.set_alpha(0.65)
    parts["cmedians"].set_color("black")
    parts["cmedians"].set_linewidth(1.8)

    for i, d in enumerate(dists, start=1):
        med = float(np.median(d))
        ax.annotate(f"{med:.1f} ms" if med < 100 else f"{med:.0f} ms",
                    xy=(i, med), xytext=(i + 0.12, med),
                    fontsize=SGX_ANNOTATION_SIZE, va="center")

    ax.set_yscale("log")
    ax.set_xticks(range(1, len(regimes) + 1))
    ax.set_xticklabels([name for name, *_ in regimes])
    ax.set_ylabel("per-request latency (ms, log scale)")
    ax.set_title("Calibrated SGX latency distribution by deployment regime")
    ax.grid(True, axis="y", which="both", alpha=0.25)
    save_pdf(fig, OUT_DIR, "g2_latency_distribution")


# --------------------------------------------------------------------------- #
# g3: throughput recovery vs attestation amortization batch size               #
# --------------------------------------------------------------------------- #
def fig_attestation_amortization(host: HostMeasurements, r: SgxRanges) -> None:
    batch = np.arange(1, 65)
    rng = np.random.default_rng(7)
    n = 4000

    base_cpu = host.transferable_compute_ms(large=False)
    mee = rng.uniform(r.mee_slowdown[0], r.mee_slowdown[1], n)
    tr = N_TRANSITIONS * cycles_to_ms(
        rng.uniform(r.transition_cycles[0], r.transition_cycles[1], n), r.clock_hz)
    quote = rng.uniform(r.attest_ms[0], r.attest_ms[1], n)
    per_req_compute = mee * base_cpu + tr  # ms, excluding attestation

    p50, lo, hi = [], [], []
    for b in batch:
        lat = per_req_compute + quote / b          # amortize one quote over b requests
        thr = 1000.0 / lat
        p50.append(np.percentile(thr, 50))
        lo.append(np.percentile(thr, 5))
        hi.append(np.percentile(thr, 95))
    p50, lo, hi = map(np.array, (p50, lo, hi))

    fig, ax = plt.subplots()
    ax.fill_between(batch, lo, hi, color=PALETTE[0], alpha=0.2,
                    label="p5--p95 Monte-Carlo band")
    ax.plot(batch, p50, color=PALETTE[0], marker="o", markevery=6, label="median throughput")
    ax.axhline(p50[0], color=PALETTE[1], linestyle="--", linewidth=1.5,
               label=f"per-request quote ($\\approx${p50[0]:.0f} req/s)")
    ax.annotate("attestation amortized\n(compute-bound ceiling)",
                xy=(batch[-1], p50[-1]), xytext=(34, p50[-1] * 0.62),
                fontsize=SGX_ANNOTATION_SIZE,
                arrowprops=dict(arrowstyle="->", color=PALETTE[7]))
    ax.set_xlabel("attestation batch size (requests per DCAP quote)")
    ax.set_ylabel("single-worker throughput (req/s)")
    ax.set_title("Throughput recovery via attestation amortization")
    ax.set_xlim(1, 64)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", framealpha=0.9)
    save_pdf(fig, OUT_DIR, "g3_attestation_amortization")


def main() -> None:
    apply_sgx_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("measuring host-side transferable costs ...")
    host = run_host_measurements()
    r = SgxRanges()
    fig_latency_composition_area(host, r)
    fig_latency_distribution(host, r)
    fig_attestation_amortization(host, r)
    print(f"wrote figures to {OUT_DIR}")
    for p in sorted(OUT_DIR.glob("*.pdf")):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
