from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


MAX_BUFFER_BYTES = 1024 * 1024
ARGUMENT_PARSER = argparse.ArgumentParser(add_help=False)
ARGUMENT_PARSER.add_argument("--configuration", default="Debug")
ARGS, UNITTEST_ARGS = ARGUMENT_PARSER.parse_known_args()


class HashBufferTests(unittest.TestCase):
    host: Path

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
        cls.host_dir = cls.host.parent

    def invoke_file(self, payload: bytes) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            stream.write(payload)
            path = Path(stream.name)
        try:
            return subprocess.run(
                [str(self.host), "--hash-file", str(path)],
                cwd=self.host_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            path.unlink(missing_ok=True)

    def assert_hash_matches(self, payload: bytes) -> None:
        completed = self.invoke_file(payload)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            f"Hash = {hashlib.sha256(payload).hexdigest()}",
        )

    def test_empty(self) -> None:
        self.assert_hash_matches(b"")

    def test_small(self) -> None:
        self.assert_hash_matches(b"TrustCircuit HashBuffer")

    def test_maximum(self) -> None:
        self.assert_hash_matches(os.urandom(MAX_BUFFER_BYTES))

    def test_oversized_fails_closed(self) -> None:
        completed = self.invoke_file(os.urandom(MAX_BUFFER_BYTES + 1))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")

    def test_malformed_hex_fails_closed(self) -> None:
        completed = subprocess.run(
            [str(self.host), "--hash-hex", "not-hex"],
            cwd=self.host_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS])
