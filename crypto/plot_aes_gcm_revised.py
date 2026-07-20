from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.make_paper_figures import (  # noqa: E402
    apply_style,
    figure_aes_gcm_memory_revised,
    figure_aes_gcm_throughput_revised,
    read_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render revised AES-GCM throughput and host-memory panels.")
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "results" / "summary" / "aes_gcm_scaling_v2_summary.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "results" / "figures" / "abe",
    )
    args = parser.parse_args()
    apply_style()
    rows = read_csv(args.summary)
    print(figure_aes_gcm_throughput_revised(rows, args.out_dir))
    print(figure_aes_gcm_memory_revised(rows, args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
