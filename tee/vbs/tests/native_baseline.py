from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from vbs_reference import (
    FIXED_SCALE,
    aes_256_gcm_encrypt,
    build_canonical_aad,
    encode_dataset,
    make_request,
)


VBS_ROOT = Path(__file__).resolve().parents[1]
RESPONSE_FIELDS = {
    "ok",
    "request_id",
    "result",
    "result_fixed",
    "result_hash",
    "actual_privacy_cost_fixed",
    "transcript_hash",
    "enclave_identity",
    "execution_unix_ms",
    "native_attestation_evidence",
    "attestation_evidence",
    "row_count",
    "timings_us",
    "error",
}


class NativeBaselineTests(unittest.TestCase):
    configuration = "Debug"

    @classmethod
    def setUpClass(cls) -> None:
        cls.binary_root = VBS_ROOT / "x64" / cls.configuration
        cls.native = cls.binary_root / "TrustCircuitNative.exe"
        cls.vbs = cls.binary_root / "TrustCircuitHost.exe"
        if not cls.native.is_file() or not cls.vbs.is_file():
            raise unittest.SkipTest("build Native and VBS processors first")

    def _request(self, directory: Path, function_id: int) -> tuple[Path, dict]:
        values = [0, 10, 30, 60, 100]
        plaintext = encode_dataset([value * FIXED_SCALE for value in values])
        payload = directory / "dataset.enc"
        request, _ = make_request(
            payload,
            plaintext,
            function_id,
            0,
            100 * FIXED_SCALE,
            int(time.time() * 1000) + 300_000,
            apply_dp=False,
            key=bytes(range(32)),
            nonce=bytes(range(12)),
        )
        request.update(
            {
                "request_id": f"native-parity-{function_id}",
                "asset_id": "asset-native-parity",
                "consumer_id": "consumer-native-parity",
                "policy_hash": hashlib.sha256(b"native-parity-policy").hexdigest(),
                "policy_version": 1,
            }
        )
        aad = build_canonical_aad(request)
        ciphertext, tag = aes_256_gcm_encrypt(
            bytes.fromhex(request["key_hex"]),
            bytes.fromhex(request["nonce"]),
            aad,
            plaintext,
        )
        request["aad"] = aad.hex()
        request["authentication_tag"] = tag.hex()
        payload.write_bytes(ciphertext)
        request_path = directory / f"request-{function_id}.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path, request

    def _run(self, binary: Path, request_path: Path) -> tuple[int, dict]:
        completed = subprocess.run(
            [str(binary), str(request_path)],
            cwd=self.binary_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return completed.returncode, json.loads(completed.stdout)

    def _assert_parity(self, function_id: int, expected: int) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-native-test-") as temporary:
            request_path, _ = self._request(Path(temporary), function_id)
            native_code, native = self._run(self.native, request_path)
            vbs_code, vbs = self._run(self.vbs, request_path)
            self.assertEqual(native_code, 0)
            self.assertEqual(vbs_code, 0)
            self.assertEqual(set(native), RESPONSE_FIELDS)
            self.assertEqual(set(vbs), RESPONSE_FIELDS)
            self.assertTrue(native["ok"] and vbs["ok"])
            self.assertEqual(native["result_fixed"], expected)
            self.assertEqual(native["result_fixed"], vbs["result_fixed"])
            self.assertEqual(native["result_hash"], vbs["result_hash"])
            self.assertEqual(native["row_count"], vbs["row_count"])
            self.assertEqual(native["actual_privacy_cost_fixed"], 0)
            self.assertEqual(vbs["actual_privacy_cost_fixed"], 0)
            self.assertIsNone(native["native_attestation_evidence"])
            self.assertIsInstance(vbs["native_attestation_evidence"], str)

    def test_count_parity_and_schema(self) -> None:
        self._assert_parity(1, 5 * FIXED_SCALE)

    def test_mean_parity_and_schema(self) -> None:
        self._assert_parity(2, 40 * FIXED_SCALE)

    def test_both_processors_reject_modified_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tc-native-test-") as temporary:
            request_path, request = self._request(Path(temporary), 2)
            tag = bytearray.fromhex(request["authentication_tag"])
            tag[0] ^= 1
            request["authentication_tag"] = tag.hex()
            request_path.write_text(json.dumps(request), encoding="utf-8")
            for binary in (self.native, self.vbs):
                code, response = self._run(binary, request_path)
                self.assertNotEqual(code, 0)
                self.assertFalse(response["ok"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--configuration", default="Debug")
    known, remaining = parser.parse_known_args()
    NativeBaselineTests.configuration = known.configuration
    unittest.main(argv=[__file__, *remaining])
