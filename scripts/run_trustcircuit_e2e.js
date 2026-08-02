"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const { ethers } = require("hardhat");
const {
  PUBLIC_SIGNAL_NAMES,
  buildProofInput,
} = require("./lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "vcp_v2_js", "vcp_v2.wasm");
const ZKEY = path.join(BUILD, "vcp_v2_final.zkey");
const VKEY = path.join(BUILD, "vcp_v2_vkey.json");

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

function requirePath(name, fallback) {
  const value = process.env[name] || fallback;
  if (!value) throw new Error(`missing ${name}`);
  return path.resolve(ROOT, value);
}

function hex(buffer) {
  return ethers.hexlify(buffer);
}

async function deploy(name, stageMetrics, ...args) {
  const started = nowMs();
  const factory = await ethers.getContractFactory(name);
  const contract = await factory.deploy(...args);
  const receipt = await contract.deploymentTransaction().wait();
  stageMetrics.push({
    stage: `deploy_${name}`,
    latency_ms: nowMs() - started,
    gas_used: receipt.gasUsed.toString(),
    success: true,
  });
  return contract;
}

async function transact(stageMetrics, stage, transactionPromise) {
  const started = nowMs();
  const transaction = await transactionPromise;
  const receipt = await transaction.wait();
  stageMetrics.push({
    stage,
    latency_ms: nowMs() - started,
    gas_used: receipt.gasUsed.toString(),
    success: receipt.status === 1,
  });
  return receipt;
}

async function main() {
  const bundlePath = requirePath("TRUSTCIRCUIT_PHASE7_BUNDLE");
  const outputPath = requirePath(
    "TRUSTCIRCUIT_PHASE7_OUTPUT",
    path.join("results", "raw", "e2e", "latest", "settlement.json")
  );
  for (const required of [bundlePath, WASM, ZKEY, VKEY]) {
    if (!fs.existsSync(required)) throw new Error(`missing required artifact: ${required}`);
  }
  const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
  if (bundle.schema !== "TrustCircuit.VCPBundle.v2") {
    throw new Error("unsupported VCP bundle schema");
  }
  if (bundle.execution?.attestation_evidence?.validated !== true) {
    throw new Error("bundle does not contain validated native evidence");
  }

  const totalStarted = nowMs();
  const stageMetrics = [];
  const [provider, consumer, validator] = await ethers.getSigners();

  const registry = await deploy("DataRegistry", stageMetrics);
  const access = await deploy("AccessController", stageMetrics);
  const budget = await deploy("BudgetLedger", stageMetrics);
  const audit = await deploy("AuditLedger", stageMetrics);
  const validatorRegistry = await deploy("ValidatorRegistry", stageMetrics);
  const nativeVerifier = await deploy("VCPGroth16Verifier", stageMetrics);
  const adapter = await deploy(
    "ComplianceVerifier",
    stageMetrics,
    await nativeVerifier.getAddress()
  );
  const settlement = await deploy(
    "TrustCircuitSettlement",
    stageMetrics,
    await registry.getAddress(),
    await access.getAddress(),
    await budget.getAddress(),
    await adapter.getAddress(),
    await audit.getAddress(),
    await validatorRegistry.getAddress()
  );

  const settlementAddress = await settlement.getAddress();
  for (const [stage, module] of [
    ["grant_access_coordinator", access],
    ["grant_budget_coordinator", budget],
    ["grant_audit_coordinator", audit],
    ["grant_verifier_coordinator", adapter],
  ]) {
    await transact(stageMetrics, stage, module.setCoordinator(settlementAddress, true));
  }

  const poseidon = await buildPoseidon();
  const witness = {
    policyMatrix: [[1n, 1n], [0n, 1n]],
    resultOpening: 20260719001n,
  };
  const preliminary = buildProofInput(
    bundle.request,
    bundle.execution,
    poseidon,
    witness
  );
  const nativeStatement = bundle.execution.attestation_evidence;
  const validatorId = `0x${nativeStatement.validator_identity}`;
  const unsignedStatement = {
    validatorId,
    nativeDigest: `0x${nativeStatement.evidence_sha256}`,
    contextCommitment: preliminary.values.contextCommitment,
    expiresAtUnixMs: BigInt(nativeStatement.expires_at_unix_ms),
    signature: "0x",
  };
  await transact(
    stageMetrics,
    "activate_validator",
    validatorRegistry.activateValidator(validatorId, validator.address)
  );
  const payload = await validatorRegistry.statementPayload(unsignedStatement);
  const attestationStatement = {
    ...unsignedStatement,
    signature: await validator.signMessage(ethers.getBytes(payload)),
  };
  const proofInput = buildProofInput(bundle.request, bundle.execution, poseidon, {
    ...witness,
    attestationStatement,
  });

  for (const [name, encoded] of Object.entries(
    bundle.phase7.fields_without_nullifier
  )) {
    if (proofInput.publicByName[name] !== BigInt(encoded)) {
      throw new Error(`Python/JavaScript VCP encoding mismatch for ${name}`);
    }
  }

  const proofStarted = nowMs();
  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    proofInput.input,
    WASM,
    ZKEY
  );
  stageMetrics.push({
    stage: "groth16_prove",
    latency_ms: nowMs() - proofStarted,
    gas_used: "0",
    success: true,
  });
  if (
    publicSignals.length !== PUBLIC_SIGNAL_NAMES.length ||
    publicSignals.some((value, index) => value !== proofInput.publicSignals[index])
  ) {
    throw new Error("prover returned a different canonical public-signal vector");
  }
  const verificationKey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const verifyStarted = nowMs();
  const verifiedOffchain = await snarkjs.groth16.verify(
    verificationKey,
    publicSignals,
    proof
  );
  stageMetrics.push({
    stage: "groth16_verify_offchain",
    latency_ms: nowMs() - verifyStarted,
    gas_used: "0",
    success: verifiedOffchain,
  });
  if (!verifiedOffchain) throw new Error("off-chain Groth16 verification failed");
  const [a, b, c, signals] = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );

  const values = proofInput.values;
  const requestKey = hex(values.requestKey);
  const assetKey = hex(values.assetKey);
  const consumerKey = hex(values.consumerKey);
  const dataHash = hex(values.dataHash);
  const dpConfigHash = hex(values.dpConfigHash);
  const freshnessNonce = hex(values.freshnessNonce);
  const purposeHash = ethers.id("TrustCircuit.Purpose.Research.v2");
  const deadline = BigInt(bundle.request.deadline_unix_ms);

  await transact(
    stageMetrics,
    "register_asset",
    registry.connect(provider).registerAssetVCP(
      assetKey,
      ethers.id("TrustCircuit.Metadata.v2"),
      dataHash,
      values.policyCommitment,
      values.policyVersion
    )
  );
  await transact(
    stageMetrics,
    "register_budget",
    budget.registerBudget(assetKey, values.reservedCost * 10n)
  );
  await transact(
    stageMetrics,
    "request_access",
    access.connect(consumer).requestAccessVCP(
      requestKey,
      assetKey,
      consumerKey,
      purposeHash,
      values.purposeId,
      values.policyCommitment,
      values.policyVersion,
      values.functionId,
      dpConfigHash,
      freshnessNonce,
      values.reservedCost,
      deadline
    )
  );
  await transact(stageMetrics, "approve_request", access.approveRequest(requestKey));
  await transact(
    stageMetrics,
    "reserve_budget",
    settlement.reserveBudgetForRequest(requestKey)
  );
  const evidence = {
    resultCommitment: values.resultCommitment,
    auditDigest: values.auditDigest,
    attestation: attestationStatement,
  };
  const settlementReceipt = await transact(
    stageMetrics,
    "atomic_settlement",
    settlement.connect(consumer).settle(requestKey, evidence, a, b, c, signals)
  );

  const budgetState = await budget.getBudget(assetKey);
  const requestState = await access.getRequest(requestKey);
  const nullifierUsed = await adapter.nullifierUsed(values.nullifier);
  const auditEvents = settlementReceipt.logs
    .map((log) => {
      try {
        return audit.interface.parseLog(log);
      } catch {
        return null;
      }
    })
    .filter((event) => event?.name === "VCPSettlementAuditRecorded");
  if (
    requestState.status !== 5n ||
    !nullifierUsed ||
    budgetState.used !== values.actualCost ||
    budgetState.reserved !== 0n ||
    auditEvents.length !== 1
  ) {
    throw new Error("post-settlement state invariant failed");
  }

  const result = {
    schema: "TrustCircuit.VCPE2E.v2",
    measurement_type: "functional_validation_not_paper_benchmark",
    ok: true,
    timestamp: new Date().toISOString(),
    request_key: requestKey,
    asset_key: assetKey,
    consumer_address: consumer.address,
    public_signal_order: PUBLIC_SIGNAL_NAMES,
    public_signals: Object.fromEntries(
      PUBLIC_SIGNAL_NAMES.map((name, index) => [name, publicSignals[index]])
    ),
    proof: {
      scheme: "groth16",
      curve: "bn254",
      verified_offchain: true,
      proof_size_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
      proving_key_bytes: fs.statSync(ZKEY).size,
    },
    settlement: {
      transaction_hash: settlementReceipt.hash,
      block_number: settlementReceipt.blockNumber,
      gas_used: settlementReceipt.gasUsed.toString(),
      budget_used: budgetState.used.toString(),
      request_status: Number(requestState.status),
      nullifier_used: nullifierUsed,
      audit_events: auditEvents.length,
    },
    stages: stageMetrics,
    total_wall_ms: nowMs() - totalStarted,
    environment: {
      node: process.version,
      platform: `${os.platform()} ${os.release()}`,
      cpu: os.cpus()[0]?.model || "unknown",
      logical_cpus: os.cpus().length,
    },
  };
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ ok: true, output: outputPath, request_key: requestKey }));
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
