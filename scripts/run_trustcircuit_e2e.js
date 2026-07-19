/*
 * Real Phase 7 local end-to-end pipeline. The VBS execution bundle is created
 * by prepare_phase7_bundle.py; this script proves its canonical context and
 * atomically settles it on the in-process Hardhat chain.
 */
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
  contextFields,
} = require("./lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "phase7_js", "phase7.wasm");
const ZKEY = path.join(BUILD, "phase7_final.zkey");
const VKEY = path.join(BUILD, "phase7_vkey.json");

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

function requirePath(name, fallback) {
  const value = process.env[name] || fallback;
  if (!value) throw new Error(`missing ${name}`);
  return path.resolve(ROOT, value);
}

function hex(buffer) {
  return `0x${buffer.toString("hex")}`;
}

async function deploy(name, ...args) {
  const started = nowMs();
  const factory = await ethers.getContractFactory(name);
  const contract = await factory.deploy(...args);
  const receipt = await contract.deploymentTransaction().wait();
  return {
    contract,
    metric: {
      stage: `deploy_${name}`,
      latency_ms: nowMs() - started,
      gas_used: receipt.gasUsed.toString(),
      success: true,
    },
  };
}

async function transact(stage, transactionPromise) {
  const started = nowMs();
  const transaction = await transactionPromise;
  const receipt = await transaction.wait();
  return {
    receipt,
    metric: {
      stage,
      latency_ms: nowMs() - started,
      gas_used: receipt.gasUsed.toString(),
      success: receipt.status === 1,
    },
  };
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
  if (bundle.schema !== "TrustCircuit.Phase7Bundle.v1") {
    throw new Error("unsupported Phase 7 bundle schema");
  }
  if (bundle.execution?.attestation_evidence?.validated !== true) {
    throw new Error("bundle does not contain validated VBS evidence");
  }

  const totalStarted = nowMs();
  const stageMetrics = [];
  const poseidon = await buildPoseidon();
  const secretNonce = 20260719001n;
  const proofInput = buildProofInput(
    bundle.request,
    bundle.execution,
    poseidon,
    secretNonce
  );
  for (const [name, encoded] of Object.entries(bundle.phase7.fields_without_nullifier)) {
    if (proofInput.values[name] !== BigInt(encoded)) {
      throw new Error(`Python/JavaScript Phase 7 encoding mismatch for ${name}`);
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
  const offchainVerified = await snarkjs.groth16.verify(
    verificationKey,
    publicSignals,
    proof
  );
  stageMetrics.push({
    stage: "groth16_verify_offchain",
    latency_ms: nowMs() - verifyStarted,
    gas_used: "0",
    success: offchainVerified,
  });
  if (!offchainVerified) throw new Error("off-chain Groth16 verification failed");
  const calldata = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );
  const [a, b, c, signals] = calldata;

  const [provider, consumer] = await ethers.getSigners();
  const deployments = {};
  for (const [key, name, args] of [
    ["registry", "DataRegistry", []],
    ["access", "AccessController", []],
    ["budget", "BudgetLedger", []],
    ["audit", "AuditLedger", []],
    ["nativeVerifier", "Phase7Groth16Verifier", []],
  ]) {
    const result = await deploy(name, ...args);
    deployments[key] = result.contract;
    stageMetrics.push(result.metric);
  }
  const adapterDeployment = await deploy(
    "ComplianceVerifier",
    await deployments.nativeVerifier.getAddress()
  );
  deployments.adapter = adapterDeployment.contract;
  stageMetrics.push(adapterDeployment.metric);
  const settlementDeployment = await deploy(
    "TrustCircuitSettlement",
    await deployments.registry.getAddress(),
    await deployments.access.getAddress(),
    await deployments.budget.getAddress(),
    await deployments.adapter.getAddress(),
    await deployments.audit.getAddress()
  );
  deployments.settlement = settlementDeployment.contract;
  stageMetrics.push(settlementDeployment.metric);

  const values = contextFields(bundle.request, bundle.execution);
  const requestKey = hex(values.requestKey);
  const assetKey = hex(values.assetKey);
  const policyHash = hex(values.policyHash);
  const dataHash = `0x${bundle.request.data_hash}`;
  const evidence = {
    dataHash,
    resultHash: hex(values.resultHash),
    transcriptHash: hex(values.transcriptHash),
    attestationDigest: hex(values.attestationDigest),
  };
  const expected = {
    requestId: values.request_id,
    assetId: values.asset_id,
    consumerId: values.consumer_id,
    policyHash: values.policy_hash,
    policyVersion: values.policy_version,
    functionId: values.function_id,
    resultHash: values.result_hash,
    maxEpsilon: values.actual_privacy_cost_fixed,
    transcriptHash: values.transcript_hash,
    attestationDigest: values.attestation_digest,
    attestationExpiresAtUnixMs:
      bundle.execution.attestation_evidence.expires_at_unix_ms,
  };
  const metadataHash = ethers.sha256(ethers.toUtf8Bytes("TrustCircuit.Phase7.Metadata.v1"));
  const purposeHash = ethers.sha256(ethers.toUtf8Bytes("research"));
  const totalBudget = values.actual_privacy_cost_fixed * 10n;

  stageMetrics.push(
    (await transact(
      "register_asset",
      deployments.registry.registerAssetV2(
        assetKey,
        metadataHash,
        dataHash,
        policyHash,
        values.policy_version
      )
    )).metric
  );
  stageMetrics.push(
    (await transact("register_budget", deployments.budget.registerBudget(assetKey, totalBudget))).metric
  );
  stageMetrics.push(
    (await transact(
      "request_access",
      deployments.access.connect(consumer).requestAccessV2(
        requestKey,
        assetKey,
        values.consumer_id,
        purposeHash,
        policyHash,
        values.policy_version,
        values.function_id,
        values.actual_privacy_cost_fixed
      )
    )).metric
  );
  stageMetrics.push(
    (await transact("approve_request", deployments.access.connect(provider).approveRequest(requestKey))).metric
  );
  stageMetrics.push(
    (await transact(
      "reserve_budget",
      deployments.settlement.connect(provider).reserveBudgetForRequest(requestKey)
    )).metric
  );
  stageMetrics.push(
    (await transact(
      "register_expectation",
      deployments.adapter.connect(provider).registerExpectation(requestKey, expected)
    )).metric
  );
  const settlementResult = await transact(
    "atomic_settlement",
    deployments.settlement.connect(consumer).settle(
      requestKey,
      evidence,
      a,
      b,
      c,
      signals
    )
  );
  stageMetrics.push(settlementResult.metric);

  const budgetState = await deployments.budget.getBudget(assetKey);
  const requestState = await deployments.access.getRequest(requestKey);
  const expectationState = await deployments.adapter.getExpectation(requestKey);
  const nullifierUsed = await deployments.adapter.nullifierUsed(values.nullifier || proofInput.nullifier);
  const auditEvents = settlementResult.receipt.logs
    .map((log) => {
      try {
        return deployments.audit.interface.parseLog(log);
      } catch {
        return null;
      }
    })
    .filter((event) => event?.name === "SettlementAuditRecorded");
  if (
    requestState.status !== 4n ||
    expectationState.verified !== true ||
    nullifierUsed !== true ||
    budgetState.used !== values.actual_privacy_cost_fixed ||
    budgetState.reserved !== 0n ||
    auditEvents.length !== 1
  ) {
    throw new Error("post-settlement state invariant failed");
  }

  const result = {
    schema: "TrustCircuit.Phase7E2E.v1",
    measurement_type: "measured",
    ok: true,
    timestamp: new Date().toISOString(),
    request_key: requestKey,
    asset_key: assetKey,
    consumer_address: consumer.address,
    public_signal_order: PUBLIC_SIGNAL_NAMES,
    public_signals: Object.fromEntries(
      PUBLIC_SIGNAL_NAMES.map((name, index) => [name, publicSignals[index]])
    ),
    vbs: {
      request_id: bundle.request.request_id,
      result: bundle.execution.result,
      result_hash: bundle.execution.result_hash,
      transcript_hash: bundle.execution.transcript_hash,
      attestation_digest: values.attestationDigest.toString("hex"),
      attestation_validated: true,
      timings_us: bundle.execution.timings_us,
      client_timings_us: bundle.client_timings_us,
    },
    proof: {
      scheme: "groth16",
      curve: "bn254",
      verified_offchain: true,
      proof_size_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
      proving_key_bytes: fs.statSync(ZKEY).size,
    },
    settlement: {
      transaction_hash: settlementResult.receipt.hash,
      block_number: settlementResult.receipt.blockNumber,
      gas_used: settlementResult.receipt.gasUsed.toString(),
      budget_total: budgetState.total.toString(),
      budget_reserved: budgetState.reserved.toString(),
      budget_used: budgetState.used.toString(),
      budget_remaining: budgetState.budgetRemaining.toString(),
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
