from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time

from tests.vbs_reference import (
    FIXED_SCALE,
    delta_to_fixed,
    encode_dataset,
    epsilon_to_fixed,
    make_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Encrypt a synthetic dataset and execute it in the VBS enclave."
    )
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--function", choices=("COUNT", "MEAN"), default="MEAN")
    parser.add_argument("--rows", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260719)
    parser.add_argument("--epsilon", type=float, default=1.0)
    parser.add_argument("--delta", type=float, default=0.00001)
    args = parser.parse_args()
    if args.rows <= 0 or args.rows > 100_000:
        parser.error("--rows must be between 1 and 100000")

    vbs_root = Path(__file__).resolve().parent
    host = vbs_root / "x64" / args.configuration / "TrustCircuitHost.exe"
    if not host.is_file():
        parser.error(f"missing host executable: {host}")

    generator = random.Random(args.seed)
    values = [generator.randint(0, 100) * FIXED_SCALE for _ in range(args.rows)]
    plaintext = encode_dataset(values)
    function_id = 1 if args.function == "COUNT" else 2

    with tempfile.TemporaryDirectory(prefix="trustcircuit-vbs-") as temporary:
        directory = Path(temporary)
        ciphertext_path = directory / "dataset.enc"
        request, ciphertext = make_request(
            ciphertext_path,
            plaintext,
            function_id,
            0,
            100 * FIXED_SCALE,
            int(time.time() * 1000) + 120_000,
            apply_dp=True,
            epsilon_requested=args.epsilon,
            epsilon_requested_fixed=epsilon_to_fixed(args.epsilon),
            delta_requested=args.delta,
            delta_requested_fixed=delta_to_fixed(args.delta),
            key=os.urandom(32),
            nonce=os.urandom(12),
        )
        request["request_id"] = "pipeline-cli"
        from tests.vbs_reference import aes_256_gcm_encrypt, build_canonical_aad

        aad = build_canonical_aad(request)
        ciphertext, tag = aes_256_gcm_encrypt(
            bytes.fromhex(str(request["key_hex"])),
            bytes.fromhex(str(request["nonce"])),
            aad,
            plaintext,
        )
        request["aad"] = aad.hex()
        request["authentication_tag"] = tag.hex()
        ciphertext_path.write_bytes(ciphertext)
        request_path = directory / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run(
            [str(host), str(request_path)],
            cwd=host.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.stderr:
            print(completed.stderr, end="", file=__import__("sys").stderr)
        print(completed.stdout.strip())
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
