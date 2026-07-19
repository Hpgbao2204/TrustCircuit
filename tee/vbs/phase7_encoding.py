from __future__ import annotations

import hashlib
import json
import struct
from typing import Any, Mapping


BN254_SCALAR_FIELD = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)
IDENTIFIER_DOMAIN = b"TrustCircuit.SettlementIdentifier.v1\x00"
ATTESTATION_DIGEST_DOMAIN = b"TrustCircuit.ValidatedAttestation.v1\x00"

PUBLIC_SIGNAL_NAMES = (
    "request_id",
    "asset_id",
    "consumer_id",
    "policy_hash",
    "policy_version",
    "function_id",
    "result_hash",
    "actual_privacy_cost_fixed",
    "nullifier",
    "transcript_hash",
    "attestation_digest",
)


class Phase7EncodingError(ValueError):
    pass


def _sized_utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > 0xFFFFFFFF:
        raise Phase7EncodingError("identifier is too long")
    return struct.pack("<I", len(encoded)) + encoded


def _require_sha256_hex(value: object, name: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise Phase7EncodingError(f"{name} must be 64 lowercase hexadecimal characters")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise Phase7EncodingError(f"invalid {name}") from error
    if len(decoded) != 32:
        raise Phase7EncodingError(f"invalid {name} length")
    return decoded


def identifier_digest(field_name: str, value: object) -> bytes:
    if field_name not in {"request_id", "asset_id", "consumer_id"}:
        raise Phase7EncodingError(f"unsupported identifier field: {field_name}")
    if not isinstance(value, str) or not value:
        raise Phase7EncodingError(f"{field_name} must be a non-empty UTF-8 string")
    return hashlib.sha256(
        IDENTIFIER_DOMAIN + _sized_utf8(field_name) + _sized_utf8(value)
    ).digest()


def bytes32_to_field(value: bytes) -> int:
    if len(value) != 32:
        raise Phase7EncodingError("field projection requires exactly 32 bytes")
    return int.from_bytes(value, byteorder="big", signed=False) % BN254_SCALAR_FIELD


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def validated_attestation_digest(statement: Mapping[str, Any]) -> bytes:
    required = {
        "format",
        "validated",
        "transcript_hash",
        "enclave_identity",
        "issued_at_unix_ms",
        "expires_at_unix_ms",
        "validator_identity",
        "evidence_sha256",
        "signature_algorithm",
        "signature",
        "native_verification",
    }
    missing = sorted(required.difference(statement))
    if missing:
        raise Phase7EncodingError(
            "validated attestation is missing: " + ", ".join(missing)
        )
    if statement.get("validated") is not True:
        raise Phase7EncodingError("attestation statement is not validated")
    for name in (
        "transcript_hash",
        "enclave_identity",
        "validator_identity",
        "evidence_sha256",
    ):
        _require_sha256_hex(statement.get(name), name)
    signature = statement.get("signature")
    if not isinstance(signature, str) or len(signature) % 2:
        raise Phase7EncodingError("invalid attestation signature")
    try:
        bytes.fromhex(signature)
    except ValueError as error:
        raise Phase7EncodingError("invalid attestation signature") from error
    return hashlib.sha256(
        ATTESTATION_DIGEST_DOMAIN + canonical_json_bytes(statement)
    ).digest()


def encode_phase7_context(
    request: Mapping[str, Any], execution: Mapping[str, Any]
) -> dict[str, Any]:
    if execution.get("ok") is not True:
        raise Phase7EncodingError("VBS execution did not succeed")
    if execution.get("request_id") != request.get("request_id"):
        raise Phase7EncodingError("execution request ID mismatch")

    statement = execution.get("attestation_evidence")
    if not isinstance(statement, Mapping):
        raise Phase7EncodingError("missing validated attestation statement")
    if statement.get("transcript_hash") != execution.get("transcript_hash"):
        raise Phase7EncodingError("attestation transcript mismatch")
    if statement.get("enclave_identity") != execution.get("enclave_identity"):
        raise Phase7EncodingError("attestation enclave identity mismatch")

    request_key = identifier_digest("request_id", request.get("request_id"))
    asset_key = identifier_digest("asset_id", request.get("asset_id"))
    consumer_key = identifier_digest("consumer_id", request.get("consumer_id"))
    policy_hash = _require_sha256_hex(request.get("policy_hash"), "policy_hash")
    result_hash = _require_sha256_hex(execution.get("result_hash"), "result_hash")
    transcript_hash = _require_sha256_hex(
        execution.get("transcript_hash"), "transcript_hash"
    )
    attestation_digest = validated_attestation_digest(statement)

    policy_version = int(request.get("policy_version", -1))
    function_id = int(request.get("function_id", -1))
    privacy_cost = int(execution.get("actual_privacy_cost_fixed", -1))
    expires_at = int(statement.get("expires_at_unix_ms", -1))
    if not 0 < policy_version <= 0xFFFFFFFFFFFFFFFF:
        raise Phase7EncodingError("policy_version is outside uint64")
    if function_id not in (1, 2):
        raise Phase7EncodingError("function_id must be COUNT (1) or MEAN (2)")
    if not 0 < privacy_cost <= 0xFFFFFFFFFFFFFFFF:
        raise Phase7EncodingError("privacy cost is outside positive uint64")
    if expires_at <= 0:
        raise Phase7EncodingError("invalid attestation expiry")

    fields_without_nullifier = {
        "request_id": bytes32_to_field(request_key),
        "asset_id": bytes32_to_field(asset_key),
        "consumer_id": bytes32_to_field(consumer_key),
        "policy_hash": bytes32_to_field(policy_hash),
        "policy_version": policy_version,
        "function_id": function_id,
        "result_hash": bytes32_to_field(result_hash),
        "actual_privacy_cost_fixed": privacy_cost,
        "transcript_hash": bytes32_to_field(transcript_hash),
        "attestation_digest": bytes32_to_field(attestation_digest),
    }
    return {
        "encoding": "TrustCircuit.Phase7.bn254.v1",
        "scalar_field": str(BN254_SCALAR_FIELD),
        "public_signal_order": list(PUBLIC_SIGNAL_NAMES),
        "request_key": request_key.hex(),
        "asset_key": asset_key.hex(),
        "consumer_key": consumer_key.hex(),
        "policy_hash": policy_hash.hex(),
        "result_hash": result_hash.hex(),
        "transcript_hash": transcript_hash.hex(),
        "attestation_digest": attestation_digest.hex(),
        "attestation_expires_at_unix_ms": expires_at,
        "fields_without_nullifier": {
            key: str(value) for key, value in fields_without_nullifier.items()
        },
    }

