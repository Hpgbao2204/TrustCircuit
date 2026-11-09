"use strict";

// Interleaved v2/v3 proving-time control on the current host state.
// Purpose: separate the cost of the salted v3 relation from host-level
// variation (power plan, thermal state) relative to the first-round run.
// Does not touch the canonical v2 evidence files.
// Run: node scripts/revision/control_v2_v3_timing.js

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { ethers } = require("ethers");
const { buildPoseidon } = require("circomlibjs");
const v2 = require("../lib/phase7_encoding");
const enc = require("../lib/vcp_v3_encoding");

const ROOT = path.resolve(__dirname, "..", "..");
const ARTIFACTS = {
  v2: { wasm: path.join(ROOT, "zk/build/vcp_v2_js/vcp_v2.wasm"), zkey: path.join(ROOT, "zk/build/vcp_v2_final.zkey") },
  v3: { wasm: path.join(ROOT, "zk/build/v3/vcp_v3_js/vcp_v3.wasm"), zkey: path.join(ROOT, "zk/build/v3/vcp_v3_final.zkey") },
};
const REPS = Number(process.env.REPS || 10);

async function inputs() {
  const poseidon = await buildPoseidon();
  const request = {
    request_id: "control", asset_id: "control-asset", consumer_id: "control-consumer",
    policy_version: 1, purpose_id: 1, function_id: 2,
    data_hash: ethers.id("dataset").slice(2), dp_config_hash: ethers.id("dp").slice(2),
    freshness_nonce: ethers.id("fresh").slice(2), epsilon_requested_fixed: 500_000,
  };
  const execution = {
    ok: true, request_id: "control", actual_privacy_cost_fixed: 400_000, result_fixed: 42,
    enclave_identity: ethers.id("enclave").slice(2),
    attestation_evidence: { validator_id: ethers.id("v"), native_digest: ethers.id("n"), expires_at_unix_ms: 4102444800000n, signature: "11".repeat(65) },
  };
  const v2Input = v2.buildProofInput(request, execution, poseidon, { policyMatrix: [[1n, 1n], [0n, 1n]], resultOpening: 987654321n }).input;
  const ctx = {
    requestKey: ethers.id("control"), assetKey: ethers.id("asset"), consumerKey: ethers.id("consumer"),
    dataCommitment: ethers.id("data"), dpConfigHash: ethers.id("dp"), freshnessNonce: ethers.id("fresh"),
    policyVersion: 1n, purposeId: 1n, functionId: 2n, reservedCost: 500_000n, actualCost: 400_000n,
    policyMatrix: [[1n, 1n], [0n, 1n]], policySalt: enc.randomField(), contextSalt: enc.randomField(),
    resultOpening: enc.randomField(), releasedResult: 42n, enclaveMeasurement: ethers.id("enclave"),
  };
  const statement = { nativeDigest: ethers.id("n"), contextCommitment: enc.contextOf(poseidon, ctx), expiresAtUnixMs: 4102444800000n, validatorIds: [ethers.id("v")], signatures: [`0x${"11".repeat(65)}`] };
  return { v2: v2Input, v3: enc.buildProofInputV3(poseidon, ctx, statement).input };
}

async function main() {
  const input = await inputs();
  const times = { v2: [], v3: [] };
  for (let i = 0; i < REPS + 2; i += 1) {
    for (const version of ["v2", "v3"]) {
      const wtns = path.join(ROOT, "zk", "build", `control_${version}.wtns`);
      await snarkjs.wtns.calculate(input[version], ARTIFACTS[version].wasm, wtns);
      const t = process.hrtime.bigint();
      await snarkjs.groth16.prove(ARTIFACTS[version].zkey, wtns);
      const ms = Number(process.hrtime.bigint() - t) / 1e6;
      fs.rmSync(wtns, { force: true });
      if (i >= 2) times[version].push(ms);
      console.log(`[control] ${version} run ${i + 1}: ${ms.toFixed(1)} ms`);
    }
  }
  const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  const result = { reps: REPS, v2_prove_mean_ms: mean(times.v2), v3_prove_mean_ms: mean(times.v3), ratio_v3_over_v2: mean(times.v3) / mean(times.v2), times };
  fs.mkdirSync(path.join(ROOT, "results/raw/revision"), { recursive: true });
  fs.writeFileSync(path.join(ROOT, "results/raw/revision/control_v2_v3_timing.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ v2: result.v2_prove_mean_ms, v3: result.v3_prove_mean_ms, ratio: result.ratio_v3_over_v2 }));
}

main().catch((e) => { console.error(e); process.exitCode = 1; }).finally(() => process.exit(process.exitCode || 0));
