from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest


VBS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VBS_ROOT))

from attestation_validator import (  # noqa: E402
    AttestationValidationError,
    validate_attestation,
)
from vbs_reference import (  # noqa: E402
    FIXED_SCALE,
    build_attestation_binding,
    build_canonical_aad,
    build_result_hash,
    build_transcript_hash,
    encode_dataset,
    make_request,
)


ARGUMENT_PARSER = argparse.ArgumentParser(add_help=False)
ARGUMENT_PARSER.add_argument("--configuration", default="Debug")
ARGS, UNITTEST_ARGS = ARGUMENT_PARSER.parse_known_args()


def flip_hex(value: str) -> str:
    replacement = "1" if value[0] != "1" else "2"
    return replacement + value[1:]


class VbsAttestationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = VBS_ROOT / "x64" / ARGS.configuration / "TrustCircuitHost.exe"
        if not cls.host.is_file():
            raise RuntimeError(f"missing host executable: {cls.host}")

    def execute(
        self,
        directory: Path,
        *,
        request_id: str = "request-phase6",
        deadline_unix_ms: int | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        plaintext = encode_dataset([10 * FIXED_SCALE, 20 * FIXED_SCALE])
        ciphertext_path = directory / f"{request_id}.enc"
        request, ciphertext = make_request(
            ciphertext_path,
            plaintext,
            2,
            0,
            100 * FIXED_SCALE,
            deadline_unix_ms or int(time.time() * 1000) + 60_000,
            key=os.urandom(32),
            nonce=os.urandom(12),
        )
        request["request_id"] = request_id
        request["aad"] = build_canonical_aad(request).hex()
        from vbs_reference import aes_256_gcm_encrypt

        ciphertext, tag = aes_256_gcm_encrypt(
            bytes.fromhex(str(request["key_hex"])),
            bytes.fromhex(str(request["nonce"])),
            bytes.fromhex(str(request["aad"])),
            plaintext,
        )
        request["authentication_tag"] = tag.hex()
        ciphertext_path.write_bytes(ciphertext)
        request_path = directory / f"{request_id}.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run(
            [str(self.host), str(request_path)],
            cwd=self.host.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"])
        return request, response

    def validate(
        self,
        directory: Path,
        request: dict[str, object],
        response: dict[str, object],
    ) -> dict[str, object]:
        statement, _ = validate_attestation(
            self.host,
            request,
            response,
            working_directory=directory / "validation",
        )
        return statement

    def assert_validation_rejected(
        self,
        directory: Path,
        request: dict[str, object],
        response: dict[str, object],
    ) -> None:
        with self.assertRaises(AttestationValidationError):
            self.validate(directory, request, response)

    def test_valid_evidence_transcript_and_compact_statement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            statement = self.validate(directory, request, response)

        result_hash = build_result_hash(int(response["result_fixed"]))
        self.assertEqual(result_hash.hex(), response["result_hash"])
        expected_transcript = build_transcript_hash(
            request,
            int(response["execution_unix_ms"]),
            int(response["result_fixed"]),
            int(response["actual_privacy_cost_fixed"]),
            result_hash,
            bytes.fromhex(str(response["enclave_identity"])),
        )
        self.assertEqual(expected_transcript.hex(), response["transcript_hash"])

        native = bytes.fromhex(str(response["native_attestation_evidence"]))
        self.assertGreaterEqual(len(native), 24 + 8 + 64)
        package_size, version, scheme, signed_size, signature_size, reserved = (
            struct.unpack_from("<6I", native)
        )
        self.assertEqual(package_size, len(native))
        self.assertEqual((version, scheme, reserved), (1, 1, 0))
        self.assertGreater(signed_size, 0)
        self.assertGreater(signature_size, 0)
        self.assertEqual(
            native[24 + 8 : 24 + 8 + 64],
            build_attestation_binding(expected_transcript),
        )
        self.assertTrue(statement["validated"])
        self.assertEqual(statement["transcript_hash"], response["transcript_hash"])
        self.assertEqual(statement["enclave_identity"], response["enclave_identity"])
        self.assertEqual(
            statement["evidence_sha256"], hashlib.sha256(native).hexdigest()
        )
        self.assertEqual(statement["signature_algorithm"], "RSASSA-PSS-SHA256")
        self.assertEqual(len(bytes.fromhex(str(statement["signature"]))), 256)

    def test_changed_request_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["request_id"] = "request-substituted"
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_changed_asset_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["asset_id"] = "asset-substituted"
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_changed_consumer_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["consumer_id"] = "consumer-substituted"
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_changed_result_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(response)
            changed["result_hash"] = flip_hex(str(changed["result_hash"]))
            self.assert_validation_rejected(directory, request, changed)

    def test_changed_policy_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["policy_hash"] = hashlib.sha256(b"substituted-policy").hexdigest()
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_changed_policy_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["policy_version"] = int(changed["policy_version"]) + 1
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_changed_function_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(request)
            changed["function_id"] = 1
            changed["aad"] = build_canonical_aad(changed).hex()
            self.assert_validation_rejected(directory, changed, response)

    def test_substituted_transcript_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(response)
            changed["transcript_hash"] = flip_hex(str(changed["transcript_hash"]))
            self.assert_validation_rejected(directory, request, changed)

    def test_wrong_enclave_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory)
            changed = copy.deepcopy(response)
            changed["enclave_identity"] = flip_hex(str(changed["enclave_identity"]))
            self.assert_validation_rejected(directory, request, changed)

    def test_substituted_native_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request, response = self.execute(directory, request_id="first")
            _, substitute = self.execute(directory, request_id="second")
            changed = copy.deepcopy(response)
            changed["native_attestation_evidence"] = substitute[
                "native_attestation_evidence"
            ]
            self.assert_validation_rejected(directory, request, changed)

    def test_stale_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            deadline = int(time.time() * 1000) + 1_500
            request, response = self.execute(
                directory, deadline_unix_ms=deadline
            )
            remaining = (deadline - int(time.time() * 1000)) / 1000
            if remaining > 0:
                time.sleep(remaining + 0.1)
            self.assert_validation_rejected(directory, request, response)


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS])
