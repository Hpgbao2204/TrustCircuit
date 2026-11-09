"use strict";

// VCP v3 (TNSE revision) witness and public-statement encoding.
//
// Differences from scripts/lib/phase7_encoding.js (VCP v2):
//   * policy commitment   ph  = H_pol(P, F, vec(M), r_pol)          (salted)
//   * context commitment  c_zk = H_ctx(..., purposeId, r_ctx)        (salted)
//   * result commitment   y_h  = H_res(result, r_res)                (unchanged, salted)
//   * dataset commitment  com_D = SHA256(tag_D || H(D) || r_D)       (salted, off-circuit)
//   * DP configuration    theta_h = keccak256(abi.encode(TAG, sigma, Delta, mech))
//                          computed by AccessController from public RDP parameters
//   * attestation hash    ah = keccak256(abi.encode(nativeDigest, c_zk, expiry,
//                          validatorIds[], signatures[]))  (k-of-n quorum statement)
// The 24-signal public interface and its order are unchanged.

const crypto = require("crypto");
const { AbiCoder, getBytes, keccak256, toUtf8Bytes } = require("ethers");
const {
  BN254_SCALAR_FIELD,
  HASH_DOMAINS,
  PUBLIC_SIGNAL_NAMES,
  domainHash,
  identifierDigest,
  splitBytes32,
} = require("./phase7_encoding");

const DATA_COMMITMENT_DOMAIN = Buffer.from("TrustCircuit.DataCommitment.v3\0", "utf8");
const DP_CONFIG_TYPEHASH = keccak256(
  toUtf8Bytes("TrustCircuitRdpConfig(uint64 sigmaFixed,uint64 sensitivityFixed,bytes32 mechanismHash)")
);
const ATTESTATION_TYPEHASH = keccak256(
  toUtf8Bytes(
    "TrustCircuitValidatedAttestation(bytes32 validatorId,bytes32 nativeDigest,uint256 contextCommitment,uint64 expiresAtUnixMs,uint256 chainId,address registry)"
  )
);
const KAPPA = 1_000_000n;
const RDP_PARAM_SCALE = 1_000_000n;

const abi = AbiCoder.defaultAbiCoder();

function randomField() {
  // Rejection sampling for a uniform element of the BN254 scalar field.
  for (;;) {
    const candidate = BigInt(`0x${crypto.randomBytes(32).toString("hex")}`) >> 2n;
    if (candidate < BN254_SCALAR_FIELD) return candidate;
  }
}

function randomBytes32() {
  return `0x${crypto.randomBytes(32).toString("hex")}`;
}

function toBuffer32(value, name) {
  const hex = typeof value === "string" ? value.replace(/^0x/, "") : value.toString("hex");
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) throw new Error(`${name} must be 32 bytes`);
  return Buffer.from(hex, "hex");
}

function normalizeMatrix(matrix) {
  if (
    !Array.isArray(matrix) ||
    matrix.length !== 2 ||
    matrix.some((row) => !Array.isArray(row) || row.length !== 2)
  ) {
    throw new Error("VCP v3 requires a fixed 2x2 policy matrix");
  }
  return matrix.map((row) =>
    row.map((value) => {
      const bit = BigInt(value);
      if (bit !== 0n && bit !== 1n) throw new Error("policy entries must be Boolean");
      return bit;
    })
  );
}

function fieldValue(value, name) {
  const result = BigInt(value);
  if (result < 0n || result >= BN254_SCALAR_FIELD) {
    throw new Error(`${name} is outside the BN254 scalar field`);
  }
  return result;
}

function policyCommitmentV3(poseidon, matrix, policySalt) {
  const normalized = normalizeMatrix(matrix);
  return domainHash(poseidon, HASH_DOMAINS.policy, [
    2n,
    2n,
    ...normalized.flat(),
    fieldValue(policySalt, "policy salt"),
  ]);
}

function saltedDataCommitment(datasetDigest, dataSalt) {
  const digest = crypto
    .createHash("sha256")
    .update(
      Buffer.concat([
        DATA_COMMITMENT_DOMAIN,
        toBuffer32(datasetDigest, "dataset digest"),
        toBuffer32(dataSalt, "data salt"),
      ])
    )
    .digest();
  return `0x${digest.toString("hex")}`;
}

function dpConfigHash(sigmaFixed, sensitivityFixed, mechanismHash) {
  return keccak256(
    abi.encode(
      ["bytes32", "uint64", "uint64", "bytes32"],
      [DP_CONFIG_TYPEHASH, BigInt(sigmaFixed), BigInt(sensitivityFixed), mechanismHash]
    )
  );
}

// ---------------------------------------------------------------------------
// RDP fixed-point accounting (mirrors BudgetLedger exactly, integer arithmetic)
// ---------------------------------------------------------------------------
function ceilDiv(a, b) {
  return (a + b - 1n) / b;
}

function rdpIncrement(alpha, sigmaFixed, sensitivityFixed) {
  const s = BigInt(sensitivityFixed);
  const sg = BigInt(sigmaFixed);
  return ceilDiv(KAPPA * BigInt(alpha) * s * s, 2n * sg * sg);
}

function rdpOffset(alpha, delta) {
  // ceil(kappa * ln(1/delta) / (alpha - 1)), computed in double precision and
  // rounded up; the registrant publishes these values at budget registration.
  const value = (Number(KAPPA) * Math.log(1 / delta)) / (Number(alpha) - 1);
  return BigInt(Math.ceil(value));
}

function conversion(vector, offsets) {
  if (vector.every((value) => value === 0n)) return 0n;
  let best = null;
  for (let i = 0; i < vector.length; i += 1) {
    const candidate = vector[i] + offsets[i];
    if (best === null || candidate < best) best = candidate;
  }
  return best;
}

function reservationAmount(orders, offsets, consumed, sigmaFixed, sensitivityFixed) {
  const maxIncrement = rdpIncrement(orders[orders.length - 1], sigmaFixed, sensitivityFixed);
  const empty = consumed.every((value) => value === 0n);
  const minOffset = offsets.reduce((a, b) => (b < a ? b : a));
  return maxIncrement + (empty ? minOffset : 0n);
}

// ---------------------------------------------------------------------------
// Quorum attestation statement
// ---------------------------------------------------------------------------
function attestationBase(nativeDigest, contextCommitment, expiresAtUnixMs) {
  return { nativeDigest, contextCommitment: BigInt(contextCommitment), expiresAtUnixMs: BigInt(expiresAtUnixMs) };
}

function validatorPayload(validatorId, base, chainId, registryAddress) {
  return keccak256(
    abi.encode(
      ["bytes32", "bytes32", "bytes32", "uint256", "uint64", "uint256", "address"],
      [
        ATTESTATION_TYPEHASH,
        validatorId,
        base.nativeDigest,
        base.contextCommitment,
        base.expiresAtUnixMs,
        BigInt(chainId),
        registryAddress,
      ]
    )
  );
}

async function signQuorum(base, signers, chainId, registryAddress) {
  // signers: [{ id: bytes32, wallet }]; the contract requires strictly increasing ids.
  const ordered = [...signers].sort((x, y) => (BigInt(x.id) < BigInt(y.id) ? -1 : 1));
  const validatorIds = [];
  const signatures = [];
  for (const signer of ordered) {
    const payload = validatorPayload(signer.id, base, chainId, registryAddress);
    validatorIds.push(signer.id);
    signatures.push(await signer.wallet.signMessage(getBytes(payload)));
  }
  return { ...base, validatorIds, signatures };
}

function quorumStatementHash(statement) {
  return keccak256(
    abi.encode(
      ["bytes32", "uint256", "uint64", "bytes32[]", "bytes[]"],
      [
        statement.nativeDigest,
        statement.contextCommitment,
        statement.expiresAtUnixMs,
        statement.validatorIds,
        statement.signatures,
      ]
    )
  );
}

// ---------------------------------------------------------------------------
// Witness / public statement
// ---------------------------------------------------------------------------
//
// ctx = {
//   requestKey, assetKey, consumerKey : bytes32 hex
//   dataCommitment, dpConfigHash, freshnessNonce : bytes32 hex
//   policyVersion, purposeId, functionId : integers
//   reservedCost, actualCost : integers (fixed-point)
//   policyMatrix, policySalt, contextSalt, resultOpening, releasedResult
//   enclaveMeasurement : bytes32 hex
// }
// Step 1: contextOf(ctx) -> c_zk (validators sign it)
// Step 2: buildProofInputV3(ctx, statement) -> circuit input + 24 public signals
function encodeCommon(poseidon, ctx) {
  const requestId = splitBytes32(toBuffer32(ctx.requestKey, "requestKey"));
  const assetId = splitBytes32(toBuffer32(ctx.assetKey, "assetKey"));
  const consumerId = splitBytes32(toBuffer32(ctx.consumerKey, "consumerKey"));
  const data = splitBytes32(toBuffer32(ctx.dataCommitment, "dataCommitment"));
  const dpConfig = splitBytes32(toBuffer32(ctx.dpConfigHash, "dpConfigHash"));
  const freshness = splitBytes32(toBuffer32(ctx.freshnessNonce, "freshnessNonce"));
  const measurement = splitBytes32(toBuffer32(ctx.enclaveMeasurement, "enclaveMeasurement"));
  const policyVersion = BigInt(ctx.policyVersion);
  const purposeId = BigInt(ctx.purposeId);
  const functionId = BigInt(ctx.functionId);
  const reservedCost = BigInt(ctx.reservedCost);
  const actualCost = BigInt(ctx.actualCost);
  const matrix = normalizeMatrix(ctx.policyMatrix);
  const policySalt = fieldValue(ctx.policySalt, "policy salt");
  const contextSalt = fieldValue(ctx.contextSalt, "context salt");
  const resultOpening = fieldValue(ctx.resultOpening, "result opening");
  const releasedResult =
    ((BigInt(ctx.releasedResult) % BN254_SCALAR_FIELD) + BN254_SCALAR_FIELD) % BN254_SCALAR_FIELD;

  const policy = policyCommitmentV3(poseidon, matrix, policySalt);
  const functionHash = domainHash(poseidon, HASH_DOMAINS.function, [functionId]);
  const result = domainHash(poseidon, HASH_DOMAINS.result, [releasedResult, resultOpening]);
  const nullifier = domainHash(poseidon, HASH_DOMAINS.nullifier, [
    assetId.lo, assetId.hi, consumerId.lo, consumerId.hi, requestId.lo, requestId.hi,
    policyVersion, purposeId, functionId, data.lo, data.hi, dpConfig.lo, dpConfig.hi,
    freshness.lo, freshness.hi,
  ]);
  const context = domainHash(poseidon, HASH_DOMAINS.context, [
    assetId.lo, assetId.hi, consumerId.lo, consumerId.hi, requestId.lo, requestId.hi,
    policy, policyVersion, data.lo, data.hi, functionHash, dpConfig.lo, dpConfig.hi,
    result, reservedCost, actualCost, measurement.lo, measurement.hi,
    freshness.lo, freshness.hi, purposeId, contextSalt,
  ]);
  return {
    requestId, assetId, consumerId, data, dpConfig, freshness, measurement,
    policyVersion, purposeId, functionId, reservedCost, actualCost, matrix,
    policySalt, contextSalt, resultOpening, releasedResult,
    policy, result, nullifier, context,
  };
}

function contextOf(poseidon, ctx) {
  return encodeCommon(poseidon, ctx).context;
}

function oneHot(identifier, width) {
  return Array.from({ length: width }, (_, index) => (BigInt(index + 1) === BigInt(identifier) ? 1n : 0n));
}

function buildProofInputV3(poseidon, ctx, statement) {
  const e = encodeCommon(poseidon, ctx);
  if (BigInt(statement.contextCommitment) !== e.context) {
    throw new Error("attestation statement is bound to a different VCP context");
  }
  const ahHex = quorumStatementHash(statement);
  const ah = splitBytes32(toBuffer32(ahHex, "attestation hash"));
  const audit = domainHash(poseidon, HASH_DOMAINS.audit, [
    e.assetId.lo, e.assetId.hi, e.consumerId.lo, e.consumerId.hi, e.requestId.lo, e.requestId.hi,
    e.policy, e.policyVersion, e.purposeId, e.functionId, e.data.lo, e.data.hi,
    e.dpConfig.lo, e.dpConfig.hi, e.freshness.lo, e.freshness.hi,
    e.reservedCost, e.actualCost, e.nullifier, ah.lo, ah.hi, e.result,
  ]);
  const publicByName = {
    request_id_lo: e.requestId.lo,
    request_id_hi: e.requestId.hi,
    asset_id_lo: e.assetId.lo,
    asset_id_hi: e.assetId.hi,
    consumer_id_lo: e.consumerId.lo,
    consumer_id_hi: e.consumerId.hi,
    policy_commitment: e.policy,
    policy_version: e.policyVersion,
    purpose_id: e.purposeId,
    function_id: e.functionId,
    data_hash_lo: e.data.lo,
    data_hash_hi: e.data.hi,
    dp_config_hash_lo: e.dpConfig.lo,
    dp_config_hash_hi: e.dpConfig.hi,
    freshness_nonce_lo: e.freshness.lo,
    freshness_nonce_hi: e.freshness.hi,
    reserved_cost: e.reservedCost,
    actual_cost: e.actualCost,
    nullifier: e.nullifier,
    context_commitment: e.context,
    attestation_hash_lo: ah.lo,
    attestation_hash_hi: ah.hi,
    result_commitment: e.result,
    audit_digest: audit,
  };
  const s = (v) => v.toString();
  const input = {
    requestIdLo: s(e.requestId.lo), requestIdHi: s(e.requestId.hi),
    assetIdLo: s(e.assetId.lo), assetIdHi: s(e.assetId.hi),
    consumerIdLo: s(e.consumerId.lo), consumerIdHi: s(e.consumerId.hi),
    policyCommitment: s(e.policy), policyVersion: s(e.policyVersion),
    purposeId: s(e.purposeId), functionId: s(e.functionId),
    dataHashLo: s(e.data.lo), dataHashHi: s(e.data.hi),
    dpConfigHashLo: s(e.dpConfig.lo), dpConfigHashHi: s(e.dpConfig.hi),
    freshnessNonceLo: s(e.freshness.lo), freshnessNonceHi: s(e.freshness.hi),
    reservedCost: s(e.reservedCost), actualCost: s(e.actualCost),
    nullifier: s(e.nullifier), contextCommitment: s(e.context),
    attestationHashLo: s(ah.lo), attestationHashHi: s(ah.hi),
    resultCommitment: s(e.result), auditDigest: s(audit),
    policyMatrix: e.matrix.map((row) => row.map(String)),
    purposeSelector: oneHot(e.purposeId, 2).map(String),
    functionSelector: oneHot(e.functionId, 2).map(String),
    releasedResult: s(e.releasedResult),
    resultOpening: s(e.resultOpening),
    enclaveMeasurementLo: s(e.measurement.lo),
    enclaveMeasurementHi: s(e.measurement.hi),
    policySalt: s(e.policySalt),
    contextSalt: s(e.contextSalt),
  };
  return {
    schema: "TrustCircuit.VCP.bn254.v3",
    input,
    publicByName,
    publicSignals: PUBLIC_SIGNAL_NAMES.map((name) => publicByName[name].toString()),
    values: {
      policyCommitment: e.policy,
      resultCommitment: e.result,
      nullifier: e.nullifier,
      contextCommitment: e.context,
      attestationHash: ahHex,
      auditDigest: audit,
    },
  };
}

module.exports = {
  ATTESTATION_TYPEHASH,
  DP_CONFIG_TYPEHASH,
  KAPPA,
  PUBLIC_SIGNAL_NAMES,
  RDP_PARAM_SCALE,
  attestationBase,
  buildProofInputV3,
  contextOf,
  conversion,
  dpConfigHash,
  identifierDigest,
  policyCommitmentV3,
  quorumStatementHash,
  randomBytes32,
  randomField,
  rdpIncrement,
  rdpOffset,
  reservationAmount,
  saltedDataCommitment,
  signQuorum,
  validatorPayload,
};
