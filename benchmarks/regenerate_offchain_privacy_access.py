"""Regenerate the four paper panels for privacy and access-controlled processing.

The script reads the existing canonical summary CSVs, applies the enlarged
paper typography, and writes only the four PDFs referenced by ``main-new.tex``.
No benchmark data or PNG files are generated.
"""

from __future__ import annotations

from pathlib import Path

from make_paper_figures import (
    apply_style,
    figure_abe_memory,
    figure_abe_throughput,
    figure_cpabe_policy_comparison_revised,
    figure_dp_error_contour,
    read_csv,
)


ROOT = Path(__file__).resolve().parents[1]
DP_OUTPUT = ROOT / "Paper" / "Figure" / "figures" / "dp"
ABE_OUTPUT = ROOT / "Paper" / "Figure" / "figures" / "abe"


def main() -> None:
    apply_style(font_delta=8)

    dp_rows = read_csv(ROOT / "results" / "summary" / "dp_utility_summary.csv")
    cpabe_rows = read_csv(ROOT / "results" / "summary" / "cpabe_policy_summary.csv")
    payload_rows = read_csv(ROOT / "results" / "summary" / "abe_payload_summary.csv")

    outputs = [
        figure_dp_error_contour(dp_rows, DP_OUTPUT),
        figure_cpabe_policy_comparison_revised(cpabe_rows, ABE_OUTPUT),
        figure_abe_throughput(payload_rows, ABE_OUTPUT),
        figure_abe_memory(payload_rows, ABE_OUTPUT),
    ]
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
