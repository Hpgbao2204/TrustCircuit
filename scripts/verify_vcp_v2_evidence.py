from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "VCP_V2_EVIDENCE.json"


def csv_rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def digest(relative: str) -> str:
    content = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def close(actual: float, expected: float, label: str, tolerance: float = 1e-6) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if digest(item["file"]) != item["sha256"]:
            raise AssertionError(f"hash mismatch: {item['file']}")
        if "rows" in item and len(csv_rows(item["file"])) != item["rows"]:
            raise AssertionError(f"row-count mismatch: {item['file']}")

    metadata = json.loads((ROOT / "zk/vcp_v2_metadata.json").read_text(encoding="utf-8"))
    circuit_claim = manifest["claims"]["circuit"]
    if metadata["public_inputs"] != circuit_claim["public_inputs"]:
        raise AssertionError("public-input count")
    if metadata["dimensions"]["constraints"] != circuit_claim["constraints"]:
        raise AssertionError("constraint count")
    if metadata["dimensions"]["private_inputs"] != circuit_claim["private_inputs"]:
        raise AssertionError("private-input count")
    if metadata["verifier_solidity_sha256"] != digest("contracts/VCPGroth16Verifier.sol"):
        raise AssertionError("metadata/verifier hash binding")

    raw = csv_rows("results/raw/phase8/vcp_v2_runs.csv")
    retained = [row for row in raw if row["is_warmup"] == "0"]
    warmups = [row for row in raw if row["is_warmup"] == "1"]
    claim = manifest["claims"]["groth16_30_run"]
    if len(retained) != claim["repetitions"] or len(warmups) != claim["warmups"]:
        raise AssertionError("warm-up/repetition count")
    if any(row["verified"] != "1" for row in raw):
        raise AssertionError("a retained proof failed verification")
    prove = [float(row["prove_time_ms"]) for row in retained]
    full_prove = [float(row["full_prove_time_ms"]) for row in retained]
    verify = [float(row["verify_time_ms"]) for row in retained]
    gas = [float(row["verifier_gas"]) for row in retained]
    close(statistics.fmean(prove), claim["prove_time_ms_mean"], "prove mean")
    close(percentile(prove, 0.50), claim["prove_time_ms_p50"], "prove p50")
    close(percentile(prove, 0.95), claim["prove_time_ms_p95"], "prove p95")
    close(statistics.fmean(full_prove), claim["full_prove_time_ms_mean"], "full-prove mean")
    close(statistics.fmean(verify), claim["verify_time_ms_mean"], "verify mean")
    close(percentile(gas, 0.50), claim["verifier_gas_p50"], "verifier gas p50")
    close(percentile(gas, 0.95), claim["verifier_gas_p95"], "verifier gas p95")
    for field in ("proof_abi_bytes", "proving_key_bytes", "verification_key_bytes"):
        values = {int(row[field]) for row in retained}
        if values != {claim[field]}:
            raise AssertionError(f"inconsistent {field}: {values}")
    for field in ("proof_json_bytes", "proof_and_public_json_bytes"):
        values = [int(row[field]) for row in retained]
        close(min(values), claim[f"{field}_min"], f"{field} min")
        close(statistics.fmean(values), claim[f"{field}_mean"], f"{field} mean")
        close(percentile(values, 0.50), claim[f"{field}_p50"], f"{field} p50")
        close(percentile(values, 0.95), claim[f"{field}_p95"], f"{field} p95")
        close(max(values), claim[f"{field}_max"], f"{field} max")

    integration = json.loads(
        (ROOT / "results/raw/phase8/vcp_v2_integration.json").read_text(encoding="utf-8")
    )
    integration_claim = manifest["claims"]["real_proof_integration"]
    if not integration["ok"]:
        raise AssertionError("real-proof integration failed")
    for field in (
        "tampered_public_fields_rejected",
        "policy_matrices_verified_with_same_key",
        "atomic_settlements",
    ):
        if integration[field] != integration_claim[field]:
            raise AssertionError(f"integration claim mismatch: {field}")
    if [int(value) for value in integration["settlement_gas"]] != integration_claim["settlement_gas"]:
        raise AssertionError("integration settlement gas")
    if integration["r1cs_sha256"] != metadata["r1cs_sha256"]:
        raise AssertionError("integration/R1CS hash binding")
    if integration["verification_key_sha256"] != metadata["verification_key_sha256"]:
        raise AssertionError("integration/verification-key hash binding")

    testnet_claim = manifest["claims"]["base_sepolia_final_stack"]
    testnet_summary = json.loads(
        (ROOT / "results/summary/base_sepolia_vcp_v2_summary.json").read_text(encoding="utf-8")
    )
    for field in (
        "run_id",
        "chain_id",
        "public_inputs",
        "contract_count",
        "transaction_count",
        "atomic_settlements",
        "final_budget_used",
        "deployment_total_gas",
        "deployment_total_calldata_bytes",
    ):
        if testnet_summary[field] != testnet_claim[field]:
            raise AssertionError(f"Base Sepolia claim mismatch: {field}")
    for summary_group, summary_field, claim_field in (
        ("settlement_gas", "p50", "settlement_gas_p50"),
        ("settlement_gas", "p95", "settlement_gas_p95"),
        ("settlement_fee_micro_eth", "p50", "settlement_fee_micro_eth_p50"),
        ("settlement_fee_micro_eth", "p95", "settlement_fee_micro_eth_p95"),
        ("settlement_inclusion_ms", "p50", "settlement_inclusion_ms_p50"),
        ("settlement_inclusion_ms", "p95", "settlement_inclusion_ms_p95"),
    ):
        close(
            float(testnet_summary[summary_group][summary_field]),
            float(testnet_claim[claim_field]),
            f"Base Sepolia {claim_field}",
        )
    run_root = (
        ROOT
        / "results/raw/phase8/testnet"
        / f"base_sepolia_vcp_v2_{testnet_claim['run_id']}"
    )
    testnet_config = json.loads((run_root / "config.json").read_text(encoding="utf-8"))
    testnet_result = json.loads((run_root / "run_result.json").read_text(encoding="utf-8"))
    transactions = list(csv.DictReader((run_root / "transactions.csv").open(newline="", encoding="utf-8")))
    proofs = list(csv.DictReader((run_root / "proof_preparation.csv").open(newline="", encoding="utf-8")))
    if testnet_config["r1cs_sha256"] != metadata["r1cs_sha256"]:
        raise AssertionError("Base Sepolia/R1CS hash binding")
    if testnet_config["verification_key_sha256"] != metadata["verification_key_sha256"]:
        raise AssertionError("Base Sepolia/verification-key hash binding")
    if any(row["status"] != "1" for row in transactions):
        raise AssertionError("Base Sepolia transaction failure")
    if any(row["verified"] != "1" for row in proofs):
        raise AssertionError("Base Sepolia proof-preparation failure")
    if len(testnet_result["addresses"]) != testnet_claim["contract_count"]:
        raise AssertionError("Base Sepolia deployment address count")

    def operation_values(suffix: str, field: str) -> list[float]:
        return [float(row[field]) for row in transactions if row["operation"].endswith(suffix)]

    access_gas = operation_values("_access", "gas_used")
    approve_gas = operation_values("_approve", "gas_used")
    reserve_gas = operation_values("_reserve", "gas_used")
    settlement_rows = [row for row in transactions if row["operation"].endswith("_settle_vcp_v2")]
    settlement_gas = [float(row["gas_used"]) for row in settlement_rows]
    settlement_inclusion = [float(row["inclusion_latency_ms"]) for row in settlement_rows]
    proof_generation = [float(row["prove_time_ms"]) for row in proofs]
    proof_verification = [float(row["verify_time_ms"]) for row in proofs]
    isolated_verifier_gas = percentile(gas, 0.50)
    authorization_gas = percentile(access_gas, 0.50) + percentile(approve_gas, 0.50)
    reservation_gas = percentile(reserve_gas, 0.50)
    atomic_settlement_gas = percentile(settlement_gas, 0.50)
    assurance = testnet_summary["assurance_gas_envelopes"]
    close(
        assurance["isolated_proof_verification"]["total"],
        isolated_verifier_gas,
        "isolated assurance envelope",
    )
    close(assurance["atomic_settlement"]["total"], atomic_settlement_gas, "atomic assurance envelope")
    close(
        assurance["full_request_lifecycle"]["total"],
        authorization_gas + reservation_gas + atomic_settlement_gas,
        "full lifecycle assurance envelope",
    )
    close(
        assurance["atomic_settlement"]["atomic_state_updates_residual"],
        atomic_settlement_gas - isolated_verifier_gas,
        "atomic settlement residual",
    )
    latency = testnet_summary["proof_settlement_latency_composition_ms"]
    for label, probability in (("p50", 0.50), ("p95", 0.95)):
        expected_prove = percentile(proof_generation, probability)
        expected_verify = percentile(proof_verification, probability)
        expected_inclusion = percentile(settlement_inclusion, probability)
        close(latency[label]["proof_generation_ms"], expected_prove, f"{label} proof generation")
        close(latency[label]["offchain_verification_ms"], expected_verify, f"{label} off-chain verification")
        close(latency[label]["settlement_inclusion_ms"], expected_inclusion, f"{label} settlement inclusion")
        close(
            latency[label]["component_sum_ms"],
            expected_prove + expected_verify + expected_inclusion,
            f"{label} composed latency",
        )

    manuscript = (ROOT / "Paper/main-new.tex").read_text(encoding="utf-8")
    required_manuscript_claims = (
        "$40{,}161$ constraints",
        "$1.007$ s on average",
        "$723$-byte median snarkjs JSON",
        "$374{,}753$ gas at the median",
        "$554{,}496$ gas at the median",
        "$2.964$ s",
        "$6{,}714{,}037$ gas",
        "$29{,}517$ bytes of deployment calldata",
        "$179{,}743$-gas residual",
        "$1{,}036{,}608$-gas median lifecycle",
        "$4.536$ seconds",
    )
    for text in required_manuscript_claims:
        if text not in manuscript:
            raise AssertionError(f"canonical manuscript claim missing: {text}")
    forbidden_legacy_claims = (
        "A two-rule VCP proof requires $176$",
        "generates a $943$-byte VCP proof",
        "requires $255{,}757$ gas for isolated verification",
        "settlement consumes $471{,}163$ gas",
        "$71.1\\%$--$90.3\\%$ lower prover latency",
    )
    for text in forbidden_legacy_claims:
        if text in manuscript:
            raise AssertionError(f"legacy claim remains in manuscript: {text}")
    for figure in (
        "figure_1a_deployment_resources.pdf",
        "figure_1b_assurance_gas.pdf",
        "figure_1c_proof_settlement_latency.pdf",
        "figure_2a_settlement_latency.pdf",
    ):
        figure_path = ROOT / "Paper/Figure/figures/base-sepolia" / figure
        if not figure_path.exists() or figure_path.stat().st_size == 0:
            raise AssertionError(f"missing Base Sepolia manuscript panel: {figure}")

    print(
        f"PASS: VCP v2 evidence verified ({len(retained)} measured runs, "
        f"{integration['tampered_public_fields_rejected']} tamper cases, "
        f"{integration['atomic_settlements']} local atomic settlements, "
        f"{testnet_claim['atomic_settlements']} Base Sepolia settlements)"
    )


if __name__ == "__main__":
    main()
