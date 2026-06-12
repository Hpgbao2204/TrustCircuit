const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

async function record(rows, name, txPromise) {
  const start = process.hrtime.bigint();
  const tx = await txPromise;
  const receipt = await tx.wait();
  const end = process.hrtime.bigint();
  rows.push({
    operation: name,
    tx_hash: receipt.hash,
    gas_used: receipt.gasUsed.toString(),
    latency_ms: (Number(end - start) / 1_000_000).toFixed(3),
    success: true,
  });
}

function writeCsv(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  const body = rows.map((row) => headers.map((header) => row[header]).join(","));
  fs.writeFileSync(filePath, `${headers.join(",")}\n${body.join("\n")}\n`);
}

async function main() {
  const [provider, consumer] = await ethers.getSigners();
  const rows = [];
  const assetId = ethers.id("asset:healthcare:001");
  const requestId = ethers.id("request:001");
  const purposeHash = ethers.id("research:aggregate");
  const metadataHash = ethers.id("metadata:v1");
  const dataHash = ethers.id("data:v1");
  const policyHash = ethers.id("policy:v1");
  const totalBudget = 1_000_000n;
  const epsilonCost = 500_000n;

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

  await record(rows, "registerAsset", registry.registerAsset(assetId, metadataHash, dataHash, policyHash));
  await record(rows, "registerBudget", budget.registerBudget(assetId, totalBudget));
  await record(rows, "requestAccess", access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilonCost));
  await record(rows, "approveRequest", access.connect(provider).approveRequest(requestId));
  await record(rows, "reserveBudget", budget.reserveBudget(assetId, requestId, epsilonCost));
  await record(rows, "submitProof", verifier.submitProof(requestId, assetId, ethers.id("mock-proof:001"), true));
  await record(rows, "consumeBudget", budget.consumeBudget(assetId, requestId, epsilonCost));
  await record(rows, "recordAudit", audit.recordAudit(requestId, assetId, 6, ethers.id("pipeline-complete")));
  await record(rows, "completeRequest", access.completeRequest(requestId));

  writeCsv(path.join("results", "raw", "gas_report.csv"), rows);
  console.log("results/raw/gas_report.csv");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
