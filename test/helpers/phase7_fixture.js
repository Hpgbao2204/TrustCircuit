"use strict";

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");

const ROOT = path.resolve(__dirname, "..", "..");
const WASM = path.join(ROOT, "zk", "build", "phase7_js", "phase7.wasm");
const ZKEY = path.join(ROOT, "zk", "build", "phase7_final.zkey");

let fixturePromise;

function artifactsExist() {
  return fs.existsSync(WASM) && fs.existsSync(ZKEY);
}

async function createFixture() {
  if (!artifactsExist()) {
    throw new Error("run `node zk/scripts/build_phase7.js` before Phase 7 tests");
  }
  const poseidon = await buildPoseidon();
  const F = poseidon.F;
  const values = {
    requestId: 333n,
    assetId: 111n,
    consumerId: 222n,
    policyHash: 444n,
    policyVersion: 1n,
    functionId: 2n,
    resultHash: 666n,
    epsilonCost: 500_000n,
    transcriptHash: 777n,
    attestationDigest: 888n,
    secretNonce: 555n,
  };
  const context0 = F.toObject(
    poseidon([
      values.requestId,
      values.assetId,
      values.consumerId,
      values.policyHash,
      values.policyVersion,
    ])
  );
  const context1 = F.toObject(
    poseidon([
      values.functionId,
      values.resultHash,
      values.epsilonCost,
      values.transcriptHash,
      values.attestationDigest,
    ])
  );
  values.nullifier = F.toObject(
    poseidon([context0, context1, values.secretNonce])
  );
  const input = {
    requestId: values.requestId.toString(),
    assetId: values.assetId.toString(),
    consumerId: values.consumerId.toString(),
    policyHash: values.policyHash.toString(),
    policyVersion: values.policyVersion.toString(),
    functionId: values.functionId.toString(),
    resultHash: values.resultHash.toString(),
    epsilonCost: values.epsilonCost.toString(),
    nullifier: values.nullifier.toString(),
    transcriptHash: values.transcriptHash.toString(),
    attestationDigest: values.attestationDigest.toString(),
    allowedPolicyHash: values.policyHash.toString(),
    maxBudget: values.epsilonCost.toString(),
    secretNonce: values.secretNonce.toString(),
    policyField: ["1000", "1001"],
  };
  const { proof, publicSignals } = await snarkjs.groth16.fullProve(input, WASM, ZKEY);
  const calldata = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );
  return {
    values,
    input,
    proof,
    publicSignals,
    a: calldata[0],
    b: calldata[1],
    c: calldata[2],
    signals: calldata[3],
  };
}

function loadPhase7Fixture() {
  if (!fixturePromise) fixturePromise = createFixture();
  return fixturePromise;
}

module.exports = { artifactsExist, loadPhase7Fixture };

