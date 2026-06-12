/*
 * Multi-scheme proof-system comparison for the TrustCircuit compliance relation.
 *
 * Instantiates the SAME Circom compliance circuit (base, 2 composable rules)
 * under three EVM-verifiable argument systems and measures the trade-off:
 *   - Groth16  (per-circuit trusted setup, smallest proof/gas)
 *   - PLONK    (universal/updatable trusted setup)
 *   - fflonk   (universal setup, FFT-friendly, larger proof, cheaper prover)
 *
 * For each scheme it records prove/verify time, proof size, proving- and
 * verification-key sizes, and peak RSS, and exports a Solidity verifier so the
 * companion Hardhat script can measure on-chain verification gas.
 *
 * Outputs:
 *   results/raw/zk_schemes.csv
 *   results/summary/zk_schemes_summary.csv
 *   results/summary/zk_schemes_config.json
 *   contracts/ComplianceGroth16Verifier.sol
 *   contracts/CompliancePlonkVerifier.sol
 *   contracts/ComplianceFflonkVerifier.sol
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
const RAW = path.join(ROOT, "results", "raw", "zk_schemes.csv");
const SUMMARY = path.join(ROOT, "results", "summary", "zk_schemes_summary.csv");
const CONFIG = path.join(ROOT, "results", "summary", "zk_schemes_config.json");

const PTAU_POWER = 16;
const BUDGET_BITS = 64;
const RULES = 2;
const REPS = 12;

const SCHEMES = [
  { name: "groth16", setupModel: "per-circuit", solidity: "ComplianceGroth16Verifier.sol" },
  { name: "plonk", setupModel: "universal", solidity: "CompliancePlonkVerifier.sol" },
  { name: "fflonk", setupModel: "universal", solidity: "ComplianceFflonkVerifier.sol" },
];

function sh(cmd, args) {
  return execFileSync(cmd, args, { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], maxBuffer: 1 << 26 }).toString();
}
function snk(args) { return sh("node", [SNARKJS_CLI, ...args]); }
function ensureDir(p) { fs.mkdirSync(p, { recursive: true }); }
function fileSize(p) { return fs.existsSync(p) ? fs.statSync(p).size : 0; }
function mean(a) { return a.reduce((s, x) => s + x, 0) / a.length; }
function std(a) { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length); }

async function buildInput(poseidon, nRules) {
  const F = poseidon.F;
  const assetId = 111n, consumerId = 222n, requestId = 333n, policyHash = 444n, secretNonce = 555n;
  const maxBudget = 5_000_000n, epsilonCost = 500_000n;
  const nullifier = F.toObject(poseidon([consumerId, requestId, secretNonce]));
  const attestationHash = F.toObject(poseidon([assetId, requestId, policyHash, epsilonCost]));
  return {
    assetId: "111", consumerId: "222", requestId: "333", policyHash: "444",
    epsilonCost: epsilonCost.toString(), nullifier: nullifier.toString(),
    attestationHash: attestationHash.toString(), allowedPolicyHash: "444",
    maxBudget: maxBudget.toString(), secretNonce: "555",
    policyField: Array.from({ length: nRules }, (_, i) => String(1000 + i)),
  };
}

async function main() {
  ensureDir(BUILD); ensureDir(path.dirname(RAW)); ensureDir(path.dirname(SUMMARY));

  // stripped library copy so the wrapper owns `component main`
  const libPath = path.join(ROOT, "zk", "circuits", "compliance_lib.circom");
  fs.copyFileSync(path.join(ROOT, "zk", "circuits", "compliance_check.circom"), libPath);
  fs.writeFileSync(libPath, fs.readFileSync(libPath, "utf8").replace(/component main[\s\S]*$/m, "\n"));

  // universal powers of tau (large enough for fflonk blow-up)
  const pot0 = path.join(BUILD, `pot${PTAU_POWER}_0.ptau`);
  const pot1 = path.join(BUILD, `pot${PTAU_POWER}_1.ptau`);
  const potFinal = path.join(BUILD, `pot${PTAU_POWER}_final.ptau`);
  if (!fs.existsSync(potFinal)) {
    console.log(`[zk-cmp] powers of tau 2^${PTAU_POWER} ...`);
    snk(["powersoftau", "new", "bn128", String(PTAU_POWER), pot0, "-v"]);
    snk(["powersoftau", "contribute", pot0, pot1, "--name=tc", "-v", "-e=tc-cmp-entropy"]);
    snk(["powersoftau", "prepare", "phase2", pot1, potFinal, "-v"]);
  }

  // compile base circuit
  const name = `cmp_${RULES}`;
  const circuit = path.join(BUILD, `${name}.circom`);
  fs.writeFileSync(circuit, `pragma circom 2.1.6;
include "${path.join(ROOT, "zk", "circuits").replace(/\\/g, "/")}/compliance_lib.circom";
component main {public [assetId, consumerId, requestId, policyHash, epsilonCost, nullifier, attestationHash]} = ComplianceCheck(${RULES}, ${BUDGET_BITS});
`);
  console.log("[zk-cmp] compiling base circuit ...");
  sh(CIRCOM, [circuit, "--r1cs", "--wasm", "--sym", "-o", BUILD, "-l", CIRCOMLIB]);
  const r1cs = path.join(BUILD, `${name}.r1cs`);
  const wasm = path.join(BUILD, `${name}_js`, `${name}.wasm`);
  const info = snk(["r1cs", "info", r1cs]);
  const constraints = Number((info.match(/# of Constraints:\s*(\d+)/i) || [])[1] || NaN);

  const poseidon = await buildPoseidon();
  const input = await buildInput(poseidon, RULES);
  const wtns = path.join(BUILD, `${name}.wtns`);
  await snarkjs.wtns.calculate(input, wasm, wtns);

  const rows = [];
  for (const scheme of SCHEMES) {
    console.log(`[zk-cmp] scheme=${scheme.name}`);
    const zkey = path.join(BUILD, `${name}_${scheme.name}.zkey`);
    const vkeyPath = path.join(BUILD, `${name}_${scheme.name}_vkey.json`);
    try {
      if (scheme.name === "groth16") {
        const zkey0 = path.join(BUILD, `${name}_groth16_0.zkey`);
        snk(["groth16", "setup", r1cs, potFinal, zkey0]);
        snk(["zkey", "contribute", zkey0, zkey, "--name=tc2", "-v", "-e=tc-cmp-2"]);
      } else if (scheme.name === "plonk") {
        snk(["plonk", "setup", r1cs, potFinal, zkey]);
      } else if (scheme.name === "fflonk") {
        snk(["fflonk", "setup", r1cs, potFinal, zkey]);
      }
      snk(["zkey", "export", "verificationkey", zkey, vkeyPath]);
      const vkey = JSON.parse(fs.readFileSync(vkeyPath, "utf8"));

      const proveTimes = [], verifyTimes = [];
      let proofBytes = 0, peakRss = 0, lastProof = null, lastPublic = null;
      for (let i = 0; i < REPS; i++) {
        const t0 = process.hrtime.bigint();
        const { proof, publicSignals } = await snarkjs[scheme.name].prove(zkey, wtns);
        const t1 = process.hrtime.bigint();
        proveTimes.push(Number(t1 - t0) / 1e6);
        const v0 = process.hrtime.bigint();
        const ok = await snarkjs[scheme.name].verify(vkey, publicSignals, proof);
        const v1 = process.hrtime.bigint();
        verifyTimes.push(Number(v1 - v0) / 1e6);
        if (!ok) throw new Error(`verify failed for ${scheme.name}`);
        peakRss = Math.max(peakRss, process.memoryUsage().rss);
        proofBytes = Buffer.byteLength(JSON.stringify({ proof, publicSignals }));
        lastProof = proof; lastPublic = publicSignals;
      }

      // export Solidity verifier + calldata
      const solOut = path.join(ROOT, "contracts", scheme.solidity);
      snk(["zkey", "export", "solidityverifier", zkey, solOut]);
      fs.writeFileSync(path.join(BUILD, `${name}_${scheme.name}_proof.json`), JSON.stringify(lastProof));
      fs.writeFileSync(path.join(BUILD, `${name}_${scheme.name}_public.json`), JSON.stringify(lastPublic));
      let calldataOk = true;
      try {
        const calldata = snk(["zkey", "export", "soliditycalldata",
          path.join(BUILD, `${name}_${scheme.name}_public.json`),
          path.join(BUILD, `${name}_${scheme.name}_proof.json`)]);
        fs.writeFileSync(path.join(BUILD, `${name}_${scheme.name}_calldata.txt`), calldata.trim());
      } catch (e) { calldataOk = false; console.log(`[zk-cmp] calldata export failed for ${scheme.name}: ${e.message}`); }

      rows.push({
        scheme: scheme.name,
        setup_model: scheme.setupModel,
        curve: "bn128",
        constraints,
        public_inputs: lastPublic.length,
        proof_size_bytes: proofBytes,
        prove_time_ms_mean: mean(proveTimes).toFixed(3),
        prove_time_ms_std: std(proveTimes).toFixed(3),
        verify_time_ms_mean: mean(verifyTimes).toFixed(3),
        proving_key_bytes: fileSize(zkey),
        verification_key_bytes: fileSize(vkeyPath),
        peak_rss_mb: (peakRss / (1024 * 1024)).toFixed(1),
        reps: REPS,
        calldata_exported: calldataOk,
      });
    } catch (e) {
      console.log(`[zk-cmp] scheme ${scheme.name} failed: ${e.message}`);
      rows.push({
        scheme: scheme.name, setup_model: scheme.setupModel, curve: "bn128", constraints,
        public_inputs: "", proof_size_bytes: "", prove_time_ms_mean: "", prove_time_ms_std: "",
        verify_time_ms_mean: "", proving_key_bytes: "", verification_key_bytes: "", peak_rss_mb: "",
        reps: REPS, calldata_exported: false
      });
    }
  }

  const headers = Object.keys(rows[0]);
  const csv = [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))].join("\n") + "\n";
  fs.writeFileSync(RAW, csv);
  fs.writeFileSync(SUMMARY, csv);
  fs.writeFileSync(CONFIG, JSON.stringify({
    schemes: SCHEMES.map((s) => s.name), curve: "bn128", hash: "poseidon",
    rules: RULES, budget_bits: BUDGET_BITS, ptau_power: PTAU_POWER, reps: REPS,
    circom_version: sh(CIRCOM, ["--version"]).trim(),
    snarkjs_version: require(path.join(ROOT, "node_modules", "snarkjs", "package.json")).version,
    node: process.version, platform: `${os.platform()} ${os.release()}`, cpus: os.cpus().length,
    note: "Same compliance circuit instantiated under Groth16/PLONK/fflonk; local Windows measurement.",
  }, null, 2));
  console.log(RAW);
}

main().then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); });
