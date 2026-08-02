"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

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
const RETAINED_METADATA = path.join(ROOT, "zk", "vcp_v2_metadata.json");
const TOTAL_PHASES = 6;
const HEARTBEAT_MS = 30_000;

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

function elapsedText(started) {
  const seconds = Math.floor((Date.now() - started) / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return [hours, minutes, remainder]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function phase(index, message) {
  const checkpoint = Math.round(((index - 1) / TOTAL_PHASES) * 100);
  console.log(
    `[vcp-v2] PHASE ${index}/${TOTAL_PHASES} | pipeline checkpoint ${checkpoint}% | ${message}`
  );
}

function phaseComplete(index, started) {
  const checkpoint = Math.round((index / TOTAL_PHASES) * 100);
  console.log(
    `[vcp-v2] PHASE ${index}/${TOTAL_PHASES} complete | pipeline checkpoint ${checkpoint}% | elapsed ${elapsedText(started)}`
  );
}

function stripAnsi(value) {
  return value.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "");
}

function runStreaming(command, args, label, heartbeatMs = HEARTBEAT_MS) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    let recentOutput = "";
    let parseBuffer = "";
    let lastProgress = "no numeric substage reported yet";
    let lastPrintedKey = "";
    const child = spawn(command, args, {
      cwd: ROOT,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    console.log(`[vcp-v2][${label}] started pid=${child.pid}`);

    const inspect = (chunk, destination) => {
      const text = chunk.toString();
      destination.write(text);
      recentOutput = `${recentOutput}${text}`.slice(-65_536);
      parseBuffer += stripAnsi(text);
      const lines = parseBuffer.split(/\r?\n/);
      parseBuffer = lines.pop() || "";
      for (const line of lines) {
        const match = line.match(/([^:\r\n]{1,100}):\s*(\d+)\s*\/\s*(\d+)/);
        if (!match) continue;
        const current = Number(match[2]);
        const total = Number(match[3]);
        if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) continue;
        const percent = Math.min(100, (current / total) * 100);
        const stage = match[1].trim();
        const key = `${stage}|${percent.toFixed(1)}`;
        lastProgress = `${stage}: ${percent.toFixed(1)}% (${current}/${total})`;
        if (key !== lastPrintedKey) {
          console.log(`[vcp-v2][${label}] substage ${lastProgress}`);
          lastPrintedKey = key;
        }
      }
    };
    child.stdout.on("data", (chunk) => inspect(chunk, process.stdout));
    child.stderr.on("data", (chunk) => inspect(chunk, process.stderr));

    const heartbeat = setInterval(() => {
      console.log(
        `[vcp-v2][${label}] still running | elapsed ${elapsedText(started)} | ${lastProgress}`
      );
    }, heartbeatMs);

    child.on("error", (error) => {
      clearInterval(heartbeat);
      reject(error);
    });
    child.on("close", (code, signal) => {
      clearInterval(heartbeat);
      if (code === 0) {
        console.log(`[vcp-v2][${label}] complete | elapsed ${elapsedText(started)}`);
        resolve();
        return;
      }
      reject(
        new Error(
          `${label} failed (exit=${code}, signal=${signal || "none"})\n${stripAnsi(recentOutput)}`
        )
      );
    });
  });
}

function snarkjsStreaming(args, label) {
  return runStreaming("node", [SNARKJS, ...args], label);
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function parseR1csInfo(output) {
  const value = (label) => {
    const match = output.match(new RegExp(`# of ${label}:\\s*(\\d+)`, "i"));
    if (!match) throw new Error(`missing R1CS dimension: ${label}`);
    return Number(match[1]);
  };
  return {
    wires: value("Wires"),
    constraints: value("Constraints"),
    private_inputs: value("Private Inputs"),
    public_inputs: value("Public Inputs"),
    labels: value("Labels"),
    outputs: value("Outputs"),
  };
}

async function ensurePowersOfTau() {
  const pot0 = path.join(BUILD, `pot${PTAU_POWER}_0.ptau`);
  const pot1 = path.join(BUILD, `pot${PTAU_POWER}_1.ptau`);
  const potFinal = path.join(BUILD, `pot${PTAU_POWER}_final.ptau`);
  const potCheckpoint = path.join(
    BUILD,
    `pot${PTAU_POWER}_final_checkpoint.json`
  );
  if (ptauCheckpointMatches(potCheckpoint, pot1, potFinal)) {
    console.log(`[vcp-v2] reusing hash-checked ${path.basename(potFinal)}`);
    return potFinal;
  }

  if (fs.existsSync(potFinal)) {
    console.log(
      `[vcp-v2] cached ${path.basename(potFinal)} has no valid completion checkpoint; rebuilding it`
    );
    fs.rmSync(potFinal, { force: true });
  }
  fs.rmSync(potCheckpoint, { force: true });

  if (!fs.existsSync(pot0)) {
    console.log(`[vcp-v2] creating powers of tau 2^${PTAU_POWER}`);
    await snarkjsStreaming(
      ["powersoftau", "new", "bn128", String(PTAU_POWER), pot0, "-v"],
      "powers-of-tau/new"
    );
  } else {
    console.log(`[vcp-v2] reusing cached ${path.basename(pot0)}`);
  }
  if (!fs.existsSync(pot1)) {
    await snarkjsStreaming([
      "powersoftau", "contribute", pot0, pot1,
      "--name=trustcircuit-vcp-v2-dev", "-v", "-e=trustcircuit-vcp-v2-dev-entropy",
    ], "powers-of-tau/contribute");
  } else {
    console.log(`[vcp-v2] reusing cached ${path.basename(pot1)}`);
  }
  await snarkjsStreaming(
    ["powersoftau", "prepare", "phase2", pot1, potFinal, "-v"],
    "powers-of-tau/prepare-phase2"
  );
  writePtauCheckpoint(potCheckpoint, pot1, potFinal);
  return potFinal;
}

function ptauCheckpointMatches(checkpointPath, sourcePath, artifactPath) {
  if (
    !fs.existsSync(checkpointPath) ||
    !fs.existsSync(sourcePath) ||
    !fs.existsSync(artifactPath)
  ) return false;
  try {
    const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
    return (
      checkpoint.power === PTAU_POWER &&
      checkpoint.source_sha256 === sha256File(sourcePath) &&
      checkpoint.artifact_sha256 === sha256File(artifactPath)
    );
  } catch {
    return false;
  }
}

function writePtauCheckpoint(checkpointPath, sourcePath, artifactPath) {
  fs.writeFileSync(
    checkpointPath,
    `${JSON.stringify({
      schema: "TrustCircuit.PowersOfTauCheckpoint.v1",
      power: PTAU_POWER,
      source_sha256: sha256File(sourcePath),
      artifact_sha256: sha256File(artifactPath),
      artifact_bytes: fs.statSync(artifactPath).size,
      completed: true,
    }, null, 2)}\n`
  );
}

function checkpointMatches(checkpointPath, artifactPath, r1csSha256) {
  if (!fs.existsSync(checkpointPath) || !fs.existsSync(artifactPath)) return false;
  try {
    const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
    return (
      checkpoint.r1cs_sha256 === r1csSha256 &&
      checkpoint.artifact_sha256 === sha256File(artifactPath)
    );
  } catch {
    return false;
  }
}

function writeCheckpoint(checkpointPath, artifactPath, r1csSha256, stage) {
  fs.writeFileSync(
    checkpointPath,
    `${JSON.stringify({
      schema: "TrustCircuit.VCPBuildCheckpoint.v1",
      stage,
      r1cs_sha256: r1csSha256,
      artifact_sha256: sha256File(artifactPath),
      artifact_bytes: fs.statSync(artifactPath).size,
    }, null, 2)}\n`
  );
}

function removeStale(paths) {
  for (const target of paths) fs.rmSync(target, { force: true });
}

async function main() {
  const buildStarted = Date.now();
  const compileOnly = process.argv.includes("--compile-only");
  if (process.argv.includes("--progress-self-test")) {
    await runStreaming(
      process.execPath,
      [
        "-e",
        "let n=0;const t=setInterval(()=>{console.log(`processing constraints: ${n}/100`);n+=25;if(n>100)clearInterval(t)},250)",
      ],
      "progress/self-test",
      500
    );
    console.log("[vcp-v2] PROGRESS SELF-TEST COMPLETE 100%");
    return;
  }
  if (!fs.existsSync(CIRCOM)) throw new Error(`missing Circom compiler: ${CIRCOM}`);
  fs.mkdirSync(BUILD, { recursive: true });

  phase(1, "compile canonical 24-public-input circuit");
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

  run(CIRCOM, [wrapper, "--r1cs", "--wasm", "--sym", "-o", BUILD, "-l", CIRCOMLIB]);
  phaseComplete(1, buildStarted);
  const r1cs = path.join(BUILD, `${NAME}.r1cs`);
  const r1csSha256 = sha256File(r1cs);
  if (compileOnly) {
    const dimensions = parseR1csInfo(snarkjs(["r1cs", "info", r1cs]));
    if (dimensions.public_inputs !== PUBLIC_INPUTS.length) {
      throw new Error(
        `R1CS exposes ${dimensions.public_inputs} public inputs, expected ${PUBLIC_INPUTS.length}`
      );
    }
    console.log(
      `[vcp-v2] COMPILE-ONLY COMPLETE | constraints=${dimensions.constraints} | public_inputs=${dimensions.public_inputs} | R1CS SHA-256 ${r1csSha256}`
    );
    return;
  }
  const zkey0 = path.join(BUILD, `${NAME}_0.zkey`);
  const zkey = path.join(BUILD, `${NAME}_final.zkey`);
  const vkey = path.join(BUILD, `${NAME}_vkey.json`);
  const metadataPath = path.join(BUILD, `${NAME}_build.json`);
  const setupCheckpoint = path.join(BUILD, `${NAME}_setup_checkpoint.json`);
  const contributionCheckpoint = path.join(
    BUILD,
    `${NAME}_contribution_checkpoint.json`
  );
  let canReuse = false;
  if (fs.existsSync(zkey) && fs.existsSync(metadataPath)) {
    try {
      const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
      canReuse = metadata.r1cs_sha256 === r1csSha256;
    } catch {
      canReuse = false;
    }
  }
  phase(2, "prepare or reuse Powers-of-Tau 2^16");
  const ptau = await ensurePowersOfTau();
  phaseComplete(2, buildStarted);

  phase(3, "Groth16 setup (longest phase; verbose progress and 30 s heartbeat enabled)");
  if (canReuse) {
    console.log("[vcp-v2][groth16/setup] final key matches R1CS; setup skipped");
  } else if (checkpointMatches(setupCheckpoint, zkey0, r1csSha256)) {
    console.log("[vcp-v2][groth16/setup] resuming from verified setup checkpoint");
  } else {
    removeStale([zkey0, zkey, setupCheckpoint, contributionCheckpoint]);
    await snarkjsStreaming(
      ["groth16", "setup", r1cs, ptau, zkey0, "-v"],
      "groth16/setup"
    );
    writeCheckpoint(setupCheckpoint, zkey0, r1csSha256, "groth16_setup");
  }
  phaseComplete(3, buildStarted);

  phase(4, "apply local-development zkey contribution");
  if (canReuse) {
    console.log("[vcp-v2][zkey/contribute] final key matches R1CS; contribution skipped");
  } else if (checkpointMatches(contributionCheckpoint, zkey, r1csSha256)) {
    console.log("[vcp-v2][zkey/contribute] resuming from verified contribution checkpoint");
  } else {
    removeStale([zkey, contributionCheckpoint]);
    await snarkjsStreaming([
      "zkey", "contribute", zkey0, zkey,
      "--name=trustcircuit-vcp-v2-dev", "-v", "-e=trustcircuit-vcp-v2-zkey-entropy",
    ], "zkey/contribute");
    writeCheckpoint(contributionCheckpoint, zkey, r1csSha256, "zkey_contribution");
  }
  phaseComplete(4, buildStarted);

  phase(5, "export verification key and Solidity verifier");
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
  phaseComplete(5, buildStarted);

  phase(6, "validate dimensions and retain cryptographic metadata");
  const dimensions = parseR1csInfo(snarkjs(["r1cs", "info", r1cs]));
  if (dimensions.public_inputs !== PUBLIC_INPUTS.length) {
    throw new Error(
      `R1CS exposes ${dimensions.public_inputs} public inputs, expected ${PUBLIC_INPUTS.length}`
    );
  }
  const metadata = {
    schema: "TrustCircuit.VCP.bn254.v2",
    circuit_source: "zk/circuits/compliance_check.circom",
    verifier_source: "contracts/VCPGroth16Verifier.sol",
    public_input_order: PUBLIC_INPUTS,
    public_inputs: PUBLIC_INPUTS.length,
    policy_purposes: 2,
    policy_functions: 2,
    budget_bits: 64,
    dimensions,
    r1cs_sha256: r1csSha256,
    wasm_sha256: sha256File(path.join(BUILD, `${NAME}_js`, `${NAME}.wasm`)),
    proving_key_sha256: sha256File(zkey),
    verification_key_sha256: sha256File(vkey),
    verifier_solidity_sha256: sha256File(VERIFIER),
    circom_version: run(CIRCOM, ["--version"]).trim(),
    snarkjs_version: require(path.join(ROOT, "node_modules", "snarkjs", "package.json")).version,
    setup_scope: "local development only; not a production ceremony",
  };
  const serializedMetadata = `${JSON.stringify(metadata, null, 2)}\n`;
  fs.writeFileSync(metadataPath, serializedMetadata);
  fs.writeFileSync(RETAINED_METADATA, serializedMetadata);
  phaseComplete(6, buildStarted);
  console.log(`[vcp-v2] R1CS SHA-256 ${r1csSha256}`);
  console.log(`[vcp-v2] verifier ${VERIFIER}`);
  console.log(`[vcp-v2] COMPLETE 100% | total elapsed ${elapsedText(buildStarted)}`);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
