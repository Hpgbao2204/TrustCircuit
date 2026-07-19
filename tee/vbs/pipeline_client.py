from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
from typing import Any

import psutil

from attestation_validator import attach_validated_attestation
from tests.vbs_reference import (
    FIXED_SCALE,
    aes_256_gcm_encrypt,
    aggregate_reference,
    build_canonical_aad,
    delta_to_fixed,
    encode_dataset,
    epsilon_to_fixed,
    make_request,
)


class VbsPipelineError(RuntimeError):
    pass


def _safe_private_bytes(process: psutil.Process) -> int:
    try:
        full = process.memory_full_info()
        for field in ("private", "uss"):
            value = getattr(full, field, None)
            if isinstance(value, int):
                return value
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    return 0


def _run_with_process_metrics(
    command: list[str], *, cwd: Path, timeout: float
) -> tuple[subprocess.CompletedProcess[str], dict[str, int | float]]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    peak_working_set = 0
    peak_private_bytes = 0
    peak_normalized_cpu_percent = 0.0
    logical_cpus = max(os.cpu_count() or 1, 1)
    monitored = psutil.Process(process.pid)
    previous_sample = started
    previous_cpu_seconds = 0.0
    last_cpu_seconds = 0.0
    sample_count = 0
    while process.poll() is None:
        sampled_at = time.monotonic()
        if sampled_at - started > timeout:
            process.kill()
            process.communicate()
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            memory = monitored.memory_info()
            peak_working_set = max(peak_working_set, int(memory.rss))
            peak_private_bytes = max(
                peak_private_bytes, _safe_private_bytes(monitored)
            )
            cpu_times = monitored.cpu_times()
            last_cpu_seconds = float(cpu_times.user + cpu_times.system)
            interval = sampled_at - previous_sample
            if interval > 0:
                normalized = (
                    (last_cpu_seconds - previous_cpu_seconds)
                    / interval
                    / logical_cpus
                    * 100.0
                )
                peak_normalized_cpu_percent = max(
                    peak_normalized_cpu_percent,
                    min(max(normalized, 0.0), 100.0),
                )
            previous_sample = sampled_at
            previous_cpu_seconds = last_cpu_seconds
            sample_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
        time.sleep(0.001)
    stdout, stderr = process.communicate()
    wall_ms = (time.monotonic() - started) * 1000.0
    return (
        subprocess.CompletedProcess(command, process.returncode, stdout, stderr),
        {
            "wall_ms": wall_ms,
            "process_cpu_time_ms": last_cpu_seconds * 1000.0,
            "normalized_peak_cpu_percent": peak_normalized_cpu_percent,
            "peak_working_set_bytes": peak_working_set,
            "peak_private_bytes": peak_private_bytes,
            "resource_sample_count": sample_count,
        },
    )


def _run_with_peak_rss(
    command: list[str], *, cwd: Path, timeout: float
) -> tuple[subprocess.CompletedProcess[str], int]:
    """Compatibility wrapper for callers that only need working-set RSS."""
    completed, metrics = _run_with_process_metrics(
        command, cwd=cwd, timeout=timeout
    )
    return completed, int(metrics["peak_working_set_bytes"])


def host_path(vbs_root: Path, configuration: str) -> Path:
    if configuration not in {"Debug", "Release"}:
        raise VbsPipelineError("configuration must be Debug or Release")
    value = vbs_root / "x64" / configuration / "TrustCircuitHost.exe"
    if not value.is_file():
        raise VbsPipelineError(f"missing host executable: {value}")
    return value


def execute_synthetic_request(
    *,
    vbs_root: Path,
    configuration: str,
    function_name: str,
    rows: int,
    seed: int,
    epsilon: float,
    delta: float,
    request_id: str,
    asset_id: str,
    consumer_id: str,
    policy_hash: str | None = None,
    policy_version: int = 1,
    processor: str = "vbs",
    validate_attestation_evidence: bool = True,
    timeout: float = 30,
) -> dict[str, Any]:
    if rows <= 0 or rows > 100_000:
        raise VbsPipelineError("rows must be between 1 and 100000")
    if function_name not in {"COUNT", "MEAN"}:
        raise VbsPipelineError("function must be COUNT or MEAN")
    if processor not in {"vbs", "native"}:
        raise VbsPipelineError("processor must be vbs or native")
    if processor == "native" and validate_attestation_evidence:
        raise VbsPipelineError("Native execution has no VBS evidence to validate")
    host = host_path(vbs_root, configuration)
    processor_binary = (
        host
        if processor == "vbs"
        else vbs_root / "x64" / configuration / "TrustCircuitNative.exe"
    )
    if not processor_binary.is_file():
        raise VbsPipelineError(f"missing processor executable: {processor_binary}")
    function_id = 1 if function_name == "COUNT" else 2
    generator = random.Random(seed)

    generation_started = time.perf_counter_ns()
    values = [generator.randint(0, 100) * FIXED_SCALE for _ in range(rows)]
    plaintext = encode_dataset(values)
    generation_us = (time.perf_counter_ns() - generation_started) // 1000
    reference_started = time.perf_counter_ns()
    true_result_fixed = aggregate_reference(function_id, values)
    reference_aggregate_us = (time.perf_counter_ns() - reference_started) // 1000
    python_rss_bytes = psutil.Process().memory_info().rss

    with tempfile.TemporaryDirectory(prefix="trustcircuit-vbs-") as temporary:
        directory = Path(temporary)
        ciphertext_path = directory / "dataset.enc"
        deadline_unix_ms = int(time.time() * 1000) + 300_000
        request, _ = make_request(
            ciphertext_path,
            plaintext,
            function_id,
            0,
            100 * FIXED_SCALE,
            deadline_unix_ms,
            apply_dp=True,
            epsilon_requested=epsilon,
            epsilon_requested_fixed=epsilon_to_fixed(epsilon),
            delta_requested=delta,
            delta_requested_fixed=delta_to_fixed(delta),
            key=os.urandom(32),
            nonce=os.urandom(12),
        )
        request.update(
            {
                "request_id": request_id,
                "asset_id": asset_id,
                "consumer_id": consumer_id,
                "policy_hash": policy_hash
                or hashlib.sha256(b"TrustCircuit.Phase7.Policy.v1").hexdigest(),
                "policy_version": policy_version,
            }
        )

        encryption_started = time.perf_counter_ns()
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
        encryption_us = (time.perf_counter_ns() - encryption_started) // 1000

        request_path = directory / "request.json"
        request_path.write_text(
            json.dumps(request, separators=(",", ":")), encoding="utf-8"
        )
        host_started = time.perf_counter_ns()
        completed, host_process_metrics = _run_with_process_metrics(
            [str(processor_binary), str(request_path)],
            cwd=processor_binary.parent,
            timeout=timeout,
        )
        host_process_us = (time.perf_counter_ns() - host_started) // 1000
        try:
            execution = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise VbsPipelineError(
                "TrustCircuitHost did not emit one JSON response"
            ) from error
        if completed.returncode != 0 or execution.get("ok") is not True:
            diagnostic = completed.stderr.strip()
            raise VbsPipelineError(
                "TrustCircuitHost rejected the request"
                + (f": {diagnostic}" if diagnostic else "")
            )

        validation_us = 0
        validated = execution
        if validate_attestation_evidence:
            validation_started = time.perf_counter_ns()
            validated = attach_validated_attestation(
                host,
                request,
                execution,
                working_directory=directory,
            )
            validation_us = (
                time.perf_counter_ns() - validation_started
            ) // 1000

        public_request = {
            key: value
            for key, value in request.items()
            if key not in {"key_hex"}
        }
        client_timings = {
            "dataset_generation": int(generation_us),
            "reference_aggregate": int(reference_aggregate_us),
            "encryption_and_write": int(encryption_us),
            "host_subprocess_wall": int(host_process_us),
            "attestation_validation_wall": int(validation_us),
        }
        return {
            "request": public_request,
            "execution": validated,
            "reference": {
                "rows": rows,
                "seed": seed,
                "function": function_name,
                "true_result_fixed": true_result_fixed,
                "plaintext_bytes": len(plaintext),
                "ciphertext_bytes": len(ciphertext),
                "python_rss_bytes": python_rss_bytes,
                "host_peak_rss_bytes": int(
                    host_process_metrics["peak_working_set_bytes"]
                ),
                "host_peak_private_bytes": int(
                    host_process_metrics["peak_private_bytes"]
                ),
                "host_process_cpu_time_ms": float(
                    host_process_metrics["process_cpu_time_ms"]
                ),
                "host_normalized_peak_cpu_percent": float(
                    host_process_metrics["normalized_peak_cpu_percent"]
                ),
                "host_resource_sample_count": int(
                    host_process_metrics["resource_sample_count"]
                ),
                "processor": processor,
                "attestation_validated": validate_attestation_evidence,
            },
            "client_timings_us": client_timings,
        }
