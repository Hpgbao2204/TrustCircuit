from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import struct
import subprocess
import tempfile
import time
import unittest

from vbs_reference import (
    FIXED_SCALE,
    aggregate_reference,
    conservative_privacy_cost_fixed,
    delta_to_fixed,
    encode_dataset,
    epsilon_to_fixed,
    gaussian_noise_multiplier,
    make_request,
)


ARGUMENT_PARSER = argparse.ArgumentParser(add_help=False)
ARGUMENT_PARSER.add_argument("--configuration", default="Debug")
ARGS, UNITTEST_ARGS = ARGUMENT_PARSER.parse_known_args()
RESULT_DOMAIN = b"TrustCircuit.Result.v1\x00"
EPSILON = 1.0
DELTA = 0.00001
EPSILON_FIXED = epsilon_to_fixed(EPSILON)
DELTA_FIXED = delta_to_fixed(DELTA)


class DifferentialPrivacyPipelineTests(unittest.TestCase):
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
        *,
        epsilon: float = EPSILON,
        delta: float = DELTA,
    ) -> tuple[dict[str, object], Path]:
        plaintext = encode_dataset(values)
        ciphertext_path = directory / "dataset.enc"
        request, ciphertext = make_request(
            ciphertext_path,
            plaintext,
            function_id,
            lower,
            upper,
            int(time.time() * 1000) + 120_000,
            apply_dp=True,
            epsilon_requested=epsilon,
            epsilon_requested_fixed=epsilon_to_fixed(epsilon),
            delta_requested=delta,
            delta_requested_fixed=delta_to_fixed(delta),
            key=os.urandom(32),
            nonce=os.urandom(12),
        )
        ciphertext_path.write_bytes(ciphertext)
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request, request_path

    def invoke(
        self, request: dict[str, object], request_path: Path
    ) -> tuple[int, dict[str, object], str]:
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run(
            [str(self.host), str(request_path)],
            cwd=self.host.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        response = json.loads(completed.stdout, parse_float=Decimal)
        return completed.returncode, response, completed.stderr

    @staticmethod
    def result_fixed(response: dict[str, object]) -> int:
        return int(Decimal(response["result"]) * FIXED_SCALE)

    def test_cost_matches_rdp_reference_and_result_hash(self) -> None:
        values = [FIXED_SCALE] * 100
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), values, 1, FIXED_SCALE, FIXED_SCALE
            )
            return_code, response, stderr = self.invoke(request, request_path)
        self.assertEqual(return_code, 0, stderr)
        expected_cost = conservative_privacy_cost_fixed(
            EPSILON_FIXED, DELTA_FIXED
        )
        self.assertEqual(response["actual_privacy_cost_fixed"], expected_cost)
        self.assertGreaterEqual(
            response["actual_privacy_cost_fixed"], EPSILON_FIXED
        )
        result_fixed = self.result_fixed(response)
        expected_hash = hashlib.sha256(
            RESULT_DOMAIN + struct.pack("<q", result_fixed)
        ).hexdigest()
        self.assertEqual(response["result_hash"], expected_hash)
        self.assertEqual(len(response["transcript_hash"]), 64)
        self.assertGreaterEqual(response["timings_us"]["dp_noise"], 0)

    def test_repeated_release_basic_composition(self) -> None:
        values = [FIXED_SCALE] * 50
        releases = 8
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), values, 1, 0, FIXED_SCALE
            )
            costs = []
            outputs = []
            for _ in range(releases):
                return_code, response, stderr = self.invoke(request, request_path)
                self.assertEqual(return_code, 0, stderr)
                costs.append(int(response["actual_privacy_cost_fixed"]))
                outputs.append(self.result_fixed(response))
        single_cost = conservative_privacy_cost_fixed(
            EPSILON_FIXED, DELTA_FIXED
        )
        self.assertEqual(sum(costs), releases * single_cost)
        self.assertGreater(len(set(outputs)), 1)

    def test_count_noise_statistical_utility(self) -> None:
        values = [FIXED_SCALE] * 100
        trials = 32
        results = []
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), values, 1, 0, FIXED_SCALE
            )
            for _ in range(trials):
                return_code, response, stderr = self.invoke(request, request_path)
                self.assertEqual(return_code, 0, stderr)
                results.append(self.result_fixed(response) / FIXED_SCALE)
        true_count = aggregate_reference(1, values) / FIXED_SCALE
        standard_error = gaussian_noise_multiplier(
            EPSILON_FIXED, DELTA_FIXED
        ) / math.sqrt(trials)
        self.assertLess(abs(statistics.mean(results) - true_count), 4 * standard_error)

    def test_mean_query_has_dp_output_and_reference_cost(self) -> None:
        values = [10 * FIXED_SCALE, 20 * FIXED_SCALE, 30 * FIXED_SCALE]
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), values, 2, 0, 40 * FIXED_SCALE
            )
            return_code, response, stderr = self.invoke(request, request_path)
        self.assertEqual(return_code, 0, stderr)
        self.assertTrue(math.isfinite(float(response["result"])))
        self.assertEqual(
            response["actual_privacy_cost_fixed"],
            conservative_privacy_cost_fixed(EPSILON_FIXED, DELTA_FIXED),
        )

    def test_fixed_point_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), [FIXED_SCALE], 1, 0, FIXED_SCALE
            )
            request["epsilon_requested_fixed"] = EPSILON_FIXED - 1
            return_code, response, _ = self.invoke(request, request_path)
        self.assertNotEqual(return_code, 0)
        self.assertFalse(response["ok"])

    def test_zero_epsilon_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary), [FIXED_SCALE], 1, 0, FIXED_SCALE, epsilon=0.0
            )
            return_code, response, _ = self.invoke(request, request_path)
        self.assertNotEqual(return_code, 0)
        self.assertFalse(response["ok"])

    def test_delta_outside_open_unit_interval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request, request_path = self.create_case(
                Path(temporary),
                [FIXED_SCALE],
                1,
                0,
                FIXED_SCALE,
                delta=1.0,
            )
            return_code, response, _ = self.invoke(request, request_path)
        self.assertNotEqual(return_code, 0)
        self.assertFalse(response["ok"])


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS])
