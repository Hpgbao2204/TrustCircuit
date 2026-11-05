"use strict";

// Run: npx hardhat run scripts/revision/run_attack_matrix.js
// Output: results/raw/revision/attack_matrix.json and .csv

const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");
const { EXPECTED, runAttackMatrix } = require("./attack_scenarios");

const OUT = path.resolve(__dirname, "..", "..", "results", "raw", "revision");

async function main() {
  const started = Date.now();
  const rows = await runAttackMatrix(ethers, { log: (line) => console.log(`[attack-matrix] ${line}`) });
  const withExpectation = rows.map((row) => ({
    ...row,
    expected: EXPECTED[row.attack][row.design],
    matches: EXPECTED[row.attack][row.design] === row.result,
  }));
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(
    path.join(OUT, "attack_matrix.json"),
    `${JSON.stringify(
      {
        schema: "TrustCircuit.Revision.AttackMatrix.v1",
        timestamp_utc: new Date().toISOString(),
        network: "hardhat",
        validator_quorum: "2-of-3; F4/N use the two compromised keys",
        trustcircuit_proofs: "real Groth16 VCP v3 proofs",
        seconds: (Date.now() - started) / 1000,
        rows: withExpectation,
      },
      null,
      2
    )}\n`
  );
  const header = "attack,design,result,expected,matches,detail";
  const csv = withExpectation.map((r) =>
    [r.attack, r.design, r.result, r.expected, r.matches, `"${String(r.detail).replaceAll('"', "'")}"`].join(",")
  );
  fs.writeFileSync(path.join(OUT, "attack_matrix.csv"), `${header}\n${csv.join("\n")}\n`);
  const mismatches = withExpectation.filter((r) => !r.matches);
  console.log(`[attack-matrix] ${withExpectation.length} cells, ${mismatches.length} mismatches, ${((Date.now() - started) / 1000).toFixed(1)} s`);
  if (mismatches.length) process.exitCode = 1;
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  // snarkjs keeps curve worker threads alive; exit explicitly.
  .finally(() => process.exit(process.exitCode || 0));
