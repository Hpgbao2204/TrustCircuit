"use strict";

const crypto = require("crypto");

const BN254_SCALAR_FIELD =
  21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const IDENTIFIER_DOMAIN = Buffer.from("TrustCircuit.SettlementIdentifier.v1\0", "utf8");
const ATTESTATION_DIGEST_DOMAIN = Buffer.from(
  "TrustCircuit.ValidatedAttestation.v1\0",
  "utf8"
);

const PUBLIC_SIGNAL_NAMES = [
  "request_id",
  "asset_id",
  "consumer_id",
  "policy_hash",
  "policy_version",
  "function_id",
  "result_hash",
  "actual_privacy_cost_fixed",
  "nullifier",
  "transcript_hash",
  "attestation_digest",
];

function sizedUtf8(value) {
  const encoded = Buffer.from(value, "utf8");
  const size = Buffer.alloc(4);
  size.writeUInt32LE(encoded.length);
  return Buffer.concat([size, encoded]);
}

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest();
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

function bytes32ToField(value) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value, "hex");
  if (bytes.length !== 32) throw new Error("field projection requires 32 bytes");
  return BigInt(`0x${bytes.toString("hex")}`) % BN254_SCALAR_FIELD;
}

function sortedValue(value) {
  if (Array.isArray(value)) return value.map(sortedValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortedValue(value[key])])
    );
  }
  return value;
}

function canonicalJsonBytes(value) {
  return Buffer.from(JSON.stringify(sortedValue(value)), "utf8");
}

function validatedAttestationDigest(statement) {
  if (!statement || statement.validated !== true) {
    throw new Error("attestation statement is not validated");
  }
  return sha256(
    Buffer.concat([ATTESTATION_DIGEST_DOMAIN, canonicalJsonBytes(statement)])
  );
}

function contextFields(request, execution) {
  const statement = execution.attestation_evidence;
  if (!statement || statement.transcript_hash !== execution.transcript_hash) {
    throw new Error("validated attestation transcript mismatch");
  }
  const requestKey = identifierDigest("request_id", request.request_id);
  const assetKey = identifierDigest("asset_id", request.asset_id);
  const consumerKey = identifierDigest("consumer_id", request.consumer_id);
  const policyHash = Buffer.from(request.policy_hash, "hex");
  const resultHash = Buffer.from(execution.result_hash, "hex");
  const transcriptHash = Buffer.from(execution.transcript_hash, "hex");
  const attestationDigest = validatedAttestationDigest(statement);
  for (const [name, value] of Object.entries({
    policyHash,
    resultHash,
    transcriptHash,
    attestationDigest,
  })) {
    if (value.length !== 32) throw new Error(`${name} is not bytes32`);
  }
  return {
    requestKey,
    assetKey,
    consumerKey,
    policyHash,
    resultHash,
    transcriptHash,
    attestationDigest,
    request_id: bytes32ToField(requestKey),
    asset_id: bytes32ToField(assetKey),
    consumer_id: bytes32ToField(consumerKey),
    policy_hash: bytes32ToField(policyHash),
    policy_version: BigInt(request.policy_version),
    function_id: BigInt(request.function_id),
    result_hash: bytes32ToField(resultHash),
    actual_privacy_cost_fixed: BigInt(execution.actual_privacy_cost_fixed),
    transcript_hash: bytes32ToField(transcriptHash),
    attestation_digest: bytes32ToField(attestationDigest),
  };
}

function buildProofInput(request, execution, poseidon, secretNonce, policyFields = [1000n, 1001n]) {
  const values = contextFields(request, execution);
  const F = poseidon.F;
  const context0 = F.toObject(
    poseidon([
      values.request_id,
      values.asset_id,
      values.consumer_id,
      values.policy_hash,
      values.policy_version,
    ])
  );
  const context1 = F.toObject(
    poseidon([
      values.function_id,
      values.result_hash,
      values.actual_privacy_cost_fixed,
      values.transcript_hash,
      values.attestation_digest,
    ])
  );
  const nullifier = F.toObject(poseidon([context0, context1, BigInt(secretNonce)]));
  const publicByName = {
    request_id: values.request_id,
    asset_id: values.asset_id,
    consumer_id: values.consumer_id,
    policy_hash: values.policy_hash,
    policy_version: values.policy_version,
    function_id: values.function_id,
    result_hash: values.result_hash,
    actual_privacy_cost_fixed: values.actual_privacy_cost_fixed,
    nullifier,
    transcript_hash: values.transcript_hash,
    attestation_digest: values.attestation_digest,
  };
  const input = {
    requestId: publicByName.request_id.toString(),
    assetId: publicByName.asset_id.toString(),
    consumerId: publicByName.consumer_id.toString(),
    policyHash: publicByName.policy_hash.toString(),
    policyVersion: publicByName.policy_version.toString(),
    functionId: publicByName.function_id.toString(),
    resultHash: publicByName.result_hash.toString(),
    epsilonCost: publicByName.actual_privacy_cost_fixed.toString(),
    nullifier: publicByName.nullifier.toString(),
    transcriptHash: publicByName.transcript_hash.toString(),
    attestationDigest: publicByName.attestation_digest.toString(),
    allowedPolicyHash: publicByName.policy_hash.toString(),
    maxBudget: publicByName.actual_privacy_cost_fixed.toString(),
    secretNonce: BigInt(secretNonce).toString(),
    policyField: policyFields.map((value) => BigInt(value).toString()),
  };
  return {
    input,
    values,
    nullifier,
    publicSignals: PUBLIC_SIGNAL_NAMES.map((name) => publicByName[name].toString()),
  };
}

module.exports = {
  ATTESTATION_DIGEST_DOMAIN,
  BN254_SCALAR_FIELD,
  IDENTIFIER_DOMAIN,
  PUBLIC_SIGNAL_NAMES,
  buildProofInput,
  bytes32ToField,
  canonicalJsonBytes,
  contextFields,
  identifierDigest,
  validatedAttestationDigest,
};

