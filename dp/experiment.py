"""Differential Privacy utility experiment for TrustCircuit.

This script is intentionally practical: generate a synthetic healthcare dataset,
run aggregate queries under Gaussian noise, export raw rows, summary rows, and a
utility plot that can be used directly in the project report.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, pstdev

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.paper_plot_style import apply_paper_style, save_pdf


EPSILON_SCALE = 1_000_000
DEFAULT_EPSILONS = (0.1, 0.5, 1.0, 2.0, 5.0)


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int
    rows: int
    trials: int
    epsilon_values: tuple[float, ...]
    delta: float
    raw_output: Path
    summary_output: Path
    config_output: Path
    figure_output: Path


def epsilon_to_fixed(epsilon: float) -> int:
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    return math.ceil(epsilon * EPSILON_SCALE)


def synthetic_healthcare(rows: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Generate a synthetic healthcare cohort with *correlated* demographic and
    clinical attributes.

    Marginal parameters (means/spreads/ranges and ~18% diabetes prevalence) are
    chosen to mirror adult population statistics reported by the U.S. CDC NHANES
    program; no real records are used, so the released cohort carries no
    disclosure risk and is exactly reproducible from the seed.

    Correlation is induced by a Gaussian copula: a latent multivariate normal
    with positive correlations couples age, systolic blood pressure, and
    cholesterol; the diabetes indicator is then drawn from a logistic model of
    the (standardised) clinical attributes so that risk rises with age, blood
    pressure, and cholesterol.
    """
    # latent correlation among (age, systolic_bp, cholesterol)
    corr = np.array([
        [1.00, 0.35, 0.30],
        [0.35, 1.00, 0.28],
        [0.30, 0.28, 1.00],
    ])
    means = np.array([48.0, 124.0, 200.0])
    sds = np.array([15.0, 18.0, 42.0])
    cov = corr * np.outer(sds, sds)
    latent = rng.multivariate_normal(means, cov, size=rows)

    ages = latent[:, 0].clip(18, 90)
    systolic_bp = latent[:, 1].clip(80, 210)
    cholesterol = latent[:, 2].clip(100, 360)

    # diabetes risk rises with standardised age / BP / cholesterol (logistic);
    # the intercept is tuned to ~18% population prevalence.
    z = (
        -1.85
        + 0.55 * (ages - 48.0) / 15.0
        + 0.35 * (systolic_bp - 124.0) / 18.0
        + 0.30 * (cholesterol - 200.0) / 42.0
    )
    prob = 1.0 / (1.0 + np.exp(-z))
    diabetic = (rng.random(rows) < prob).astype(int)

    return {
        "age": ages,
        "systolic_bp": systolic_bp,
        "cholesterol": cholesterol,
        "diabetic": diabetic,
    }


def gaussian_mechanism(value: float, sensitivity: float, epsilon: float, delta: float, rng: np.random.Generator) -> float:
    sigma = sensitivity * math.sqrt(2 * math.log(1.25 / delta)) / epsilon
    return value + rng.normal(0, sigma)


def query_specs(data: dict[str, np.ndarray]) -> list[dict[str, float | str]]:
    n = len(data["age"])
    return [
        {
            "query": "mean_age",
            "true_value": float(np.mean(data["age"])),
            "sensitivity": 72 / n,
        },
        {
            "query": "mean_systolic_bp",
            "true_value": float(np.mean(data["systolic_bp"])),
            "sensitivity": 130 / n,
        },
        {
            "query": "mean_cholesterol",
            "true_value": float(np.mean(data["cholesterol"])),
            "sensitivity": 260 / n,
        },
        {
            "query": "diabetes_count",
            "true_value": float(np.sum(data["diabetic"])),
            "sensitivity": 1.0,
        },
        {
            "query": "high_bp_count",
            "true_value": float(np.sum(data["systolic_bp"] >= 140)),
            "sensitivity": 1.0,
        },
        {
            "query": "high_cholesterol_count",
            "true_value": float(np.sum(data["cholesterol"] >= 240)),
            "sensitivity": 1.0,
        },
    ]


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), p))


def write_raw(config: ExperimentConfig) -> list[dict[str, str | float | int]]:
    rng = np.random.default_rng(config.seed)
    data = synthetic_healthcare(config.rows, rng)
    queries = query_specs(data)
    rows: list[dict[str, str | float | int]] = []

    config.raw_output.parent.mkdir(parents=True, exist_ok=True)
    with config.raw_output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "seed",
            "dataset",
            "query",
            "epsilon",
            "epsilon_fixed",
            "delta",
            "trial",
            "true_value",
            "noisy_value",
            "absolute_error",
            "relative_error",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for epsilon in config.epsilon_values:
            for spec in queries:
                true_value = float(spec["true_value"])
                sensitivity = float(spec["sensitivity"])
                for trial in range(config.trials):
                    noisy_value = gaussian_mechanism(true_value, sensitivity, epsilon, config.delta, rng)
                    absolute_error = abs(noisy_value - true_value)
                    relative_error = absolute_error / max(abs(true_value), 1.0)
                    row = {
                        "seed": config.seed,
                        "dataset": "synthetic_healthcare",
                        "query": str(spec["query"]),
                        "epsilon": epsilon,
                        "epsilon_fixed": epsilon_to_fixed(epsilon),
                        "delta": config.delta,
                        "trial": trial,
                        "true_value": true_value,
                        "noisy_value": noisy_value,
                        "absolute_error": absolute_error,
                        "relative_error": relative_error,
                    }
                    writer.writerow(row)
                    rows.append(row)
    return rows


def write_summary(config: ExperimentConfig, raw_rows: list[dict[str, str | float | int]]) -> None:
    grouped: dict[tuple[str, str, float], list[dict[str, str | float | int]]] = {}
    for row in raw_rows:
        key = (str(row["dataset"]), str(row["query"]), float(row["epsilon"]))
        grouped.setdefault(key, []).append(row)

    config.summary_output.parent.mkdir(parents=True, exist_ok=True)
    with config.summary_output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "dataset",
            "query",
            "epsilon",
            "epsilon_fixed",
            "trials",
            "true_value",
            "noisy_mean",
            "absolute_error_mean",
            "relative_error_mean",
            "relative_error_percent_mean",
            "relative_error_std",
            "relative_error_p50",
            "relative_error_p95",
            "relative_error_p99",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for (dataset, query, epsilon), rows in sorted(grouped.items()):
            relative_errors = [float(row["relative_error"]) for row in rows]
            absolute_errors = [float(row["absolute_error"]) for row in rows]
            noisy_values = [float(row["noisy_value"]) for row in rows]
            writer.writerow(
                {
                    "dataset": dataset,
                    "query": query,
                    "epsilon": epsilon,
                    "epsilon_fixed": epsilon_to_fixed(epsilon),
                    "trials": len(rows),
                    "true_value": float(rows[0]["true_value"]),
                    "noisy_mean": mean(noisy_values),
                    "absolute_error_mean": mean(absolute_errors),
                    "relative_error_mean": mean(relative_errors),
                    "relative_error_percent_mean": mean(relative_errors) * 100,
                    "relative_error_std": pstdev(relative_errors),
                    "relative_error_p50": percentile(relative_errors, 50),
                    "relative_error_p95": percentile(relative_errors, 95),
                    "relative_error_p99": percentile(relative_errors, 99),
                }
            )


def write_config(config: ExperimentConfig) -> None:
    config.config_output.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    for key in ("raw_output", "summary_output", "config_output", "figure_output"):
        payload[key] = str(payload[key])
    payload["epsilon_values"] = list(config.epsilon_values)
    config.config_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_plot(config: ExperimentConfig, raw_rows: list[dict[str, str | float | int]]) -> None:
    grouped: dict[tuple[str, float], list[float]] = {}
    for row in raw_rows:
        key = (str(row["query"]), float(row["epsilon"]))
        grouped.setdefault(key, []).append(float(row["relative_error"]))

    queries = sorted({query for query, _ in grouped})
    epsilons = sorted({epsilon for _, epsilon in grouped})
    config.figure_output.parent.mkdir(parents=True, exist_ok=True)
    matrix = np.array([[mean(grouped[(query, epsilon)]) * 100 for epsilon in epsilons] for query in queries])

    apply_paper_style()
    fig, ax = plt.subplots()
    image = ax.imshow(matrix, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(np.arange(len(epsilons)), [str(epsilon) for epsilon in epsilons])
    ax.set_yticks(np.arange(len(queries)), [query.replace("_", "\n") for query in queries])
    ax.set_xlabel("epsilon")
    ax.set_title("DP utility heatmap")
    for y in range(matrix.shape[0]):
        for x in range(matrix.shape[1]):
            ax.text(x, y, f"{matrix[y, x]:.2f}", ha="center", va="center", fontsize=11)
    fig.colorbar(image, ax=ax, label="relative error (%)")
    save_pdf(fig, config.figure_output.parent, config.figure_output.stem)


def export_cohort(config: ExperimentConfig) -> Path:
    """Write the generated cohort to data/generated/ for reproducibility.

    The file is fully synthetic (seeded) and carries no disclosure risk; it lets
    reviewers reproduce the exact dataset used in the privacy-utility study.
    """
    rng = np.random.default_rng(config.seed)
    data = synthetic_healthcare(config.rows, rng)
    out = Path("data/generated/synthetic_healthcare_cohort.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["record_id", "age", "systolic_bp", "cholesterol", "diabetic"])
        for i in range(config.rows):
            writer.writerow([
                i,
                round(float(data["age"][i]), 4),
                round(float(data["systolic_bp"][i]), 4),
                round(float(data["cholesterol"][i]), 4),
                int(data["diabetic"][i]),
            ])
    return out


def run(config: ExperimentConfig) -> None:
    raw_rows = write_raw(config)
    write_summary(config, raw_rows)
    write_config(config)
    write_plot(config, raw_rows)
    cohort = export_cohort(config)
    print(config.raw_output)
    print(config.summary_output)
    print(config.figure_output)
    print(cohort)


def parse_args() -> ExperimentConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--trials", type=int, default=500)
    parser.add_argument("--delta", type=float, default=1e-5)
    parser.add_argument("--epsilons", type=float, nargs="+", default=list(DEFAULT_EPSILONS))
    parser.add_argument("--raw-output", type=Path, default=Path("results/raw/dp_utility.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("results/summary/dp_utility_summary.csv"))
    parser.add_argument("--config-output", type=Path, default=Path("results/summary/dp_config.json"))
    parser.add_argument("--figure-output", type=Path, default=Path("results/figures/dp_utility_matrix.pdf"))
    args = parser.parse_args()
    return ExperimentConfig(
        seed=args.seed,
        rows=args.rows,
        trials=args.trials,
        epsilon_values=tuple(args.epsilons),
        delta=args.delta,
        raw_output=args.raw_output,
        summary_output=args.summary_output,
        config_output=args.config_output,
        figure_output=args.figure_output,
    )


if __name__ == "__main__":
    run(parse_args())
