/*
 * Experiment 5 (Q1 plan): proof-binding attacks.
 *
 * A cryptographically valid Groth16 proof is NOT sufficient for compliance: a
 * proof must be bound to the exact request, asset, consumer, policy, epsilon
 * ceiling and a single-use nullifier. We replay one honest proof under seven
 * misuse cases against three verifier designs:
 *
 *   MockComplianceVerifier  - records a boolean; no real check (always accepts).
 *   Groth16Verifier (raw)   - checks crypto validity only; ignores binding.
 *   ComplianceVerifier      - the TrustCircuit adapter; binds + budget + nullifier.
 *
 * A secure design must REJECT every attack while accepting the honest case.
 *
 * Output:
 *   results/q1/raw/proof_binding_attacks.csv
 *
 * Usage: npx hardhat run benchmarks/proof_binding_attacks.js
 */
const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

const ROOT = path.resolve(__dirname, "..");
// benchmark_zk_schemes.js exports both this calldata and the final
// ComplianceGroth16Verifier.sol from the same Groth16 setup. Using the scaling
// benchmark's calldata here would pair a proof with a different proving key.
const CALLDATA = path.join(ROOT, "zk", "build", "cmp_2_groth16_calldata.txt");
const SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

function loadCalldata() {
  const raw = fs.readFileSync(CALLDATA, "utf8").trim();
  const [a, b, c, input] = JSON.parse(`[${raw}]`);
  return { a, b, c, input };
}

function csvEscape(v) {
  const t = String(v ?? "");
  return /[",\n]/.test(t) ? `"${t.replaceAll('"', '""')}"` : t;
}

function writeCsv(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  const content = [headers.join(","), ...rows.map((r) => headers.map((h) => csvEscape(r[h])).join(","))].join("\n");
  fs.writeFileSync(filePath, `${content}\n`);
}

function idToField(requestId) {
  return BigInt(requestId) % SCALAR_FIELD;
}

// requestId (bytes32) whose field reduction equals `signal`.
function requestIdForSignal(signal) {
  return ethers.zeroPadValue(ethers.toBeHex(signal % SCALAR_FIELD), 32);
}

async function tryMock(mock, requestId, assetId) {
  // an attacker simply asserts accepted=true; mock has no real verification.
  try {
    const tx = await mock.submitProof(requestId, assetId, ethers.id("p"), true);
    const rec = await tx.wait();
    return { accepted: true, gas: rec.gasUsed.toString(), reason: "" };
  } catch (e) {
    return { accepted: false, gas: "", reason: e.shortMessage || e.message };
  }
}

async function tryRaw(raw, a, b, c, input) {
  // raw verifier only checks crypto validity, ignores application binding.
  try {
    const ok = await raw.verifyProof(a, b, c, input);
    return { accepted: Boolean(ok), gas: "", reason: ok ? "" : "crypto_invalid" };
  } catch (e) {
    return { accepted: false, gas: "", reason: e.shortMessage || e.message };
  }
}

async function tryAdapter(adapter, requestId, expectation, a, b, c, input) {
  // register expectation (owner) then submit; capture revert reason + gas.
  try {
    await (await adapter.registerExpectation(requestId, expectation)).wait();
  } catch (e) {
    return { accepted: false, gas: "", reason: `register:${e.shortMessage || e.message}` };
  }
  try {
    const tx = await adapter.submitCompliance(requestId, a, b, c, input);
    const rec = await tx.wait();
    return { accepted: true, gas: rec.gasUsed.toString(), reason: "" };
  } catch (e) {
    return { accepted: false, gas: "", reason: e.shortMessage || e.message };
  }
}

async function main() {
  const { a, b, c, input } = loadCalldata();
  const request = BigInt(input[0]);
  const asset = BigInt(input[1]);
  const consumer = BigInt(input[2]);
  const policy = BigInt(input[3]);
  const epsilon = BigInt(input[7]);
  const honestRequestId = requestIdForSignal(request);
  const honestExp = {
    requestId: request,
    assetId: asset,
    consumerId: consumer,
    policyHash: policy,
    policyVersion: BigInt(input[4]),
    functionId: BigInt(input[5]),
    resultHash: BigInt(input[6]),
    maxEpsilon: 5_000_000n,
    transcriptHash: BigInt(input[9]),
    attestationDigest: BigInt(input[10]),
    attestationExpiresAtUnixMs: 4_102_444_800_000n,
  };

  const Mock = await ethers.getContractFactory("MockComplianceVerifier");
  const Raw = await ethers.getContractFactory("Groth16Verifier");
  const Adapter = await ethers.getContractFactory("ComplianceVerifier");

  const mock = await Mock.deploy(); await mock.waitForDeployment();
  const raw = await Raw.deploy(); await raw.waitForDeployment();

  const rows = [];

  async function freshAdapter() {
    const rawV = await Raw.deploy(); await rawV.waitForDeployment();
    const ad = await Adapter.deploy(await rawV.getAddress()); await ad.waitForDeployment();
    return ad;
  }

  // tampered proof: flip the low limb of a[0] while keeping field membership.
  const tamperedA = [...a];
  tamperedA[0] = (BigInt(a[0]) ^ 1n).toString();

  const cases = [
    {
      name: "honest_valid",
      // baseline: must be accepted by the adapter.
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        const ap = await tryAdapter(ad, honestRequestId, honestExp, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "reuse_other_requestId",
      run: async () => {
        const ad = await freshAdapter();
        const otherReq = requestIdForSignal(request + 12345n);
        // register a DIFFERENT request, submit the proof whose request signal
        // still encodes the original -> must mismatch.
        const m = await tryMock(mock, otherReq, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        const ap = await tryAdapter(ad, otherReq, honestExp, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "reuse_other_assetId",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset + 7n));
        const r = await tryRaw(raw, a, b, c, input);
        const ap = await tryAdapter(ad, honestRequestId, { ...honestExp, assetId: asset + 7n }, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "reuse_other_consumerId",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        const ap = await tryAdapter(ad, honestRequestId, { ...honestExp, consumerId: consumer + 9n }, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "wrong_policyHash",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        const ap = await tryAdapter(ad, honestRequestId, { ...honestExp, policyHash: policy + 1n }, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "epsilon_above_budget",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        // register a budget ceiling BELOW the proven epsilon cost.
        const ap = await tryAdapter(ad, honestRequestId, { ...honestExp, maxEpsilon: epsilon - 1n }, a, b, c, input);
        return { m, r, ap };
      },
    },
    {
      name: "nullifier_replay",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, a, b, c, input);
        // first submission consumes the proof's nullifier and marks the request
        // verified; resubmitting the SAME proof must be rejected (replay).
        await (await ad.registerExpectation(honestRequestId, honestExp)).wait();
        await (await ad.submitCompliance(honestRequestId, a, b, c, input)).wait();
        let ap;
        try {
          const tx = await ad.submitCompliance(honestRequestId, a, b, c, input);
          const rec = await tx.wait();
          ap = { accepted: true, gas: rec.gasUsed.toString(), reason: "" };
        } catch (e) {
          ap = { accepted: false, gas: "", reason: e.shortMessage || e.message };
        }
        return { m, r, ap };
      },
    },
    {
      name: "tampered_proof",
      run: async () => {
        const ad = await freshAdapter();
        const m = await tryMock(mock, honestRequestId, requestIdForSignal(asset));
        const r = await tryRaw(raw, tamperedA, b, c, input);
        const ap = await tryAdapter(ad, honestRequestId, honestExp, tamperedA, b, c, input);
        return { m, r, ap };
      },
    },
  ];

  for (const tc of cases) {
    let res;
    try {
      res = await tc.run();
    } catch (e) {
      res = { m: { accepted: false, gas: "", reason: "harness_error" }, r: { accepted: false, gas: "", reason: "harness_error" }, ap: { accepted: false, gas: "", reason: e.message } };
    }
    rows.push({
      attack_case: tc.name,
      accepted_by_mock: res.m.accepted ? 1 : 0,
      accepted_by_raw_verifier: res.r.accepted ? 1 : 0,
      accepted_by_adapter: res.ap.accepted ? 1 : 0,
      adapter_revert_reason: res.ap.reason,
      adapter_gas_used: res.ap.gas,
      raw_reason: res.r.reason,
    });
    process.stdout.write(`[binding] ${tc.name}: mock=${res.m.accepted ? 1 : 0} raw=${res.r.accepted ? 1 : 0} adapter=${res.ap.accepted ? 1 : 0}\n`);
  }

  const out = path.join("results", "q1", "raw", "proof_binding_attacks.csv");
  writeCsv(out, rows);
  console.log(out);
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
