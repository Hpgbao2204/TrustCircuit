/*
 * Measure on-chain Groth16 verification gas for the exported compliance verifier.
 *
 * Uses the real proof/public-signal calldata produced by benchmark_zk.js
 * (zk/build/compliance_2_calldata.txt) against the exported
 * contracts/ComplianceGroth16Verifier.sol (snarkjs Groth16Verifier).
 *
 * Appends a row to results/raw/zk_benchmark.csv-companion file
 * results/summary/zk_onchain_gas.csv.
 */
const fs = require("fs");
const path = require("path");
const { ethers, artifacts } = require("hardhat");

async function main() {
  const buildDir = path.join(__dirname, "..", "zk", "build");
  const calldataPath = path.join(buildDir, "compliance_2_calldata.txt");
  if (!fs.existsSync(calldataPath)) {
    throw new Error("calldata not found; run `npm run zk:benchmark` first");
  }
  const raw = fs.readFileSync(calldataPath, "utf8").trim();
  const [a, b, c, input] = JSON.parse(`[${raw}]`);

  const Verifier = await ethers.getContractFactory("Groth16Verifier");
  const verifier = await Verifier.deploy();
  await verifier.waitForDeployment();

  const ok = await verifier.verifyProof(a, b, c, input);
  if (!ok) throw new Error("on-chain verification returned false");

  // estimateGas on the view function = intrinsic + calldata + execution cost
  const gas = await verifier.verifyProof.estimateGas(a, b, c, input);

  const deployTx = verifier.deploymentTransaction();
  const deployRcpt = await deployTx.wait();

  const out = path.join(__dirname, "..", "results", "summary", "zk_onchain_gas.csv");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const headers = "scheme,curve,circuit,public_inputs,verify_gas,deploy_gas,verified";
  const row = `groth16,bn128,compliance_2,${input.length},${gas.toString()},${deployRcpt.gasUsed.toString()},${ok}`;
  fs.writeFileSync(out, `${headers}\n${row}\n`);

  console.log(`verify_gas=${gas.toString()} deploy_gas=${deployRcpt.gasUsed.toString()} verified=${ok}`);
  console.log(out);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
