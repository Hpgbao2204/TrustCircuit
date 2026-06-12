const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { ethers } = require("hardhat");

const DEFAULT_VARIANTS = ["TC-Full", "TC-Full-ZK", "NoZK", "NoBudget", "ACL-Only", "OffChain"];

const ZK_CALLDATA_PATH = path.join(__dirname, "..", "zk", "build", "compliance_2_calldata.txt");
const ZK_SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

// Load the real Groth16 proof/calldata produced by `npm run zk:benchmark`.
// Returns null if the artifact is missing so the runner can skip TC-Full-ZK
// gracefully instead of failing the whole benchmark.
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
  const envName = `TC_${name.replace(/^--/, "").replaceAll("-", "_").toUpperCase()}`;
  if (process.env[envName]) return process.env[envName];
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

function nowMs() {
  const [seconds, nanoseconds] = process.hrtime();
  return seconds * 1000 + nanoseconds / 1e6;
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (text.includes(",") || text.includes('"') || text.includes("\n")) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

function runAggregateWorkload(rows, rounds, seed, withDpNoise) {
  let sum = 0;
  let count = 0;
  let state = BigInt(seed || 1);

  for (let round = 0; round < rounds; round += 1) {
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

function writeCsv(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  const content = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvEscape(row[header])).join(",")),
  ].join("\n");
  fs.writeFileSync(filePath, `${content}\n`);
}

async function deployContracts() {
  const DataRegistry = await ethers.getContractFactory("DataRegistry");
  const AccessController = await ethers.getContractFactory("AccessController");
  const BudgetLedger = await ethers.getContractFactory("BudgetLedger");
  const AuditLedger = await ethers.getContractFactory("AuditLedger");
  const MockComplianceVerifier = await ethers.getContractFactory("MockComplianceVerifier");

  const registry = await DataRegistry.deploy();
  const access = await AccessController.deploy();
  const budget = await BudgetLedger.deploy();
  const audit = await AuditLedger.deploy();
  const verifier = await MockComplianceVerifier.deploy();

  await Promise.all([
    registry.waitForDeployment(),
    access.waitForDeployment(),
    budget.waitForDeployment(),
    audit.waitForDeployment(),
    verifier.waitForDeployment(),
  ]);

  return { registry, access, budget, audit, verifier };
}

// Deploy the real ZK stack: the snarkjs-exported Groth16 verifier plus the
// request-bound ComplianceVerifier adapter used by the TC-Full-ZK variant.
async function deployZkStack() {
  const Groth16Verifier = await ethers.getContractFactory("Groth16Verifier");
  const ComplianceVerifier = await ethers.getContractFactory("ComplianceVerifier");

  const groth16 = await Groth16Verifier.deploy();
  await groth16.waitForDeployment();
  const adapter = await ComplianceVerifier.deploy(await groth16.getAddress());
  await adapter.waitForDeployment();

  return { groth16, adapter };
}

async function recordTx(rows, base, stage, txPromise) {
  const start = nowMs();
  try {
    const tx = await txPromise;
    const receipt = await tx.wait();
    rows.push({
      ...base,
      stage,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: receipt.gasUsed.toString(),
      success: true,
      error_type: "",
    });
  } catch (error) {
    rows.push({
      ...base,
      stage,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: "",
      success: false,
      error_type: error.shortMessage || error.message,
    });
  }
}

async function recordWork(rows, base, stage, fn, gasUsed = "") {
  const start = nowMs();
  try {
    const result = fn();
    rows.push({
      ...base,
      stage,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: gasUsed,
      success: true,
      error_type: "",
      work_digest: typeof result === "string" ? result.slice(0, 18) : "",
    });
  } catch (error) {
    rows.push({
      ...base,
      stage,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: "",
      success: false,
      error_type: error.message,
      work_digest: "",
    });
  }
}

function localBaseWithDigest(base) {
  return {
    ...base,
    work_digest: "",
  };
}

async function recordLocal(rows, base, stage, ms, gasUsed = "") {
  const start = nowMs();
  const end = start + ms;
  while (nowMs() < end) {
    Math.sqrt(end * 17);
  }
  rows.push({
    ...base,
    stage,
    latency_ms: (nowMs() - start).toFixed(3),
    gas_used: gasUsed,
    success: true,
    error_type: "",
    work_digest: "",
  });
}

async function runPipeline({ rows, variant, runIndex, clientCount, seed, teeRows, teeRounds, proveHashRounds }) {
  const [provider, consumer] = await ethers.getSigners();
  const contracts = variant === "OffChain" ? null : await deployContracts();
  const suffix = `${variant}:${runIndex}:${Date.now()}`;
  const assetId = ethers.id(`asset:${suffix}`);
  const requestId = ethers.id(`request:${suffix}`);
  const base = {
    run_id: `run-${runIndex}`,
    timestamp: new Date().toISOString(),
    variant,
    client_count: clientCount,
    request_id: requestId,
    asset_id: assetId,
    seed,
    tee_rows: teeRows,
    tee_rounds: teeRounds,
    prove_hash_rounds: proveHashRounds,
    work_digest: "",
  };

  if (variant === "OffChain") {
    await recordLocal(rows, base, "register_offchain", 1);
    await recordLocal(rows, base, "request_offchain", 1);
    await recordWork(rows, base, "compute_offchain", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, false);
      return runHashWorkload(64, JSON.stringify(result));
    });
    await recordLocal(rows, base, "audit_offchain", 1);
    return;
  }

  // Real end-to-end variant: the compliance stage submits an actual Groth16
  // proof to the on-chain ComplianceVerifier adapter (no mock proof). Ids are
  // derived from the proof's public signals so the binding checks pass.
  if (variant === "TC-Full-ZK") {
    const zk = loadZkCalldata();
    if (!zk) {
      await recordWork(rows, base, "zk_calldata_missing", () => {
        throw new Error("zk/build/compliance_2_calldata.txt not found; run `npm run zk:benchmark`");
      });
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
    const zkPurposeHash = ethers.id("purpose:research");
    const zkMetadataHash = ethers.id(`metadata:zk:${suffix}`);
    const zkDataHash = ethers.id(`data:zk:${suffix}`);
    const zkTotalBudget = 5_000_000n;
    const zkEvidenceHash = ethers.id(`evidence:zk:${suffix}`);

    const zkBase = { ...base, request_id: zkRequestId, asset_id: zkAssetId };
    const { adapter } = await deployZkStack();

    await recordTx(rows, zkBase, "registerAsset", contracts.registry.registerAsset(zkAssetId, zkMetadataHash, zkDataHash, zkPolicyHash));
    await recordTx(rows, zkBase, "requestAccess", contracts.access.connect(consumer).requestAccess(zkRequestId, zkAssetId, zkPurposeHash, epsilonSignal));
    await recordTx(rows, zkBase, "approveRequest", contracts.access.connect(provider).approveRequest(zkRequestId));
    await recordTx(rows, zkBase, "registerBudget", contracts.budget.registerBudget(zkAssetId, zkTotalBudget));
    await recordTx(rows, zkBase, "reserveBudget", contracts.budget.reserveBudget(zkAssetId, zkRequestId, epsilonSignal));

    await recordWork(rows, zkBase, "tee_compute", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, true);
      return runHashWorkload(64, JSON.stringify(result));
    });

    // bind the request to the proof's public commitments, then verify on-chain
    await recordTx(rows, zkBase, "zk_register_expectation",
      adapter.registerExpectation(zkRequestId, assetSignal, consumerSignal, policySignal, zkTotalBudget));
    await recordTx(rows, zkBase, "zk_verify_proof",
      adapter.submitCompliance(zkRequestId, zk.a, zk.b, zk.c, zk.input));

    await recordTx(rows, zkBase, "consumeBudget", contracts.budget.consumeBudget(zkAssetId, zkRequestId, epsilonSignal));
    await recordTx(rows, zkBase, "recordAudit", contracts.audit.recordAudit(zkRequestId, zkAssetId, 6, zkEvidenceHash));
    await recordTx(rows, zkBase, "completeRequest", contracts.access.completeRequest(zkRequestId));
    return;
  }

  const metadataHash = ethers.id(`metadata:${suffix}`);
  const dataHash = ethers.id(`data:${suffix}`);
  const policyHash = ethers.id("policy:research:aggregate");
  const purposeHash = ethers.id("purpose:research");
  const totalBudget = 5_000_000n;
  const epsilonCost = variant === "NoDP" ? 1n : 500_000n;
  const proofHash = ethers.id(`mock-proof:${suffix}`);
  const evidenceHash = ethers.id(`evidence:${suffix}`);

  await recordTx(rows, base, "registerAsset", contracts.registry.registerAsset(assetId, metadataHash, dataHash, policyHash));
  await recordTx(rows, base, "requestAccess", contracts.access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilonCost));
  await recordTx(rows, base, "approveRequest", contracts.access.connect(provider).approveRequest(requestId));

  if (variant !== "ACL-Only" && variant !== "NoBudget") {
    await recordTx(rows, base, "registerBudget", contracts.budget.registerBudget(assetId, totalBudget));
    await recordTx(rows, base, "reserveBudget", contracts.budget.reserveBudget(assetId, requestId, epsilonCost));
  }

  if (variant !== "ACL-Only") {
    await recordWork(rows, base, variant === "NoDP" ? "compute_no_dp" : "tee_compute", () => {
      const result = runAggregateWorkload(teeRows, teeRounds, seed + runIndex, variant !== "NoDP");
      return runHashWorkload(64, JSON.stringify(result));
    });
  }

  if (variant === "TC-Full") {
    await recordWork(rows, base, "mock_prove", () => runHashWorkload(proveHashRounds, `${requestId}:${proofHash}`));
    await recordTx(rows, base, "submitProof", contracts.verifier.submitProof(requestId, assetId, proofHash, true));
  }

  if (variant !== "ACL-Only" && variant !== "NoBudget") {
    await recordTx(rows, base, "consumeBudget", contracts.budget.consumeBudget(assetId, requestId, epsilonCost));
  }

  await recordTx(rows, base, "recordAudit", contracts.audit.recordAudit(requestId, assetId, 6, evidenceHash));
  await recordTx(rows, base, "completeRequest", contracts.access.completeRequest(requestId));
}

async function main() {
  const runs = Number(argValue("--runs", "5"));
  const clientCount = Number(argValue("--clients", "1"));
  const seed = Number(argValue("--seed", "42"));
  const variantArg = argValue("--variants", DEFAULT_VARIANTS.join(","));
  const variants = variantArg.split(",").map((v) => v.trim()).filter(Boolean);
  const outPath = argValue("--out", path.join("results", "raw", "e2e_pipeline.csv"));
  const teeRows = Number(argValue("--tee-rows", "25000"));
  const teeRounds = Number(argValue("--tee-rounds", "3"));
  const proveHashRounds = Number(argValue("--prove-hash-rounds", "20000"));
  const rows = [];

  for (const variant of variants) {
    for (let runIndex = 0; runIndex < runs; runIndex += 1) {
      await runPipeline({ rows, variant, runIndex, clientCount, seed, teeRows, teeRounds, proveHashRounds });
    }
  }

  writeCsv(outPath, rows);
  console.log(outPath);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
