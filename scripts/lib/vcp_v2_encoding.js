"use strict";

const crypto = require("crypto");
const { AbiCoder, getBytes, hexlify, keccak256 } = require("ethers");

const BN254_SCALAR_FIELD =
  21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const UINT128_MASK = (1n << 128n) - 1n;

const IDENTIFIER_DOMAIN = Buffer.from("TrustCircuit.SettlementIdentifier.v2\0", "utf8");
const DP_CONFIG_DOMAIN = Buffer.from("TrustCircuit.DpConfig.v2\0", "utf8");
const FRESHNESS_DOMAIN = Buffer.from("TrustCircuit.Freshness.v2\0", "utf8");

const HASH_DOMAINS = Object.freeze({
  policy: 1n,
  function: 2n,
  nullifier: 3n,
  result: 4n,
  context: 5n,
  audit: 6n,
});

const PUBLIC_SIGNAL_NAMES = Object.freeze([
  "request_id_lo",
  "request_id_hi",
  "asset_id_lo",
  "asset_id_hi",
  "consumer_id_lo",
  "consumer_id_hi",
  "policy_commitment",
  "policy_version",
  "purpose_id",
  "function_id",
  "data_hash_lo",
  "data_hash_hi",
  "dp_config_hash_lo",
  "dp_config_hash_hi",
  "freshness_nonce_lo",
  "freshness_nonce_hi",
  "reserved_cost",
  "actual_cost",
  "nullifier",
  "context_commitment",
  "attestation_hash_lo",
  "attestation_hash_hi",
  "result_commitment",
  "audit_digest",
]);

function sizedUtf8(value) {
  const encoded = Buffer.from(value, "utf8");
  const size = Buffer.alloc(4);
  size.writeUInt32LE(encoded.length);
  return Buffer.concat([size, encoded]);
}

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest();
}

function requireBytes32(value, name) {
  let bytes;
  if (Buffer.isBuffer(value)) {
    bytes = value;
  } else if (typeof value === "string") {
    const normalized = value.startsWith("0x") ? value.slice(2) : value;
    if (!/^[0-9a-fA-F]{64}$/.test(normalized)) {
      throw new Error(`${name} must be exactly 32 bytes`);
    }
    bytes = Buffer.from(normalized, "hex");
  } else {
    throw new Error(`${name} must be bytes32`);
  }
  if (bytes.length !== 32) throw new Error(`${name} must be exactly 32 bytes`);
  return bytes;
}

function identifierDigest(fieldName, value) {
  if (!["request_id", "asset_id", "consumer_id"].includes(fieldName)) {
    throw new Error(`unsupported identifier field: ${fieldName}`);
  }
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${fieldName} must be a non-empty UTF-8 string`);
  }
  return sha256(
    Buffer.concat([IDENTIFIER_DOMAIN, sizedUtf8(fieldName), sizedUtf8(value)])
  );
}

function splitBytes32(value, name = "bytes32") {
  const bytes = requireBytes32(value, name);
  const integer = BigInt(`0x${bytes.toString("hex")}`);
  return {
    lo: integer & UINT128_MASK,
    hi: integer >> 128n,
  };
}

function joinBytes32(lo, hi) {
  const low = BigInt(lo);
  const high = BigInt(hi);
  if (low < 0n || low > UINT128_MASK || high < 0n || high > UINT128_MASK) {
    throw new Error("bytes32 limb is outside uint128");
  }
  return Buffer.from(
    ((high << 128n) | low).toString(16).padStart(64, "0"),
    "hex"
  );
}

function field(value, name = "field value") {
  const result = BigInt(value);
  if (result < 0n || result >= BN254_SCALAR_FIELD) {
    throw new Error(`${name} is outside the BN254 scalar field`);
  }
  return result;
}

function signedField(value) {
  const integer = BigInt(value);
  return ((integer % BN254_SCALAR_FIELD) + BN254_SCALAR_FIELD) %
    BN254_SCALAR_FIELD;
}

function poseidonObject(poseidon, values) {
  return BigInt(poseidon.F.toObject(poseidon(values.map(BigInt))));
}

function domainHash(poseidon, domain, values) {
  let state = poseidonObject(poseidon, [BigInt(domain), BigInt(values.length)]);
  for (const value of values) {
    state = poseidonObject(poseidon, [state, BigInt(value)]);
  }
  return state;
}

function normalizePolicyMatrix(matrix) {
  if (
    !Array.isArray(matrix) ||
    matrix.length !== 2 ||
    matrix.some((row) => !Array.isArray(row) || row.length !== 2)
  ) {
    throw new Error("VCP v2 currently requires a fixed 2x2 policy matrix");
  }
  return matrix.map((row) =>
    row.map((value) => {
      const bit = BigInt(value);
      if (bit !== 0n && bit !== 1n) throw new Error("policy entries must be Boolean");
      return bit;
    })
  );
}

function policyCommitment(poseidon, matrix) {
  const normalized = normalizePolicyMatrix(matrix);
  return domainHash(poseidon, HASH_DOMAINS.policy, [
    2n,
    2n,
    ...normalized.flat(),
  ]);
}

function oneHot(identifier, width, name) {
  const value = Number(identifier);
  if (!Number.isSafeInteger(value) || value < 1 || value > width) {
    throw new Error(`${name} must be in [1, ${width}]`);
  }
  return Array.from({ length: width }, (_, index) =>
    index + 1 === value ? 1n : 0n
  );
}

function canonicalJsonBytes(value) {
  function sorted(item) {
    if (Array.isArray(item)) return item.map(sorted);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.keys(item).sort().map((key) => [key, sorted(item[key])])
      );
    }
    return item;
  }
  return Buffer.from(JSON.stringify(sorted(value)), "utf8");
}

function derivedDpConfigHash(request) {
  const encoded = canonicalJsonBytes({
    epsilon_requested: request.epsilon_requested,
    delta_requested: request.delta_requested,
    lower_bound_fixed: request.lower_bound_fixed,
    upper_bound_fixed: request.upper_bound_fixed,
    apply_dp: request.apply_dp,
  });
  return sha256(Buffer.concat([DP_CONFIG_DOMAIN, encoded]));
}

function derivedFreshnessNonce(request) {
  if (request.freshness_nonce) {
    return requireBytes32(request.freshness_nonce, "freshness_nonce");
  }
  const source = request.nonce
    ? Buffer.from(String(request.nonce).replace(/^0x/, ""), "hex")
    : sizedUtf8(String(request.request_id));
  return sha256(Buffer.concat([FRESHNESS_DOMAIN, source]));
}

function normalizeAttestationStatement(statement, contextCommitment) {
  if (!statement || typeof statement !== "object") {
    throw new Error("missing validated attestation statement");
  }
  const validatorId = requireBytes32(
    statement.validatorId || statement.validator_id || statement.validator_identity,
    "validator_id"
  );
  const nativeDigest = requireBytes32(
    statement.nativeDigest || statement.native_digest || statement.evidence_sha256,
    "native_digest"
  );
  const carriedContext = field(
    statement.contextCommitment ?? statement.context_commitment ?? contextCommitment,
    "attestation context commitment"
  );
  if (carriedContext !== contextCommitment) {
    throw new Error("attestation statement is bound to a different VCP context");
  }
  const expiresAtUnixMs = BigInt(
    statement.expires_at_unix_ms ?? statement.expiresAtUnixMs
  );
  if (expiresAtUnixMs <= 0n || expiresAtUnixMs > (1n << 64n) - 1n) {
    throw new Error("attestation expiry is outside uint64");
  }
  const signatureText = statement.signature;
  if (typeof signatureText !== "string" || !/^(0x)?[0-9a-fA-F]+$/.test(signatureText)) {
    throw new Error("attestation signature must be hexadecimal");
  }
  const signature = signatureText.startsWith("0x")
    ? signatureText
    : `0x${signatureText}`;
  return {
    validatorId: hexlify(validatorId),
    nativeDigest: hexlify(nativeDigest),
    contextCommitment,
    expiresAtUnixMs,
    signature,
  };
}

function attestationStatementHash(statement) {
  const abi = AbiCoder.defaultAbiCoder();
  return Buffer.from(
    getBytes(
      keccak256(
        abi.encode(
          ["bytes32", "bytes32", "uint256", "uint64", "bytes"],
          [
            statement.validatorId,
            statement.nativeDigest,
            statement.contextCommitment,
            statement.expiresAtUnixMs,
            statement.signature,
          ]
        )
      )
    )
  );
}

function buildProofInput(request, execution, poseidon, witness = {}) {
  if (!request || !execution || execution.ok !== true) {
    throw new Error("a successful execution is required");
  }
  if (request.request_id !== execution.request_id) {
    throw new Error("execution request ID mismatch");
  }
  if (typeof witness === "bigint" || typeof witness === "number") {
    witness = { resultOpening: BigInt(witness) };
  }

  const matrix = normalizePolicyMatrix(witness.policyMatrix);
  const purposeId = BigInt(request.purpose_id ?? witness.purposeId);
  const functionId = BigInt(request.function_id);
  const policyVersion = BigInt(request.policy_version);
  const reservedCost = BigInt(
    request.epsilon_requested_fixed ?? witness.reservedCost
  );
  const actualCost = BigInt(execution.actual_privacy_cost_fixed);
  if (policyVersion <= 0n || policyVersion > (1n << 64n) - 1n) {
    throw new Error("policy_version is outside positive uint64");
  }
  if (
    reservedCost <= 0n ||
    actualCost <= 0n ||
    actualCost > reservedCost ||
    reservedCost > (1n << 64n) - 1n
  ) {
    throw new Error("invalid privacy budget relation");
  }

  const requestKey = identifierDigest("request_id", request.request_id);
  const assetKey = identifierDigest("asset_id", request.asset_id);
  const consumerKey = identifierDigest("consumer_id", request.consumer_id);
  const dataHash = requireBytes32(request.data_hash, "data_hash");
  const dpConfigHash = request.dp_config_hash
    ? requireBytes32(request.dp_config_hash, "dp_config_hash")
    : derivedDpConfigHash(request);
  const freshnessNonce = derivedFreshnessNonce(request);
  const enclaveMeasurement = requireBytes32(
    execution.enclave_identity,
    "enclave_identity"
  );

  const requestId = splitBytes32(requestKey, "request_id");
  const assetId = splitBytes32(assetKey, "asset_id");
  const consumerId = splitBytes32(consumerKey, "consumer_id");
  const data = splitBytes32(dataHash, "data_hash");
  const dpConfig = splitBytes32(dpConfigHash, "dp_config_hash");
  const freshness = splitBytes32(freshnessNonce, "freshness_nonce");
  const measurement = splitBytes32(enclaveMeasurement, "enclave_identity");

  const purposeSelector = oneHot(purposeId, 2, "purpose_id");
  const functionSelector = oneHot(functionId, 2, "function_id");
  if (matrix[Number(purposeId) - 1][Number(functionId) - 1] !== 1n) {
    throw new Error("requested purpose/function is disallowed by the policy matrix");
  }

  const policy = policyCommitment(poseidon, matrix);
  const functionHash = domainHash(poseidon, HASH_DOMAINS.function, [functionId]);
  const releasedResult = signedField(
    execution.result_fixed ?? execution.result ?? witness.releasedResult
  );
  const resultOpening = field(witness.resultOpening, "result opening");
  const result = domainHash(poseidon, HASH_DOMAINS.result, [
    releasedResult,
    resultOpening,
  ]);

  const nullifier = domainHash(poseidon, HASH_DOMAINS.nullifier, [
    assetId.lo,
    assetId.hi,
    consumerId.lo,
    consumerId.hi,
    requestId.lo,
    requestId.hi,
    policyVersion,
    purposeId,
    functionId,
    data.lo,
    data.hi,
    dpConfig.lo,
    dpConfig.hi,
    freshness.lo,
    freshness.hi,
  ]);

  const context = domainHash(poseidon, HASH_DOMAINS.context, [
    assetId.lo,
    assetId.hi,
    consumerId.lo,
    consumerId.hi,
    requestId.lo,
    requestId.hi,
    policy,
    policyVersion,
    data.lo,
    data.hi,
    functionHash,
    dpConfig.lo,
    dpConfig.hi,
    result,
    reservedCost,
    actualCost,
    measurement.lo,
    measurement.hi,
    freshness.lo,
    freshness.hi,
    purposeId,
  ]);

  const attestationStatement = normalizeAttestationStatement(
    witness.attestationStatement || execution.attestation_evidence,
    context
  );
  const attestationHashBytes = attestationStatementHash(attestationStatement);
  const attestationHash = splitBytes32(attestationHashBytes, "attestation_hash");

  const audit = domainHash(poseidon, HASH_DOMAINS.audit, [
    assetId.lo,
    assetId.hi,
    consumerId.lo,
    consumerId.hi,
    requestId.lo,
    requestId.hi,
    policy,
    policyVersion,
    purposeId,
    functionId,
    data.lo,
    data.hi,
    dpConfig.lo,
    dpConfig.hi,
    freshness.lo,
    freshness.hi,
    reservedCost,
    actualCost,
    nullifier,
    attestationHash.lo,
    attestationHash.hi,
    result,
  ]);

  const publicByName = {
    request_id_lo: requestId.lo,
    request_id_hi: requestId.hi,
    asset_id_lo: assetId.lo,
    asset_id_hi: assetId.hi,
    consumer_id_lo: consumerId.lo,
    consumer_id_hi: consumerId.hi,
    policy_commitment: policy,
    policy_version: policyVersion,
    purpose_id: purposeId,
    function_id: functionId,
    data_hash_lo: data.lo,
    data_hash_hi: data.hi,
    dp_config_hash_lo: dpConfig.lo,
    dp_config_hash_hi: dpConfig.hi,
    freshness_nonce_lo: freshness.lo,
    freshness_nonce_hi: freshness.hi,
    reserved_cost: reservedCost,
    actual_cost: actualCost,
    nullifier,
    context_commitment: context,
    attestation_hash_lo: attestationHash.lo,
    attestation_hash_hi: attestationHash.hi,
    result_commitment: result,
    audit_digest: audit,
  };

  const input = {
    requestIdLo: requestId.lo.toString(),
    requestIdHi: requestId.hi.toString(),
    assetIdLo: assetId.lo.toString(),
    assetIdHi: assetId.hi.toString(),
    consumerIdLo: consumerId.lo.toString(),
    consumerIdHi: consumerId.hi.toString(),
    policyCommitment: policy.toString(),
    policyVersion: policyVersion.toString(),
    purposeId: purposeId.toString(),
    functionId: functionId.toString(),
    dataHashLo: data.lo.toString(),
    dataHashHi: data.hi.toString(),
    dpConfigHashLo: dpConfig.lo.toString(),
    dpConfigHashHi: dpConfig.hi.toString(),
    freshnessNonceLo: freshness.lo.toString(),
    freshnessNonceHi: freshness.hi.toString(),
    reservedCost: reservedCost.toString(),
    actualCost: actualCost.toString(),
    nullifier: nullifier.toString(),
    contextCommitment: context.toString(),
    attestationHashLo: attestationHash.lo.toString(),
    attestationHashHi: attestationHash.hi.toString(),
    resultCommitment: result.toString(),
    auditDigest: audit.toString(),
    policyMatrix: matrix.map((row) => row.map(String)),
    purposeSelector: purposeSelector.map(String),
    functionSelector: functionSelector.map(String),
    releasedResult: releasedResult.toString(),
    resultOpening: resultOpening.toString(),
    enclaveMeasurementLo: measurement.lo.toString(),
    enclaveMeasurementHi: measurement.hi.toString(),
  };

  return {
    schema: "TrustCircuit.VCP.bn254.v2",
    input,
    publicSignals: PUBLIC_SIGNAL_NAMES.map((name) =>
      publicByName[name].toString()
    ),
    publicByName,
    values: {
      requestKey,
      assetKey,
      consumerKey,
      dataHash,
      dpConfigHash,
      freshnessNonce,
      enclaveMeasurement,
      policyCommitment: policy,
      resultCommitment: result,
      nullifier,
      contextCommitment: context,
      attestationHash: attestationHashBytes,
      auditDigest: audit,
      reservedCost,
      actualCost,
      policyVersion,
      purposeId,
      functionId,
    },
    attestationStatement,
  };
}

module.exports = {
  BN254_SCALAR_FIELD,
  HASH_DOMAINS,
  IDENTIFIER_DOMAIN,
  PUBLIC_SIGNAL_NAMES,
  attestationStatementHash,
  buildProofInput,
  canonicalJsonBytes,
  domainHash,
  identifierDigest,
  joinBytes32,
  normalizeAttestationStatement,
  policyCommitment,
  splitBytes32,
};
