/*
 * Experiment 2 (Q1 plan): end-to-end ablation across the TrustCircuit
 * guarantee stack, measured on the local Hardhat EVM with real contracts and a
 * real Groth16 proof.
 *
 * Variants (each removes/adds one guarantee relative to the full pipeline):
 *   OffChain                  - no chain at all (local compute baseline)
 *   ACL-Only                  - registry + access control only
 *   NoBudget                  - + TEE compute + audit, but no privacy budget
 *   NoZK                      - full lifecycle with budget, no compliance proof
 *   TC-Full-MockZK            - full lifecycle + mock proof record
 *   TC-Full-ZK-VerifyOnly     - full lifecycle + on-chain Groth16 verify
 *   TC-Full-ZK-ProveAndVerify - + real off-chain snarkjs proving (timed)
 *
 * Per-stage rows go to results/q1/raw/e2e_ablation.csv. The Python summarizer
 * (summarize_q1.py) aggregates the requested metrics (mean/p95/p99 latency,
 * total gas, proof gas, success rate, throughput).
 *
 * Usage: npx hardhat run benchmarks/e2e_ablation.js -- --runs 50
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const snarkjs = require("snarkjs");
const { ethers } = require("hardhat");

const ROOT = path.resolve(__dirname, "..");
const BUILD = path.join(ROOT, "zk", "build");
const ZK_CALLDATA_PATH = path.join(BUILD, "compliance_2_calldata.txt");
const ZK_ZKEY = path.join(BUILD, "compliance_2_final.zkey");
const ZK_WTNS = path.join(BUILD, "compliance_2_witness.wtns");
const ZK_SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

const DEFAULT_VARIANTS = [
  "OffChain",
  "ACL-Only",
  "NoBudget",
  "NoZK",
  "TC-Full-MockZK",
  "TC-Full-ZK-VerifyOnly",
  "TC-Full-ZK-ProveAndVerify",
];

function loadZkCalldata() {
  try {
    if (!fs.existsSync(ZK_CALLDATA_PATH)) return null;
    const raw = fs.readFileSync(ZK_CALLDATA_PATH, "utf8").trim();
    const [a, b, c, input] = JSON.parse(`[${raw}]`);
    return { a, b, c, input };
  } catch (error) {
    return null;
  }
}

function argValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

function nowMs() {
  const [s, ns] = process.hrtime();
  return s * 1000 + ns / 1e6;
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (text.includes(",") || text.includes('"') || text.includes("\n")) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

function writeCsv(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  const content = [
    headers.join(","),
    ...rows.map((row) => headers.map((h) => csvEscape(row[h])).join(",")),
  ].join("\n");
  fs.writeFileSync(filePath, `${content}\n`);
}

function runAggregateWorkload(rows, rounds, seed, withDpNoise) {
  let sum = 0;
  let count = 0;
  let state = BigInt(seed || 1);
  for (let r = 0; r < rounds; r += 1) {
    for (let i = 0; i < rows; i += 1) {
      state = (state * 1103515245n + 12345n) & 0x7fffffffn;
      const age = 18 + Number(state % 73n);
      const bp = 80 + Number((state / 3n) % 131n);
      if (bp >= 140) count += 1;
      sum += age;
    }
  }
  const meanAge = sum / Math.max(rows * rounds, 1);
  const dpNoise = withDpNoise ? Math.sin(Number(state % 100000n)) * 0.25 : 0;
  return { meanAge: meanAge + dpNoise, count, state: state.toString() };
}

function runHashWorkload(rounds, seedText) {
  let digest = Buffer.from(seedText);
  for (let i = 0; i < rounds; i += 1) {
    digest = crypto.createHash("sha256").update(digest).update(String(i)).digest();
  }
  return `0x${digest.toString("hex")}`;
}

async function recordTx(rows, base, stage, txPromise) {
  const start = nowMs();
  try {
    const tx = await txPromise;
    const receipt = await tx.wait();
    rows.push({ ...base, stage, latency_ms: (nowMs() - start).toFixed(4), gas_used: receipt.gasUsed.toString(), success: true, error_type: "" });
  } catch (error) {
    rows.push({ ...base, stage, latency_ms: (nowMs() - start).toFixed(4), gas_used: "", success: false, error_type: error.shortMessage || error.message });
  }
}

async function recordWork(rows, base, stage, fn) {
  const start = nowMs();
  try {
    fn();
    rows.push({ ...base, stage, latency_ms: (nowMs() - start).toFixed(4), gas_used: "", success: true, error_type: "" });
  } catch (error) {
    rows.push({ ...base, stage, latency_ms: (nowMs() - start).toFixed(4), gas_used: "", success: false, error_type: error.message });
  }
}

function recordLocal(rows, base, stage, ms) {
  const start = nowMs();
  const end = start + ms;
  while (nowMs() < end) Math.sqrt(end * 17);
  rows.push({ ...base, stage, latency_ms: (nowMs() - start).toFixed(4), gas_used: "", success: true, error_type: "" });
}

async function deployCore() {
  const DataRegistry = await ethers.getContractFactory("DataRegistry");
  const AccessController = await ethers.getContractFactory("AccessController");
  const BudgetLedger = await ethers.getContractFactory("BudgetLedger");
  const AuditLedger = await ethers.getContractFactory("AuditLedger");
  const MockComplianceVerifier = await ethers.getContractFactory("MockComplianceVerifier");
  const [registry, access, budget, audit, verifier] = await Promise.all([
    DataRegistry.deploy(), AccessController.deploy(), BudgetLedger.deploy(),
    AuditLedger.deploy(), MockComplianceVerifier.deploy(),
  ]);
  await Promise.all([
    registry.waitForDeployment(), access.waitForDeployment(), budget.waitForDeployment(),
    audit.waitForDeployment(), verifier.waitForDeployment(),
  ]);
  return { registry, access, budget, audit, verifier };
}

async function deployZkAdapter() {
  const Groth16Verifier = await ethers.getContractFactory("Groth16Verifier");
  const ComplianceVerifier = await ethers.getContractFactory("ComplianceVerifier");
  const groth16 = await Groth16Verifier.deploy();
  await groth16.waitForDeployment();
  const adapter = await ComplianceVerifier.deploy(await groth16.getAddress());
  await adapter.waitForDeployment();
  return adapter;
}

const ZK_VARIANTS = new Set(["TC-Full-ZK-VerifyOnly", "TC-Full-ZK-ProveAndVerify"]);

async function runPipeline(ctx) {
  const { rows, variant, runIndex, seed, teeRows, teeRounds, proveHashRounds } = ctx;
  const [provider, consumer] = await ethers.getSigners();
  const suffix = `${variant}:${runIndex}:${Date.now()}:${Math.random()}`;
  const base = {
    run_id: `run-${runIndex}`,
    timestamp: new Date().toISOString(),
    variant,
    request_id: "",
    asset_id: "",
    seed,
  };

  if (variant === "OffChain") {
    recordLocal(rows, base, "register_offchain", 1);
    recordLocal(rows, base, "request_offchain", 1);
    await recordWork(rows, base, "compute_offchain", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, false);
      return runHashWorkload(64, JSON.stringify(result));
    });
    recordLocal(rows, base, "audit_offchain", 1);
    return;
  }

  const contracts = await deployCore();

  if (ZK_VARIANTS.has(variant)) {
    const zk = loadZkCalldata();
    if (!zk) {
      await recordWork(rows, base, "zk_calldata_missing", () => { throw new Error("run npm run zk:benchmark first"); });
      return;
    }
    const assetSignal = BigInt(zk.input[0]);
    const consumerSignal = BigInt(zk.input[1]);
    const requestSignal = BigInt(zk.input[2]);
    const policySignal = BigInt(zk.input[3]);
    const epsilonSignal = BigInt(zk.input[4]);
    const zkAssetId = ethers.zeroPadValue(ethers.toBeHex(assetSignal % ZK_SCALAR_FIELD), 32);
    const zkRequestId = ethers.zeroPadValue(ethers.toBeHex(requestSignal % ZK_SCALAR_FIELD), 32);
    const zkPolicyHash = ethers.zeroPadValue(ethers.toBeHex(policySignal % ZK_SCALAR_FIELD), 32);
    const purposeHash = ethers.id("purpose:research");
    const metadataHash = ethers.id(`metadata:${suffix}`);
    const dataHash = ethers.id(`data:${suffix}`);
    const totalBudget = 5_000_000n;
    const evidenceHash = ethers.id(`evidence:${suffix}`);
    base.request_id = zkRequestId;
    base.asset_id = zkAssetId;
    const adapter = await deployZkAdapter();

    await recordTx(rows, base, "registerAsset", contracts.registry.registerAsset(zkAssetId, metadataHash, dataHash, zkPolicyHash));
    await recordTx(rows, base, "requestAccess", contracts.access.connect(consumer).requestAccess(zkRequestId, zkAssetId, purposeHash, epsilonSignal));
    await recordTx(rows, base, "approveRequest", contracts.access.connect(provider).approveRequest(zkRequestId));
    await recordTx(rows, base, "registerBudget", contracts.budget.registerBudget(zkAssetId, totalBudget));
    await recordTx(rows, base, "reserveBudget", contracts.budget.reserveBudget(zkAssetId, zkRequestId, epsilonSignal));
    await recordWork(rows, base, "tee_compute", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, true);
      return runHashWorkload(64, JSON.stringify(result));
    });

    if (variant === "TC-Full-ZK-ProveAndVerify") {
      // real off-chain Groth16 proving cost (snarkjs over the same circuit).
      const start = nowMs();
      let ok = true;
      try {
        await snarkjs.groth16.prove(ZK_ZKEY, ZK_WTNS);
      } catch (e) {
        ok = false;
      }
      rows.push({ ...base, stage: "zk_prove", latency_ms: (nowMs() - start).toFixed(4), gas_used: "", success: ok, error_type: ok ? "" : "prove_failed" });
    }

    await recordTx(rows, base, "zk_register_expectation", adapter.registerExpectation(zkRequestId, assetSignal, consumerSignal, policySignal, totalBudget));
    await recordTx(rows, base, "zk_verify_proof", adapter.submitCompliance(zkRequestId, zk.a, zk.b, zk.c, zk.input));
    await recordTx(rows, base, "consumeBudget", contracts.budget.consumeBudget(zkAssetId, zkRequestId, epsilonSignal));
    await recordTx(rows, base, "recordAudit", contracts.audit.recordAudit(zkRequestId, zkAssetId, 6, evidenceHash));
    await recordTx(rows, base, "completeRequest", contracts.access.completeRequest(zkRequestId));
    return;
  }

  // mock / no-zk / no-budget / acl-only share the base lifecycle.
  const assetId = ethers.id(`asset:${suffix}`);
  const requestId = ethers.id(`request:${suffix}`);
  base.request_id = requestId;
  base.asset_id = assetId;
  const metadataHash = ethers.id(`metadata:${suffix}`);
  const dataHash = ethers.id(`data:${suffix}`);
  const policyHash = ethers.id("policy:research:aggregate");
  const purposeHash = ethers.id("purpose:research");
  const totalBudget = 5_000_000n;
  const epsilonCost = 500_000n;
  const proofHash = ethers.id(`mock-proof:${suffix}`);
  const evidenceHash = ethers.id(`evidence:${suffix}`);

  await recordTx(rows, base, "registerAsset", contracts.registry.registerAsset(assetId, metadataHash, dataHash, policyHash));
  await recordTx(rows, base, "requestAccess", contracts.access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilonCost));
  await recordTx(rows, base, "approveRequest", contracts.access.connect(provider).approveRequest(requestId));

  const hasBudget = variant !== "ACL-Only" && variant !== "NoBudget";
  if (hasBudget) {
    await recordTx(rows, base, "registerBudget", contracts.budget.registerBudget(assetId, totalBudget));
    await recordTx(rows, base, "reserveBudget", contracts.budget.reserveBudget(assetId, requestId, epsilonCost));
  }

  if (variant !== "ACL-Only") {
    await recordWork(rows, base, "tee_compute", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, true);
      return runHashWorkload(64, JSON.stringify(result));
    });
  }

  if (variant === "TC-Full-MockZK") {
    await recordWork(rows, base, "mock_prove", () => runHashWorkload(proveHashRounds, `${requestId}:${proofHash}`));
    await recordTx(rows, base, "submitProof", contracts.verifier.submitProof(requestId, assetId, proofHash, true));
  }

  if (hasBudget) {
    await recordTx(rows, base, "consumeBudget", contracts.budget.consumeBudget(assetId, requestId, epsilonCost));
  }
  await recordTx(rows, base, "recordAudit", contracts.audit.recordAudit(requestId, assetId, 6, evidenceHash));
  await recordTx(rows, base, "completeRequest", contracts.access.completeRequest(requestId));
}

async function main() {
  const runs = Number(argValue("--runs", "50"));
  const seed = Number(argValue("--seed", "42"));
  const variantArg = argValue("--variants", DEFAULT_VARIANTS.join(","));
  const variants = variantArg.split(",").map((v) => v.trim()).filter(Boolean);
  const outPath = argValue("--out", path.join("results", "q1", "raw", "e2e_ablation.csv"));
  const teeRows = Number(argValue("--tee-rows", "25000"));
  const teeRounds = Number(argValue("--tee-rounds", "3"));
  const proveHashRounds = Number(argValue("--prove-hash-rounds", "20000"));
  const rows = [];

  for (const variant of variants) {
    process.stdout.write(`[e2e] ${variant} `);
    for (let runIndex = 0; runIndex < runs; runIndex += 1) {
      await runPipeline({ rows, variant, runIndex, seed, teeRows, teeRounds, proveHashRounds });
      if (runIndex % 10 === 0) process.stdout.write(".");
    }
    process.stdout.write("\n");
  }

  writeCsv(outPath, rows);
  console.log(outPath);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
