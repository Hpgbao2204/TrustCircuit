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

    print(
        f"PASS: VCP v2 evidence verified ({len(retained)} measured runs, "
        f"{integration['tampered_public_fields_rejected']} tamper cases, "
        f"{integration['atomic_settlements']} atomic settlements)"
    )


if __name__ == "__main__":
    main()
