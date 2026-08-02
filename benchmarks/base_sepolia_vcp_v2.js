"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const {
  ContractFactory,
  JsonRpcProvider,
  NonceManager,
  Wallet,
  getBytes,
  id,
} = require("ethers");
const {
  PUBLIC_SIGNAL_NAMES,
  buildProofInput,
  identifierDigest,
} = require("../scripts/lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "vcp_v2_js", "vcp_v2.wasm");
const ZKEY = path.join(BUILD, "vcp_v2_final.zkey");
const VKEY = path.join(BUILD, "vcp_v2_vkey.json");
const METADATA = path.join(ROOT, "zk", "vcp_v2_metadata.json");
const RAW_ROOT = path.join(ROOT, "results", "raw", "phase8", "testnet");
const ENV_FILE = path.join(ROOT, ".env");
const CHAIN_ID = 84532n;
const DEFAULT_RPC = "https://base-sepolia-rpc.publicnode.com";
const EXPLORER = "https://sepolia-explorer.base.org";
const FULL_REPETITIONS = 30;
const RESERVED_COST = 500_000n;
const ACTUAL_COST = 400_000n;
const CONTRACTS = [
  "DataRegistry",
  "AccessController",
  "BudgetLedger",
  "AuditLedger",
  "ValidatorRegistry",
  "VCPGroth16Verifier",
  "ComplianceVerifier",
  "TrustCircuitSettlement",
];

function readEnv() {
  const values = {};
  if (!fs.existsSync(ENV_FILE)) return values;
  for (const line of fs.readFileSync(ENV_FILE, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    values[match[1]] = match[2].replace(/^['"]|['"]$/g, "");
  }
  return values;
}

function artifactPath(name) {
  return path.join(ROOT, "artifacts", "contracts", `${name}.sol`, `${name}.json`);
}

function artifact(name) {
  const filePath = artifactPath(name);
  if (!fs.existsSync(filePath)) throw new Error(`missing ${filePath}; run npm run compile`);
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
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
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(
    filePath,
    `${headers.join(",")}\n${rows
      .map((row) => headers.map((header) => csvEscape(row[header])).join(","))
      .join("\n")}\n`
  );
}

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

async function recordTransaction(rows, category, operation, transaction, contractAddress) {
  const started = nowMs();
  process.stdout.write(
    `[base-sepolia-vcp-v2] ${operation} broadcast ${transaction.hash}; waiting for inclusion\n`
  );
  const receipt = await transaction.wait();
  const inclusionMs = nowMs() - started;
  const fee = receipt.gasUsed * (receipt.gasPrice || 0n);
  rows.push({
    measurement_type: "measured_public_testnet",
    timestamp_utc: new Date().toISOString(),
    category,
    operation,
    tx_hash: transaction.hash,
    explorer_url: `${EXPLORER}/tx/${transaction.hash}`,
    contract_address: contractAddress,
    block_number: receipt.blockNumber,
    status: receipt.status,
    gas_used: receipt.gasUsed.toString(),
    gas_price_wei: (receipt.gasPrice || 0n).toString(),
    fee_wei: fee.toString(),
    calldata_bytes:
      typeof transaction.data === "string" && transaction.data.startsWith("0x")
        ? (transaction.data.length - 2) / 2
        : "",
    inclusion_latency_ms: inclusionMs,
  });
  if (receipt.status !== 1) throw new Error(`${operation} reverted: ${transaction.hash}`);
  process.stdout.write(
    `[base-sepolia-vcp-v2] ${operation} included block=${receipt.blockNumber} gas=${receipt.gasUsed} wait_ms=${inclusionMs.toFixed(1)}\n`
  );
  return receipt;
}

async function deploy(name, signer, rows, ...args) {
  const compiled = artifact(name);
  process.stdout.write(`[base-sepolia-vcp-v2] preparing deployment ${name}\n`);
  const contract = await new ContractFactory(compiled.abi, compiled.bytecode, signer).deploy(...args);
  const transaction = contract.deploymentTransaction();
  await recordTransaction(rows, "deployment", `deploy_${name}`, transaction, await contract.getAddress());
  return contract;
}

async function main() {
  const smoke = process.argv.includes("--smoke");
  const repetitions = smoke ? 1 : FULL_REPETITIONS;
  const env = { ...readEnv(), ...process.env };
  const privateKey = env.TRUSTCIRCUIT_TESTNET_PRIVATE_KEY;
  if (!/^(0x)?[0-9a-fA-F]{64}$/.test(privateKey || "")) {
    throw new Error("TRUSTCIRCUIT_TESTNET_PRIVATE_KEY must be a 32-byte hex key in .env");
  }
  for (const required of [WASM, ZKEY, VKEY, METADATA, ...CONTRACTS.map(artifactPath)]) {
    if (!fs.existsSync(required)) throw new Error(`missing required file: ${required}`);
  }
  const metadata = JSON.parse(fs.readFileSync(METADATA, "utf8"));
  if (metadata.public_inputs !== 24) throw new Error("testnet runner requires VCP v2/24 inputs");

  const rpcUrl = env.BASE_SEPOLIA_RPC_URL || DEFAULT_RPC;
  process.stdout.write(
    `[base-sepolia-vcp-v2] starting ${smoke ? "smoke" : "full"} run; repetitions=${repetitions}; rpc=${rpcUrl}\n`
  );
  const provider = new JsonRpcProvider(rpcUrl);
  provider.pollingInterval = 2_000;
  process.stdout.write("[base-sepolia-vcp-v2] checking Base Sepolia network\n");
  const network = await provider.getNetwork();
  if (network.chainId !== CHAIN_ID) {
    throw new Error(`wrong chain: expected ${CHAIN_ID}, received ${network.chainId}`);
  }
  const signer = new NonceManager(
    new Wallet(privateKey.startsWith("0x") ? privateKey : `0x${privateKey}`, provider)
  );
  const signerAddress = await signer.getAddress();
  process.stdout.write(
    `[base-sepolia-vcp-v2] connected chain_id=${network.chainId}; signer=${signerAddress}; checking balance\n`
  );
  const balance = await provider.getBalance(signerAddress);
  if (balance === 0n) throw new Error("testnet account has zero balance");
  process.stdout.write(
    `[base-sepolia-vcp-v2] preflight complete; balance_wei=${balance}; deployments=8\n`
  );

  const runId = `${smoke ? "smoke" : "full"}_${new Date()
    .toISOString()
    .replace(/[-:.]/g, "")}`;
  const runDirectory = path.join(RAW_ROOT, `base_sepolia_vcp_v2_${runId}`);
  fs.mkdirSync(runDirectory, { recursive: true });
  const rows = [];
  const deploymentRows = [];

  const registry = await deploy("DataRegistry", signer, rows);
  const access = await deploy("AccessController", signer, rows);
  const budget = await deploy("BudgetLedger", signer, rows);
  const audit = await deploy("AuditLedger", signer, rows);
  const validatorRegistry = await deploy("ValidatorRegistry", signer, rows);
  const native = await deploy("VCPGroth16Verifier", signer, rows);
  const adapter = await deploy("ComplianceVerifier", signer, rows, await native.getAddress());
  const settlement = await deploy(
    "TrustCircuitSettlement",
    signer,
    rows,
    await registry.getAddress(),
    await access.getAddress(),
    await budget.getAddress(),
    await adapter.getAddress(),
    await audit.getAddress(),
    await validatorRegistry.getAddress()
  );
  for (const name of CONTRACTS) {
    const row = rows.find((item) => item.operation === `deploy_${name}`);
    deploymentRows.push({
      contract: name,
      address: row.contract_address,
      tx_hash: row.tx_hash,
      gas_used: row.gas_used,
      block_number: row.block_number,
    });
  }

  const settlementAddress = await settlement.getAddress();
  for (const [name, module] of [["access", access], ["budget", budget], ["audit", audit], ["adapter", adapter]]) {
    const transaction = await module.setCoordinator(settlementAddress, true);
    await recordTransaction(rows, "configuration", `grant_${name}_coordinator`, transaction, await module.getAddress());
  }
  const validatorId = id("TrustCircuit.BaseSepolia.VCPv2.Validator");
  await recordTransaction(
    rows,
    "configuration",
    "activate_validator",
    await validatorRegistry.activateValidator(validatorId, signerAddress),
    await validatorRegistry.getAddress()
  );

  const poseidon = await buildPoseidon();
  const vkey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const prepared = [];
  const proofRows = [];
  for (let index = 0; index < repetitions; index += 1) {
    process.stdout.write(
      `[base-sepolia-vcp-v2] preparing proof ${index + 1}/${repetitions}\n`
    );
    const request = {
      request_id: `${runId}-request-${index}`,
      asset_id: `${runId}-asset`,
      consumer_id: `${runId}-consumer`,
      policy_version: 1,
      purpose_id: index % 2 === 0 ? 1 : 2,
      function_id: 2,
      data_hash: id(`${runId}-data`).slice(2),
      dp_config_hash: id(`${runId}-dp`).slice(2),
      freshness_nonce: id(`${runId}-freshness-${index}`).slice(2),
      epsilon_requested_fixed: Number(RESERVED_COST),
    };
    const execution = {
      ok: true,
      request_id: request.request_id,
      actual_privacy_cost_fixed: Number(ACTUAL_COST),
      result_fixed: 1000 + index,
      enclave_identity: id("TrustCircuit.BaseSepolia.VCPv2.Enclave").slice(2),
      attestation_evidence: {
        validator_id: validatorId,
        native_digest: id(`${runId}-native-${index}`),
        expires_at_unix_ms: Date.now() + 24 * 60 * 60 * 1000,
        signature: "00",
      },
    };
    const witness = {
      policyMatrix: [[1n, 1n], [0n, 1n]],
      resultOpening: 20260802000n + BigInt(index),
    };
    const preliminary = buildProofInput(request, execution, poseidon, witness);
    const unsigned = {
      validatorId,
      nativeDigest: id(`${runId}-native-${index}`),
      contextCommitment: preliminary.values.contextCommitment,
      expiresAtUnixMs: BigInt(execution.attestation_evidence.expires_at_unix_ms),
      signature: "0x",
    };
    const payload = await validatorRegistry.statementPayload(unsigned);
    const statement = { ...unsigned, signature: await signer.signMessage(getBytes(payload)) };
    const proofInput = buildProofInput(request, execution, poseidon, {
      ...witness,
      attestationStatement: statement,
    });
    const started = nowMs();
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(
      proofInput.input,
      WASM,
      ZKEY
    );
    const proveMs = nowMs() - started;
    const verifyStarted = nowMs();
    const verified = await snarkjs.groth16.verify(vkey, publicSignals, proof);
    const verifyMs = nowMs() - verifyStarted;
    if (!verified || publicSignals.length !== PUBLIC_SIGNAL_NAMES.length) {
      throw new Error(`proof preparation failed at index ${index}`);
    }
    const [a, b, c, signals] = JSON.parse(
      `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
    );
    prepared.push({ request, proofInput, statement, a, b, c, signals });
    proofRows.push({
      measurement_type: "prepared_offchain_not_in_chain_latency",
      run_id: runId,
      proof_index: index,
      public_inputs: publicSignals.length,
      prove_time_ms: proveMs,
      verify_time_ms: verifyMs,
      proof_json_bytes: Buffer.byteLength(JSON.stringify(proof)),
      verified: 1,
    });
    process.stdout.write(
      `[base-sepolia-vcp-v2] proof ${index + 1}/${repetitions} ready prove_ms=${proveMs.toFixed(1)} verify_ms=${verifyMs.toFixed(1)}\n`
    );
  }

  const first = prepared[0];
  const assetKey = getBytes(identifierDigest("asset_id", first.request.asset_id));
  await recordTransaction(
    rows,
    "setup",
    "register_asset_vcp",
    await registry.registerAssetVCP(
      assetKey,
      id(`${runId}-metadata`),
      `0x${first.request.data_hash}`,
      first.proofInput.values.policyCommitment,
      1
    ),
    await registry.getAddress()
  );
  await recordTransaction(
    rows,
    "setup",
    "register_budget",
    await budget.registerBudget(assetKey, RESERVED_COST * BigInt(repetitions)),
    await budget.getAddress()
  );

  const settlementGas = [];
  for (let index = 0; index < prepared.length; index += 1) {
    const item = prepared[index];
    const requestKey = getBytes(identifierDigest("request_id", item.request.request_id));
    const consumerKey = getBytes(identifierDigest("consumer_id", item.request.consumer_id));
    const common = `request_${index}`;
    await recordTransaction(
      rows,
      "request",
      `${common}_access`,
      await access.requestAccessVCP(
        requestKey,
        assetKey,
        consumerKey,
        id("TrustCircuit.BaseSepolia.Purpose"),
        item.proofInput.values.purposeId,
        item.proofInput.values.policyCommitment,
        1,
        item.proofInput.values.functionId,
        `0x${item.request.dp_config_hash}`,
        `0x${item.request.freshness_nonce}`,
        RESERVED_COST,
        item.statement.expiresAtUnixMs
      ),
      await access.getAddress()
    );
    await recordTransaction(rows, "request", `${common}_approve`, await access.approveRequest(requestKey), await access.getAddress());
    await recordTransaction(rows, "request", `${common}_reserve`, await settlement.reserveBudgetForRequest(requestKey), await settlement.getAddress());
    const evidence = {
      resultCommitment: item.proofInput.values.resultCommitment,
      auditDigest: item.proofInput.values.auditDigest,
      attestation: item.statement,
    };
    const receipt = await recordTransaction(
      rows,
      "settlement",
      `${common}_settle_vcp_v2`,
      await settlement.settle(requestKey, evidence, item.a, item.b, item.c, item.signals),
      await settlement.getAddress()
    );
    settlementGas.push(receipt.gasUsed);
  }

  const finalBudget = await budget.getBudget(assetKey);
  if (
    finalBudget.used !== ACTUAL_COST * BigInt(repetitions) ||
    finalBudget.reserved !== 0n
  ) {
    throw new Error("final budget invariant failed");
  }
  const config = {
    schema: "TrustCircuit.BaseSepoliaVCPv2.v1",
    measurement_type: "measured_public_testnet",
    run_id: runId,
    mode: smoke ? "smoke" : "full",
    chain_id: CHAIN_ID.toString(),
    rpc_host: new URL(env.BASE_SEPOLIA_RPC_URL || DEFAULT_RPC).host,
    repetitions,
    public_inputs: 24,
    contract_count: CONTRACTS.length,
    contracts: CONTRACTS,
    r1cs_sha256: metadata.r1cs_sha256,
    verification_key_sha256: metadata.verification_key_sha256,
    artifact_sha256: Object.fromEntries(CONTRACTS.map((name) => [name, sha256File(artifactPath(name))])),
  };
  const result = {
    schema: "TrustCircuit.BaseSepoliaVCPv2Run.v1",
    ok: true,
    run_id: runId,
    transaction_count: rows.length,
    atomic_settlements: repetitions,
    final_budget_used: finalBudget.used.toString(),
    settlement_gas: settlementGas.map(String),
    addresses: Object.fromEntries(deploymentRows.map((row) => [row.contract, row.address])),
  };
  writeCsv(path.join(runDirectory, "transactions.csv"), rows);
  writeCsv(path.join(runDirectory, "proof_preparation.csv"), proofRows);
  fs.writeFileSync(path.join(runDirectory, "deployments.json"), `${JSON.stringify(deploymentRows, null, 2)}\n`);
  fs.writeFileSync(path.join(runDirectory, "config.json"), `${JSON.stringify(config, null, 2)}\n`);
  fs.writeFileSync(path.join(runDirectory, "run_result.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ ...result, run_directory: runDirectory }));
  provider.destroy();
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
