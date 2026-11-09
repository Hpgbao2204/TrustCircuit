"use strict";

// Shared deployment and request-lifecycle helpers for the TNSE-revision stack
// (VCP v3, ledger-enforced RDP accounting, k-of-n validator quorum, and the
// sign-and-hash / stage-wise comparison designs). Used by the Hardhat tests,
// the attack matrix, and the revision benchmarks.

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const enc = require("./vcp_v3_encoding");

const ROOT = path.resolve(__dirname, "..", "..");
const WASM = path.join(ROOT, "zk", "build", "v3", "vcp_v3_js", "vcp_v3.wasm");
const ZKEY = path.join(ROOT, "zk", "build", "v3", "vcp_v3_final.zkey");

const DEFAULT_ORDERS = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64];
const DEFAULT_DELTA = 1e-5;

let poseidonPromise;
function poseidon() {
  if (!poseidonPromise) poseidonPromise = buildPoseidon();
  return poseidonPromise;
}

function haveProvingArtifacts() {
  return fs.existsSync(WASM) && fs.existsSync(ZKEY);
}

function offsetsFor(orders, delta = DEFAULT_DELTA) {
  return orders.map((alpha) => enc.rdpOffset(alpha, delta));
}

function toSolidityProof(proof) {
  return {
    a: [proof.pi_a[0], proof.pi_a[1]],
    b: [
      [proof.pi_b[0][1], proof.pi_b[0][0]],
      [proof.pi_b[1][1], proof.pi_b[1][0]],
    ],
    c: [proof.pi_c[0], proof.pi_c[1]],
  };
}

const ZERO_PROOF = { a: [0n, 0n], b: [[0n, 0n], [0n, 0n]], c: [0n, 0n] };

async function deployed(factory, ...args) {
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

/**
 * Deploys one independent stack.
 * design: "trustcircuit" | "shs" | "stage"
 * options: { realVerifier, threshold, validators: [{ id, wallet }] }
 */
async function deployStack(ethers, design, options = {}) {
  const [operator] = await ethers.getSigners();
  const F = async (name) => ethers.getContractFactory(name);
  const registry = await deployed(await F("DataRegistry"));
  const access = await deployed(await F("AccessController"));
  const budget = await deployed(await F("BudgetLedger"));
  const audit = await deployed(await F("AuditLedger"));
  const validatorRegistry = await deployed(await F("ValidatorRegistry"));
  const stack = { design, operator, registry, access, budget, audit, validatorRegistry };

  for (const validator of options.validators || []) {
    await (await validatorRegistry.activateValidator(validator.id, validator.wallet.address)).wait();
  }
  if (options.threshold && options.threshold !== 1) {
    await (await validatorRegistry.setThreshold(options.threshold)).wait();
  }
  stack.validators = options.validators || [];

  if (design === "trustcircuit") {
    const verifier = options.realVerifier
      ? await deployed(await F("VCPv3Groth16Verifier"))
      : await deployed(await F("MockVCPGroth16Verifier"));
    const adapter = await deployed(await F("ComplianceVerifier"), await verifier.getAddress());
    const settlement = await deployed(
      await F("TrustCircuitSettlement"),
      await registry.getAddress(),
      await access.getAddress(),
      await budget.getAddress(),
      await adapter.getAddress(),
      await audit.getAddress(),
      await validatorRegistry.getAddress()
    );
    const address = await settlement.getAddress();
    for (const c of [access, budget, audit, adapter]) {
      await (await c.setCoordinator(address, true)).wait();
    }
    Object.assign(stack, { verifier, adapter, settlement });
  } else if (design === "shs") {
    const settlement = await deployed(
      await F("SignAndHashSettlement"),
      await registry.getAddress(),
      await access.getAddress(),
      await budget.getAddress(),
      await audit.getAddress(),
      await validatorRegistry.getAddress()
    );
    const address = await settlement.getAddress();
    for (const c of [access, budget, audit]) {
      await (await c.setCoordinator(address, true)).wait();
    }
    stack.settlement = settlement;
  } else if (design === "stage") {
    const settlement = await deployed(
      await F("StageWiseSettlement"),
      await access.getAddress(),
      await validatorRegistry.getAddress()
    );
    stack.settlement = settlement;
  } else {
    throw new Error(`unknown design ${design}`);
  }
  stack.chainId = (await ethers.provider.getNetwork()).chainId;
  stack.validatorRegistryAddress = await validatorRegistry.getAddress();
  return stack;
}

/**
 * Registers a VCP asset with a salted policy and dataset commitment and an
 * on-chain RDP budget. Returns the provider-side secrets.
 */
async function registerAsset(stack, provider, spec) {
  const p = await poseidon();
  const policySalt = spec.policySalt ?? enc.randomField();
  const dataSalt = spec.dataSalt ?? enc.randomBytes32();
  const datasetDigest = spec.datasetDigest ?? `0x${crypto.createHash("sha256").update(spec.name).digest("hex")}`;
  const assetKey = `0x${enc.identifierDigest("asset_id", spec.name).toString("hex")}`;
  const policyCommitment = enc.policyCommitmentV3(p, spec.matrix, policySalt);
  const dataCommitment = enc.saltedDataCommitment(datasetDigest, dataSalt);
  await (
    await stack.registry
      .connect(provider)
      .registerAssetVCP(assetKey, stack.ethers.id(`metadata:${spec.name}`), dataCommitment, policyCommitment, 1)
  ).wait();
  const orders = spec.orders || DEFAULT_ORDERS;
  const offsets = offsetsFor(orders, spec.delta || DEFAULT_DELTA);
  const total = BigInt(Math.floor(Number(enc.KAPPA) * (spec.epsilonTotal ?? 4)));
  if (stack.design === "stage") {
    await (await stack.settlement.registerBudget(assetKey, spec.stageBudget ?? total)).wait();
  } else {
    await (await stack.settlement.connect(provider).registerRdpBudget(assetKey, total, orders, offsets)).wait();
  }
  return {
    name: spec.name,
    assetKey,
    matrix: spec.matrix,
    policySalt,
    policyCommitment,
    policyVersion: 1n,
    dataCommitment,
    orders,
    offsets,
    total,
  };
}

async function updatePolicy(stack, provider, asset, matrix) {
  const p = await poseidon();
  const policySalt = enc.randomField();
  const policyCommitment = enc.policyCommitmentV3(p, matrix, policySalt);
  await (await stack.registry.connect(provider).updatePolicyVCP(asset.assetKey, policyCommitment)).wait();
  Object.assign(asset, { matrix, policySalt, policyCommitment, policyVersion: asset.policyVersion + 1n });
}

/**
 * Submits, authorizes, and reserves an RDP request. Returns the request record.
 */
async function openRequest(stack, consumer, asset, spec) {
  const ethers = stack.ethers;
  const requestKey = `0x${enc.identifierDigest("request_id", spec.name).toString("hex")}`;
  const consumerKey = `0x${enc.identifierDigest("consumer_id", spec.consumer || "consumer").toString("hex")}`;
  const mechanismHash = ethers.id(spec.mechanism || "gaussian:count:v1");
  const freshnessNonce = enc.randomBytes32();
  const latest = await ethers.provider.getBlock("latest");
  const deadlineUnixMs = BigInt(latest.timestamp + (spec.deadlineSeconds ?? 3600)) * 1000n;
  const sigmaFixed = BigInt(spec.sigmaFixed);
  const sensitivityFixed = BigInt(spec.sensitivityFixed ?? 1_000_000);
  const request = {
    requestId: requestKey,
    assetId: asset.assetKey,
    consumerId: consumerKey,
    purposeHash: ethers.id(`purpose:${spec.purposeId}`),
    purposeId: spec.purposeId,
    policyCommitment: asset.policyCommitment,
    policyVersion: asset.policyVersion,
    functionId: spec.functionId,
    sigmaFixed,
    sensitivityFixed,
    mechanismHash,
    freshnessNonce,
    deadlineUnixMs,
  };
  await (await stack.access.connect(consumer).requestAccessRDP(request)).wait();
  await (await stack.access.connect(stack.operator).approveRequest(requestKey)).wait();
  let reserved = 0n;
  if (stack.design === "stage") {
    reserved = BigInt(spec.stageAmount);
    await (await stack.settlement.connect(stack.operator).admit(requestKey, reserved)).wait();
  } else {
    await (await stack.settlement.connect(stack.operator).reserveBudgetForRequest(requestKey)).wait();
    reserved = (await stack.budget.getReservation(requestKey))[1];
  }
  return {
    ...request,
    consumer,
    asset,
    reserved,
    dpConfigHash: await stack.access.rdpConfigHash(sigmaFixed, sensitivityFixed, mechanismHash),
  };
}

/**
 * Honest processor + validator quorum + prover for one reserved request.
 * opts: { appliedSigmaFixed, releasedResult, signers (validator subset),
 *         prove (bool), enclaveMeasurement, policyMatrix override }
 */
async function executeRequest(stack, request, opts = {}) {
  const p = await poseidon();
  const asset = request.asset;
  const consumed = (await stack.budget.getRdpState(asset.assetKey))[2].map(BigInt);
  const appliedSigma = BigInt(opts.appliedSigmaFixed ?? request.sigmaFixed);
  const offsetTerm = consumed.every((v) => v === 0n)
    ? asset.offsets.reduce((a, b) => (b < a ? b : a))
    : 0n;
  // The processor's attested bound for the noise it actually applied.
  const actualCost =
    opts.actualCost ??
    enc.rdpIncrement(asset.orders[asset.orders.length - 1], appliedSigma, request.sensitivityFixed) +
      offsetTerm;
  const ctx = {
    requestKey: request.requestId,
    assetKey: asset.assetKey,
    consumerKey: request.consumerId,
    dataCommitment: asset.dataCommitment,
    dpConfigHash: request.dpConfigHash,
    freshnessNonce: request.freshnessNonce,
    policyVersion: asset.policyVersion,
    purposeId: request.purposeId,
    functionId: request.functionId,
    reservedCost: request.reserved,
    actualCost,
    policyMatrix: opts.policyMatrix ?? asset.matrix,
    policySalt: opts.policySalt ?? asset.policySalt,
    contextSalt: enc.randomField(),
    resultOpening: enc.randomField(),
    releasedResult: opts.releasedResult ?? 4242n,
    enclaveMeasurement: opts.enclaveMeasurement ?? stack.ethers.id("nitro:pcr0:approved"),
  };
  const context = enc.contextOf(p, ctx);
  const latest = await stack.ethers.provider.getBlock("latest");
  const base = enc.attestationBase(
    stack.ethers.id(`native-evidence:${request.requestId}`),
    context,
    BigInt(latest.timestamp + 3600) * 1000n
  );
  const signers = opts.signers ?? stack.validators;
  const statement = await enc.signQuorum(base, signers, stack.chainId, stack.validatorRegistryAddress);
  const built = enc.buildProofInputV3(p, ctx, statement);
  let proof = ZERO_PROOF;
  let proveMs = null;
  if (opts.prove) {
    const started = Date.now();
    const result = await snarkjs.groth16.fullProve(built.input, WASM, ZKEY);
    proveMs = Date.now() - started;
    proof = toSolidityProof(result.proof);
    if (result.publicSignals.join(",") !== built.publicSignals.join(",")) {
      throw new Error("prover public signals differ from the encoder");
    }
  }
  return { ctx, statement, built, proof, proveMs };
}

function evidenceOf(bundle) {
  return {
    resultCommitment: bundle.built.values.resultCommitment,
    auditDigest: bundle.built.values.auditDigest,
    attestation: bundle.statement,
  };
}

async function settleTrustCircuit(stack, request, bundle, overrides = {}) {
  const proof = overrides.proof ?? bundle.proof;
  return stack.settlement
    .connect(request.consumer)
    .settle(
      overrides.requestKey ?? request.requestId,
      overrides.evidence ?? evidenceOf(bundle),
      proof.a,
      proof.b,
      proof.c,
      overrides.publicSignals ?? bundle.built.publicSignals
    );
}

async function shsSignatures(stack, publicSignals, admissible, signers) {
  const message = await stack.settlement.shsMessage(publicSignals, admissible);
  return signGeneric(stack, message, signers);
}

async function signGeneric(stack, message, signers) {
  const abi = stack.ethers.AbiCoder.defaultAbiCoder();
  const ordered = [...signers].sort((x, y) => (BigInt(x.id) < BigInt(y.id) ? -1 : 1));
  const ids = [];
  const sigs = [];
  for (const signer of ordered) {
    const payload = stack.ethers.keccak256(
      abi.encode(["bytes32", "bytes32", "uint256", "address"], [message, signer.id, stack.chainId, stack.validatorRegistryAddress])
    );
    ids.push(signer.id);
    sigs.push(await signer.wallet.signMessage(stack.ethers.getBytes(payload)));
  }
  return { ids, sigs };
}

async function settleShs(stack, request, bundle, admissible = 1, signers = stack.validators, publicSignals) {
  const pub = publicSignals ?? bundle.built.publicSignals;
  const { ids, sigs } = await shsSignatures(stack, pub, admissible, signers);
  return stack.settlement
    .connect(request.consumer)
    .settle(request.requestId, evidenceOf(bundle), pub, admissible, ids, sigs);
}

async function settleStage(stack, request, executionId, resultCommitment, signers = stack.validators) {
  const typehash = await stack.settlement.EXEC_TYPEHASH();
  const abi = stack.ethers.AbiCoder.defaultAbiCoder();
  const message = stack.ethers.keccak256(
    abi.encode(["bytes32", "bytes32", "uint256"], [typehash, executionId, resultCommitment])
  );
  const { ids, sigs } = await signGeneric(stack, message, signers);
  return stack.settlement
    .connect(request.consumer)
    .settle(request.requestId, { executionId, resultCommitment, validatorIds: ids, signatures: sigs });
}

async function makeValidators(ethers, count, offset = 10) {
  const signers = await ethers.getSigners();
  return Array.from({ length: count }, (_, i) => ({
    id: ethers.id(`validator:${i + 1}`),
    wallet: signers[offset + i],
  }));
}

async function attach(stack, ethers) {
  stack.ethers = ethers;
  return stack;
}

module.exports = {
  DEFAULT_DELTA,
  DEFAULT_ORDERS,
  WASM,
  ZERO_PROOF,
  ZKEY,
  attach,
  deployStack: async (ethers, design, options) => attach(await deployStack(ethers, design, options), ethers),
  enc,
  evidenceOf,
  executeRequest,
  haveProvingArtifacts,
  makeValidators,
  offsetsFor,
  openRequest,
  poseidon,
  registerAsset,
  settleShs,
  settleStage,
  settleTrustCircuit,
  shsSignatures,
  signGeneric,
  toSolidityProof,
  updatePolicy,
};
