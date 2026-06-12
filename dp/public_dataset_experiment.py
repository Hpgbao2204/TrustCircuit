"""Experiment 7 (Q1 plan): differential-privacy utility on a PUBLIC dataset.

The main DP study (dp/experiment.py) uses a synthetic cohort calibrated to
NHANES marginals. Reviewers reasonably ask whether the privacy-utility trend
holds on real, externally-sourced data. This script runs the SAME Gaussian
mechanism and query set on the UCI Adult census dataset (a standard public
tabular benchmark) and compares the relative-error-vs-epsilon behaviour against
the synthetic baseline.

Data handling:
  * We try a local cache (data/public/adult.data), then a download from the UCI
    repository. If neither is available we fall back to a deterministic,
    clearly-labelled public-style cohort so the pipeline always reproduces; the
    `dataset_source` column records which path was used.
  * Only aggregate statistics leave this script; no row-level data is exported.

Outputs:
    results/q1/raw/public_dp_utility.csv
    results/q1/summary/public_dp_utility_summary.csv
    results/q1/figures/public_vs_synthetic_dp_error.pdf
"""

from __future__ import annotations

import csv
import math
import sys
import urllib.request
from pathlib import Path
from statistics import mean, pstdev

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.paper_plot_style import apply_paper_style, save_pdf  # noqa: E402

EPSILONS = (0.1, 0.5, 1.0, 2.0, 5.0)
DELTA = 1e-5
TRIALS = 500
SEED = 42

CACHE = Path("data/public/adult.data")
UCI_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
ADULT_COLUMNS = [
    "age", "workclass", "fnlwgt", "education", "education_num", "marital_status",
    "occupation", "relationship", "race", "sex", "capital_gain", "capital_loss",
    "hours_per_week", "native_country", "income",
]

RAW = Path("results/q1/raw/public_dp_utility.csv")
SUMMARY = Path("results/q1/summary/public_dp_utility_summary.csv")
FIGURE = Path("results/q1/figures/public_vs_synthetic_dp_error.pdf")
SYNTH_SUMMARY = Path("results/summary/dp_utility_summary.csv")


def gaussian_mechanism(value: float, sensitivity: float, epsilon: float, delta: float, rng: np.random.Generator) -> float:
    sigma = sensitivity * math.sqrt(2 * math.log(1.25 / delta)) / epsilon
    return value + rng.normal(0, sigma)


def load_adult() -> tuple[dict[str, np.ndarray], str]:
    """Return numeric columns and a source tag (uci_cache / uci_download / fallback)."""
    text = None
    source = "fallback_public_style"
    if CACHE.exists():
        text = CACHE.read_text(encoding="utf-8", errors="ignore")
        source = "uci_cache"
    else:
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(UCI_URL, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            CACHE.write_text(text, encoding="utf-8")
            source = "uci_download"
        except Exception:
            text = None

    if text is not None:
        ages, hours, gains, incomes = [], [], [], []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != len(ADULT_COLUMNS):
                continue
            try:
                ages.append(float(parts[0]))
                hours.append(float(parts[12]))
                gains.append(float(parts[10]))
                incomes.append(1.0 if parts[14].startswith(">50K") else 0.0)
            except ValueError:
                continue
        if len(ages) > 1000:
            return ({
                "age": np.array(ages),
                "hours_per_week": np.array(hours),
                "capital_gain": np.array(gains),
                "high_income": np.array(incomes),
            }, source)

    # deterministic fallback (clearly labelled) so the pipeline never breaks.
    rng = np.random.default_rng(SEED)
    n = 32561  # Adult train size
    age = rng.gamma(shape=10.0, scale=3.9, size=n).clip(17, 90)
    hours = rng.normal(40.4, 12.3, size=n).clip(1, 99)
    gains = (rng.random(n) < 0.085) * rng.gamma(2.0, 4000.0, size=n)
    income = (rng.random(n) < 0.24).astype(float)
    return ({"age": age, "hours_per_week": hours, "capital_gain": gains, "high_income": income},
            "fallback_public_style")


def query_specs(data: dict[str, np.ndarray]) -> list[dict]:
    n = len(data["age"])
    return [
        {"query": "mean_age", "true_value": float(np.mean(data["age"])), "sensitivity": (90 - 17) / n},
        {"query": "mean_hours_per_week", "true_value": float(np.mean(data["hours_per_week"])), "sensitivity": (99 - 1) / n},
        {"query": "mean_capital_gain", "true_value": float(np.mean(data["capital_gain"])), "sensitivity": 99999 / n},
        {"query": "high_income_count", "true_value": float(np.sum(data["high_income"])), "sensitivity": 1.0},
        {"query": "record_count", "true_value": float(n), "sensitivity": 1.0},
    ]


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def run() -> str:
    data, source = load_adult()
    queries = query_specs(data)
    rng = np.random.default_rng(SEED)

    RAW.parent.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict] = []
    with RAW.open("w", newline="", encoding="utf-8") as f:
        fields = ["dataset_source", "query", "epsilon", "delta", "trial",
                  "true_value", "noisy_value", "absolute_error", "relative_error"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for epsilon in EPSILONS:
            for spec in queries:
                tv = float(spec["true_value"])
                sens = float(spec["sensitivity"])
                for trial in range(TRIALS):
                    nv = gaussian_mechanism(tv, sens, epsilon, DELTA, rng)
                    ae = abs(nv - tv)
                    re = ae / max(abs(tv), 1.0)
                    row = {"dataset_source": source, "query": spec["query"], "epsilon": epsilon,
                           "delta": DELTA, "trial": trial, "true_value": tv, "noisy_value": nv,
                           "absolute_error": ae, "relative_error": re}
                    w.writerow(row)
                    raw_rows.append(row)

    # summary
    grouped: dict[tuple[str, float], list[dict]] = {}
    for r in raw_rows:
        grouped.setdefault((r["query"], float(r["epsilon"])), []).append(r)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        fields = ["dataset_source", "query", "epsilon", "trials", "true_value",
                  "absolute_error_mean", "relative_error_mean", "relative_error_percent_mean",
                  "relative_error_std", "relative_error_p50", "relative_error_p95", "relative_error_p99",
                  "utility_retention", "epsilon_consumed"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for (query, epsilon), rs in sorted(grouped.items()):
            rel = [float(r["relative_error"]) for r in rs]
            ab = [float(r["absolute_error"]) for r in rs]
            re_mean = mean(rel)
            w.writerow({
                "dataset_source": source, "query": query, "epsilon": epsilon, "trials": len(rs),
                "true_value": float(rs[0]["true_value"]),
                "absolute_error_mean": mean(ab), "relative_error_mean": re_mean,
                "relative_error_percent_mean": re_mean * 100,
                "relative_error_std": pstdev(rel), "relative_error_p50": percentile(rel, 50),
                "relative_error_p95": percentile(rel, 95), "relative_error_p99": percentile(rel, 99),
                "utility_retention": 1.0 - re_mean, "epsilon_consumed": epsilon,
            })

    plot(source)
    print(RAW)
    print(SUMMARY)
    print(FIGURE)
    return source


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plot(source: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pub = read_csv(SUMMARY)
    pub_by_eps: dict[float, list[float]] = {}
    for r in pub:
        pub_by_eps.setdefault(float(r["epsilon"]), []).append(float(r["relative_error_percent_mean"]))
    eps = sorted(pub_by_eps)
    pub_mean = [mean(pub_by_eps[e]) for e in eps]

    synth_mean = None
    if SYNTH_SUMMARY.exists():
        syn = read_csv(SYNTH_SUMMARY)
        syn_by_eps: dict[float, list[float]] = {}
        for r in syn:
            syn_by_eps.setdefault(float(r["epsilon"]), []).append(float(r["relative_error_percent_mean"]))
        synth_mean = [mean(syn_by_eps[e]) for e in eps if e in syn_by_eps]

    apply_paper_style()
    fig, ax = plt.subplots()
    ax.loglog(eps, pub_mean, marker="o", color="#d62728", label=f"public ({source})")
    if synth_mean and len(synth_mean) == len(eps):
        ax.loglog(eps, synth_mean, marker="s", color="#1f77b4", label="synthetic (NHANES-calibrated)")
    ax.set_xlabel("privacy budget $\\varepsilon$")
    ax.set_ylabel("mean relative error (%)")
    ax.set_title("DP utility: public vs synthetic")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    save_pdf(fig, FIGURE.parent, FIGURE.stem)


if __name__ == "__main__":
    run()
