from __future__ import annotations

import hashlib
import json
import struct
from typing import Any, Mapping


BN254_SCALAR_FIELD = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)
IDENTIFIER_DOMAIN = b"TrustCircuit.SettlementIdentifier.v2\x00"
DP_CONFIG_DOMAIN = b"TrustCircuit.DpConfig.v2\x00"
FRESHNESS_DOMAIN = b"TrustCircuit.Freshness.v2\x00"

PUBLIC_SIGNAL_NAMES = (
    "request_id_lo",
    "request_id_hi",
    "asset_id_lo",
    "asset_id_hi",
    "consumer_id_lo",
    "consumer_id_hi",
    "policy_commitment",
    "policy_version",
    "purpose_id",
    "function_id",
    "data_hash_lo",
    "data_hash_hi",
    "dp_config_hash_lo",
    "dp_config_hash_hi",
    "freshness_nonce_lo",
    "freshness_nonce_hi",
    "reserved_cost",
    "actual_cost",
    "nullifier",
    "context_commitment",
    "attestation_hash_lo",
    "attestation_hash_hi",
    "result_commitment",
    "audit_digest",
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


def split_bytes32(value: bytes) -> tuple[int, int]:
    if len(value) != 32:
        raise Phase7EncodingError("limb encoding requires exactly 32 bytes")
    integer = int.from_bytes(value, byteorder="big", signed=False)
    return integer & ((1 << 128) - 1), integer >> 128


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def validate_attestation_shape(statement: Mapping[str, Any]) -> None:
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
    # VCP v2 hashes the Solidity ABI encoding of the complete validator
    # statement with Keccak-256. That final hash is produced by the JS/EVM
    # adapter, not by this Python pre-encoder.


def _derived_dp_config_hash(request: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(
        DP_CONFIG_DOMAIN
        + canonical_json_bytes(
            {
                "epsilon_requested": request.get("epsilon_requested"),
                "delta_requested": request.get("delta_requested"),
                "lower_bound_fixed": request.get("lower_bound_fixed"),
                "upper_bound_fixed": request.get("upper_bound_fixed"),
                "apply_dp": request.get("apply_dp"),
            }
        )
    ).digest()


def _derived_freshness_nonce(request: Mapping[str, Any]) -> bytes:
    explicit = request.get("freshness_nonce")
    if explicit is not None:
        return _require_sha256_hex(explicit, "freshness_nonce")
    nonce = request.get("nonce")
    if isinstance(nonce, str):
        try:
            source = bytes.fromhex(nonce.removeprefix("0x"))
        except ValueError as error:
            raise Phase7EncodingError("invalid nonce") from error
    else:
        request_id = request.get("request_id")
        if not isinstance(request_id, str):
            raise Phase7EncodingError("missing request_id")
        source = _sized_utf8(request_id)
    return hashlib.sha256(FRESHNESS_DOMAIN + source).digest()


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
    validate_attestation_shape(statement)
    data_hash = _require_sha256_hex(request.get("data_hash"), "data_hash")
    dp_config_hash = (
        _require_sha256_hex(request.get("dp_config_hash"), "dp_config_hash")
        if request.get("dp_config_hash") is not None
        else _derived_dp_config_hash(request)
    )
    freshness_nonce = _derived_freshness_nonce(request)
    enclave_measurement = _require_sha256_hex(
        execution.get("enclave_identity"), "enclave_identity"
    )

    policy_version = int(request.get("policy_version", -1))
    purpose_id = int(request.get("purpose_id", -1))
    function_id = int(request.get("function_id", -1))
    reserved_cost = int(request.get("epsilon_requested_fixed", -1))
    privacy_cost = int(execution.get("actual_privacy_cost_fixed", -1))
    expires_at = int(statement.get("expires_at_unix_ms", -1))
    if not 0 < policy_version <= 0xFFFFFFFFFFFFFFFF:
        raise Phase7EncodingError("policy_version is outside uint64")
    if purpose_id not in (1, 2):
        raise Phase7EncodingError("purpose_id must be in the fixed policy family")
    if function_id not in (1, 2):
        raise Phase7EncodingError("function_id must be COUNT (1) or MEAN (2)")
    if not 0 < reserved_cost <= 0xFFFFFFFFFFFFFFFF:
        raise Phase7EncodingError("reserved cost is outside positive uint64")
    if not 0 < privacy_cost <= 0xFFFFFFFFFFFFFFFF:
        raise Phase7EncodingError("privacy cost is outside positive uint64")
    if privacy_cost > reserved_cost:
        raise Phase7EncodingError("actual privacy cost exceeds reservation")
    if expires_at <= 0:
        raise Phase7EncodingError("invalid attestation expiry")

    request_lo, request_hi = split_bytes32(request_key)
    asset_lo, asset_hi = split_bytes32(asset_key)
    consumer_lo, consumer_hi = split_bytes32(consumer_key)
    data_lo, data_hi = split_bytes32(data_hash)
    dp_lo, dp_hi = split_bytes32(dp_config_hash)
    freshness_lo, freshness_hi = split_bytes32(freshness_nonce)
    measurement_lo, measurement_hi = split_bytes32(enclave_measurement)

    fields_without_nullifier = {
        "request_id_lo": request_lo,
        "request_id_hi": request_hi,
        "asset_id_lo": asset_lo,
        "asset_id_hi": asset_hi,
        "consumer_id_lo": consumer_lo,
        "consumer_id_hi": consumer_hi,
        "policy_version": policy_version,
        "purpose_id": purpose_id,
        "function_id": function_id,
        "data_hash_lo": data_lo,
        "data_hash_hi": data_hi,
        "dp_config_hash_lo": dp_lo,
        "dp_config_hash_hi": dp_hi,
        "freshness_nonce_lo": freshness_lo,
        "freshness_nonce_hi": freshness_hi,
        "reserved_cost": reserved_cost,
        "actual_cost": privacy_cost,
    }
    return {
        "encoding": "TrustCircuit.VCP.bn254.v2",
        "scalar_field": str(BN254_SCALAR_FIELD),
        "bytes32_encoding": "u = lo + 2^128 * hi; lo,hi are uint128",
        "public_signal_order": list(PUBLIC_SIGNAL_NAMES),
        "request_key": request_key.hex(),
        "asset_key": asset_key.hex(),
        "consumer_key": consumer_key.hex(),
        "data_hash": data_hash.hex(),
        "dp_config_hash": dp_config_hash.hex(),
        "freshness_nonce": freshness_nonce.hex(),
        "enclave_measurement": enclave_measurement.hex(),
        "enclave_measurement_limbs": {
            "lo": str(measurement_lo),
            "hi": str(measurement_hi),
        },
        "validator_id": statement["validator_identity"],
        "native_digest": statement["evidence_sha256"],
        "validator_signature": statement["signature"],
        "attestation_expires_at_unix_ms": expires_at,
        "derived_by_prover": [
            "policy_commitment",
            "nullifier",
            "context_commitment",
            "attestation_hash_lo",
            "attestation_hash_hi",
            "result_commitment",
            "audit_digest",
        ],
        "fields_without_nullifier": {
            key: str(value) for key, value in fields_without_nullifier.items()
        },
    }
