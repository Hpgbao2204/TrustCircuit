"use strict";

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const { ethers } = require("hardhat");
const {
  PUBLIC_SIGNAL_NAMES,
  buildProofInput,
  identifierDigest,
} = require("./lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..");
const BUILD = path.join(ROOT, "zk", "build");
const WASM = path.join(BUILD, "vcp_v2_js", "vcp_v2.wasm");
const ZKEY = path.join(BUILD, "vcp_v2_final.zkey");
const VKEY = path.join(BUILD, "vcp_v2_vkey.json");
const METADATA = path.join(ROOT, "zk", "vcp_v2_metadata.json");
const OUTPUT = path.join(
  ROOT,
  "results",
  "raw",
  "phase8",
  "vcp_v2_integration.json"
);

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

async function timed(label, operation) {
  const started = nowMs();
  process.stdout.write(`[vcp-real-proof] ${label} started\n`);
  const heartbeat = setInterval(() => {
    process.stdout.write(
      `[vcp-real-proof] ${label} still running | elapsed ${((nowMs() - started) / 1000).toFixed(1)} s\n`
    );
  }, 30_000);
  try {
    const result = await operation();
    process.stdout.write(
      `[vcp-real-proof] ${label} complete | elapsed ${((nowMs() - started) / 1000).toFixed(1)} s\n`
    );
    return result;
  } finally {
    clearInterval(heartbeat);
  }
}

function hex(buffer) {
  return ethers.hexlify(buffer);
}

async function deploy(name, ...args) {
  const factory = await ethers.getContractFactory(name);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

async function deploySystem() {
  const registry = await deploy("DataRegistry");
  const access = await deploy("AccessController");
  const budget = await deploy("BudgetLedger");
  const audit = await deploy("AuditLedger");
  const validatorRegistry = await deploy("ValidatorRegistry");
  const native = await deploy("VCPGroth16Verifier");
  const adapter = await deploy("ComplianceVerifier", await native.getAddress());
  const settlement = await deploy(
    "TrustCircuitSettlement",
    await registry.getAddress(),
    await access.getAddress(),
    await budget.getAddress(),
    await adapter.getAddress(),
    await audit.getAddress(),
    await validatorRegistry.getAddress()
  );
  const settlementAddress = await settlement.getAddress();
  for (const module of [access, budget, audit, adapter]) {
    await (await module.setCoordinator(settlementAddress, true)).wait();
  }
  return { registry, access, budget, audit, validatorRegistry, native, adapter, settlement };
}

async function createCase({
  system,
  poseidon,
  consumer,
  validator,
  validatorId,
  suffix,
  policyMatrix,
  purposeId,
  functionId,
}) {
  const latest = await ethers.provider.getBlock("latest");
  const expiresAtUnixMs = BigInt(latest.timestamp + 3600) * 1000n;
  const request = {
    request_id: `vcp-real-proof-request-${suffix}`,
    asset_id: `vcp-real-proof-asset-${suffix}`,
    consumer_id: `vcp-real-proof-consumer-${suffix}`,
    policy_version: 1,
    purpose_id: purposeId,
    function_id: functionId,
    data_hash: ethers.id(`vcp-real-proof-data-${suffix}`).slice(2),
    dp_config_hash: ethers.id(`vcp-real-proof-dp-${suffix}`).slice(2),
    freshness_nonce: ethers.id(`vcp-real-proof-freshness-${suffix}`).slice(2),
    epsilon_requested_fixed: 500_000,
  };
  const execution = {
    ok: true,
    request_id: request.request_id,
    actual_privacy_cost_fixed: 400_000,
    result_fixed: 40 + suffix,
    enclave_identity: ethers.id("vcp-real-proof-enclave").slice(2),
    attestation_evidence: {
      validator_id: validatorId,
      native_digest: ethers.id(`vcp-real-proof-native-${suffix}`),
      expires_at_unix_ms: expiresAtUnixMs,
      signature: "00",
    },
  };
  const witness = {
    policyMatrix,
    resultOpening: 20260802000n + BigInt(suffix),
  };
  const preliminary = buildProofInput(request, execution, poseidon, witness);
  const unsignedStatement = {
    validatorId,
    nativeDigest: ethers.id(`vcp-real-proof-native-${suffix}`),
    contextCommitment: preliminary.values.contextCommitment,
    expiresAtUnixMs,
    signature: "0x",
  };
  const payload = await system.validatorRegistry.statementPayload(unsignedStatement);
  const statement = {
    ...unsignedStatement,
    signature: await validator.signMessage(ethers.getBytes(payload)),
  };
  const proofInput = buildProofInput(request, execution, poseidon, {
    ...witness,
    attestationStatement: statement,
  });
  const witnessPath = path.join(BUILD, `vcp_v2_real_proof_${suffix}.wtns`);
  await timed(
    `policy ${suffix}/2 witness generation`,
    () => snarkjs.wtns.calculate(proofInput.input, WASM, witnessPath)
  );
  const { proof, publicSignals } = await timed(
    `policy ${suffix}/2 Groth16 proving`,
    () => snarkjs.groth16.prove(ZKEY, witnessPath)
  );
  fs.rmSync(witnessPath, { force: true });
  const vkey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  if (!(await timed(
    `policy ${suffix}/2 off-chain verification`,
    () => snarkjs.groth16.verify(vkey, publicSignals, proof)
  ))) {
    throw new Error(`off-chain proof verification failed for policy ${suffix}`);
  }
  if (
    publicSignals.length !== 24 ||
    publicSignals.some((value, index) => value !== proofInput.publicSignals[index])
  ) {
    throw new Error(`public-signal order mismatch for policy ${suffix}`);
  }
  const [a, b, c, signals] = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );

  const values = proofInput.values;
  const requestKey = hex(identifierDigest("request_id", request.request_id));
  const assetKey = hex(identifierDigest("asset_id", request.asset_id));
  const consumerKey = hex(identifierDigest("consumer_id", request.consumer_id));
  await (await system.registry.registerAssetVCP(
    assetKey,
    ethers.id(`vcp-real-proof-metadata-${suffix}`),
    `0x${request.data_hash}`,
    values.policyCommitment,
    values.policyVersion
  )).wait();
  await (await system.budget.registerBudget(assetKey, 5_000_000n)).wait();
  await (await system.access.connect(consumer).requestAccessVCP(
    requestKey,
    assetKey,
    consumerKey,
    ethers.id(`vcp-real-proof-purpose-${suffix}`),
    values.purposeId,
    values.policyCommitment,
    values.policyVersion,
    values.functionId,
    `0x${request.dp_config_hash}`,
    `0x${request.freshness_nonce}`,
    values.reservedCost,
    expiresAtUnixMs
  )).wait();
  await (await system.access.approveRequest(requestKey)).wait();
  await (await system.settlement.reserveBudgetForRequest(requestKey)).wait();
  return {
    requestKey,
    assetKey,
    proofInput,
    a,
    b,
    c,
    signals,
    evidence: {
      resultCommitment: values.resultCommitment,
      auditDigest: values.auditDigest,
      attestation: statement,
    },
  };
}

async function assertAllPublicFieldsBound(system, consumer, testCase) {
  process.stdout.write("[vcp-real-proof] checking 24 single-field mutations\n");
  for (let index = 0; index < PUBLIC_SIGNAL_NAMES.length; index += 1) {
    const tampered = [...testCase.signals];
    tampered[index] = (BigInt(tampered[index]) + 1n).toString();
    let rejected = false;
    try {
      await system.settlement.connect(consumer).settle.staticCall(
        testCase.requestKey,
        testCase.evidence,
        testCase.a,
        testCase.b,
        testCase.c,
        tampered
      );
    } catch {
      rejected = true;
    }
    if (!rejected) {
      throw new Error(`tampered public field was accepted: ${PUBLIC_SIGNAL_NAMES[index]}`);
    }
    process.stdout.write(
      `[vcp-real-proof] tamper rejected ${index + 1}/${PUBLIC_SIGNAL_NAMES.length}: ${PUBLIC_SIGNAL_NAMES[index]}\n`
    );
  }
}

async function settleAndAssert(system, consumer, testCase) {
  const transaction = await system.settlement.connect(consumer).settle(
    testCase.requestKey,
    testCase.evidence,
    testCase.a,
    testCase.b,
    testCase.c,
    testCase.signals
  );
  const receipt = await transaction.wait();
  const [budget, request, nullifierUsed] = await Promise.all([
    system.budget.getBudget(testCase.assetKey),
    system.access.getRequest(testCase.requestKey),
    system.adapter.nullifierUsed(testCase.proofInput.values.nullifier),
  ]);
  const auditEvents = receipt.logs
    .map((log) => {
      try {
        return system.audit.interface.parseLog(log);
      } catch {
        return null;
      }
    })
    .filter((event) => event?.name === "VCPSettlementAuditRecorded");
  if (
    budget.used !== testCase.proofInput.values.actualCost ||
    budget.reserved !== 0n ||
    request.status !== 5n ||
    !nullifierUsed ||
    auditEvents.length !== 1
  ) {
    throw new Error("atomic settlement invariant failed");
  }
  return receipt;
}

async function main() {
  for (const required of [WASM, ZKEY, VKEY]) {
    if (!fs.existsSync(required)) {
      throw new Error(`missing ${required}; run npm run vcp:build first`);
    }
  }
  const [, consumer, validator] = await ethers.getSigners();
  const poseidon = await buildPoseidon();
  const system = await timed("deploy final eight-contract local stack", deploySystem);
  const validatorId = ethers.id("vcp-real-proof-validator");
  await (await system.validatorRegistry.activateValidator(validatorId, validator.address)).wait();

  const first = await createCase({
    system,
    poseidon,
    consumer,
    validator,
    validatorId,
    suffix: 1,
    policyMatrix: [[1n, 1n], [0n, 1n]],
    purposeId: 1,
    functionId: 2,
  });
  const second = await createCase({
    system,
    poseidon,
    consumer,
    validator,
    validatorId,
    suffix: 2,
    policyMatrix: [[0n, 1n], [1n, 0n]],
    purposeId: 2,
    functionId: 1,
  });

  await assertAllPublicFieldsBound(system, consumer, first);
  const firstReceipt = await settleAndAssert(system, consumer, first);
  const secondReceipt = await settleAndAssert(system, consumer, second);
  const metadata = JSON.parse(fs.readFileSync(METADATA, "utf8"));
  const result = {
    ok: true,
    schema: "TrustCircuit.VCPRealProofIntegration.v2",
    measurement_type: "functional_validation_local",
    timestamp_utc: new Date().toISOString(),
    public_inputs: PUBLIC_SIGNAL_NAMES.length,
    tampered_public_fields_rejected: PUBLIC_SIGNAL_NAMES.length,
    policy_matrices_verified_with_same_key: 2,
    atomic_settlements: 2,
    settlement_gas: [firstReceipt.gasUsed.toString(), secondReceipt.gasUsed.toString()],
    r1cs_sha256: metadata.r1cs_sha256,
    verification_key_sha256: metadata.verification_key_sha256,
    verifier_solidity_sha256: metadata.verifier_solidity_sha256,
  };
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  fs.writeFileSync(OUTPUT, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ ...result, output: OUTPUT }));
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
