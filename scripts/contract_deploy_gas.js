/*
 * Measure one-time deployment gas for every TrustCircuit contract on the local
 * Hardhat EVM. Deployment (one-time) cost is a different gas dimension from the
 * per-call execution cost in contract_gas_summary.csv.
 *
 * Output: results/summary/contract_deploy_gas.csv
 */
const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");

const CONTRACTS = [
  { name: "DataRegistry", role: "registry" },
  { name: "AccessController", role: "access" },
  { name: "BudgetLedger", role: "budget" },
  { name: "AuditLedger", role: "audit" },
  { name: "MockComplianceVerifier", role: "compliance-mock" },
  { name: "Groth16Verifier", role: "compliance-zk" },
  { name: "PlonkVerifier", role: "compliance-zk" },
  { name: "FflonkVerifier", role: "compliance-zk" },
];

async function main() {
  const rows = [];
  for (const c of CONTRACTS) {
    const Factory = await ethers.getContractFactory(c.name);
    const inst = await Factory.deploy();
    await inst.waitForDeployment();
    const rcpt = await inst.deploymentTransaction().wait();
    const bytecode = (await ethers.provider.getCode(await inst.getAddress())).length / 2 - 1;
    rows.push({ name: c.name, role: c.role, deploy_gas: rcpt.gasUsed.toString(), runtime_bytes: bytecode });
    console.log(`${c.name}: deploy_gas=${rcpt.gasUsed} bytes=${bytecode}`);
  }

  const out = path.join(__dirname, "..", "results", "summary", "contract_deploy_gas.csv");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const headers = "contract,role,deploy_gas,runtime_bytes";
  fs.writeFileSync(out, `${headers}\n${rows.map((r) => `${r.name},${r.role},${r.deploy_gas},${r.runtime_bytes}`).join("\n")}\n`);
  console.log(out);
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
