"use strict";

// Base Sepolia campaign for the TNSE revision (VCP v3, ledger RDP accounting,
// 2-of-3 validator quorum, multisignature governance, retired deployer).
//
// Roles (each a distinct key):
//   deployer   : TRUSTCIRCUIT_TESTNET_PRIVATE_KEY from .env; deploys and funds
//                the other roles, then hands ownership to the multisig and
//                drops its coordinator rights (no privilege afterwards)
//   governance : TimelockMultisig, 2-of-3 owners, timelock GOV_DELAY seconds
//   operator   : lifecycle coordinator (request approval, reservation)
//   provider   : registers the asset, salted policy, and RDP budget
//   consumer   : submits requests and settlement transactions
//   validators : three keys; every statement carries two signatures
// Role keys other than the deployer are generated per run and kept only in
// secrets/base_sepolia_v3_<run>.json (git-ignored) so leftover test ETH can be
// swept back with --sweep <file>.
//
// Usage:
//   node benchmarks/base_sepolia_v3.js --smoke          1 lifecycle
//   node benchmarks/base_sepolia_v3.js                  30 lifecycles
//   node benchmarks/base_sepolia_v3.js --local          against http://127.0.0.1:8545
//   node benchmarks/base_sepolia_v3.js --sweep secrets/base_sepolia_v3_<run>.json

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const {
  ContractFactory, JsonRpcProvider, NonceManager, Wallet, formatEther, id,
} = require("ethers");
const enc = require("../scripts/lib/vcp_v3_encoding");
const { poseidon, toSolidityProof, offsetsFor, DEFAULT_ORDERS } = require("../scripts/lib/v3_stack");

const ROOT = path.resolve(__dirname, "..");
const WASM = path.join(ROOT, "zk", "build", "v3", "vcp_v3_js", "vcp_v3.wasm");
const ZKEY = path.join(ROOT, "zk", "build", "v3", "vcp_v3_final.zkey");
const METADATA = path.join(ROOT, "zk", "vcp_v3_metadata.json");
const RAW_ROOT = path.join(ROOT, "results", "raw", "revision", "testnet");
const SUMMARY = path.join(ROOT, "results", "summary", "revision", "base_sepolia_v3_summary.json");
const SECRETS = path.join(ROOT, "secrets");
const ENV_FILE = path.join(ROOT, ".env");
const BASE_SEPOLIA = 84532n;
const DEFAULT_RPC = "https://base-sepolia-rpc.publicnode.com";
const EXPLORER = "https://sepolia-explorer.base.org";
const GOV_DELAY = 60;
const MATRIX = [[1n, 1n], [0n, 1n]];
const CAL_MIX = [0.05, 0.1, 0.2, 0.5];
const CONTRACTS = [
  "DataRegistry", "AccessController", "BudgetLedger", "AuditLedger", "ValidatorRegistry",
  "VCPv3Groth16Verifier", "ComplianceVerifier", "TrustCircuitSettlement", "TimelockMultisig",
];

const arg = (name) => process.argv.includes(`--${name}`);
const argValue = (name) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
};
const nowMs = () => Number(process.hrtime.bigint()) / 1e6;
const log = (m) => process.stdout.write(`[base-sepolia-v3] ${m}\n`);

function readEnv() {
  const values = {};
  if (!fs.existsSync(ENV_FILE)) return values;
  for (const line of fs.readFileSync(ENV_FILE, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m) values[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
  }
  return values;
}

function artifact(name) {
  const file = path.join(ROOT, "artifacts", "contracts", `${name}.sol`, `${name}.json`);
  if (!fs.existsSync(file)) throw new Error(`missing ${file}; run npx hardhat compile`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function sigmaFixedFor(eps) {
  return BigInt(Math.ceil((Math.sqrt(2 * Math.log(1.25 / 1e-5)) / eps) * 1e6));
}

function quantile(values, q) {
  const s = [...values].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  return s[Math.floor(pos)] + (s[Math.ceil(pos)] - s[Math.floor(pos)]) * (pos - Math.floor(pos));
}

function writeCsv(file, rows) {
  const headers = Object.keys(rows[0]);
  const esc = (v) => {
    const t = String(v ?? "");
    return /[",\n]/.test(t) ? `"${t.replaceAll('"', '""')}"` : t;
  };
  fs.writeFileSync(file, `${headers.join(",")}\n${rows.map((r) => headers.map((h) => esc(r[h])).join(",")).join("\n")}\n`);
}

async function sweep(file, rpcUrl) {
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  const provider = new JsonRpcProvider(rpcUrl);
  for (const [role, key] of Object.entries(data.keys)) {
    const wallet = new Wallet(key, provider);
    const balance = await provider.getBalance(wallet.address);
    const fee = await provider.getFeeData();
    const price = (fee.maxFeePerGas ?? fee.gasPrice) * 2n;
    const cost = 21_000n * price;
    if (balance <= cost) continue;
    const tx = await wallet.sendTransaction({ to: data.deployer, value: balance - cost, gasLimit: 21_000n, maxFeePerGas: price, maxPriorityFeePerGas: fee.maxPriorityFeePerGas ?? 1n });
    await tx.wait();
    log(`swept ${formatEther(balance - cost)} ETH from ${role}`);
  }
  provider.destroy();
}

async function main() {
  const env = { ...readEnv(), ...process.env };
  const local = arg("local");
  const rpcUrl = local ? "http://127.0.0.1:8545" : env.BASE_SEPOLIA_RPC_URL || DEFAULT_RPC;
  if (argValue("sweep")) return sweep(argValue("sweep"), rpcUrl);
  const smoke = arg("smoke");
  const repetitions = smoke ? 1 : Number(argValue("n") || 30);
  const deployerKey = local
    ? "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80" // Hardhat account #0 (public test key)
    : env.TRUSTCIRCUIT_TESTNET_PRIVATE_KEY;
  if (!/^(0x)?[0-9a-fA-F]{64}$/.test(deployerKey || "")) {
    throw new Error("TRUSTCIRCUIT_TESTNET_PRIVATE_KEY must be a 32-byte hex key in .env");
  }
  for (const f of [WASM, ZKEY, METADATA]) if (!fs.existsSync(f)) throw new Error(`missing ${f}`);
  const metadata = JSON.parse(fs.readFileSync(METADATA, "utf8"));

  const provider = new JsonRpcProvider(rpcUrl);
  provider.pollingInterval = local ? 200 : 1_000;
  const network = await provider.getNetwork();
  if (!local && network.chainId !== BASE_SEPOLIA) throw new Error(`wrong chain ${network.chainId}`);
  const deployerWallet = new Wallet(deployerKey.startsWith("0x") ? deployerKey : `0x${deployerKey}`, provider);
  const deployer = new NonceManager(deployerWallet);
  const balance = await provider.getBalance(deployerWallet.address);
  log(`chain ${network.chainId}; deployer ${deployerWallet.address}; balance ${formatEther(balance)} ETH; lifecycles ${repetitions}`);

  const runId = `${local ? "local" : smoke ? "smoke" : "full"}_${new Date().toISOString().replace(/[-:.]/g, "")}`;
  const runDir = path.join(RAW_ROOT, `base_sepolia_v3_${runId}`);
  fs.mkdirSync(runDir, { recursive: true });

  // ---- role keys -----------------------------------------------------------
  const roles = {};
  for (const role of ["operator", "provider", "consumer", "validator1", "validator2", "validator3", "owner1", "owner2", "owner3"]) {
    roles[role] = Wallet.createRandom().connect(provider);
  }
  fs.mkdirSync(SECRETS, { recursive: true });
  const secretsFile = path.join(SECRETS, `base_sepolia_v3_${runId}.json`);
  fs.writeFileSync(secretsFile, JSON.stringify({
    note: "Per-run testnet role keys. Test ETH only. Git-ignored.",
    deployer: deployerWallet.address,
    keys: Object.fromEntries(Object.entries(roles).map(([r, w]) => [r, w.privateKey])),
  }, null, 2));
  const signer = Object.fromEntries(Object.entries(roles).map(([r, w]) => [r, new NonceManager(w)]));

  const rows = [];
  async function record(category, operation, txPromise, from) {
    const tx = await txPromise;
    const started = nowMs();
    const receipt = await tx.wait();
    const latency = nowMs() - started;
    if (receipt.status !== 1) throw new Error(`${operation} reverted: ${tx.hash}`);
    rows.push({
      category, operation, from, tx_hash: tx.hash, explorer_url: `${EXPLORER}/tx/${tx.hash}`,
      contract_address: receipt.contractAddress || tx.to || "", block_number: receipt.blockNumber,
      gas_used: receipt.gasUsed.toString(), gas_price_wei: (receipt.gasPrice || 0n).toString(),
      fee_wei: (receipt.gasUsed * (receipt.gasPrice || 0n)).toString(),
      calldata_bytes: (tx.data.length - 2) / 2, inclusion_latency_ms: latency.toFixed(1),
    });
    log(`${operation} block ${receipt.blockNumber} gas ${receipt.gasUsed} ${latency.toFixed(0)} ms`);
    return receipt;
  }
  async function deploy(name, ...args) {
    const a = artifact(name);
    const contract = await new ContractFactory(a.abi, a.bytecode, deployer).deploy(...args);
    await record("deployment", `deploy_${name}`, Promise.resolve(contract.deploymentTransaction()), "deployer");
    return contract;
  }

  // ---- fund roles ---------------------------------------------------------
  // Gas budgets per role (generous upper bounds), priced at 3x the current max fee.
  const fee = await provider.getFeeData();
  const unitPrice = (fee.maxFeePerGas ?? fee.gasPrice) * 3n;
  const gasBudget = {
    operator: 400_000n * BigInt(repetitions) + 300_000n,
    provider: 600_000n,
    consumer: 1_300_000n * BigInt(repetitions),
    owner1: 300_000n, owner2: 200_000n, owner3: 300_000n,
  };
  const needed = Object.values(gasBudget).reduce((a, b) => a + b, 0n) * unitPrice + 25_000_000n * unitPrice;
  log(`estimated spend <= ${formatEther(needed)} ETH at ${unitPrice} wei/gas`);
  if (balance < needed) throw new Error(`deployer balance ${formatEther(balance)} ETH is below the estimate`);
  for (const [role, gas] of Object.entries(gasBudget)) {
    await record("funding", `fund_${role}`, deployer.sendTransaction({ to: roles[role].address, value: gas * unitPrice }), "deployer");
  }

  // ---- deployment ----------------------------------------------------------
  const registry = await deploy("DataRegistry");
  const access = await deploy("AccessController");
  const budget = await deploy("BudgetLedger");
  const audit = await deploy("AuditLedger");
  const validatorRegistry = await deploy("ValidatorRegistry");
  const verifier = await deploy("VCPv3Groth16Verifier");
  const adapter = await deploy("ComplianceVerifier", await verifier.getAddress());
  const settlement = await deploy(
    "TrustCircuitSettlement",
    await registry.getAddress(), await access.getAddress(), await budget.getAddress(),
    await adapter.getAddress(), await audit.getAddress(), await validatorRegistry.getAddress()
  );
  const multisig = await deploy("TimelockMultisig", [roles.owner1.address, roles.owner2.address, roles.owner3.address], 2, GOV_DELAY);
  const settlementAddress = await settlement.getAddress();
  const multisigAddress = await multisig.getAddress();

  // ---- configuration, then retire the deployer -------------------------------
  for (const [name, c] of [["access", access], ["budget", budget], ["audit", audit], ["adapter", adapter]]) {
    await record("configuration", `grant_settlement_${name}`, c.setCoordinator(settlementAddress, true), "deployer");
  }
  await record("configuration", "grant_operator_access", access.setCoordinator(roles.operator.address, true), "deployer");
  await record("configuration", "grant_operator_settlement", settlement.setCoordinator(roles.operator.address, true), "deployer");
  const validators = [1, 2, 3].map((i) => ({ id: id(`TrustCircuit.BaseSepolia.v3.validator${i}`), wallet: roles[`validator${i}`] }));
  for (const v of validators) {
    await record("configuration", `activate_${v.wallet.address.slice(0, 8)}`, validatorRegistry.activateValidator(v.id, v.wallet.address), "deployer");
  }
  await record("configuration", "set_threshold_2", validatorRegistry.setThreshold(2), "deployer");
  for (const [name, c] of [["access", access], ["budget", budget], ["audit", audit], ["adapter", adapter], ["settlement", settlement], ["validator_registry", validatorRegistry]]) {
    if (name !== "validator_registry") {
      await record("retire_deployer", `revoke_deployer_${name}`, c.setCoordinator(deployerWallet.address, false), "deployer");
    }
    await record("retire_deployer", `transfer_${name}_to_multisig`, c.transferOwnership(multisigAddress), "deployer");
  }

  // ---- governance action through the multisig (timelocked) ----------------------
  const ms1 = multisig.connect(signer.owner1);
  const setThreshold = validatorRegistry.interface.encodeFunctionData("setThreshold", [2]);
  await record("governance", "multisig_propose", ms1.propose(await validatorRegistry.getAddress(), setThreshold), "owner1");
  await record("governance", "multisig_approve", multisig.connect(signer.owner2).approve(0), "owner2");
  log(`waiting ${GOV_DELAY + 5} s for the governance timelock`);
  if (local) {
    await provider.send("evm_increaseTime", [GOV_DELAY + 5]);
    await provider.send("evm_mine", []);
  } else {
    await new Promise((r) => setTimeout(r, (GOV_DELAY + 5) * 1000));
  }
  await record("governance", "multisig_execute", multisig.connect(signer.owner3).execute(0), "owner3");

  // ---- asset registration by the provider ----------------------------------
  const p = await poseidon();
  const policySalt = enc.randomField();
  const policyCommitment = enc.policyCommitmentV3(p, MATRIX, policySalt);
  const dataCommitment = enc.saltedDataCommitment(id(`${runId}:dataset`), enc.randomBytes32());
  const assetKey = `0x${enc.identifierDigest("asset_id", `${runId}-asset`).toString("hex")}`;
  const orders = DEFAULT_ORDERS;
  const offsets = offsetsFor(orders);
  await record("setup", "register_asset", registry.connect(signer.provider).registerAssetVCP(assetKey, id(`${runId}:metadata`), dataCommitment, policyCommitment, 1), "provider");
  await record("setup", "register_rdp_budget", settlement.connect(signer.provider).registerRdpBudget(assetKey, 50_000_000n, orders, offsets), "provider");

  // ---- lifecycles ----------------------------------------------------------
  const proofRows = [];
  const consumerKey = `0x${enc.identifierDigest("consumer_id", `${runId}-consumer`).toString("hex")}`;
  for (let i = 0; i < repetitions; i += 1) {
    const requestKey = `0x${enc.identifierDigest("request_id", `${runId}-request-${i}`).toString("hex")}`;
    const sigmaFixed = sigmaFixedFor(CAL_MIX[i % CAL_MIX.length]);
    const mechanismHash = id("gaussian:count:v1");
    const freshnessNonce = enc.randomBytes32();
    const latest = await provider.getBlock("latest");
    const request = {
      requestId: requestKey, assetId: assetKey, consumerId: consumerKey, purposeHash: id("purpose:1"),
      purposeId: 1, policyCommitment, policyVersion: 1, functionId: 2, sigmaFixed, sensitivityFixed: 1_000_000n,
      mechanismHash, freshnessNonce, deadlineUnixMs: BigInt(latest.timestamp + 3600) * 1000n,
    };
    await record("request", `request_${i}_access`, access.connect(signer.consumer).requestAccessRDP(request), "consumer");
    await record("request", `request_${i}_approve`, access.connect(signer.operator).approveRequest(requestKey), "operator");
    await record("request", `request_${i}_reserve`, settlement.connect(signer.operator).reserveBudgetForRequest(requestKey), "operator");
    const reserved = (await budget.getReservation(requestKey))[1];
    const consumed = (await budget.getRdpState(assetKey))[2].map(BigInt);
    const offsetTerm = consumed.every((v) => v === 0n) ? offsets.reduce((a, b) => (b < a ? b : a)) : 0n;
    const actualCost = enc.rdpIncrement(orders.at(-1), sigmaFixed, 1_000_000n) + offsetTerm;
    const ctx = {
      requestKey, assetKey, consumerKey, dataCommitment,
      dpConfigHash: await access.rdpConfigHash(sigmaFixed, 1_000_000n, mechanismHash),
      freshnessNonce, policyVersion: 1n, purposeId: 1n, functionId: 2n, reservedCost: reserved, actualCost,
      policyMatrix: MATRIX, policySalt, contextSalt: enc.randomField(), resultOpening: enc.randomField(),
      releasedResult: BigInt(1000 + i), enclaveMeasurement: id("nitro:pcr0:approved"),
    };
    const base = enc.attestationBase(id(`${runId}:native:${i}`), enc.contextOf(p, ctx), BigInt(latest.timestamp + 3600) * 1000n);
    const statement = await enc.signQuorum(base, validators.slice(0, 2), network.chainId, await validatorRegistry.getAddress());
    const built = enc.buildProofInputV3(p, ctx, statement);
    const t = nowMs();
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(built.input, WASM, ZKEY);
    proofRows.push({ index: i, full_prove_ms: (nowMs() - t).toFixed(1) });
    const sol = toSolidityProof(proof);
    await record(
      "settlement",
      `request_${i}_settle`,
      settlement.connect(signer.consumer).settle(
        requestKey,
        { resultCommitment: built.values.resultCommitment, auditDigest: built.values.auditDigest, attestation: statement },
        sol.a, sol.b, sol.c, publicSignals
      ),
      "consumer"
    );
  }

  // ---- invariants and outputs ----------------------------------------------
  const [total, reservedLeft, used] = await budget.getBudget(assetKey);
  const consumedFinal = (await budget.getRdpState(assetKey))[2].map(BigInt);
  if (reservedLeft !== 0n || used !== enc.conversion(consumedFinal, offsets)) throw new Error("budget invariant failed");
  const deployerFlags = await Promise.all([access, budget, audit, adapter, settlement].map((c) => c.isCoordinator(deployerWallet.address)));
  const owners = await Promise.all([access, budget, audit, adapter, settlement, validatorRegistry].map((c) => c.owner()));
  if (deployerFlags.some(Boolean) || owners.some((o) => o !== multisigAddress)) throw new Error("deployer was not retired");

  writeCsv(path.join(runDir, "transactions.csv"), rows);
  writeCsv(path.join(runDir, "proof_preparation.csv"), proofRows);
  const settles = rows.filter((r) => r.category === "settlement");
  const deploys = rows.filter((r) => r.category === "deployment");
  const settleGas = settles.map((r) => Number(r.gas_used));
  const latencies = settles.map((r) => Number(r.inclusion_latency_ms) / 1000);
  const blocks = rows.map((r) => r.block_number);
  const summary = {
    schema: "TrustCircuit.Revision.BaseSepoliaV3.v1",
    run_id: runId,
    mode: local ? "local" : smoke ? "smoke" : "full",
    chain_id: network.chainId.toString(),
    rpc_host: new URL(rpcUrl).host,
    block_range: [Math.min(...blocks), Math.max(...blocks)],
    lifecycles: repetitions,
    successful_transactions: rows.length,
    contracts: CONTRACTS,
    deployment_gas_total: deploys.reduce((s, r) => s + Number(r.gas_used), 0),
    deployment_calldata_bytes_total: deploys.reduce((s, r) => s + r.calldata_bytes, 0),
    deployment_gas_by_contract: Object.fromEntries(deploys.map((r) => [r.operation.replace("deploy_", ""), Number(r.gas_used)])),
    settle_gas: { p50: quantile(settleGas, 0.5), p95: quantile(settleGas, 0.95), min: Math.min(...settleGas), max: Math.max(...settleGas) },
    settle_fee_wei_p50: quantile(settles.map((r) => Number(r.fee_wei)), 0.5),
    gas_price_wei_p50: quantile(settles.map((r) => Number(r.gas_price_wei)), 0.5),
    inclusion_latency_s: { p50: quantile(latencies, 0.5), p95: quantile(latencies, 0.95), max: Math.max(...latencies) },
    validator_quorum: "2-of-3",
    governance: { contract: "TimelockMultisig", threshold: 2, owners: 3, delay_s: GOV_DELAY },
    deployer_retired: true,
    rdp: { total_budget: total.toString(), used: used.toString(), orders },
    vcp: { circuit_sha256: metadata.circuit_sha256, final_zkey_sha256: metadata.final_zkey_sha256, setup_note: metadata.note },
    addresses: Object.fromEntries(deploys.map((r) => [r.operation.replace("deploy_", ""), r.contract_address])),
    roles: Object.fromEntries(Object.entries(roles).map(([r, w]) => [r, w.address])),
  };
  fs.writeFileSync(path.join(runDir, "run_summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
  if (!local && !smoke) {
    fs.mkdirSync(path.dirname(SUMMARY), { recursive: true });
    fs.writeFileSync(SUMMARY, `${JSON.stringify(summary, null, 2)}\n`);
  }
  log(`done: ${rows.length} tx, settle gas p50 ${summary.settle_gas.p50}, latency p50 ${summary.inclusion_latency_s.p50.toFixed(3)} s`);
  log(`role keys: ${path.relative(ROOT, secretsFile)} (sweep leftovers with --sweep)`);
  provider.destroy();
}

main()
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  })
  .finally(() => process.exit(process.exitCode || 0));
