"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const CIRCOM = path.join(ROOT, "tools", "circom.exe");
const SNARKJS = path.join(ROOT, "node_modules", "snarkjs", "build", "cli.cjs");
const CIRCOMLIB = path.join(ROOT, "node_modules", "circomlib", "circuits");
const CIRCUIT_SOURCE = path.join(ROOT, "zk", "circuits", "compliance_check.circom");
const CIRCUIT_LIBRARY = path.join(ROOT, "zk", "circuits", "compliance_lib.circom");
const BUILD = path.join(ROOT, "zk", "build");
const NAME = "vcp_v2";
const PTAU_POWER = 16;
const VERIFIER = path.join(ROOT, "contracts", "VCPGroth16Verifier.sol");

const PUBLIC_INPUTS = [
  "requestIdLo", "requestIdHi",
  "assetIdLo", "assetIdHi",
  "consumerIdLo", "consumerIdHi",
  "policyCommitment", "policyVersion", "purposeId", "functionId",
  "dataHashLo", "dataHashHi",
  "dpConfigHashLo", "dpConfigHashHi",
  "freshnessNonceLo", "freshnessNonceHi",
  "reservedCost", "actualCost", "nullifier", "contextCommitment",
  "attestationHashLo", "attestationHashHi",
  "resultCommitment", "auditDigest",
];

function run(command, args) {
  return execFileSync(command, args, {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 1 << 27,
  }).toString();
}

function snarkjs(args) {
  return run("node", [SNARKJS, ...args]);
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function ensurePowersOfTau() {
  const pot0 = path.join(BUILD, `pot${PTAU_POWER}_0.ptau`);
  const pot1 = path.join(BUILD, `pot${PTAU_POWER}_1.ptau`);
  const potFinal = path.join(BUILD, `pot${PTAU_POWER}_final.ptau`);
  if (!fs.existsSync(potFinal)) {
    console.log(`[vcp-v2] preparing powers of tau 2^${PTAU_POWER}`);
    snarkjs(["powersoftau", "new", "bn128", String(PTAU_POWER), pot0, "-v"]);
    snarkjs([
      "powersoftau", "contribute", pot0, pot1,
      "--name=trustcircuit-vcp-v2-dev", "-v", "-e=trustcircuit-vcp-v2-dev-entropy",
    ]);
    snarkjs(["powersoftau", "prepare", "phase2", pot1, potFinal, "-v"]);
  }
  return potFinal;
}

function main() {
  if (!fs.existsSync(CIRCOM)) throw new Error(`missing Circom compiler: ${CIRCOM}`);
  fs.mkdirSync(BUILD, { recursive: true });

  fs.copyFileSync(CIRCUIT_SOURCE, CIRCUIT_LIBRARY);
  fs.writeFileSync(
    CIRCUIT_LIBRARY,
    fs.readFileSync(CIRCUIT_LIBRARY, "utf8").replace(/component main[\s\S]*$/m, "\n")
  );
  const wrapper = path.join(BUILD, `${NAME}.circom`);
  fs.writeFileSync(
    wrapper,
    `pragma circom 2.1.6;\ninclude "${CIRCUIT_LIBRARY.replace(/\\/g, "/")}";\n` +
      `component main {public [${PUBLIC_INPUTS.join(", ")}]} = ComplianceCheck(2, 2, 64);\n`
  );

  console.log("[vcp-v2] compiling paper-aligned 2x2 policy-family circuit");
  run(CIRCOM, [wrapper, "--r1cs", "--wasm", "--sym", "-o", BUILD, "-l", CIRCOMLIB]);
  const r1cs = path.join(BUILD, `${NAME}.r1cs`);
  const r1csSha256 = sha256File(r1cs);
  const zkey0 = path.join(BUILD, `${NAME}_0.zkey`);
  const zkey = path.join(BUILD, `${NAME}_final.zkey`);
  const vkey = path.join(BUILD, `${NAME}_vkey.json`);
  const metadataPath = path.join(BUILD, `${NAME}_build.json`);
  let canReuse = false;
  if (fs.existsSync(zkey) && fs.existsSync(metadataPath)) {
    const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
    canReuse = metadata.r1cs_sha256 === r1csSha256;
  }
  if (!canReuse) {
    const ptau = ensurePowersOfTau();
    console.log("[vcp-v2] generating local-development Groth16 key");
    snarkjs(["groth16", "setup", r1cs, ptau, zkey0]);
    snarkjs([
      "zkey", "contribute", zkey0, zkey,
      "--name=trustcircuit-vcp-v2-dev", "-v", "-e=trustcircuit-vcp-v2-zkey-entropy",
    ]);
  } else {
    console.log("[vcp-v2] reusing key whose R1CS hash matches");
  }
  snarkjs(["zkey", "export", "verificationkey", zkey, vkey]);
  const temporaryVerifier = path.join(BUILD, `${NAME}_verifier.sol`);
  snarkjs(["zkey", "export", "solidityverifier", zkey, temporaryVerifier]);
  const source = fs
    .readFileSync(temporaryVerifier, "utf8")
    .replace(/contract\s+Groth16Verifier\b/, "contract VCPGroth16Verifier");
  if (!source.includes("contract VCPGroth16Verifier")) {
    throw new Error("could not assign unique VCP v2 verifier contract name");
  }
  fs.writeFileSync(VERIFIER, source);
  fs.writeFileSync(
    metadataPath,
    JSON.stringify(
      {
        schema: "TrustCircuit.VCP.bn254.v2",
        r1cs_sha256: r1csSha256,
        public_inputs: PUBLIC_INPUTS.length,
        policy_purposes: 2,
        policy_functions: 2,
        budget_bits: 64,
        circom_version: run(CIRCOM, ["--version"]).trim(),
        snarkjs_version: require(path.join(ROOT, "node_modules", "snarkjs", "package.json")).version,
        local_development_setup: true,
      },
      null,
      2
    )
  );
  console.log(`[vcp-v2] R1CS SHA-256 ${r1csSha256}`);
  console.log(`[vcp-v2] verifier ${VERIFIER}`);
}

try {
  main();
} catch (error) {
  console.error(error.stack || error.message);
  process.exitCode = 1;
}
