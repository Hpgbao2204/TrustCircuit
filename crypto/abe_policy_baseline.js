/*
 * Matched policy-latency benchmark for the existing TrustCircuit KEM-DEM
 * baseline. The all-of-N access tree ensures both encryption and decryption
 * process every policy attribute. Setup and user-key issuance are deliberately
 * outside the timed region, matching the pairing-based AC17/FAME benchmark.
 */
"use strict";

const abe = require("./abe_hybrid");

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

const policySizes = argument("--policy-sizes", "5,10,15,20,25")
  .split(",")
  .map((value) => Number(value.trim()));
const repetitions = Number(argument("--reps", "30"));
const warmups = Number(argument("--warmups", "5"));
const payloadBytes = Number(argument("--payload-bytes", "32"));

if (
  !policySizes.length ||
  policySizes.some((value) => !Number.isInteger(value) || value <= 0) ||
  !Number.isInteger(repetitions) || repetitions <= 0 ||
  !Number.isInteger(warmups) || warmups < 0 ||
  !Number.isInteger(payloadBytes) || payloadBytes <= 0
) {
  throw new Error("invalid benchmark arguments");
}

function elapsedMs(start, end) {
  return Number(end - start) / 1e6;
}

function makeContext(attributeCount) {
  const attributes = Array.from({ length: attributeCount }, (_, index) => `A${String(index + 1).padStart(3, "0")}`);
  const policy = abe.AND(...attributes.map((attribute) => abe.leaf(attribute)));
  const authority = new abe.Authority();
  const publicParameters = authority.publicKeysFor(attributes);
  const userKey = authority.issueKey(attributes);
  return { policy, publicParameters, userKey };
}

function execute(context, payload) {
  const encryptStart = process.hrtime.bigint();
  const ciphertext = abe.encrypt(
    context.publicParameters,
    JSON.parse(JSON.stringify(context.policy)),
    payload
  );
  const encryptEnd = process.hrtime.bigint();
  const recovered = abe.decrypt(context.userKey, ciphertext);
  const decryptEnd = process.hrtime.bigint();
  if (!recovered || !recovered.equals(payload)) {
    throw new Error("KEM-DEM plaintext mismatch");
  }
  return {
    encryptMs: elapsedMs(encryptStart, encryptEnd),
    decryptMs: elapsedMs(encryptEnd, decryptEnd),
  };
}

const payload = Buffer.alloc(payloadBytes, 0x54);
const rows = [
  "implementation,scheme,operation,policy_attributes,repetition,payload_bytes,latency_ms,success",
];

for (const attributeCount of policySizes) {
  const context = makeContext(attributeCount);
  for (let index = 0; index < warmups; index++) execute(context, payload);
  for (let repetition = 0; repetition < repetitions; repetition++) {
    const timings = execute(context, payload);
    rows.push(
      `kem_dem_baseline,LSSS_secp256k1_ECIES_AES256GCM,encrypt,${attributeCount},${repetition},${payloadBytes},${timings.encryptMs.toFixed(6)},true`
    );
    rows.push(
      `kem_dem_baseline,LSSS_secp256k1_ECIES_AES256GCM,decrypt,${attributeCount},${repetition},${payloadBytes},${timings.decryptMs.toFixed(6)},true`
    );
  }
}

process.stdout.write(rows.join("\n") + "\n");
