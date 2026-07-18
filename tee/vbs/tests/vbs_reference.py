from __future__ import annotations

import math
import ctypes
from ctypes import wintypes
import hashlib
import struct
from decimal import Decimal, ROUND_CEILING
from typing import Iterable


FIXED_SCALE = 1_000_000
DATASET_MAGIC = b"TCVBSDS1"
DATASET_VERSION = 1
MAX_DATASET_ROWS = 100_000
DELTA_FIXED_SCALE = 1_000_000_000_000
REQUEST_DOMAIN = b"TrustCircuit.Request.v1\x00"


class BcryptAuthenticatedCipherModeInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("dwInfoVersion", wintypes.ULONG),
        ("pbNonce", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbNonce", wintypes.ULONG),
        ("pbAuthData", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbAuthData", wintypes.ULONG),
        ("pbTag", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbTag", wintypes.ULONG),
        ("pbMacContext", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbMacContext", wintypes.ULONG),
        ("cbAAD", wintypes.ULONG),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", wintypes.ULONG),
    ]


def _byte_array(value: bytes) -> ctypes.Array[ctypes.c_ubyte]:
    return (ctypes.c_ubyte * len(value)).from_buffer_copy(value)


def _check_ntstatus(status: int, operation: str) -> None:
    if status < 0:
        raise OSError(f"{operation} failed with NTSTATUS 0x{status & 0xffffffff:08x}")


def aes_256_gcm_encrypt(
    key: bytes, nonce: bytes, aad: bytes, plaintext: bytes
) -> tuple[bytes, bytes]:
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("AES-256-GCM requires a 32-byte key and 12-byte nonce")

    bcrypt = ctypes.WinDLL("bcrypt.dll")
    bcrypt.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptSetProperty.restype = ctypes.c_long
    bcrypt.BCryptGetProperty.restype = ctypes.c_long
    bcrypt.BCryptGenerateSymmetricKey.restype = ctypes.c_long
    bcrypt.BCryptEncrypt.restype = ctypes.c_long
    bcrypt.BCryptDestroyKey.restype = ctypes.c_long
    bcrypt.BCryptCloseAlgorithmProvider.restype = ctypes.c_long

    algorithm = ctypes.c_void_p()
    key_handle = ctypes.c_void_p()
    status = bcrypt.BCryptOpenAlgorithmProvider(
        ctypes.byref(algorithm), "AES", None, 0
    )
    _check_ntstatus(status, "BCryptOpenAlgorithmProvider")
    try:
        chaining_mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        status = bcrypt.BCryptSetProperty(
            algorithm,
            "ChainingMode",
            ctypes.cast(chaining_mode, ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.sizeof(chaining_mode),
            0,
        )
        _check_ntstatus(status, "BCryptSetProperty")

        object_length = wintypes.ULONG()
        copied = wintypes.ULONG()
        status = bcrypt.BCryptGetProperty(
            algorithm,
            "ObjectLength",
            ctypes.byref(object_length),
            ctypes.sizeof(object_length),
            ctypes.byref(copied),
            0,
        )
        _check_ntstatus(status, "BCryptGetProperty")
        key_object = (ctypes.c_ubyte * object_length.value)()
        key_bytes = _byte_array(key)
        status = bcrypt.BCryptGenerateSymmetricKey(
            algorithm,
            ctypes.byref(key_handle),
            key_object,
            object_length.value,
            key_bytes,
            len(key),
            0,
        )
        _check_ntstatus(status, "BCryptGenerateSymmetricKey")
        try:
            nonce_bytes = _byte_array(nonce)
            aad_bytes = _byte_array(aad)
            tag_bytes = (ctypes.c_ubyte * 16)()
            plaintext_bytes = _byte_array(plaintext)
            ciphertext_bytes = (ctypes.c_ubyte * len(plaintext))()
            auth = BcryptAuthenticatedCipherModeInfo()
            auth.cbSize = ctypes.sizeof(auth)
            auth.dwInfoVersion = 1
            auth.pbNonce = nonce_bytes
            auth.cbNonce = len(nonce)
            auth.pbAuthData = aad_bytes
            auth.cbAuthData = len(aad)
            auth.pbTag = tag_bytes
            auth.cbTag = len(tag_bytes)
            result_size = wintypes.ULONG()
            status = bcrypt.BCryptEncrypt(
                key_handle,
                plaintext_bytes,
                len(plaintext),
                ctypes.byref(auth),
                None,
                0,
                ciphertext_bytes,
                len(ciphertext_bytes),
                ctypes.byref(result_size),
                0,
            )
            _check_ntstatus(status, "BCryptEncrypt")
            if result_size.value != len(plaintext):
                raise RuntimeError("unexpected AES-GCM ciphertext length")
            return bytes(ciphertext_bytes), bytes(tag_bytes)
        finally:
            if key_handle.value:
                bcrypt.BCryptDestroyKey(key_handle)
    finally:
        if algorithm.value:
            bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


def _sized_utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def build_canonical_aad(request: dict[str, object]) -> bytes:
    data_hash = bytes.fromhex(str(request["data_hash"]))
    if len(data_hash) != 32:
        raise ValueError("data_hash must be SHA-256")
    return b"".join(
        [
            REQUEST_DOMAIN,
            _sized_utf8(str(request["request_id"])),
            _sized_utf8(str(request["asset_id"])),
            _sized_utf8(str(request["consumer_id"])),
            _sized_utf8(str(request["policy_hash"])),
            _sized_utf8(str(request["encrypted_payload_path"])),
            data_hash,
            struct.pack("<Q", int(request["policy_version"])),
            struct.pack("<I", int(request["function_id"])),
            struct.pack("<Q", int(request["epsilon_requested_fixed"])),
            struct.pack("<Q", int(request["delta_requested_fixed"])),
            struct.pack("<q", int(request["lower_bound_fixed"])),
            struct.pack("<q", int(request["upper_bound_fixed"])),
            struct.pack("<Q", int(request["deadline_unix_ms"])),
            bytes([1 if bool(request["apply_dp"]) else 0]),
        ]
    )


def make_request(
    encrypted_payload_path: Path,
    plaintext: bytes,
    function_id: int,
    lower_bound_fixed: int,
    upper_bound_fixed: int,
    deadline_unix_ms: int,
    *,
    apply_dp: bool = False,
    epsilon_requested: float = 0.0,
    epsilon_requested_fixed: int = 0,
    delta_requested: float = 0.0,
    delta_requested_fixed: int = 0,
    key: bytes,
    nonce: bytes,
) -> tuple[dict[str, object], bytes]:
    request: dict[str, object] = {
        "operation": "execute",
        "request_id": "request-phase4",
        "asset_id": "asset-synthetic",
        "consumer_id": "consumer-test",
        "policy_hash": hashlib.sha256(b"phase4-policy").hexdigest(),
        "policy_version": 1,
        "function_id": function_id,
        "epsilon_requested": epsilon_requested,
        "delta_requested": delta_requested,
        "epsilon_requested_fixed": epsilon_requested_fixed,
        "delta_requested_fixed": delta_requested_fixed,
        "encrypted_payload_path": str(encrypted_payload_path.resolve()),
        "key_hex": key.hex(),
        "nonce": nonce.hex(),
        "authentication_tag": "",
        "aad": "",
        "data_hash": hashlib.sha256(plaintext).hexdigest(),
        "lower_bound_fixed": lower_bound_fixed,
        "upper_bound_fixed": upper_bound_fixed,
        "deadline_unix_ms": deadline_unix_ms,
        "apply_dp": apply_dp,
    }
    aad = build_canonical_aad(request)
    ciphertext, tag = aes_256_gcm_encrypt(key, nonce, aad, plaintext)
    request["aad"] = aad.hex()
    request["authentication_tag"] = tag.hex()
    return request, ciphertext


def encode_dataset(values_fixed: Iterable[int]) -> bytes:
    values = list(values_fixed)
    if len(values) > MAX_DATASET_ROWS:
        raise ValueError("too many rows")
    return (
        DATASET_MAGIC
        + struct.pack("<II", DATASET_VERSION, len(values))
        + b"".join(struct.pack("<q", value) for value in values)
    )


def aggregate_reference(function_id: int, values_fixed: list[int]) -> int:
    if function_id == 1:
        return len(values_fixed) * FIXED_SCALE
    if function_id == 2 and values_fixed:
        return math.trunc(sum(values_fixed) / len(values_fixed))
    raise ValueError("invalid query")


def epsilon_to_fixed(value: float) -> int:
    return int(
        (Decimal(str(value)) * Decimal(FIXED_SCALE)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def delta_to_fixed(value: float) -> int:
    return int(
        (Decimal(str(value)) * Decimal(DELTA_FIXED_SCALE)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def gaussian_noise_multiplier(epsilon_fixed: int, delta_fixed: int) -> float:
    epsilon = epsilon_fixed / FIXED_SCALE
    delta = delta_fixed / DELTA_FIXED_SCALE
    return math.sqrt(2.0 * math.log(1.25 / delta)) / epsilon


def rdp_epsilon_reference(epsilon_fixed: int, delta_fixed: int) -> float:
    delta = delta_fixed / DELTA_FIXED_SCALE
    multiplier = gaussian_noise_multiplier(epsilon_fixed, delta_fixed)
    return min(
        alpha / (2.0 * multiplier * multiplier)
        + math.log(1.0 / delta) / (alpha - 1.0)
        for alpha in range(2, 65)
    )


def conservative_privacy_cost_fixed(
    epsilon_fixed: int, delta_fixed: int
) -> int:
    requested = epsilon_fixed / FIXED_SCALE
    accounted = max(
        requested, rdp_epsilon_reference(epsilon_fixed, delta_fixed)
    )
    return math.ceil(accounted * FIXED_SCALE)
