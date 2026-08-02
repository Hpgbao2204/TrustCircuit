"use strict";

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const { ethers } = require("hardhat");
const {
  PUBLIC_SIGNAL_NAMES,
  buildProofInput,
} = require("../../scripts/lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..", "..");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "vcp_v2_js", "vcp_v2.wasm");
const ZKEY = path.join(BUILD, "vcp_v2_final.zkey");
const VKEY = path.join(BUILD, "vcp_v2_vkey.json");
const METADATA = path.join(ROOT, "zk", "vcp_v2_metadata.json");
const RAW = path.join(ROOT, "results", "raw", "phase8", "vcp_v2_runs.csv");
const SUMMARY = path.join(ROOT, "results", "summary", "vcp_v2_summary.csv");
const CONFIG = path.join(ROOT, "results", "summary", "vcp_v2_config.json");
const REPS = Number(process.env.TRUSTCIRCUIT_VCP_REPS || 30);
const WARMUPS = Number(process.env.TRUSTCIRCUIT_VCP_WARMUPS || 2);

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

async function timed(label, operation) {
  const started = nowMs();
  process.stdout.write(`[vcp-v2-benchmark] ${label} started\n`);
  const heartbeat = setInterval(() => {
    process.stdout.write(
      `[vcp-v2-benchmark] ${label} still running | elapsed ${((nowMs() - started) / 1000).toFixed(1)} s\n`
    );
  }, 30_000);
  try {
    const result = await operation();
    process.stdout.write(
      `[vcp-v2-benchmark] ${label} complete | elapsed ${((nowMs() - started) / 1000).toFixed(1)} s\n`
    );
    return result;
  } finally {
    clearInterval(heartbeat);
  }
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeCsv(filePath, rows) {
  if (!rows.length) throw new Error(`refusing to write empty CSV: ${filePath}`);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(
    filePath,
    `${headers.join(",")}\n${rows
      .map((row) => headers.map((header) => csvEscape(row[header])).join(","))
      .join("\n")}\n`
  );
}

function mean(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function std(values) {
  if (values.length < 2) return 0;
  const average = mean(values);
  return Math.sqrt(
    values.reduce((sum, value) => sum + (value - average) ** 2, 0) /
      (values.length - 1)
  );
}

function percentile(values, percent) {
  const sorted = [...values].sort((left, right) => left - right);
  const position = ((sorted.length - 1) * percent) / 100;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function stats(values, prefix) {
  return {
    [`${prefix}_mean`]: mean(values),
    [`${prefix}_std`]: std(values),
    [`${prefix}_p50`]: percentile(values, 50),
    [`${prefix}_p95`]: percentile(values, 95),
  };
}

function sizeStats(values, prefix) {
  return {
    [`${prefix}_min`]: Math.min(...values),
    [`${prefix}_mean`]: mean(values),
    [`${prefix}_p50`]: percentile(values, 50),
    [`${prefix}_p95`]: percentile(values, 95),
    [`${prefix}_max`]: Math.max(...values),
  };
}

async function inputForPolicy(poseidon, policyMatrix, purposeId, functionId, suffix) {
  const request = {
    request_id: `vcp-v2-benchmark-${suffix}`,
    asset_id: "vcp-v2-benchmark-asset",
    consumer_id: "vcp-v2-benchmark-consumer",
    policy_version: 1,
    purpose_id: purposeId,
    function_id: functionId,
    data_hash: ethers.id("vcp-v2-dataset").slice(2),
    dp_config_hash: ethers.id("vcp-v2-dp-config").slice(2),
    freshness_nonce: ethers.id(`vcp-v2-freshness-${suffix}`).slice(2),
    epsilon_requested_fixed: 500_000,
  };
  const execution = {
    ok: true,
    request_id: request.request_id,
    actual_privacy_cost_fixed: 400_000,
    result_fixed: 42,
    enclave_identity: ethers.id("vcp-v2-enclave").slice(2),
    attestation_evidence: {
      validator_id: ethers.id("vcp-v2-validator"),
      native_digest: ethers.id(`vcp-v2-native-${suffix}`),
      expires_at_unix_ms: 4_102_444_800_000,
      signature: "01",
    },
  };
  return buildProofInput(request, execution, poseidon, {
    policyMatrix,
    resultOpening: 20260802001n + BigInt(suffix),
  });
}

async function main() {
  if (!Number.isInteger(REPS) || REPS < 1 || !Number.isInteger(WARMUPS) || WARMUPS < 0) {
    throw new Error("repetitions and warm-ups must be non-negative integers");
  }
  for (const required of [WASM, ZKEY, VKEY, METADATA]) {
    if (!fs.existsSync(required)) {
      throw new Error(`missing ${required}; run npm run vcp:build first`);
    }
  }
  const metadata = JSON.parse(fs.readFileSync(METADATA, "utf8"));
  if (metadata.public_inputs !== 24 || PUBLIC_SIGNAL_NAMES.length !== 24) {
    throw new Error("canonical VCP v2 public-input count is not 24");
  }

  const poseidon = await buildPoseidon();
  const proofInput = await inputForPolicy(
    poseidon,
    [[1n, 1n], [0n, 1n]],
    1,
    2,
    1
  );
  const vkey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const Verifier = await ethers.getContractFactory("VCPGroth16Verifier");
  const verifier = await Verifier.deploy();
  await verifier.waitForDeployment();
  const [signer] = await ethers.getSigners();

  const rows = [];
  for (let iteration = 0; iteration < WARMUPS + REPS; iteration += 1) {
    const warmup = iteration < WARMUPS;
    const run = warmup ? iteration : iteration - WARMUPS;
    const runLabel = `${warmup ? "warmup" : "run"} ${run + 1}/${warmup ? WARMUPS : REPS}`;
    const witnessPath = path.join(BUILD, `vcp_v2_benchmark_${iteration}.wtns`);
    const witnessStarted = nowMs();
    await timed(
      `${runLabel} witness generation`,
      () => snarkjs.wtns.calculate(proofInput.input, WASM, witnessPath)
    );
    const witnessMs = nowMs() - witnessStarted;
    const proveStarted = nowMs();
    const { proof, publicSignals } = await timed(
      `${runLabel} Groth16 proving`,
      () => snarkjs.groth16.prove(ZKEY, witnessPath)
    );
    const proveMs = nowMs() - proveStarted;
    const verifyStarted = nowMs();
    const verified = await timed(
      `${runLabel} off-chain verification`,
      () => snarkjs.groth16.verify(vkey, publicSignals, proof)
    );
    const verifyMs = nowMs() - verifyStarted;
    fs.rmSync(witnessPath, { force: true });
    if (!verified) throw new Error(`off-chain verification failed at iteration ${iteration}`);
    if (
      publicSignals.length !== 24 ||
      publicSignals.some((value, index) => value !== proofInput.publicSignals[index])
    ) {
      throw new Error(`public-signal mismatch at iteration ${iteration}`);
    }
    const [a, b, c, signals] = JSON.parse(
      `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
    );
    if (!(await verifier.verifyProof(a, b, c, signals))) {
      throw new Error(`Solidity verifier rejected proof at iteration ${iteration}`);
    }
    const receipt = await timed(`${runLabel} isolated verifier transaction`, async () => {
      const transaction = await signer.sendTransaction({
        to: await verifier.getAddress(),
        data: verifier.interface.encodeFunctionData("verifyProof", [a, b, c, signals]),
      });
      return transaction.wait();
    });
    rows.push({
      measurement_type: "measured_local",
      timestamp_utc: new Date().toISOString(),
      circuit: "vcp_v2_2x2_policy_family",
      scheme: "groth16",
      curve: "bn254",
      run,
      is_warmup: warmup ? 1 : 0,
      public_inputs: publicSignals.length,
      constraints: metadata.dimensions.constraints,
      witness_time_ms: witnessMs,
      prove_time_ms: proveMs,
      full_prove_time_ms: witnessMs + proveMs,
      verify_time_ms: verifyMs,
      verifier_gas: receipt.gasUsed.toString(),
      proof_abi_bytes: 8 * 32,
      proof_json_bytes: Buffer.byteLength(JSON.stringify(proof)),
      proof_and_public_json_bytes: Buffer.byteLength(
        JSON.stringify({ proof, publicSignals })
      ),
      proving_key_bytes: fs.statSync(ZKEY).size,
      verification_key_bytes: fs.statSync(VKEY).size,
      verified: 1,
    });
    process.stdout.write(`[vcp-v2-benchmark] ${runLabel} retained\n`);
  }

  const retained = rows.filter((row) => row.is_warmup === 0);
  const summary = {
    measurement_type: "measured_local",
    circuit: "vcp_v2_2x2_policy_family",
    scheme: "groth16",
    curve: "bn254",
    repetitions: retained.length,
    warmups: WARMUPS,
    public_inputs: 24,
    constraints: metadata.dimensions.constraints,
    ...stats(retained.map((row) => row.witness_time_ms), "witness_time_ms"),
    ...stats(retained.map((row) => row.prove_time_ms), "prove_time_ms"),
    ...stats(retained.map((row) => row.full_prove_time_ms), "full_prove_time_ms"),
    ...stats(retained.map((row) => row.verify_time_ms), "verify_time_ms"),
    ...stats(retained.map((row) => Number(row.verifier_gas)), "verifier_gas"),
    proof_abi_bytes: retained[0].proof_abi_bytes,
    ...sizeStats(retained.map((row) => row.proof_json_bytes), "proof_json_bytes"),
    ...sizeStats(
      retained.map((row) => row.proof_and_public_json_bytes),
      "proof_and_public_json_bytes"
    ),
    proving_key_bytes: retained[0].proving_key_bytes,
    verification_key_bytes: retained[0].verification_key_bytes,
  };
  writeCsv(RAW, rows);
  writeCsv(SUMMARY, [summary]);
  fs.writeFileSync(
    CONFIG,
    `${JSON.stringify({
      schema: "TrustCircuit.VCPBenchmark.v2",
      timestamp_utc: new Date().toISOString(),
      repetitions: REPS,
      warmups: WARMUPS,
      measurement_type: "measured_local",
      proof_size_definitions: {
        proof_abi_bytes: "Groth16 A/B/C only: eight uint256 field elements",
        proof_json_bytes: "snarkjs proof JSON encoded as UTF-8",
        proof_and_public_json_bytes: "snarkjs proof plus all 24 public signals encoded as UTF-8",
      },
      metadata_sha256: sha256File(METADATA),
      r1cs_sha256: metadata.r1cs_sha256,
      verification_key_sha256: metadata.verification_key_sha256,
      verifier_solidity_sha256: metadata.verifier_solidity_sha256,
      node: process.version,
      platform: `${os.platform()} ${os.release()}`,
      cpu: os.cpus()[0]?.model || "unknown",
      logical_cpus: os.cpus().length,
    }, null, 2)}\n`
  );
  console.log(JSON.stringify({ ok: true, raw: RAW, summary: SUMMARY, config: CONFIG }));
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
