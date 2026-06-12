"""Paper-grade plotting defaults for TrustCircuit figures."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt


FIG_SIZE = (12, 6)
FONT_SIZE = 14
LINE_WIDTH = 2.0
MARKER_SIZE = 5
PDF_DPI = 300
PALETTE = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
    "#8c564b",
    "#7f7f7f",
]


def apply_paper_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": FIG_SIZE,
            "font.size": FONT_SIZE,
            "axes.titlesize": FONT_SIZE + 1,
            "axes.labelsize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE,
            "ytick.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE - 1,
            "figure.titlesize": FONT_SIZE + 2,
            "lines.linewidth": LINE_WIDTH,
            "lines.markersize": MARKER_SIZE,
            "savefig.format": "pdf",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def pdf_path(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.pdf"


def save_pdf(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    output = pdf_path(out_dir, name)
    fig.set_size_inches(*FIG_SIZE, forward=True)
    fig.tight_layout()
    fig.savefig(output, dpi=PDF_DPI)
    plt.close(fig)
    return output


def remove_png_figures(out_dir: Path) -> list[Path]:
    if not out_dir.exists():
        return []
    removed: list[Path] = []
    for path in out_dir.glob("*.png"):
        path.unlink()
        removed.append(path)
    return removed
