/*
 * TrustCircuit public-testnet settlement experiment.
 *
 * Scope: Base Sepolia blockchain deployment and settlement only. Synthetic
 * request contexts and Groth16 proofs are prepared before any measured chain
 * transaction. No VBS/Nitro execution or proof-generation latency is included
 * in the blockchain measurements.
 */
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const {
  ContractFactory,
  JsonRpcProvider,
  NonceManager,
  Wallet,
  formatEther,
  getBytes,
  id,
  keccak256,
  toUtf8Bytes,
  zeroPadValue,
  toBeHex,
} = require("ethers");

const ROOT = path.resolve(__dirname, "..");
const RAW_ROOT = path.join(ROOT, "results", "raw", "phase8", "testnet");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "phase7_js", "phase7.wasm");
const ZKEY = path.join(BUILD, "phase7_final.zkey");
const VKEY = path.join(BUILD, "phase7_vkey.json");
const ENV_FILE = path.join(ROOT, ".env");

const NETWORK_NAME = "Base Sepolia";
const CHAIN_ID = 84532n;
const RPC_URL = "https://base-sepolia-rpc.publicnode.com";
const EXPLORER_URL = "https://sepolia-explorer.base.org";
const EXPECTED_ADDRESS = "0x862dAd21b3C2F6702fB3b7D784346b0b89Fa8b9F";
const DEPLOYMENT_REPETITIONS = 10;
const SUCCESS_REPETITIONS = 30;
const REVERT_REPETITIONS = 10;
const CONFIRMATION_DEPTHS = [5, 12];
const EPSILON_FIXED = 500_000n;
const EXPERIMENT_SEED = 20260722n;
const REVERT_GAS_LIMIT = 2_000_000n;
const RECEIPT_TIMEOUT_MS = 180_000;
const CONFIRMATION_TIMEOUT_MS = 300_000;
const SCALAR_FIELD =
  21888242871839275222246405745257275088548364400416034343698204186575808495617n;

const CONTRACTS = [
  "DataRegistry",
  "AccessController",
  "BudgetLedger",
  "AuditLedger",
  "Phase7Groth16Verifier",
  "ComplianceVerifier",
  "TrustCircuitSettlement",
];

function monotonicMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256File(filePath) {
  return sha256Bytes(fs.readFileSync(filePath));
}

function gitValue(args) {
  try {
    return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

function loadPrivateKey() {
  const text = fs.readFileSync(ENV_FILE, "utf8");
  const line = text
    .split(/\r?\n/)
    .find((item) => /^\s*TRUSTCIRCUIT_TESTNET_PRIVATE_KEY\s*=/.test(item));
  if (!line) throw new Error(".env does not define TRUSTCIRCUIT_TESTNET_PRIVATE_KEY");
  const value = line
    .slice(line.indexOf("=") + 1)
    .trim()
    .replace(/^['"]|['"]$/g, "");
  if (/^[0-9a-fA-F]{64}$/.test(value)) return `0x${value}`;
  if (!/^0x[0-9a-fA-F]{64}$/.test(value)) {
    throw new Error("TRUSTCIRCUIT_TESTNET_PRIVATE_KEY is not a 32-byte hex key");
  }
  return value;
}

function artifactPath(name) {
  return path.join(ROOT, "artifacts", "contracts", `${name}.sol`, `${name}.json`);
}

function loadArtifact(name) {
  const filePath = artifactPath(name);
  if (!fs.existsSync(filePath)) throw new Error(`missing compiled artifact: ${filePath}`);
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeCsv(filePath, rows, headers) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const body = rows.map((row) => headers.map((header) => csvEscape(row[header])).join(","));
  fs.writeFileSync(filePath, `${headers.join(",")}\n${body.join("\n")}${body.length ? "\n" : ""}`);
}

function writeJsonAtomic(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`);
  fs.renameSync(temporary, filePath);
}

function bytes32(label) {
  return keccak256(toUtf8Bytes(`TrustCircuit.PublicTestnet.v1|${label}`));
}

function fieldOf(value) {
  return BigInt(value) % SCALAR_FIELD;
}

function paddedBytes32(value) {
  return zeroPadValue(toBeHex(BigInt(value)), 32);
}

function calldataStats(data) {
  const bytes = getBytes(data || "0x");
  let zero = 0;
  for (const byte of bytes) if (byte === 0) zero += 1;
  return {
    calldata_bytes: bytes.length,
    calldata_zero_bytes: zero,
    calldata_nonzero_bytes: bytes.length - zero,
  };
}

function bigIntHex(value) {
  return value == null ? 0n : BigInt(value);
}

function transactionHeaders() {
  return [
    "measurement_type",
    "run_id",
    "timestamp_utc",
    "chain",
    "chain_id",
    "rpc_host",
    "category",
    "operation",
    "iteration",
    "suite_iteration",
    "request_id",
    "asset_id",
    "tx_hash",
    "explorer_url",
    "contract_address",
    "block_number",
    "status",
    "success",
    "expected_revert",
    "error_type",
    "submit_ack_ms",
    "inclusion_latency_ms",
    "confirmation_5_latency_ms",
    "confirmation_12_latency_ms",
    "post_inclusion_confirmation_5_ms",
    "post_inclusion_confirmation_12_ms",
    "gas_used",
    "effective_gas_price_wei",
    "l2_execution_fee_wei",
    "l1_fee_wei",
    "total_fee_wei",
    "calldata_bytes",
    "calldata_zero_bytes",
    "calldata_nonzero_bytes",
    "rollback_verified",
    "post_request_status",
    "post_nullifier_used",
    "post_audit_events",
    "post_budget_used_fixed",
    "config_hash",
  ];
}

class ResultStore {
  constructor(runDirectory, config) {
    this.runDirectory = runDirectory;
    this.config = config;
    this.rows = [];
    this.proofRows = [];
    this.addresses = [];
  }

  checkpoint() {
    writeJsonAtomic(path.join(this.runDirectory, "transactions.json"), this.rows);
    writeCsv(
      path.join(this.runDirectory, "transactions.csv"),
      this.rows,
      transactionHeaders()
    );
    if (this.proofRows.length) {
      const headers = Object.keys(this.proofRows[0]);
      writeCsv(path.join(this.runDirectory, "proof_preparation.csv"), this.proofRows, headers);
      writeJsonAtomic(path.join(this.runDirectory, "proof_preparation.json"), this.proofRows);
    }
    writeJsonAtomic(path.join(this.runDirectory, "deployments.json"), this.addresses);
    writeJsonAtomic(path.join(this.runDirectory, "config.json"), this.config);
  }

  addRow(row) {
    this.rows.push(row);
    this.checkpoint();
  }
}

class ConfirmationTracker {
  constructor(provider, store) {
    this.provider = provider;
    this.store = store;
    this.pending = [];
    this.running = true;
    this.loopPromise = this.loop();
  }

  track(row, broadcastStartedMs, includedMs) {
    Object.defineProperties(row, {
      _broadcastStartedMs: { value: broadcastStartedMs },
      _includedMs: { value: includedMs },
    });
    this.pending.push(row);
  }

  async loop() {
    while (this.running || this.pending.length) {
      try {
        const current = await this.provider.getBlockNumber();
        const now = monotonicMs();
        let changed = false;
        for (const row of this.pending) {
          for (const depth of CONFIRMATION_DEPTHS) {
            const key = `confirmation_${depth}_latency_ms`;
            const postKey = `post_inclusion_confirmation_${depth}_ms`;
            if (
              row[key] === "" &&
              current >= Number(row.block_number) + depth - 1
            ) {
              row[key] = +(now - row._broadcastStartedMs).toFixed(3);
              row[postKey] = +(now - row._includedMs).toFixed(3);
              changed = true;
            }
          }
        }
        this.pending = this.pending.filter((row) =>
          CONFIRMATION_DEPTHS.some((depth) => row[`confirmation_${depth}_latency_ms`] === "")
        );
        if (changed) this.store.checkpoint();
      } catch {
        // Transient read failures are retried; transaction rows remain checkpointed.
      }
      await delay(500);
    }
  }

  async finish() {
    const started = monotonicMs();
    while (this.pending.length && monotonicMs() - started < CONFIRMATION_TIMEOUT_MS) {
      await delay(500);
    }
    const timedOut = this.pending.length;
    this.running = false;
    if (timedOut) this.pending = [];
    await this.loopPromise;
    if (timedOut) {
      throw new Error(`${timedOut} transactions did not reach 12 confirmations`);
    }
  }
}

async function rawReceipt(provider, hash) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      return await provider.send("eth_getTransactionReceipt", [hash]);
    } catch (error) {
      if (attempt === 4) throw error;
      await delay(500 * (attempt + 1));
    }
  }
  return null;
}

async function rowFromReceipt({
  provider,
  config,
  category,
  operation,
  iteration,
  suiteIteration,
  requestId,
  assetId,
  contractAddress,
  transaction,
  receipt,
  expectedRevert,
  errorType,
  startedMs,
  acknowledgedMs,
  includedMs,
}) {
  const raw = await rawReceipt(provider, transaction.hash);
  const gasUsed = receipt.gasUsed;
  const gasPrice = receipt.gasPrice ?? bigIntHex(raw?.effectiveGasPrice);
  const l2Fee = gasUsed * gasPrice;
  const l1Fee = bigIntHex(raw?.l1Fee);
  const status = Number(receipt.status);
  return {
    measurement_type: "measured_public_testnet",
    run_id: config.run_id,
    timestamp_utc: new Date().toISOString(),
    chain: NETWORK_NAME,
    chain_id: CHAIN_ID.toString(),
    rpc_host: new URL(RPC_URL).host,
    category,
    operation,
    iteration,
    suite_iteration: suiteIteration ?? "",
    request_id: requestId ?? "",
    asset_id: assetId ?? "",
    tx_hash: transaction.hash,
    explorer_url: `${EXPLORER_URL}/tx/${transaction.hash}`,
    contract_address: contractAddress ?? receipt.contractAddress ?? "",
    block_number: receipt.blockNumber,
    status,
    success: status === 1 ? 1 : 0,
    expected_revert: expectedRevert ? 1 : 0,
    error_type: errorType ?? "",
    submit_ack_ms: +(acknowledgedMs - startedMs).toFixed(3),
    inclusion_latency_ms: +(includedMs - startedMs).toFixed(3),
    confirmation_5_latency_ms: "",
    confirmation_12_latency_ms: "",
    post_inclusion_confirmation_5_ms: "",
    post_inclusion_confirmation_12_ms: "",
    gas_used: gasUsed.toString(),
    effective_gas_price_wei: gasPrice.toString(),
    l2_execution_fee_wei: l2Fee.toString(),
    l1_fee_wei: l1Fee.toString(),
    total_fee_wei: (l2Fee + l1Fee).toString(),
    ...calldataStats(transaction.data),
    rollback_verified: "",
    post_request_status: "",
    post_nullifier_used: "",
    post_audit_events: "",
    post_budget_used_fixed: "",
    config_hash: config.config_hash,
  };
}

async function waitForReceiptAllowRevert(transaction) {
  try {
    return await transaction.wait(1, RECEIPT_TIMEOUT_MS);
  } catch (error) {
    if (error.receipt) return error.receipt;
    throw error;
  }
}

async function deployMeasured({
  name,
  args,
  signer,
  provider,
  config,
  store,
  tracker,
  suiteIteration,
}) {
  const artifact = loadArtifact(name);
  const factory = new ContractFactory(artifact.abi, artifact.bytecode, signer);
  const startedMs = monotonicMs();
  const contract = await factory.deploy(...args);
  const transaction = contract.deploymentTransaction();
  const acknowledgedMs = monotonicMs();
  const receipt = await transaction.wait(1, RECEIPT_TIMEOUT_MS);
  const includedMs = monotonicMs();
  const address = await contract.getAddress();
  const row = await rowFromReceipt({
    provider,
    config,
    category: "deployment",
    operation: `deploy_${name}`,
    iteration: suiteIteration,
    suiteIteration,
    contractAddress: address,
    transaction,
    receipt,
    expectedRevert: false,
    startedMs,
    acknowledgedMs,
    includedMs,
  });
  store.addresses.push({
    suite_iteration: suiteIteration,
    contract: name,
    address,
    tx_hash: transaction.hash,
    block_number: receipt.blockNumber,
  });
  tracker.track(row, startedMs, includedMs);
  store.addRow(row);
  process.stdout.write(
    `[base-sepolia] suite=${suiteIteration} deployed ${name} gas=${row.gas_used}\n`
  );
  return contract;
}

async function deploySuite(context, suiteIteration) {
  const common = { ...context, suiteIteration };
  const registry = await deployMeasured({ name: "DataRegistry", args: [], ...common });
  const access = await deployMeasured({ name: "AccessController", args: [], ...common });
  const budget = await deployMeasured({ name: "BudgetLedger", args: [], ...common });
  const audit = await deployMeasured({ name: "AuditLedger", args: [], ...common });
  const native = await deployMeasured({ name: "Phase7Groth16Verifier", args: [], ...common });
  const adapter = await deployMeasured({
    name: "ComplianceVerifier",
    args: [await native.getAddress()],
    ...common,
  });
  const settlement = await deployMeasured({
    name: "TrustCircuitSettlement",
    args: [
      await registry.getAddress(),
      await access.getAddress(),
      await budget.getAddress(),
      await adapter.getAddress(),
      await audit.getAddress(),
    ],
    ...common,
  });
  return { registry, access, budget, audit, native, adapter, settlement };
}

async function sendMeasured({
  context,
  category,
  operation,
  iteration,
  requestId,
  assetId,
  contractAddress,
  send,
  expectedRevert = false,
  errorType = "",
}) {
  const startedMs = monotonicMs();
  const transaction = await send();
  const acknowledgedMs = monotonicMs();
  const receipt = await waitForReceiptAllowRevert(transaction);
  const includedMs = monotonicMs();
  const row = await rowFromReceipt({
    provider: context.provider,
    config: context.config,
    category,
    operation,
    iteration,
    requestId,
    assetId,
    contractAddress,
    transaction,
    receipt,
    expectedRevert,
    errorType,
    startedMs,
    acknowledgedMs,
    includedMs,
  });
  if (expectedRevert && row.status !== 0) {
    throw new Error(`${operation} unexpectedly succeeded: ${transaction.hash}`);
  }
  if (!expectedRevert && row.status !== 1) {
    throw new Error(`${operation} unexpectedly reverted: ${transaction.hash}`);
  }
  context.tracker.track(row, startedMs, includedMs);
  context.store.addRow(row);
  process.stdout.write(
    `[base-sepolia] ${operation} iteration=${iteration} status=${row.status} gas=${row.gas_used}\n`
  );
  return { row, receipt, transaction };
}

async function prepareProofs({ mode, count, runId, assetKey, policyHash }) {
  const poseidon = await buildPoseidon();
  const F = poseidon.F;
  const verificationKey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const prepared = [];
  const rows = [];
  const assetId = fieldOf(assetKey);
  const policyField = fieldOf(policyHash);
  const consumerId = fieldOf(bytes32(`${runId}|consumer`));
  for (let index = 0; index < count; index += 1) {
    const requestKey = bytes32(`${runId}|request|${index}`);
    const resultHash = bytes32(`${runId}|result|${index}`);
    const transcriptHash = bytes32(`${runId}|transcript|${index}`);
    const attestationDigest = bytes32(`${runId}|attestation|${index}`);
    const requestId = fieldOf(requestKey);
    const functionId = index % 2 === 0 ? 2n : 1n;
    const secretNonce = EXPERIMENT_SEED + BigInt(index) + 1n;
    const context0 = F.toObject(
      poseidon([requestId, assetId, consumerId, policyField, 1n])
    );
    const context1 = F.toObject(
      poseidon([
        functionId,
        fieldOf(resultHash),
        EPSILON_FIXED,
        fieldOf(transcriptHash),
        fieldOf(attestationDigest),
      ])
    );
    const nullifier = F.toObject(poseidon([context0, context1, secretNonce]));
    const input = {
      requestId: requestId.toString(),
      assetId: assetId.toString(),
      consumerId: consumerId.toString(),
      policyHash: policyField.toString(),
      policyVersion: "1",
      functionId: functionId.toString(),
      resultHash: fieldOf(resultHash).toString(),
      epsilonCost: EPSILON_FIXED.toString(),
      nullifier: nullifier.toString(),
      transcriptHash: fieldOf(transcriptHash).toString(),
      attestationDigest: fieldOf(attestationDigest).toString(),
      allowedPolicyHash: policyField.toString(),
      maxBudget: EPSILON_FIXED.toString(),
      secretNonce: secretNonce.toString(),
      policyField: ["1000", "1001"],
    };
    const started = monotonicMs();
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(input, WASM, ZKEY);
    const proveMs = monotonicMs() - started;
    const verifyStarted = monotonicMs();
    const verified = await snarkjs.groth16.verify(verificationKey, publicSignals, proof);
    const verifyMs = monotonicMs() - verifyStarted;
    if (!verified) throw new Error(`off-chain proof ${index} failed verification`);
    const calldata = JSON.parse(
      `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
    );
    const expectedSignals = [
      requestId,
      assetId,
      consumerId,
      policyField,
      1n,
      functionId,
      fieldOf(resultHash),
      EPSILON_FIXED,
      nullifier,
      fieldOf(transcriptHash),
      fieldOf(attestationDigest),
    ].map(String);
    if (
      publicSignals.length !== expectedSignals.length ||
      publicSignals.some((value, signalIndex) => value !== expectedSignals[signalIndex])
    ) {
      throw new Error(`canonical public-signal mismatch for proof ${index}`);
    }
    prepared.push({
      index,
      requestKey,
      requestId,
      assetKey,
      assetId,
      consumerId,
      policyHash,
      policyField,
      functionId,
      resultHash,
      transcriptHash,
      attestationDigest,
      nullifier,
      a: calldata[0],
      b: calldata[1],
      c: calldata[2],
      signals: calldata[3],
      evidence: {
        dataHash: bytes32(`${runId}|data`),
        resultHash,
        transcriptHash,
        attestationDigest,
      },
    });
    rows.push({
      measurement_type: "prepared_offchain_not_in_chain_latency",
      mode,
      run_id: runId,
      proof_index: index,
      request_id: requestKey,
      prove_time_ms: +proveMs.toFixed(3),
      verify_time_ms: +verifyMs.toFixed(3),
      proof_bundle_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
      verified: 1,
    });
    process.stdout.write(`[base-sepolia] prepared proof ${index + 1}/${count}\n`);
  }
  return { prepared, rows };
}

async function setupRequest(context, system, item, iteration, category) {
  const common = {
    context,
    category: "setup",
    iteration,
    requestId: item.requestKey,
    assetId: item.assetKey,
  };
  await sendMeasured({
    ...common,
    operation: `${category}_request_access`,
    contractAddress: await system.access.getAddress(),
    send: () =>
      system.access.requestAccessV2(
        item.requestKey,
        item.assetKey,
        item.consumerId,
        id("TrustCircuit.PublicTestnet.Purpose.research"),
        item.policyHash,
        1,
        item.functionId,
        EPSILON_FIXED
      ),
  });
  await sendMeasured({
    ...common,
    operation: `${category}_approve_request`,
    contractAddress: await system.access.getAddress(),
    send: () => system.access.approveRequest(item.requestKey),
  });
  await sendMeasured({
    ...common,
    operation: `${category}_reserve_budget`,
    contractAddress: await system.settlement.getAddress(),
    send: () => system.settlement.reserveBudgetForRequest(item.requestKey),
  });
  await sendMeasured({
    ...common,
    operation: `${category}_register_expectation`,
    contractAddress: await system.adapter.getAddress(),
    send: () =>
      system.adapter.registerExpectation(item.requestKey, {
        requestId: item.requestId,
        assetId: item.assetId,
        consumerId: item.consumerId,
        policyHash: item.policyField,
        policyVersion: 1,
        functionId: item.functionId,
        resultHash: fieldOf(item.resultHash),
        maxEpsilon: EPSILON_FIXED,
        transcriptHash: fieldOf(item.transcriptHash),
        attestationDigest: fieldOf(item.attestationDigest),
        attestationExpiresAtUnixMs: BigInt(Date.now() + 30 * 24 * 60 * 60 * 1000),
      }),
  });
}

async function stateSnapshot(system, item) {
  const [budget, request, expectation, nullifierUsed] = await Promise.all([
    system.budget.getBudget(item.assetKey),
    system.access.getRequest(item.requestKey),
    system.adapter.getExpectation(item.requestKey),
    system.adapter.nullifierUsed(item.nullifier),
  ]);
  return {
    budget_total: budget.total.toString(),
    budget_reserved: budget.reserved.toString(),
    budget_used: budget.used.toString(),
    budget_remaining: budget.budgetRemaining.toString(),
    request_status: Number(request.status),
    expectation_verified: expectation.verified,
    expectation_nullifier: expectation.nullifier.toString(),
    nullifier_used: nullifierUsed,
  };
}

function sameSnapshot(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function parseRevertName(error, interfaces) {
  const candidates = [
    error?.data,
    error?.error?.data,
    error?.info?.error?.data,
    error?.revert?.data,
  ].filter((value) => typeof value === "string" && value.startsWith("0x"));
  for (const data of candidates) {
    for (const iface of interfaces) {
      try {
        return iface.parseError(data)?.name || "unknown";
      } catch {
        // Try the next ABI.
      }
    }
  }
  return error?.revert?.name || error?.shortMessage || "unknown";
}

async function expectedRevertName(system, item, args) {
  try {
    await system.settlement.settle.staticCall(item.requestKey, item.evidence, ...args);
    return "unexpected_static_success";
  } catch (error) {
    return parseRevertName(error, [
      system.settlement.interface,
      system.adapter.interface,
      system.budget.interface,
      system.access.interface,
    ]);
  }
}

async function sendSettlement(context, system, item, iteration, operation, args) {
  const result = await sendMeasured({
    context,
    category: "settlement",
    operation,
    iteration,
    requestId: item.requestKey,
    assetId: item.assetKey,
    contractAddress: await system.settlement.getAddress(),
    send: () => system.settlement.settle(item.requestKey, item.evidence, ...args),
  });
  const snapshot = await stateSnapshot(system, item);
  const auditEvents = result.receipt.logs
    .map((log) => {
      try {
        return system.audit.interface.parseLog(log);
      } catch {
        return null;
      }
    })
    .filter((event) => event?.name === "SettlementAuditRecorded");
  if (
    snapshot.request_status !== 4 ||
    snapshot.expectation_verified !== true ||
    snapshot.nullifier_used !== true ||
    auditEvents.length !== 1
  ) {
    throw new Error(`post-settlement invariant failed for ${item.requestKey}`);
  }
  result.row.post_request_status = snapshot.request_status;
  result.row.post_nullifier_used = snapshot.nullifier_used ? 1 : 0;
  result.row.post_audit_events = auditEvents.length;
  result.row.post_budget_used_fixed = snapshot.budget_used;
  context.store.checkpoint();
  return result;
}

async function sendExpectedRevert(context, system, item, iteration, operation, args) {
  const before = await stateSnapshot(system, item);
  const errorType = await expectedRevertName(system, item, args);
  const data = system.settlement.interface.encodeFunctionData("settle", [
    item.requestKey,
    item.evidence,
    ...args,
  ]);
  const result = await sendMeasured({
    context,
    category: "revert",
    operation,
    iteration,
    requestId: item.requestKey,
    assetId: item.assetKey,
    contractAddress: await system.settlement.getAddress(),
    expectedRevert: true,
    errorType,
    send: () =>
      context.signer.sendTransaction({
        to: system.settlement.target,
        data,
        gasLimit: REVERT_GAS_LIMIT,
      }),
  });
  const after = await stateSnapshot(system, item);
  result.row.rollback_verified = sameSnapshot(before, after) ? 1 : 0;
  if (result.row.rollback_verified !== 1) {
    throw new Error(`${operation} changed state despite reverting`);
  }
  context.store.checkpoint();
  return result;
}

async function main() {
  const mode = process.argv.includes("--smoke") ? "smoke" : "full";
  const deploymentRepetitions = mode === "smoke" ? 1 : DEPLOYMENT_REPETITIONS;
  const successRepetitions = mode === "smoke" ? 1 : SUCCESS_REPETITIONS;
  const revertRepetitions = mode === "smoke" ? 0 : REVERT_REPETITIONS;
  for (const required of [ENV_FILE, WASM, ZKEY, VKEY, ...CONTRACTS.map(artifactPath)]) {
    if (!fs.existsSync(required)) throw new Error(`missing required file: ${required}`);
  }

  const runId = `${mode}_${new Date().toISOString().replace(/[-:.]/g, "").replace("Z", "Z")}`;
  const runDirectory = path.join(RAW_ROOT, `base_sepolia_${runId}`);
  fs.mkdirSync(runDirectory, { recursive: true });
  const artifactHashes = Object.fromEntries(
    CONTRACTS.map((name) => [name, sha256File(artifactPath(name))])
  );
  const identity = {
    schema: "TrustCircuit.PublicTestnetConfig.v1",
    network: NETWORK_NAME,
    chain_id: CHAIN_ID.toString(),
    rpc_host: new URL(RPC_URL).host,
    deployment_repetitions: deploymentRepetitions,
    success_repetitions: successRepetitions,
    revert_repetitions: revertRepetitions,
    confirmation_depths: CONFIRMATION_DEPTHS,
    epsilon_fixed: EPSILON_FIXED.toString(),
    seed: EXPERIMENT_SEED.toString(),
    git_commit: gitValue(["rev-parse", "HEAD"]),
    r1cs_sha256: sha256File(path.join(BUILD, "phase7.r1cs")),
    zkey_sha256: sha256File(ZKEY),
    vkey_sha256: sha256File(VKEY),
    artifact_sha256: artifactHashes,
  };
  const config = {
    ...identity,
    run_id: runId,
    mode,
    measurement_type: "measured_public_testnet",
    scope: "blockchain deployment and settlement only; synthetic proofs prepared before measurement; no VBS/Nitro",
    timestamp_started_utc: new Date().toISOString(),
    explorer_url: EXPLORER_URL,
    expected_deployer_address: EXPECTED_ADDRESS,
    git_dirty: gitValue(["status", "--porcelain"]).length > 0,
    node: process.version,
    platform: `${os.platform()} ${os.release()}`,
    cpu: os.cpus()[0]?.model || "unknown",
    logical_cpus: os.cpus().length,
    solidity: "0.8.24 optimizer=enabled runs=200",
    snarkjs: require(path.join(ROOT, "node_modules", "snarkjs", "package.json")).version,
    config_hash: sha256Bytes(JSON.stringify(identity)),
  };
  const store = new ResultStore(runDirectory, config);
  store.checkpoint();

  const provider = new JsonRpcProvider(RPC_URL, CHAIN_ID, { staticNetwork: true });
  provider.pollingInterval = 500;
  const wallet = new Wallet(loadPrivateKey(), provider);
  if (wallet.address.toLowerCase() !== EXPECTED_ADDRESS.toLowerCase()) {
    throw new Error(`configured wallet ${wallet.address} does not match expected address`);
  }
  const network = await provider.getNetwork();
  if (network.chainId !== CHAIN_ID) throw new Error(`wrong chain ID ${network.chainId}`);
  const startingBalance = await provider.getBalance(wallet.address);
  if (startingBalance < 10_000_000_000_000_000n) {
    throw new Error(`insufficient Base Sepolia balance: ${formatEther(startingBalance)} ETH`);
  }
  config.deployer_address = wallet.address;
  config.starting_balance_wei = startingBalance.toString();
  config.starting_balance_eth = formatEther(startingBalance);
  const signer = new NonceManager(wallet);
  const tracker = new ConfirmationTracker(provider, store);
  const context = { provider, signer, config, store, tracker };

  const assetKey = bytes32(`${runId}|asset`);
  const policyHash = bytes32(`${runId}|policy`);
  const proofCount = successRepetitions + revertRepetitions;
  const proofPreparation = await prepareProofs({
    mode,
    count: proofCount,
    runId,
    assetKey,
    policyHash,
  });
  store.proofRows.push(...proofPreparation.rows);
  store.checkpoint();

  let system;
  for (let iteration = 0; iteration < deploymentRepetitions; iteration += 1) {
    system = await deploySuite(context, iteration);
  }
  config.canonical_deployment_iteration = deploymentRepetitions - 1;
  config.canonical_addresses = {
    registry: await system.registry.getAddress(),
    access_controller: await system.access.getAddress(),
    budget_ledger: await system.budget.getAddress(),
    audit_ledger: await system.audit.getAddress(),
    groth16_verifier: await system.native.getAddress(),
    compliance_adapter: await system.adapter.getAddress(),
    settlement: await system.settlement.getAddress(),
  };
  store.checkpoint();

  const first = proofPreparation.prepared[0];
  const totalSettlements = BigInt(successRepetitions + revertRepetitions);
  const totalBudget = EPSILON_FIXED * (totalSettlements + 20n);
  await sendMeasured({
    context,
    category: "setup",
    operation: "register_asset",
    iteration: 0,
    assetId: assetKey,
    contractAddress: await system.registry.getAddress(),
    send: () =>
      system.registry.registerAssetV2(
        assetKey,
        id("TrustCircuit.PublicTestnet.Metadata.v1"),
        first.evidence.dataHash,
        policyHash,
        1
      ),
  });
  await sendMeasured({
    context,
    category: "setup",
    operation: "register_budget",
    iteration: 0,
    assetId: assetKey,
    contractAddress: await system.budget.getAddress(),
    send: () => system.budget.registerBudget(assetKey, totalBudget),
  });

  for (let iteration = 0; iteration < successRepetitions; iteration += 1) {
    const item = proofPreparation.prepared[iteration];
    await setupRequest(context, system, item, iteration, "valid");
    await sendSettlement(
      context,
      system,
      item,
      iteration,
      "atomic_settlement_valid",
      [item.a, item.b, item.c, item.signals]
    );
  }

  for (let iteration = 0; iteration < revertRepetitions; iteration += 1) {
    const item = proofPreparation.prepared[successRepetitions + iteration];
    await setupRequest(context, system, item, iteration, "attack");

    const wrongSignals = [...item.signals];
    wrongSignals[6] = ((BigInt(wrongSignals[6]) + 1n) % SCALAR_FIELD).toString();
    await sendExpectedRevert(
      context,
      system,
      item,
      iteration,
      "revert_context_mismatch",
      [item.a, item.b, item.c, wrongSignals]
    );

    const tamperedA = [...item.a];
    tamperedA[0] = (BigInt(tamperedA[0]) ^ 1n).toString();
    await sendExpectedRevert(
      context,
      system,
      item,
      iteration,
      "revert_invalid_proof",
      [tamperedA, item.b, item.c, item.signals]
    );

    await sendSettlement(
      context,
      system,
      item,
      iteration,
      "attack_control_valid_settlement",
      [item.a, item.b, item.c, item.signals]
    );

    await sendExpectedRevert(
      context,
      system,
      item,
      iteration,
      "revert_replay",
      [item.a, item.b, item.c, item.signals]
    );
  }

  await tracker.finish();
  const finalBudget = await system.budget.getBudget(assetKey);
  const expectedUsed = EPSILON_FIXED * totalSettlements;
  if (
    finalBudget.used !== expectedUsed ||
    finalBudget.reserved !== 0n ||
    finalBudget.total < finalBudget.used
  ) {
    throw new Error("final privacy-budget invariant failed");
  }
  const endingBalance = await provider.getBalance(wallet.address);
  config.timestamp_finished_utc = new Date().toISOString();
  config.ending_balance_wei = endingBalance.toString();
  config.ending_balance_eth = formatEther(endingBalance);
  config.balance_spent_wei = (startingBalance - endingBalance).toString();
  config.final_budget = {
    total: finalBudget.total.toString(),
    reserved: finalBudget.reserved.toString(),
    used: finalBudget.used.toString(),
    remaining: finalBudget.budgetRemaining.toString(),
  };
  store.checkpoint();

  const result = {
    schema: "TrustCircuit.PublicTestnetRun.v1",
    ok: true,
    mode,
    run_id: runId,
    run_directory: path.relative(ROOT, runDirectory).replaceAll("\\", "/"),
    chain: NETWORK_NAME,
    chain_id: CHAIN_ID.toString(),
    deployer_address: wallet.address,
    transaction_count: store.rows.length,
    successful_transactions: store.rows.filter((row) => row.status === 1).length,
    reverted_transactions: store.rows.filter((row) => row.status === 0).length,
    rollback_checks_passed: store.rows
      .filter((row) => row.category === "revert")
      .every((row) => row.rollback_verified === 1),
    canonical_addresses: config.canonical_addresses,
    final_budget: config.final_budget,
  };
  writeJsonAtomic(path.join(runDirectory, "run_result.json"), result);
  const latest = {
    ...result,
    raw_directory: result.run_directory,
    processed_directory: "",
  };
  writeJsonAtomic(path.join(RAW_ROOT, `${mode}_latest.json`), latest);
  if (mode === "full") {
    writeJsonAtomic(path.join(RAW_ROOT, "public_testnet_status.json"), {
      measurement_type: "measured_public_testnet",
      executed: true,
      chain: NETWORK_NAME,
      chain_id: CHAIN_ID.toString(),
      run_id: runId,
      raw_directory: result.run_directory,
      transaction_count: result.transaction_count,
      canonical_addresses: config.canonical_addresses,
    });
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  provider.destroy();
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
