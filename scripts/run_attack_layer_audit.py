from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw" / "phase8"
LAYERS = ("enclave", "attestation_validator", "circuit_adapter", "solidity_settlement")


def run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    return completed.returncode, completed.stdout + completed.stderr


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def main() -> int:
    suites = [
        (
            "phase4",
            [
                "python",
                str(ROOT / "tee/vbs/tests/phase4_encrypted_path.py"),
                "--configuration",
                "Debug",
                "-v",
            ],
        ),
        (
            "phase6",
            [
                "python",
                str(ROOT / "tee/vbs/tests/phase6_attestation.py"),
                "--configuration",
                "Debug",
                "-v",
            ],
        ),
        ("hardhat", ["npm.cmd", "test"]),
    ]
    outputs: dict[str, str] = {}
    suite_metadata: list[dict[str, Any]] = []
    for name, command in suites:
        exit_code, output = run(command)
        if exit_code != 0:
            raise RuntimeError(f"attack-layer source suite failed: {name}\n{output}")
        outputs[name] = output
        suite_metadata.append(
            {
                "name": name,
                "command": command,
                "exit_code": exit_code,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            }
        )

    cases = [
        ("ciphertext_tampering", "enclave", "phase4", "test_ciphertext_tampering_is_rejected"),
        ("nonce_tampering", "enclave", "phase4", "test_nonce_tampering_is_rejected"),
        ("authentication_tag_tampering", "enclave", "phase4", "test_authentication_tag_tampering_is_rejected"),
        ("aad_context_tampering", "enclave", "phase4", "test_aad_tampering_is_rejected"),
        ("committed_hash_tampering", "enclave", "phase4", "test_wrong_committed_data_hash_is_rejected"),
        ("request_id_substitution", "attestation_validator", "phase6", "test_changed_request_id_is_rejected"),
        ("asset_id_substitution", "attestation_validator", "phase6", "test_changed_asset_id_is_rejected"),
        ("consumer_id_substitution", "attestation_validator", "phase6", "test_changed_consumer_id_is_rejected"),
        ("policy_hash_substitution", "attestation_validator", "phase6", "test_changed_policy_hash_is_rejected"),
        ("policy_version_substitution", "attestation_validator", "phase6", "test_changed_policy_version_is_rejected"),
        ("function_id_substitution", "attestation_validator", "phase6", "test_changed_function_id_is_rejected"),
        ("result_hash_substitution", "attestation_validator", "phase6", "test_changed_result_hash_is_rejected"),
        ("transcript_substitution", "attestation_validator", "phase6", "test_substituted_transcript_is_rejected"),
        ("enclave_identity_substitution", "attestation_validator", "phase6", "test_wrong_enclave_identity_is_rejected"),
        ("attestation_substitution", "attestation_validator", "phase6", "test_substituted_native_evidence_is_rejected"),
        ("stale_attestation", "attestation_validator", "phase6", "test_stale_evidence_is_rejected"),
        ("public_asset_mismatch", "circuit_adapter", "hardhat", "rejects wrong asset"),
        ("public_consumer_mismatch", "circuit_adapter", "hardhat", "rejects wrong consumer"),
        ("public_policy_mismatch", "circuit_adapter", "hardhat", "rejects wrong policy"),
        ("public_result_mismatch", "circuit_adapter", "hardhat", "rejects wrong result"),
        ("over_budget", "circuit_adapter", "hardhat", "rejects over-budget settlement"),
        ("proof_tampering", "circuit_adapter", "hardhat", "rejects a tampered Groth16 proof"),
        ("nullifier_replay", "circuit_adapter", "hardhat", "rejects a replay"),
        ("caller_substitution", "solidity_settlement", "hardhat", "rejects a wrong consumer address"),
        ("request_key_substitution", "solidity_settlement", "hardhat", "rejects a wrong request"),
    ]
    rows: list[dict[str, Any]] = []
    for attack_case, first_layer, suite, source_test in cases:
        if source_test not in outputs[suite]:
            raise RuntimeError(
                f"source test result was not observed: {suite}::{source_test}"
            )
        row: dict[str, Any] = {
            "measurement_type": "functional_test_evidence",
            "attack_case": attack_case,
            "first_rejecting_layer": first_layer,
            "source_suite": suite,
            "source_test": source_test,
            "test_passed": 1,
        }
        for layer in LAYERS:
            row[layer] = int(layer == first_layer)
        rows.append(row)

    RAW.mkdir(parents=True, exist_ok=True)
    csv_path = RAW / "attack_binding_matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    config = {
        "schema": "TrustCircuit.AttackLayerAudit.v1",
        "measurement_type": "functional_test_evidence",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": bool(git_value("status", "--porcelain")),
        "platform": platform.platform(),
        "layers": LAYERS,
        "cases": len(rows),
        "suites": suite_metadata,
        "interpretation": (
            "A one marks the earliest layer whose named rejection test passed; "
            "zero cells are not claims that later layers accepted the attack."
        ),
    }
    (RAW / "attack_binding_matrix_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "cases": len(rows), "output": str(csv_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
