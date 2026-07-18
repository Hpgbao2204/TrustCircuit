from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any


COMMON_TRANSCRIPT_FIELDS = (
    "request_id",
    "asset_id",
    "consumer_id",
    "policy_hash",
    "policy_version",
    "function_id",
    "epsilon_requested",
    "delta_requested",
    "epsilon_requested_fixed",
    "delta_requested_fixed",
    "encrypted_payload_path",
    "aad",
    "data_hash",
    "lower_bound_fixed",
    "upper_bound_fixed",
    "deadline_unix_ms",
    "apply_dp",
)


class AttestationValidationError(RuntimeError):
    pass


def _require_hex(value: object, name: str, byte_length: int | None = None) -> str:
    if not isinstance(value, str) or len(value) % 2:
        raise AttestationValidationError(f"invalid {name}")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise AttestationValidationError(f"invalid {name}") from error
    if byte_length is not None and len(decoded) != byte_length:
        raise AttestationValidationError(f"invalid {name} length")
    return value


def build_validation_request(
    request: dict[str, object], execution: dict[str, object]
) -> dict[str, object]:
    validation: dict[str, object] = {"operation": "validate_attestation"}
    for field in COMMON_TRANSCRIPT_FIELDS:
        if field not in request:
            raise AttestationValidationError(f"missing request field: {field}")
        validation[field] = request[field]
    for field in (
        "execution_unix_ms",
        "result_fixed",
        "actual_privacy_cost_fixed",
        "result_hash",
        "transcript_hash",
        "enclave_identity",
        "native_attestation_evidence",
    ):
        if field not in execution:
            raise AttestationValidationError(f"missing execution field: {field}")
        validation[field] = execution[field]
    return validation


def validate_attestation(
    host: Path,
    request: dict[str, object],
    execution: dict[str, object],
    *,
    timeout: float = 30,
    working_directory: Path | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    validation_request = build_validation_request(request, execution)
    if working_directory is None:
        with tempfile.TemporaryDirectory(prefix="trustcircuit-attestation-") as value:
            return validate_attestation(
                host,
                request,
                execution,
                timeout=timeout,
                working_directory=Path(value),
            )

    working_directory.mkdir(parents=True, exist_ok=True)
    validation_path = working_directory / "attestation-validation.json"
    validation_path.write_text(
        json.dumps(validation_request, separators=(",", ":")),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [str(host), str(validation_path)],
        cwd=host.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AttestationValidationError(
            "validator did not emit exactly one JSON response"
        ) from error
    if completed.returncode != 0 or response.get("ok") is not True:
        diagnostic = completed.stderr.strip()
        raise AttestationValidationError(
            "VBS attestation validation failed"
            + (f": {diagnostic}" if diagnostic else "")
        )

    transcript_hash = _require_hex(
        response.get("transcript_hash"), "validated transcript hash", 32
    )
    enclave_identity = _require_hex(
        response.get("enclave_identity"), "validated enclave identity", 32
    )
    if transcript_hash != execution.get("transcript_hash"):
        raise AttestationValidationError("validator returned a different transcript")
    if enclave_identity != execution.get("enclave_identity"):
        raise AttestationValidationError("validator returned a different enclave identity")
    if response.get("request_id") != request.get("request_id"):
        raise AttestationValidationError("validator returned a different request ID")
    _require_hex(response.get("validator_identity"), "validator identity", 32)
    _require_hex(response.get("evidence_sha256"), "evidence hash", 32)
    _require_hex(response.get("signature"), "validator signature")
    if response.get("signature_algorithm") != "RSASSA-PSS-SHA256":
        raise AttestationValidationError("unsupported validator signature algorithm")
    issued_at = response.get("issued_at_unix_ms")
    expires_at = response.get("expires_at_unix_ms")
    if (
        not isinstance(issued_at, int)
        or not isinstance(expires_at, int)
        or issued_at > expires_at
    ):
        raise AttestationValidationError("invalid validator validity interval")

    statement = {
        "format": response["format"],
        "validated": True,
        "transcript_hash": transcript_hash,
        "enclave_identity": enclave_identity,
        "issued_at_unix_ms": issued_at,
        "expires_at_unix_ms": expires_at,
        "validator_identity": response["validator_identity"],
        "evidence_sha256": response["evidence_sha256"],
        "signature_algorithm": response["signature_algorithm"],
        "signature": response["signature"],
        "native_verification": response["native_verification"],
    }
    timings = response.get("timings_us")
    if not isinstance(timings, dict) or not all(
        isinstance(value, int) and value >= 0 for value in timings.values()
    ):
        raise AttestationValidationError("invalid validator timings")
    return statement, timings


def attach_validated_attestation(
    host: Path,
    request: dict[str, object],
    execution: dict[str, Any],
    *,
    working_directory: Path | None = None,
) -> dict[str, Any]:
    statement, validator_timings = validate_attestation(
        host,
        request,
        execution,
        working_directory=working_directory,
    )
    combined = dict(execution)
    combined["attestation_evidence"] = statement
    combined.pop("native_attestation_evidence", None)
    timings = dict(combined.get("timings_us", {}))
    timings["attestation_validation_host"] = validator_timings["host_total"]
    timings["attestation_validation_enclave"] = validator_timings[
        "attestation_validation"
    ]
    combined["timings_us"] = timings
    return combined


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and compress same-machine TrustCircuit VBS evidence."
    )
    parser.add_argument("--host", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--execution", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    execution = json.loads(args.execution.read_text(encoding="utf-8"))
    statement, _ = validate_attestation(args.host, request, execution)
    print(json.dumps(statement, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
