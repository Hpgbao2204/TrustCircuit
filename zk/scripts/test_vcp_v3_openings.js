"use strict";

// Commitment-opening test for VCP v3. With the public statement fixed, a
// witness exists only for the correct openings: changing the policy salt,
// the result opening, the context salt, the released result, or one policy
// entry makes witness generation fail, because the recomputed commitment no
// longer equals the public ph, y_h, or c_zk. The valid opening is also proved
// and verified end to end.
//
// Run:    npx hardhat run zk/scripts/test_vcp_v3_openings.js
// Output: results/raw/vcp_v3_openings.json (new file; no evidence is overwritten)

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { ethers } = require("hardhat");
const enc = require("../../scripts/lib/vcp_v3_encoding");
const { poseidon } = require("../../scripts/lib/v3_stack");

const ROOT = path.resolve(__dirname, "..", "..");
const BUILD = path.join(ROOT, "zk", "build", "v3");
const WASM = path.join(BUILD, "vcp_v3_js", "vcp_v3.wasm");
const ZKEY = path.join(BUILD, "vcp_v3_final.zkey");
const VKEY = path.join(BUILD, "vcp_v3_vkey.json");
const OUT = path.join(ROOT, "results", "raw", "vcp_v3_openings.json");
const FR = 21888242871839275222717131064964665186774689052522876004126218863519127025617n;

function context() {
  return {
    requestKey: ethers.id("openings:request"),
    assetKey: ethers.id("openings:asset"),
    consumerKey: ethers.id("openings:consumer"),
    dataCommitment: enc.saltedDataCommitment(ethers.id("openings:dataset"), enc.randomBytes32()),
    dpConfigHash: enc.dpConfigHash(4_844_805n, 1_000_000n, ethers.id("gaussian:count:v1")),
    freshnessNonce: enc.randomBytes32(),
    policyVersion: 1n,
    purposeId: 1n,
    functionId: 2n,
    reservedCost: 1_394_200n,
    actualCost: 1_394_200n,
    policyMatrix: [[1, 1], [0, 1]],
    policySalt: enc.randomField(),
    contextSalt: enc.randomField(),
    resultOpening: enc.randomField(),
    releasedResult: 4242n,
    enclaveMeasurement: ethers.id("nitro:pcr0:approved"),
  };
}

const bump = (v) => ((BigInt(v) + 1n) % FR).toString();

async function witnessExists(input) {
  try {
    await snarkjs.wtns.calculate(input, WASM, { type: "mem" });
    return true;
  } catch (_) {
    return false;
  }
}

async function main() {
  const p = await poseidon();
  const ctx = context();
  const statement = {
    nativeDigest: ethers.id("native:openings"),
    contextCommitment: enc.contextOf(p, ctx),
    expiresAtUnixMs: 4_102_444_800_000n,
    validatorIds: [ethers.id("validator:1"), ethers.id("validator:2")],
    signatures: [`0x${"11".repeat(65)}`, `0x${"22".repeat(65)}`],
  };
  const input = enc.buildProofInputV3(p, ctx, statement).input;

  const { proof, publicSignals } = await snarkjs.groth16.fullProve(input, WASM, ZKEY);
  const vkey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const validVerifies = await snarkjs.groth16.verify(vkey, publicSignals, proof);

  // Each case changes one private opening and keeps the public statement fixed.
  const cases = [
    ["wrong policy salt r_Pi (ph)", (x) => { x.policySalt = bump(x.policySalt); }],
    ["wrong result opening r_y (y_h)", (x) => { x.resultOpening = bump(x.resultOpening); }],
    ["wrong context salt r_chi (c_zk)", (x) => { x.contextSalt = bump(x.contextSalt); }],
    ["wrong released result (y_h)", (x) => { x.releasedResult = bump(x.releasedResult); }],
    ["flipped policy entry M[0][0] (ph)", (x) => { x.policyMatrix[0][0] = x.policyMatrix[0][0] === "1" ? "0" : "1"; }],
  ];
  const results = [{ case: "valid openings", witness: await witnessExists(input), proof_verifies: validVerifies }];
  for (const [name, mutate] of cases) {
    const x = JSON.parse(JSON.stringify(input));
    mutate(x);
    results.push({ case: name, witness: await witnessExists(x) });
  }

  const pass = results[0].witness && validVerifies && results.slice(1).every((r) => !r.witness);
  const out = { circuit: "vcp_v3", generated_at: new Date().toISOString(), pass, results };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, `${JSON.stringify(out, null, 2)}\n`);
  console.table(results);
  console.log(pass ? "PASS" : "FAIL", "->", path.relative(ROOT, OUT));
  if (!pass) process.exitCode = 1;
}

// snarkjs keeps curve worker threads alive, so exit explicitly.
main()
  .then(() => process.exit(process.exitCode || 0))
  .catch((e) => { console.error(e); process.exit(1); });
