"""Experiment 6 (Q1 plan): TEE redundancy vs malicious-worker fraction.

Simulator-level robustness study (NOT SGX hardware security). We model an
N-of-N worker pool that executes a request under k-redundancy and accepts an
output only when a majority of independently-attested workers agree. We sweep
the fraction of malicious workers and the attack type, and measure how
redundancy converts a single point of failure into a detectable disagreement.

Configs:        single_worker, 3/5/7-worker majority
malicious_frac: 0, 0.1, 0.25, 0.33, 0.5, 0.67
attack_type:    wrong_result, wrong_epsilon, skip_dp_noise, stale_attestation
trials:         100

Metrics: attack_success_rate, detection_rate, false_accept_rate,
         latency_overhead, worker_cost_multiplier.

Outputs:
    results/q1/raw/tee_redundancy_attacks.csv
    results/q1/summary/tee_redundancy_attacks_summary.csv
    results/q1/summary/tee_redundancy_config.json
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

RAW = Path("results/q1/raw/tee_redundancy_attacks.csv")
SUMMARY = Path("results/q1/summary/tee_redundancy_attacks_summary.csv")
CONFIG = Path("results/q1/summary/tee_redundancy_config.json")

CONFIGS = {"single_worker": 1, "3_worker_majority": 3, "5_worker_majority": 5, "7_worker_majority": 7}
MALICIOUS_FRACTIONS = [0.0, 0.1, 0.25, 0.33, 0.5, 0.67]
ATTACK_TYPES = ["wrong_result", "wrong_epsilon", "skip_dp_noise", "stale_attestation"]
TRIALS = 100
SEED = 2026

# stale_attestation is caught by an attestation-freshness check at every worker
# independently of voting, so a single honest verifier detects it. The other
# three attacks alter the committed output and are caught only by cross-worker
# disagreement (majority voting).
ATTESTATION_CHECKED = {"stale_attestation"}


def majority_threshold(k: int) -> int:
    return k // 2 + 1


def simulate(rng: np.random.Generator, k: int, p: float, attack: str) -> dict[str, float]:
    threshold = majority_threshold(k)
    attack_success = 0
    detected = 0
    false_accept = 0

    for _ in range(TRIALS):
        # each worker is independently malicious with probability p.
        malicious = rng.random(k) < p
        n_mal = int(malicious.sum())

        if attack in ATTESTATION_CHECKED:
            # freshness is verifiable per-worker: any malicious (stale) worker is
            # flagged; the request is rejected if any worker fails attestation.
            if n_mal > 0:
                detected += 1
            # a stale attestation never yields an accepted wrong result.
            continue

        if k == 1:
            # no redundancy: a malicious worker's output is accepted blindly.
            if malicious[0]:
                attack_success += 1
                false_accept += 1
            continue

        # k>=3: malicious workers collude on one wrong value; honest agree on
        # the correct value. The wrong value is accepted iff it has a majority.
        if n_mal >= threshold:
            attack_success += 1
            false_accept += 1
        elif n_mal > 0:
            # disagreement without a malicious majority -> detected & rejected.
            detected += 1
        # n_mal == 0 -> clean run, nothing to detect.

    # cost / latency model: k workers run in parallel, so wall-clock latency
    # grows only with tail/synchronisation overhead (~5% per extra worker),
    # while the resource (worker) cost grows linearly with k.
    latency_overhead = 1.0 + 0.05 * (k - 1)
    worker_cost_multiplier = float(k)

    return {
        "attack_success_rate": attack_success / TRIALS,
        "detection_rate": detected / TRIALS,
        "false_accept_rate": false_accept / TRIALS,
        "latency_overhead": latency_overhead,
        "worker_cost_multiplier": worker_cost_multiplier,
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)

    raw_fields = ["config", "workers", "malicious_fraction", "attack_type",
                  "trials", "attack_success_rate", "detection_rate",
                  "false_accept_rate", "latency_overhead", "worker_cost_multiplier"]
    rows: list[dict] = []
    for config, k in CONFIGS.items():
        for p in MALICIOUS_FRACTIONS:
            for attack in ATTACK_TYPES:
                m = simulate(rng, k, p, attack)
                rows.append({
                    "config": config, "workers": k, "malicious_fraction": p,
                    "attack_type": attack, "trials": TRIALS, **m,
                })

    with RAW.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=raw_fields)
        w.writeheader()
        w.writerows(rows)

    # summary: average over attack types per (config, malicious_fraction).
    summary: list[dict] = []
    for config, k in CONFIGS.items():
        for p in MALICIOUS_FRACTIONS:
            sub = [r for r in rows if r["config"] == config and r["malicious_fraction"] == p]
            summary.append({
                "config": config, "workers": k, "malicious_fraction": p,
                "mean_attack_success_rate": float(np.mean([r["attack_success_rate"] for r in sub])),
                "mean_detection_rate": float(np.mean([r["detection_rate"] for r in sub])),
                "mean_false_accept_rate": float(np.mean([r["false_accept_rate"] for r in sub])),
                "latency_overhead": sub[0]["latency_overhead"],
                "worker_cost_multiplier": sub[0]["worker_cost_multiplier"],
            })
    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    CONFIG.write_text(json.dumps({
        "configs": CONFIGS, "malicious_fractions": MALICIOUS_FRACTIONS,
        "attack_types": ATTACK_TYPES, "trials": TRIALS, "seed": SEED,
        "note": "Simulator-level redundancy robustness, not SGX hardware security.",
    }, indent=2), encoding="utf-8")

    print(RAW)
    print(SUMMARY)


if __name__ == "__main__":
    main()
