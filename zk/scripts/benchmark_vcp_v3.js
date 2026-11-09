"use strict";

// VCP v3 proof-cost benchmark (TNSE revision, R3.2).
// Same methodology as zk/scripts/benchmark_vcp_v2.js: 2 warm-up + 30 retained
// proofs; prove-only time excludes witness generation; isolated verifier gas is
// the gasUsed of a transaction calling verifyProof. It also runs the
// single-field mutation test over all 24 public signals and checks that two
// distinct policy matrices verify under the same circuit-specific key.
//
// Run: npx hardhat run zk/scripts/benchmark_vcp_v3.js
// Output: results/raw/revision/vcp_v3_runs.csv,
//         results/summary/revision/vcp_v3_summary.json

const fs = require("fs");
const os = require("os");
const path = require("path");
const snarkjs = require("snarkjs");
const { ethers } = require("hardhat");
const enc = require("../../scripts/lib/vcp_v3_encoding");
const { poseidon, toSolidityProof } = require("../../scripts/lib/v3_stack");

const ROOT = path.resolve(__dirname, "..", "..");
const BUILD = path.join(ROOT, "zk", "build", "v3");
const WASM = path.join(BUILD, "vcp_v3_js", "vcp_v3.wasm");
const ZKEY = path.join(BUILD, "vcp_v3_final.zkey");
const VKEY = path.join(BUILD, "vcp_v3_vkey.json");
const METADATA = path.join(ROOT, "zk", "vcp_v3_metadata.json");
const RAW = path.join(ROOT, "results", "raw", "revision", "vcp_v3_runs.csv");
const SUMMARY = path.join(ROOT, "results", "summary", "revision", "vcp_v3_summary.json");
const REPS = Number(process.env.TRUSTCIRCUIT_VCP_REPS || 30);
const WARMUPS = Number(process.env.TRUSTCIRCUIT_VCP_WARMUPS || 2);

const nowMs = () => Number(process.hrtime.bigint()) / 1e6;
const mean = (v) => v.reduce((s, x) => s + x, 0) / v.length;
function quantile(values, q) {
  const s = [...values].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}
function stats(values) {
  const m = mean(values);
  const sd = values.length > 1 ? Math.sqrt(values.reduce((s, x) => s + (x - m) ** 2, 0) / (values.length - 1)) : 0;
  return { mean: m, std: sd, p50: quantile(values, 0.5), p95: quantile(values, 0.95), min: Math.min(...values), max: Math.max(...values) };
}

function context(matrix, purposeId, functionId, tag) {
  return {
    requestKey: ethers.id(`bench:request:${tag}`),
    assetKey: ethers.id("bench:asset"),
    consumerKey: ethers.id("bench:consumer"),
    dataCommitment: enc.saltedDataCommitment(ethers.id("bench:dataset"), enc.randomBytes32()),
    dpConfigHash: enc.dpConfigHash(4_844_805n, 1_000_000n, ethers.id("gaussian:count:v1")),
    freshnessNonce: enc.randomBytes32(),
    policyVersion: 1n,
    purposeId,
    functionId,
    reservedCost: 1_394_200n,
    actualCost: 1_394_200n,
    policyMatrix: matrix,
    policySalt: enc.randomField(),
    contextSalt: enc.randomField(),
    resultOpening: enc.randomField(),
    releasedResult: 4242n,
    enclaveMeasurement: ethers.id("nitro:pcr0:approved"),
  };
}

async function proofInputFor(matrix, purposeId, functionId, tag) {
  const p = await poseidon();
  const ctx = context(matrix, purposeId, functionId, tag);
  const statement = {
    nativeDigest: ethers.id(`native:${tag}`),
    contextCommitment: enc.contextOf(p, ctx),
    expiresAtUnixMs: 4_102_444_800_000n,
    validatorIds: [ethers.id("validator:1"), ethers.id("validator:2")],
    signatures: [`0x${"11".repeat(65)}`, `0x${"22".repeat(65)}`],
  };
  return enc.buildProofInputV3(p, ctx, statement);
}

function writeCsv(file, rows) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(file, `${headers.join(",")}\n${rows.map((r) => headers.map((h) => r[h]).join(",")).join("\n")}\n`);
}

async function main() {
  for (const file of [WASM, ZKEY, VKEY, METADATA]) {
    if (!fs.existsSync(file)) throw new Error(`missing ${file}; run the v3 ceremony first`);
  }
  const metadata = JSON.parse(fs.readFileSync(METADATA, "utf8"));
  const constraints = Number(metadata.r1cs_info.find((l) => l.includes("Constraints")).split(":")[1]);
  const vkey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const Verifier = await ethers.getContractFactory("VCPv3Groth16Verifier");
  const verifier = await Verifier.deploy();
  await verifier.waitForDeployment();
  const [signer] = await ethers.getSigners();
  const proofInput = await proofInputFor([[1n, 1n], [0n, 1n]], 1n, 2n, "main");

  const rows = [];
  let lastProof;
  for (let iteration = 0; iteration < WARMUPS + REPS; iteration += 1) {
    const warmup = iteration < WARMUPS;
    const wtns = path.join(BUILD, `vcp_v3_bench_${iteration}.wtns`);
    let t = nowMs();
    await snarkjs.wtns.calculate(proofInput.input, WASM, wtns);
    const witnessMs = nowMs() - t;
    t = nowMs();
    const { proof, publicSignals } = await snarkjs.groth16.prove(ZKEY, wtns);
    const proveMs = nowMs() - t;
    t = nowMs();
    const ok = await snarkjs.groth16.verify(vkey, publicSignals, proof);
    const verifyMs = nowMs() - t;
    fs.rmSync(wtns, { force: true });
    if (!ok) throw new Error("off-chain verification failed");
    if (publicSignals.join(",") !== proofInput.publicSignals.join(",")) throw new Error("public signal mismatch");
    const sol = toSolidityProof(proof);
    const tx = await signer.sendTransaction({
      to: await verifier.getAddress(),
      data: verifier.interface.encodeFunctionData("verifyProof", [sol.a, sol.b, sol.c, publicSignals]),
    });
    const receipt = await tx.wait();
    if (!(await verifier.verifyProof(sol.a, sol.b, sol.c, publicSignals))) throw new Error("Solidity verifier rejected");
    lastProof = { sol, publicSignals };
    rows.push({
      run: warmup ? iteration : iteration - WARMUPS,
      is_warmup: warmup ? 1 : 0,
      witness_time_ms: witnessMs.toFixed(3),
      prove_time_ms: proveMs.toFixed(3),
      full_prove_time_ms: (witnessMs + proveMs).toFixed(3),
      verify_time_ms: verifyMs.toFixed(3),
      verifier_gas: receipt.gasUsed.toString(),
      proof_json_bytes: Buffer.byteLength(JSON.stringify(proof)),
      proof_and_public_json_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
    });
    process.stdout.write(
      `[vcp-v3] ${warmup ? "warmup" : "run"} ${iteration + 1}/${WARMUPS + REPS} prove ${proveMs.toFixed(1)} ms gas ${receipt.gasUsed}\n`
    );
  }
  writeCsv(RAW, rows);

  // Single-field mutation test over all 24 public signals.
  const mutations = [];
  for (let index = 0; index < 24; index += 1) {
    const mutated = [...lastProof.publicSignals];
    mutated[index] = (BigInt(mutated[index]) + 1n).toString();
    const accepted = await verifier.verifyProof(lastProof.sol.a, lastProof.sol.b, lastProof.sol.c, mutated);
    mutations.push({ index, name: enc.PUBLIC_SIGNAL_NAMES[index], accepted });
  }

  // Two distinct policy matrices that both admit (purpose 1, function 2).
  const policies = [];
  for (const [tag, matrix] of [["policyA", [[1n, 1n], [0n, 1n]]], ["policyB", [[0n, 1n], [1n, 0n]]]]) {
    const input = await proofInputFor(matrix, 1n, 2n, tag);
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(input.input, WASM, ZKEY);
    const sol = toSolidityProof(proof);
    policies.push({
      tag,
      matrix: matrix.map((r) => r.map(String)),
      policy_commitment: input.publicByName.policy_commitment.toString(),
      accepted_offchain: await snarkjs.groth16.verify(vkey, publicSignals, proof),
      accepted_onchain: await verifier.verifyProof(sol.a, sol.b, sol.c, publicSignals),
    });
  }
  // Same matrix, two salts: commitments differ (hiding against enumeration).
  const p = await poseidon();
  const m = [[1n, 1n], [0n, 1n]];
  const saltedDiffer = enc.policyCommitmentV3(p, m, enc.randomField()) !== enc.policyCommitmentV3(p, m, enc.randomField());

  const retained = rows.filter((r) => r.is_warmup === 0);
  const pick = (k) => retained.map((r) => Number(r[k]));
  const summary = {
    schema: "TrustCircuit.VCPv3.Benchmark.v1",
    timestamp_utc: new Date().toISOString(),
    host: { cpu: os.cpus()[0].model, logical_cpus: os.cpus().length, memory_gb: Math.round(os.totalmem() / 2 ** 30), platform: `${os.platform()} ${os.release()}`, node: process.version },
    circuit: metadata.circuit,
    circuit_sha256: metadata.circuit_sha256,
    final_zkey_sha256: metadata.final_zkey_sha256,
    setup_note: metadata.note,
    constraints,
    public_inputs: 24,
    private_inputs: Number(metadata.r1cs_info.find((l) => l.includes("Private")).split(":")[1]),
    warmups: WARMUPS,
    repetitions: REPS,
    witness_time_ms: stats(pick("witness_time_ms")),
    prove_time_ms: stats(pick("prove_time_ms")),
    full_prove_time_ms: stats(pick("full_prove_time_ms")),
    verify_time_ms: stats(pick("verify_time_ms")),
    verifier_gas: stats(pick("verifier_gas")),
    proof_abi_bytes: 256,
    proof_json_bytes: stats(pick("proof_json_bytes")),
    proof_and_public_json_bytes: stats(pick("proof_and_public_json_bytes")),
    proving_key_bytes: fs.statSync(ZKEY).size,
    verification_key_bytes: fs.statSync(VKEY).size,
    mutation_test: { fields: 24, rejected: mutations.filter((m) => !m.accepted).length, detail: mutations },
    policy_family_test: policies,
    salted_policy_commitments_differ: saltedDiffer,
  };
  fs.mkdirSync(path.dirname(SUMMARY), { recursive: true });
  fs.writeFileSync(SUMMARY, `${JSON.stringify(summary, null, 2)}\n`);
  console.log(JSON.stringify({
    constraints,
    prove_mean_ms: summary.prove_time_ms.mean.toFixed(2),
    full_prove_mean_ms: summary.full_prove_time_ms.mean.toFixed(2),
    verify_mean_ms: summary.verify_time_ms.mean.toFixed(2),
    verifier_gas_p50: summary.verifier_gas.p50,
    mutations_rejected: summary.mutation_test.rejected,
    policies: policies.map((x) => x.accepted_onchain),
  }, null, 2));
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  // snarkjs keeps curve worker threads alive; exit explicitly.
  .finally(() => process.exit(process.exitCode || 0));
