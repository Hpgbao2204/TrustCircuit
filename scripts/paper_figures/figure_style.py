"""Shared visual language and vector-PDF output helpers."""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt


REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "Paper" / "figures" / "redesigned_panels"

COLORS = {
    "blue": "#286F9E",
    "cyan": "#49A7B8",
    "green": "#3E9C76",
    "lime": "#92B84B",
    "orange": "#E58C3B",
    "red": "#C8514D",
    "purple": "#8064A2",
    "gold": "#D5AA35",
    "gray": "#7A7F87",
    "dark": "#263238",
    "light": "#E9EEF2",
}

PALETTE = [
    COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["red"],
    COLORS["purple"], COLORS["cyan"], COLORS["gold"], COLORS["gray"],
]

STAGE_COLORS = {
    "access": COLORS["blue"],
    "budget": COLORS["green"],
    "tee": COLORS["purple"],
    "proof": COLORS["orange"],
    "settlement": COLORS["red"],
    "audit": COLORS["gold"],
    "decrypt": COLORS["blue"],
    "aggregate": COLORS["green"],
    "dp_noise": COLORS["lime"],
    "transcript": COLORS["orange"],
    "attestation_generation": COLORS["purple"],
    "host_residual": COLORS["gray"],
}


def apply_style() -> None:
    """Reset Matplotlib and apply a compact IEEE-friendly style."""
    plt.rcdefaults()
    plt.rcParams.update(
        {
            "figure.figsize": (7.15, 4.65),
            "figure.dpi": 120,
            "font.size": 9.0,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.3,
            "axes.linewidth": 0.8,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 8.2,
            "ytick.labelsize": 8.2,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "legend.fontsize": 7.8,
            "legend.frameon": True,
            "legend.framealpha": 0.92,
            "legend.edgecolor": "#CCD3D8",
            "grid.color": "#D7DDE1",
            "grid.linewidth": 0.55,
            "grid.alpha": 0.7,
            "lines.linewidth": 1.6,
            "lines.markersize": 5.0,
            "patch.linewidth": 0.7,
            "savefig.format": "pdf",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def new_figure(*, figsize: tuple[float, float] = (7.15, 4.65)):
    apply_style()
    fig, ax = plt.subplots(figsize=figsize)
    return fig, ax


def finish_axis(ax, *, grid: str = "y") -> None:
    if grid:
        ax.grid(True, axis=grid)
    ax.margins(x=0.03)


def save_pdf(fig, filename: str) -> Path:
    if not re.fullmatch(r"fig[1-6][a-e]_[a-z0-9_]+\.pdf", filename):
        raise ValueError(f"Unexpected panel filename: {filename}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    try:
        fig.savefig(
            path,
            bbox_inches="tight",
            pad_inches=0.06,
            metadata={
                "Creator": "TrustCircuit redesigned figure generator",
                "Title": filename,
                "CreationDate": None,
                "ModDate": None,
            },
        )
    finally:
        plt.close(fig)
    print(path.relative_to(REPO))
    return path


def short_variant(value: str) -> str:
    return {
        "baseline_minimal": "Minimal",
        "access_only": "Access only",
        "no_budget": "No budget",
        "no_zk": "No ZK",
        "no_tee": "No TEE*",
        "full_trustcircuit": "Full TC",
    }.get(value, value.replace("_", " ").title())


def payload_label(payload_bytes: int | float) -> str:
    value = float(payload_bytes)
    if value >= 1024**2:
        return f"{value / 1024**2:.2g} MiB"
    return f"{value / 1024:.0f} KiB"


def human_number(value: float) -> str:
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.1f}"
