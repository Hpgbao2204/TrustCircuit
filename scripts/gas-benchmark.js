const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

function envValue(name, fallback) {
  return process.env[name] || fallback;
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

async function record(rows, base, operation, txPromise) {
  const start = nowMs();
  try {
    const tx = await txPromise;
    const receipt = await tx.wait();
    rows.push({
      ...base,
      operation,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: receipt.gasUsed.toString(),
      tx_hash: receipt.hash,
      success: true,
      error_type: "",
    });
  } catch (error) {
    rows.push({
      ...base,
      operation,
      latency_ms: (nowMs() - start).toFixed(3),
      gas_used: "",
      tx_hash: "",
      success: false,
      error_type: error.shortMessage || error.message,
    });
  }
}

async function runFullIteration(rows, contracts, signers, i, seed) {
  const [provider, consumer] = signers;
  const variant = "TC-Full";
  const suffix = `gas:${variant}:${seed}:${i}`;
  const assetId = ethers.id(`asset:${suffix}`);
  const requestId = ethers.id(`request:${suffix}`);
  const totalBudget = 5_000_000n;
  const epsilonCost = 500_000n;
  const base = {
    run_id: `gas-run-${i}`,
    timestamp: new Date().toISOString(),
    variant,
    request_id: requestId,
    asset_id: assetId,
    seed,
  };

  await record(rows, base, "registerAsset", contracts.registry.registerAsset(
    assetId,
    ethers.id(`metadata:${suffix}`),
    ethers.id(`data:${suffix}`),
    ethers.id("policy:research:aggregate"),
  ));
  await record(rows, base, "registerBudget", contracts.budget.registerBudget(assetId, totalBudget));
  await record(rows, base, "requestAccess", contracts.access.connect(consumer).requestAccess(
    requestId,
    assetId,
    ethers.id("purpose:research"),
    epsilonCost,
  ));
  await record(rows, base, "approveRequest", contracts.access.connect(provider).approveRequest(requestId));
  await record(rows, base, "reserveBudget", contracts.budget.reserveBudget(assetId, requestId, epsilonCost));
  await record(rows, base, "submitProof", contracts.verifier.submitProof(
    requestId,
    assetId,
    ethers.id(`mock-proof:${suffix}`),
    true,
  ));
  await record(rows, base, "consumeBudget", contracts.budget.consumeBudget(assetId, requestId, epsilonCost));
  await record(rows, base, "recordAudit", contracts.audit.recordAudit(
    requestId,
    assetId,
    6,
    ethers.id(`evidence:${suffix}`),
  ));
  await record(rows, base, "completeRequest", contracts.access.completeRequest(requestId));
}

async function runVariantIteration(rows, contracts, signers, variant, i, seed) {
  const [provider, consumer] = signers;
  const suffix = `gas:${variant}:${seed}:${i}`;
  const assetId = ethers.id(`asset:${suffix}`);
  const requestId = ethers.id(`request:${suffix}`);
  const totalBudget = 5_000_000n;
  const epsilonCost = variant === "NoDP" ? 1n : 500_000n;
  const base = {
    run_id: `gas-run-${i}`,
    timestamp: new Date().toISOString(),
    variant,
    request_id: requestId,
    asset_id: assetId,
    seed,
  };

  await record(rows, base, "registerAsset", contracts.registry.registerAsset(
    assetId,
    ethers.id(`metadata:${suffix}`),
    ethers.id(`data:${suffix}`),
    ethers.id("policy:research:aggregate"),
  ));
  await record(rows, base, "requestAccess", contracts.access.connect(consumer).requestAccess(
    requestId,
    assetId,
    ethers.id("purpose:research"),
    epsilonCost,
  ));
  await record(rows, base, "approveRequest", contracts.access.connect(provider).approveRequest(requestId));

  if (variant !== "ACL-Only" && variant !== "NoBudget") {
    await record(rows, base, "registerBudget", contracts.budget.registerBudget(assetId, totalBudget));
    await record(rows, base, "reserveBudget", contracts.budget.reserveBudget(assetId, requestId, epsilonCost));
  }

  if (variant === "TC-Full") {
    await record(rows, base, "submitProof", contracts.verifier.submitProof(
      requestId,
      assetId,
      ethers.id(`mock-proof:${suffix}`),
      true,
    ));
  }

  if (variant !== "ACL-Only" && variant !== "NoBudget") {
    await record(rows, base, "consumeBudget", contracts.budget.consumeBudget(assetId, requestId, epsilonCost));
  }

  await record(rows, base, "recordAudit", contracts.audit.recordAudit(
    requestId,
    assetId,
    6,
    ethers.id(`evidence:${suffix}`),
  ));
  await record(rows, base, "completeRequest", contracts.access.completeRequest(requestId));
}

async function main() {
  const loops = Number(envValue("TC_GAS_RUNS", "100"));
  const seed = Number(envValue("TC_SEED", "42"));
  const outPath = envValue("TC_GAS_OUT", path.join("results", "raw", "contract_gas_benchmark.csv"));
  const progressEvery = Math.max(1, Number(envValue("TC_PROGRESS_EVERY", "25")));
  const variants = envValue("TC_GAS_VARIANTS", "TC-Full,NoZK,NoBudget,ACL-Only,NoDP")
    .split(",")
    .map((variant) => variant.trim())
    .filter(Boolean);
  const contracts = await deployContracts();
  const signers = await ethers.getSigners();
  const rows = [];

  for (const variant of variants) {
    for (let i = 0; i < loops; i += 1) {
      await runVariantIteration(rows, contracts, signers, variant, i, seed);
      if ((i + 1) % progressEvery === 0 || i + 1 === loops) {
        console.log(`completed ${i + 1}/${loops} gas iterations for ${variant}`);
      }
    }
  }

  writeCsv(outPath, rows);
  console.log(outPath);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
