from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from vbs_reference import (
    FIXED_SCALE,
    aes_256_gcm_encrypt,
    aggregate_reference,
    build_canonical_aad,
    encode_dataset,
    make_request,
)


ARGUMENT_PARSER = argparse.ArgumentParser(add_help=False)
ARGUMENT_PARSER.add_argument("--configuration", default="Debug")
ARGS, UNITTEST_ARGS = ARGUMENT_PARSER.parse_known_args()
MAX_ENCRYPTED_PAYLOAD_BYTES = 16 + 100_000 * 8


def flip_hex(value: str) -> str:
    replacement = "1" if value[0] != "1" else "2"
    return replacement + value[1:]


class EncryptedPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = (
            Path(__file__).resolve().parents[1]
            / "x64"
            / ARGS.configuration
            / "TrustCircuitHost.exe"
        )
        if not cls.host.is_file():
            raise RuntimeError(f"missing host executable: {cls.host}")

    def create_case(
        self,
        directory: Path,
        values: list[int],
        function_id: int,
        lower: int,
        upper: int,
    ) -> tuple[dict[str, object], Path, Path]:
        plaintext = encode_dataset(values)
        ciphertext_path = directory / "dataset.enc"
        request, ciphertext = make_request(
            ciphertext_path,
            plaintext,
            function_id,
            lower,
            upper,
            int(time.time() * 1000) + 60_000,
            key=os.urandom(32),
            nonce=os.urandom(12),
        )
        ciphertext_path.write_bytes(ciphertext)
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request, request_path, ciphertext_path

    def invoke(
        self, request: dict[str, object], request_path: Path
    ) -> tuple[int, dict[str, object], str]:
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = __import__("subprocess").run(
            [str(self.host), str(request_path)],
            cwd=self.host.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        return completed.returncode, json.loads(completed.stdout), completed.stderr

    def assert_rejected(
        self, request: dict[str, object], request_path: Path
    ) -> None:
        return_code, response, _ = self.invoke(request, request_path)
        self.assertNotEqual(return_code, 0)
        self.assertFalse(response["ok"])

    def test_valid_count_and_response_schema(self) -> None:
        values = [1 * FIXED_SCALE, 2 * FIXED_SCALE, 3 * FIXED_SCALE]
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, _ = self.create_case(
                Path(temporary), values, 1, FIXED_SCALE, 3 * FIXED_SCALE
            )
            return_code, response, stderr = self.invoke(request, request_path)
        self.assertEqual(return_code, 0, stderr)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"], aggregate_reference(1, values) / FIXED_SCALE)
        self.assertEqual(response["actual_privacy_cost_fixed"], 0)
        self.assertEqual(len(response["result_hash"]), 64)
        self.assertEqual(len(response["transcript_hash"]), 64)
        for stage in (
            "host_total",
            "process_startup",
            "enclave_call",
            "decrypt",
            "hash",
            "aggregate",
            "dp_noise",
            "transcript",
            "attestation",
        ):
            self.assertGreaterEqual(response["timings_us"][stage], 0)

    def test_valid_mean_matches_reference(self) -> None:
        values = [-2_000_001, 1_000_000, 4_000_000]
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, _ = self.create_case(
                Path(temporary), values, 2, -3 * FIXED_SCALE, 5 * FIXED_SCALE
            )
            return_code, response, stderr = self.invoke(request, request_path)
        self.assertEqual(return_code, 0, stderr)
        self.assertEqual(
            response["result"], aggregate_reference(2, values) / FIXED_SCALE
        )

    def test_ciphertext_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, ciphertext_path = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            ciphertext = bytearray(ciphertext_path.read_bytes())
            ciphertext[-1] ^= 1
            ciphertext_path.write_bytes(ciphertext)
            self.assert_rejected(request, request_path)

    def test_nonce_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, _ = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            request["nonce"] = flip_hex(str(request["nonce"]))
            self.assert_rejected(request, request_path)

    def test_authentication_tag_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, _ = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            request["authentication_tag"] = flip_hex(
                str(request["authentication_tag"])
            )
            self.assert_rejected(request, request_path)

    def test_aad_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, _ = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            request["aad"] = flip_hex(str(request["aad"]))
            self.assert_rejected(request, request_path)

    def test_wrong_committed_data_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, ciphertext_path = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            request["data_hash"] = "00" * 32
            aad = build_canonical_aad(request)
            ciphertext, tag = aes_256_gcm_encrypt(
                bytes.fromhex(str(request["key_hex"])),
                bytes.fromhex(str(request["nonce"])),
                aad,
                encode_dataset([1]),
            )
            request["aad"] = aad.hex()
            request["authentication_tag"] = tag.hex()
            ciphertext_path.write_bytes(ciphertext)
            self.assert_rejected(request, request_path)

    def test_malformed_ciphertext_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, ciphertext_path = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            ciphertext_path.write_bytes(ciphertext_path.read_bytes()[:-1])
            self.assert_rejected(request, request_path)

    def test_oversized_ciphertext_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path, ciphertext_path = self.create_case(
                Path(temporary), [1], 1, 0, 1
            )
            ciphertext_path.write_bytes(b"\x00" * (MAX_ENCRYPTED_PAYLOAD_BYTES + 1))
            self.assert_rejected(request, request_path)


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS])
