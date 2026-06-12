/*
 * Measure on-chain verification gas for the three exported compliance verifiers
 * (Groth16, PLONK, fflonk) using the real proof calldata from
 * benchmark_zk_schemes.js. Writes results/summary/zk_schemes_gas.csv.
 */
const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

const BUILD = path.join(__dirname, "..", "zk", "build");
const SCHEMES = [
  { scheme: "groth16", contract: "Groth16Verifier", calldata: "cmp_2_groth16_calldata.txt" },
  { scheme: "plonk", contract: "PlonkVerifier", calldata: "cmp_2_plonk_calldata.txt" },
  { scheme: "fflonk", contract: "FflonkVerifier", calldata: "cmp_2_fflonk_calldata.txt" },
];

async function main() {
  const rows = [];
  for (const s of SCHEMES) {
    const cdPath = path.join(BUILD, s.calldata);
    if (!fs.existsSync(cdPath)) {
      console.log(`skip ${s.scheme}: no calldata`);
      continue;
    }
    const raw = fs.readFileSync(cdPath, "utf8").trim();
    // Tolerant parse: snarkjs emits quoted hex (groth16/plonk), unquoted hex
    // (fflonk), and sometimes bare decimal public signals. Normalise to JSON.
    let norm = raw.replace(/"/g, "");
    norm = norm.replace(/0x[0-9a-fA-F]+/g, (m) => `"${m}"`);
    norm = norm.replace(/(?<=[\[,])(\d+)(?=[\],])/g, '"$1"');
    // snarkjs separates top-level arrays inconsistently: groth16/fflonk use
    // "],[", but plonk emits "][" (newline, no comma). Normalise to "],[".
    norm = norm.replace(/\]\s*\[/g, "],[");
    const args = JSON.parse(`[${norm}]`);
    const Factory = await ethers.getContractFactory(s.contract);
    const verifier = await Factory.deploy();
    await verifier.waitForDeployment();
    const deployRcpt = await verifier.deploymentTransaction().wait();

    let ok = false;
    let gas = 0n;
    try {
      ok = await verifier.verifyProof(...args);
      gas = await verifier.verifyProof.estimateGas(...args);
    } catch (e) {
      console.log(`${s.scheme} verify/estimate error: ${e.message}`);
    }
    rows.push({ scheme: s.scheme, verify_gas: gas.toString(), deploy_gas: deployRcpt.gasUsed.toString(), verified: ok });
    console.log(`${s.scheme}: verify_gas=${gas} deploy_gas=${deployRcpt.gasUsed} verified=${ok}`);
  }

  const out = path.join(__dirname, "..", "results", "summary", "zk_schemes_gas.csv");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const headers = "scheme,verify_gas,deploy_gas,verified";
  fs.writeFileSync(out, `${headers}\n${rows.map((r) => `${r.scheme},${r.verify_gas},${r.deploy_gas},${r.verified}`).join("\n")}\n`);
  console.log(out);
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
