/*
 * Real Groth16 benchmark for the TrustCircuit Verifiable Compliance relation.
 *
 * Pipeline (all local, Windows-friendly):
 *   circom (tools/circom.exe) -> r1cs/wasm
 *   snarkjs powers-of-tau (phase 1, reused)
 *   snarkjs groth16 setup + contribute (phase 2, per circuit)
 *   circomlibjs Poseidon -> valid/invalid witness inputs
 *   snarkjs groth16 prove / verify (timed, repeated)
 *   exported Solidity verifier for the base circuit
 *
 * Outputs:
 *   results/raw/zk_benchmark.csv
 *   results/summary/zk_benchmark_summary.csv
 *   results/summary/zk_benchmark_config.json
 *   contracts/ComplianceGroth16Verifier.sol   (base circuit, on-chain verify)
 *   zk/build/...                               (intermediate artifacts)
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync } = require("child_process");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");

const ROOT = path.resolve(__dirname, "..", "..");
const CIRCOM = path.join(ROOT, "tools", "circom.exe");
const SNARKJS_CLI = path.join(ROOT, "node_modules", "snarkjs", "build", "cli.cjs");
const CIRCOMLIB = path.join(ROOT, "node_modules", "circomlib", "circuits");
const BUILD = path.join(ROOT, "zk", "build");
const RAW = path.join(ROOT, "results", "raw", "zk_benchmark.csv");
const SUMMARY = path.join(ROOT, "results", "summary", "zk_benchmark_summary.csv");
const CONFIG = path.join(ROOT, "results", "summary", "zk_benchmark_config.json");
const SOLIDITY = path.join(ROOT, "contracts", "ComplianceGroth16Verifier.sol");

const RULE_SIZES = [1, 2, 4, 6, 8, 10];
const BASE_RULES = 2;
const PROVE_REPS = 12;
const PTAU_POWER = 15;
const BUDGET_BITS = 64;

function sh(cmd, args) {
  return execFileSync(cmd, args, { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], maxBuffer: 1 << 26 }).toString();
}

function snk(args) {
  return sh("node", [SNARKJS_CLI, ...args]);
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function fileSize(p) {
  return fs.existsSync(p) ? fs.statSync(p).size : 0;
}

function mean(a) {
  return a.reduce((s, x) => s + x, 0) / a.length;
}

function std(a) {
  if (a.length < 2) return 0;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length);
}

function percentile(a, p) {
  const s = [...a].sort((x, y) => x - y);
  const idx = (s.length - 1) * (p / 100);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

function writeCircuit(nRules) {
  // compliance_check.circom declares its own main; wrappers include the stripped
  // library copy and own the main component with the chosen rule count.
  const wrapper = `pragma circom 2.1.6;
include "${path.join(ROOT, "zk", "circuits").replace(/\\/g, "/")}/compliance_lib.circom";
component main {public [assetId, consumerId, requestId, policyHash, epsilonCost, nullifier, attestationHash]} = ComplianceCheck(${nRules}, ${BUDGET_BITS});
`;
  const p = path.join(BUILD, `compliance_${nRules}.circom`);
  fs.writeFileSync(p, wrapper);
  return p;
}

function parseConstraints(r1csInfo) {
  const m = r1csInfo.match(/# of Constraints:\s*(\d+)/i) || r1csInfo.match(/Constraints:\s*(\d+)/i);
  return m ? Number(m[1]) : NaN;
}

async function buildInputs(poseidon, nRules, mode) {
  const F = poseidon.F;
  const assetId = 111n;
  const consumerId = 222n;
  const requestId = 333n;
  const policyHash = 444n;
  const secretNonce = 555n;
  const maxBudget = 5_000_000n;
  let epsilonCost = 500_000n;
  let allowedPolicyHash = policyHash;

  const nullifier = F.toObject(poseidon([consumerId, requestId, secretNonce]));
  const attestationHash = F.toObject(poseidon([assetId, requestId, policyHash, epsilonCost]));
  const policyField = Array.from({ length: nRules }, (_, i) => BigInt(1000 + i));

  if (mode === "invalid_policy") allowedPolicyHash = policyHash + 1n;
  if (mode === "invalid_budget") epsilonCost = maxBudget + 1n;
  if (mode === "invalid_nullifier") {
    return base(epsilonCost, allowedPolicyHash, nullifier + 1n, attestationHash, policyField);
  }
  // recompute attestation if epsilon changed
  const att = F.toObject(poseidon([assetId, requestId, policyHash, epsilonCost]));

  function base(eps, allowed, nul, attH, pf) {
    return {
      assetId: assetId.toString(),
      consumerId: consumerId.toString(),
      requestId: requestId.toString(),
      policyHash: policyHash.toString(),
      epsilonCost: eps.toString(),
      nullifier: nul.toString(),
      attestationHash: attH.toString(),
      allowedPolicyHash: allowed.toString(),
      maxBudget: maxBudget.toString(),
      secretNonce: secretNonce.toString(),
      policyField: pf.map((x) => x.toString()),
    };
  }
  return base(epsilonCost, allowedPolicyHash, nullifier, att, policyField);
}

async function main() {
  ensureDir(BUILD);
  ensureDir(path.dirname(RAW));
  ensureDir(path.dirname(SUMMARY));

  // Make the template available to wrappers under a stable name.
  fs.copyFileSync(path.join(ROOT, "zk", "circuits", "compliance_check.circom"),
    path.join(ROOT, "zk", "circuits", "compliance_lib.circom"));
  // Strip the trailing `component main` from the lib copy so wrappers own main.
  const libPath = path.join(ROOT, "zk", "circuits", "compliance_lib.circom");
  let lib = fs.readFileSync(libPath, "utf8").replace(/component main[\s\S]*$/m, "\n");
  fs.writeFileSync(libPath, lib);

  // ---- Phase 1: powers of tau (circuit independent, reused) ----
  const pot0 = path.join(BUILD, `pot${PTAU_POWER}_0.ptau`);
  const pot1 = path.join(BUILD, `pot${PTAU_POWER}_1.ptau`);
  const potFinal = path.join(BUILD, `pot${PTAU_POWER}_final.ptau`);
  if (!fs.existsSync(potFinal)) {
    console.log("[zk] powers of tau phase 1 ...");
    snk(["powersoftau", "new", "bn128", String(PTAU_POWER), pot0, "-v"]);
    snk(["powersoftau", "contribute", pot0, pot1, "--name=trustcircuit", "-v", "-e=trustcircuit-entropy-1"]);
    snk(["powersoftau", "prepare", "phase2", pot1, potFinal, "-v"]);
  }

  const poseidon = await buildPoseidon();
  const rows = [];

  for (const nRules of RULE_SIZES) {
    console.log(`[zk] circuit nRules=${nRules}`);
    const circuit = writeCircuit(nRules);
    const name = `compliance_${nRules}`;

    // compile
    sh(CIRCOM, [circuit, "--r1cs", "--wasm", "--sym", "-o", BUILD, "-l", CIRCOMLIB]);
    const r1cs = path.join(BUILD, `${name}.r1cs`);
    const wasm = path.join(BUILD, `${name}_js`, `${name}.wasm`);
    const info = snk(["r1cs", "info", r1cs]);
    const constraints = parseConstraints(info);

    // phase 2 setup
    const zkey0 = path.join(BUILD, `${name}_0.zkey`);
    const zkey = path.join(BUILD, `${name}_final.zkey`);
    const vkeyPath = path.join(BUILD, `${name}_vkey.json`);
    snk(["groth16", "setup", r1cs, potFinal, zkey0]);
    snk(["zkey", "contribute", zkey0, zkey, "--name=tc2", "-v", "-e=trustcircuit-entropy-2"]);
    snk(["zkey", "export", "verificationkey", zkey, vkeyPath]);
    const vkey = JSON.parse(fs.readFileSync(vkeyPath, "utf8"));

    // valid witness + proof timing
    const input = await buildInputs(poseidon, nRules, "valid");
    const wtns = path.join(BUILD, `${name}_witness.wtns`);
    await snarkjs.wtns.calculate(input, wasm, wtns);

    const proveTimes = [];
    const verifyTimes = [];
    let proofBytes = 0;
    let peakRss = 0;
    let lastProof = null;
    let lastPublic = null;
    for (let i = 0; i < PROVE_REPS; i++) {
      const t0 = process.hrtime.bigint();
      const { proof, publicSignals } = await snarkjs.groth16.prove(zkey, wtns);
      const t1 = process.hrtime.bigint();
      proveTimes.push(Number(t1 - t0) / 1e6);
      lastProof = proof;
      lastPublic = publicSignals;
      const v0 = process.hrtime.bigint();
      const ok = await snarkjs.groth16.verify(vkey, publicSignals, proof);
      const v1 = process.hrtime.bigint();
      verifyTimes.push(Number(v1 - v0) / 1e6);
      if (!ok) throw new Error(`verify failed for ${name}`);
      peakRss = Math.max(peakRss, process.memoryUsage().rss);
      proofBytes = Buffer.byteLength(JSON.stringify({ proof, publicSignals }));
    }

    // negative cases: witness generation / verification must fail
    const negatives = {};
    for (const mode of ["invalid_policy", "invalid_budget", "invalid_nullifier"]) {
      const ninput = await buildInputs(poseidon, nRules, mode);
      let rejected = false;
      try {
        const nw = path.join(BUILD, `${name}_${mode}.wtns`);
        await snarkjs.wtns.calculate(ninput, wasm, nw);
        // if witness computed, the proof must fail to verify against honest vkey
        const { proof, publicSignals } = await snarkjs.groth16.prove(zkey, nw);
        const ok = await snarkjs.groth16.verify(vkey, publicSignals, proof);
        rejected = !ok;
      } catch (e) {
        rejected = true; // unsatisfied constraint -> witness/proof rejected
      }
      negatives[mode] = rejected;
    }

    rows.push({
      scheme: "groth16",
      curve: "bn128",
      circuit: name,
      n_rules: nRules,
      constraints,
      public_inputs: lastPublic ? lastPublic.length : 0,
      proof_size_bytes: proofBytes,
      prove_time_ms_mean: mean(proveTimes),
      prove_time_ms_std: std(proveTimes),
      prove_time_ms_p95: percentile(proveTimes, 95),
      verify_time_ms_mean: mean(verifyTimes),
      verify_time_ms_p95: percentile(verifyTimes, 95),
      proving_key_bytes: fileSize(zkey),
      verification_key_bytes: fileSize(vkeyPath),
      r1cs_bytes: fileSize(r1cs),
      peak_rss_mb: peakRss / (1024 * 1024),
      reps: PROVE_REPS,
      reject_invalid_policy: negatives.invalid_policy,
      reject_invalid_budget: negatives.invalid_budget,
      reject_invalid_nullifier: negatives.invalid_nullifier,
    });

    if (nRules === BASE_RULES) {
      snk(["zkey", "export", "solidityverifier", zkey, SOLIDITY]);
      // export proof + public signals, then Solidity calldata for a gas test
      fs.writeFileSync(path.join(BUILD, `${name}_proof.json`), JSON.stringify(lastProof));
      fs.writeFileSync(path.join(BUILD, `${name}_public.json`), JSON.stringify(lastPublic));
      const calldata = snk(["zkey", "export", "soliditycalldata",
        path.join(BUILD, `${name}_public.json`), path.join(BUILD, `${name}_proof.json`)]);
      fs.writeFileSync(path.join(BUILD, `${name}_calldata.txt`), calldata.trim());
    }
  }

  // write raw csv
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(RAW, [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))].join("\n") + "\n");

  // summary == same rows here (one row per circuit); keep both for the pipeline
  fs.writeFileSync(SUMMARY, [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))].join("\n") + "\n");

  fs.writeFileSync(CONFIG, JSON.stringify({
    scheme: "groth16",
    curve: "bn128",
    hash: "poseidon (circomlib)",
    ptau_power: PTAU_POWER,
    budget_bits: BUDGET_BITS,
    rule_sizes: RULE_SIZES,
    base_rules: BASE_RULES,
    prove_reps: PROVE_REPS,
    circom_version: sh(CIRCOM, ["--version"]).trim(),
    snarkjs_version: require(path.join(ROOT, "node_modules", "snarkjs", "package.json")).version,
    node: process.version,
    platform: `${os.platform()} ${os.release()}`,
    cpus: os.cpus().length,
    note: "Real Groth16 over BN254 with Poseidon; local Windows measurement.",
  }, null, 2));

  console.log(RAW);
  console.log(SUMMARY);
  console.log(SOLIDITY);
}

main().then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); });
