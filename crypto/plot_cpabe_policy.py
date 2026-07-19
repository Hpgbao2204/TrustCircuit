from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.make_paper_figures import (  # noqa: E402
    apply_style,
    figure_cpabe_policy_comparison,
    read_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the four-curve CP-ABE policy-latency Figure 5(b).")
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "results" / "summary" / "cpabe_policy_summary.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "results" / "figures" / "abe",
    )
    args = parser.parse_args()
    apply_style()
    output = figure_cpabe_policy_comparison(read_csv(args.summary), args.out_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
