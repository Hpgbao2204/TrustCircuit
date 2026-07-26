from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PAPER_EVIDENCE.json"


def rows(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def verify_files(manifest: dict) -> None:
    for item in manifest["files"]:
        path = ROOT / item["file"]
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(content).hexdigest()
        if digest != item["sha256"]:
            raise AssertionError(f"hash mismatch: {item['file']}")
        if "rows" in item and len(rows(item["file"])) != item["rows"]:
            raise AssertionError(f"row-count mismatch: {item['file']}")


def verify_profiles() -> None:
    source = rows("results/raw/phase8/e2e_ablation.csv")
    expected = {
        "access_only": (6.3, 159.84, 0.43),
        "no_zk": (148.0, 6.84, 0.69),
        "full_trustcircuit": (378.6, 2.65, 1.37),
    }
    for variant, claim in expected.items():
        selected = [
            row for row in source
            if row["variant"] == variant
            and row["is_warmup"] == "0"
            and row["success"] == "1"
        ]
        latency = statistics.fmean(float(row["total_latency_ms"]) for row in selected)
        throughput = statistics.fmean(float(row["throughput_req_s"]) for row in selected)
        gas = statistics.fmean(float(row["total_gas"]) for row in selected) / 1_000_000
        close(latency, claim[0], 0.06, f"{variant} latency")
        close(throughput, claim[1], 0.01, f"{variant} throughput")
        close(gas, claim[2], 0.006, f"{variant} gas")


def verify_lifecycle_gas() -> None:
    source = {
        row["operation"]: float(row["mean_gas"])
        for row in rows("results/summary/contract_gas_summary.csv")
        if row["variant"] == "TC-Full"
    }
    expected = {
        "registerAsset": 136820,
        "registerBudget": 72568,
        "requestAccess": 136679,
        "approveRequest": 30899,
        "reserveBudget": 120497,
        "submitProof": 25338,
        "consumeBudget": 58775,
        "completeRequest": 30927,
        "recordAudit": 25533,
    }
    for operation, claim in expected.items():
        close(source[operation], claim, 0.51, f"{operation} gas")
    if expected["registerAsset"] + expected["registerBudget"] != 209388:
        raise AssertionError("initialization gas")
    request_path = sum(
        expected[name]
        for name in (
            "requestAccess", "approveRequest", "reserveBudget", "submitProof",
            "consumeBudget", "completeRequest", "recordAudit",
        )
    )
    if request_path != 428648:
        raise AssertionError("request-path gas")


def verify_zk() -> None:
    scaling = {int(row["n_rules"]): row for row in rows("results/summary/zk_benchmark_summary.csv")}
    expected_constraints = {1: 1927, 2: 2444, 4: 3478, 6: 4512, 8: 5546, 10: 6580}
    expected_prove = {1: 155, 2: 176, 4: 167, 6: 260, 8: 354, 10: 386}
    expected_proof = {1: 942, 2: 943, 4: 943, 6: 945, 8: 943, 10: 941}
    for rules, row in scaling.items():
        if int(row["constraints"]) != expected_constraints[rules]:
            raise AssertionError(f"{rules}-rule constraints")
        close(float(row["prove_time_ms_mean"]), expected_prove[rules], 0.51, f"{rules}-rule prove")
        if int(row["proof_size_bytes"]) != expected_proof[rules]:
            raise AssertionError(f"{rules}-rule proof size")

    backends = {row["scheme"]: row for row in rows("results/summary/zk_schemes_summary.csv")}
    close(float(backends["groth16"]["prove_time_ms_mean"]), 176, 0.51, "Groth16 prove")
    close(float(backends["plonk"]["prove_time_ms_mean"]), 3373, 0.51, "PLONK prove")
    close(float(backends["fflonk"]["prove_time_ms_mean"]), 3526, 0.51, "fflonk prove")
    gas = rows("results/summary/zk_onchain_gas.csv")[0]
    if int(gas["verify_gas"]) != 255757:
        raise AssertionError("Groth16 verifier gas")


def verify_dp_cpabe_aes() -> None:
    dp = {
        (row["query"], float(row["epsilon"])): float(row["relative_error_percent_mean"])
        for row in rows("results/summary/dp_utility_summary.csv")
    }
    close(dp[("diabetes_count", 1.0)], 0.044, 0.001, "DP diabetes epsilon=1")
    counts = [
        dp[(query, 0.1)]
        for query in ("diabetes_count", "high_bp_count", "high_cholesterol_count")
    ]
    means = [
        dp[(query, 0.1)]
        for query in ("mean_age", "mean_cholesterol", "mean_systolic_bp")
    ]
    if not (0.39 <= min(counts) <= max(counts) <= 0.48):
        raise AssertionError("DP count range")
    if not (0.08 <= min(means) <= max(means) <= 0.12):
        raise AssertionError("DP mean range")

    cpabe = {
        int(row["policy_attributes"]): row
        for row in rows("results/summary/cpabe_policy_summary.csv")
    }
    close(float(cpabe[5]["full_cpabe_encrypt_ms_mean"]), 51, 0.5, "CP-ABE 5 leaves")
    close(float(cpabe[25]["full_cpabe_encrypt_ms_mean"]), 181, 0.5, "CP-ABE 25 leaves")
    if not 23 <= float(cpabe[5]["full_cpabe_decrypt_ms_mean"]) <= 24:
        raise AssertionError("CP-ABE decrypt")

    aes = {
        int(row["payload_mb"]): row
        for row in rows("results/summary/abe_payload_summary.csv")
    }
    for payload in (128, 256):
        for field in ("enc_throughput_mbps", "dec_throughput_mbps"):
            if not 1300 <= float(aes[payload][field]) <= 1400:
                raise AssertionError(f"AES throughput {payload} MiB {field}")


def verify_nitro_and_attacks() -> None:
    latency = rows("results/raw/nitro_latency.csv")
    if sorted({int(row["payload_mib"]) for row in latency}) != [1, 8, 32, 128]:
        raise AssertionError("Nitro measured payload set")
    if any(sum(int(row["payload_mib"]) == payload for row in latency) != 5 for payload in (1, 8, 32, 128)):
        raise AssertionError("Nitro payload repetitions")

    pool = rows("results/raw/nitro_pool.csv")
    if sorted({int(row["worker_count"]) for row in pool}) != [1, 2, 4]:
        raise AssertionError("Nitro measured worker set")
    projections = rows("results/summary/nitro_pool_projection_summary.csv")
    source = {int(row["worker_count"]): row["source"] for row in projections}
    if any(source[count] != "measured" for count in (1, 2, 4)):
        raise AssertionError("Nitro measured labels")
    if any(source[count] != "projected" for count in (8, 16, 32, 64)):
        raise AssertionError("Nitro projection labels")

    attestation = rows("results/summary/nitro_attestation_summary.csv")[0]
    close(float(attestation["attestation_median_ms"]), 1.879, 0.001, "Nitro attestation")

    attacks = rows("results/raw/tee_attack_trials.csv")
    if len(attacks) != 1500:
        raise AssertionError("protocol deviation trials")
    config = json.loads((ROOT / "results/summary/tee_attack_config.json").read_text(encoding="utf-8"))
    if config["note"] != "TEE attack simulation only; not real SGX.":
        raise AssertionError("protocol deviation classification")


def verify_testnet_and_sota() -> None:
    transactions = rows(
        "results/raw/phase8/testnet/base_sepolia_full_20260722T173930848Z/transactions.csv"
    )
    deployments = [row for row in transactions if row["category"] == "deployment"]
    deployment_groups: dict[str, list[dict[str, str]]] = {}
    for row in deployments:
        deployment_groups.setdefault(row["operation"], []).append(row)
    deployment_gas = sum(
        statistics.median(float(row["gas_used"]) for row in group)
        for group in deployment_groups.values()
    )
    deployment_calldata = sum(
        statistics.median(float(row["calldata_bytes"]) for row in group)
        for group in deployment_groups.values()
    )
    close(deployment_gas, 4256636, 0.1, "Base deployment gas")
    close(deployment_calldata, 18791, 0.1, "Base deployment calldata")

    valid = [row for row in transactions if row["operation"] == "atomic_settlement_valid"]
    gas = [float(row["gas_used"]) for row in valid]
    close(statistics.median(gas), 471163, 0.1, "Base valid median gas")
    close(percentile(gas, 0.95), 471187, 0.1, "Base valid p95 gas")
    inclusion = [float(row["inclusion_latency_ms"]) / 1000 for row in valid]
    close(statistics.median(inclusion), 3.72, 0.01, "Base inclusion")
    fee = [float(row["total_fee_wei"]) / 1e12 for row in valid]
    close(statistics.median(fee), 2.8641, 0.0001, "Base fee")

    reached = 100 * (1 - (47 / 48) ** 128)
    close(reached, 93.24, 0.01, "SOTA field-space reach")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    verify_files(manifest)
    verify_profiles()
    verify_lifecycle_gas()
    verify_zk()
    verify_dp_cpabe_aes()
    verify_nitro_and_attacks()
    verify_testnet_and_sota()
    print(f"PASS: {len(manifest['files'])} evidence files and all paper claims verified")


if __name__ == "__main__":
    main()
