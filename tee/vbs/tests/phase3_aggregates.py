from __future__ import annotations

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from vbs_reference import (
    DATASET_MAGIC,
    DATASET_VERSION,
    FIXED_SCALE,
    MAX_DATASET_ROWS,
    aggregate_reference,
    encode_dataset,
)


ARGUMENT_PARSER = argparse.ArgumentParser(add_help=False)
ARGUMENT_PARSER.add_argument("--configuration", default="Debug")
ARGS, UNITTEST_ARGS = ARGUMENT_PARSER.parse_known_args()


class AggregateTests(unittest.TestCase):
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

    def invoke(
        self,
        payload: bytes,
        function_name: str,
        lower: int,
        upper: int,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            stream.write(payload)
            path = Path(stream.name)
        try:
            return subprocess.run(
                [
                    str(self.host),
                    "--aggregate-file",
                    str(path),
                    function_name,
                    str(lower),
                    str(upper),
                ],
                cwd=self.host.parent,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def parse_output(output: str) -> dict[str, int]:
        parsed: dict[str, int] = {}
        for line in output.splitlines():
            key, value = line.split(" = ", 1)
            parsed[key] = int(value)
        return parsed

    def test_count_matches_reference(self) -> None:
        values = [-2 * FIXED_SCALE, 0, 3 * FIXED_SCALE]
        completed = self.invoke(
            encode_dataset(values), "COUNT", -2 * FIXED_SCALE, 3 * FIXED_SCALE
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = self.parse_output(completed.stdout)
        self.assertEqual(output["ResultFixed"], aggregate_reference(1, values))
        self.assertEqual(output["Rows"], len(values))
        self.assertGreaterEqual(output["AggregateUs"], 0)

    def test_mean_matches_reference(self) -> None:
        values = [-2_000_001, 1_000_000, 4_000_000]
        completed = self.invoke(
            encode_dataset(values), "MEAN", -3 * FIXED_SCALE, 5 * FIXED_SCALE
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = self.parse_output(completed.stdout)
        self.assertEqual(output["ResultFixed"], aggregate_reference(2, values))

    def test_empty_count_is_zero(self) -> None:
        completed = self.invoke(encode_dataset([]), "COUNT", 0, 0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.parse_output(completed.stdout)["ResultFixed"], 0)

    def test_empty_mean_fails_closed(self) -> None:
        completed = self.invoke(encode_dataset([]), "MEAN", 0, 0)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")

    def test_out_of_range_value_fails_closed(self) -> None:
        completed = self.invoke(encode_dataset([11]), "COUNT", 0, 10)
        self.assertNotEqual(completed.returncode, 0)

    def test_malformed_magic_fails_closed(self) -> None:
        payload = b"BROKEN!!" + struct.pack("<II", DATASET_VERSION, 0)
        completed = self.invoke(payload, "COUNT", 0, 0)
        self.assertNotEqual(completed.returncode, 0)

    def test_malformed_length_fails_closed(self) -> None:
        payload = DATASET_MAGIC + struct.pack("<IIq", DATASET_VERSION, 2, 7)
        completed = self.invoke(payload, "COUNT", 0, 10)
        self.assertNotEqual(completed.returncode, 0)

    def test_oversized_row_count_fails_closed(self) -> None:
        payload = DATASET_MAGIC + struct.pack(
            "<II", DATASET_VERSION, MAX_DATASET_ROWS + 1
        )
        completed = self.invoke(payload, "COUNT", 0, 0)
        self.assertNotEqual(completed.returncode, 0)

    def test_unknown_function_fails_closed(self) -> None:
        completed = self.invoke(encode_dataset([1]), "SUM", 0, 1)
        self.assertNotEqual(completed.returncode, 0)

    def test_sum_overflow_fails_closed(self) -> None:
        maximum = (1 << 63) - 1
        completed = self.invoke(
            encode_dataset([maximum, maximum]), "MEAN", 0, maximum
        )
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS])
