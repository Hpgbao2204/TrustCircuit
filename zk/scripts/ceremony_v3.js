"use strict";

// VCP v3 Groth16 setup ceremony (TNSE revision, R2.4).
//
// Phase 1: the public Perpetual Powers of Tau transcript of the Ethereum
//          Foundation PSE team (round 80, prepared for 2^16 constraints).
// Phase 2: circuit-specific contributions, one per participant, each run on
//          the participant's own machine with fresh OS entropy that is never
//          written to disk or printed, followed by a public random beacon.
//
// Usage (from the repository root):
//   node zk/scripts/ceremony_v3.js build                 compile the circuit
//   node zk/scripts/ceremony_v3.js init                  phase-2 zkey #0 from the ptau
//   node zk/scripts/ceremony_v3.js contribute --name "Full Name"
//   node zk/scripts/ceremony_v3.js beacon --hash <64-hex> --source "<what the hash is>"
//   node zk/scripts/ceremony_v3.js finalize              verify, export vkey + Solidity verifier
//   node zk/scripts/ceremony_v3.js status
//
// A contributor only needs the latest zkey (zk/build/v3/vcp_v3_NNNN.zkey), the
// transcript (zk/ceremony/vcp_v3_transcript.json), and this script; they run
// `contribute` and return the new zkey plus the updated transcript.

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..");
const CIRCOM = path.join(ROOT, "tools", process.platform === "win32" ? "circom.exe" : "circom");
const SNARKJS = path.join(ROOT, "node_modules", "snarkjs", "build", "cli.cjs");
const CIRCOMLIB = path.join(ROOT, "node_modules", "circomlib", "circuits");
const CIRCUIT = path.join(ROOT, "zk", "circuits", "vcp_v3.circom");
const BUILD = path.join(ROOT, "zk", "build", "v3");
const R1CS = path.join(BUILD, "vcp_v3.r1cs");
const PTAU = path.join(ROOT, "zk", "ptau", "ppot_0080_16.ptau");
const PTAU_URL =
  "https://pse-trusted-setup-ppot.s3.eu-central-1.amazonaws.com/pot28_0080/ppot_0080_16.ptau";
const TRANSCRIPT = path.join(ROOT, "zk", "ceremony", "vcp_v3_transcript.json");
const FINAL_ZKEY = path.join(BUILD, "vcp_v3_final.zkey");
const VKEY = path.join(BUILD, "vcp_v3_vkey.json");
const VERIFIER = path.join(ROOT, "contracts", "VCPv3Groth16Verifier.sol");
const METADATA = path.join(ROOT, "zk", "vcp_v3_metadata.json");

function sha256File(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function snarkjs(args) {
  return execFileSync("node", [SNARKJS, ...args], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 1 << 28,
  }).toString();
}

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function loadTranscript() {
  if (!fs.existsSync(TRANSCRIPT)) throw new Error("run `init` first");
  return JSON.parse(fs.readFileSync(TRANSCRIPT, "utf8"));
}

function saveTranscript(transcript) {
  fs.mkdirSync(path.dirname(TRANSCRIPT), { recursive: true });
  fs.writeFileSync(TRANSCRIPT, `${JSON.stringify(transcript, null, 2)}\n`);
}

function zkeyName(index) {
  return path.join(BUILD, `vcp_v3_${String(index).padStart(4, "0")}.zkey`);
}

function contributionHash(output) {
  const match = output.match(/Contribution Hash:\s*([\s\S]*?)(?:\n\s*\n|\[INFO\]\s+snarkJS:\s+ZKey Ok|$)/);
  if (!match) return null;
  return match[1]
    .replace(/\[INFO\]\s+snarkJS:/g, "")
    .replace(/\s+/g, "")
    .trim();
}

function build() {
  fs.mkdirSync(BUILD, { recursive: true });
  const output = execFileSync(
    CIRCOM,
    [CIRCUIT, "--r1cs", "--wasm", "--sym", "-l", CIRCOMLIB, "-o", BUILD],
    { cwd: ROOT }
  ).toString();
  process.stdout.write(output);
}

function init() {
  if (!fs.existsSync(PTAU)) {
    throw new Error(`missing ${PTAU}; download it from ${PTAU_URL}`);
  }
  if (!fs.existsSync(R1CS)) build();
  const out = zkeyName(0);
  const started = Date.now();
  snarkjs(["groth16", "setup", R1CS, PTAU, out]);
  const info = snarkjs(["r1cs", "info", R1CS]);
  saveTranscript({
    schema: "TrustCircuit.VCPv3.Ceremony.v1",
    circuit: path.relative(ROOT, CIRCUIT).replaceAll("\\", "/"),
    circuit_sha256: sha256File(CIRCUIT),
    r1cs_sha256: sha256File(R1CS),
    r1cs_info: info
      .replace(/\x1B\[[0-9;]*m/g, "")
      .split(/\r?\n/)
      .filter((line) => /# of|Curve/.test(line))
      .map((line) => line.replace(/.*snarkJS:\s*/, "").trim()),
    phase1: {
      source: "Perpetual Powers of Tau, Ethereum Foundation PSE, round 80 (prepared, 2^16)",
      url: PTAU_URL,
      sha256: sha256File(PTAU),
    },
    phase2: [
      {
        index: 0,
        kind: "initial",
        output: path.basename(out),
        output_sha256: sha256File(out),
        seconds: (Date.now() - started) / 1000,
      },
    ],
    beacon: null,
    final: null,
  });
  console.log(`[ceremony] initial zkey written: ${out}`);
}

function contribute() {
  const name = argument("name");
  if (!name) throw new Error("--name is required");
  const transcript = loadTranscript();
  if (transcript.beacon) throw new Error("the beacon has been applied; the ceremony is closed");
  const last = transcript.phase2[transcript.phase2.length - 1];
  const input = path.join(BUILD, last.output);
  if (sha256File(input) !== last.output_sha256) {
    throw new Error(`${last.output} does not match the transcript`);
  }
  const index = last.index + 1;
  const output = zkeyName(index);
  const entropy = crypto.randomBytes(64).toString("hex");
  const started = Date.now();
  const log = snarkjs(["zkey", "contribute", input, output, `--name=${name}`, `-e=${entropy}`, "-v"]);
  transcript.phase2.push({
    index,
    kind: "contribution",
    name,
    input_sha256: last.output_sha256,
    output: path.basename(output),
    output_sha256: sha256File(output),
    contribution_hash: contributionHash(log),
    entropy: "64 bytes from the OS CSPRNG, not stored",
    timestamp: new Date().toISOString(),
    seconds: (Date.now() - started) / 1000,
  });
  saveTranscript(transcript);
  console.log(`[ceremony] contribution #${index} by ${name} written: ${output}`);
  console.log(`[ceremony] contribution hash: ${transcript.phase2.at(-1).contribution_hash}`);
}

function beacon() {
  const hash = argument("hash");
  const source = argument("source");
  if (!hash || !/^[0-9a-fA-F]{64}$/.test(hash)) throw new Error("--hash must be 64 hex characters");
  if (!source) throw new Error("--source must describe the public beacon value");
  const transcript = loadTranscript();
  const last = transcript.phase2[transcript.phase2.length - 1];
  const input = path.join(BUILD, last.output);
  const started = Date.now();
  const log = snarkjs(["zkey", "beacon", input, FINAL_ZKEY, hash, "10", "-n=Final beacon", "-v"]);
  transcript.beacon = {
    input_sha256: last.output_sha256,
    hash,
    iterations_exp: 10,
    source,
    output: path.basename(FINAL_ZKEY),
    output_sha256: sha256File(FINAL_ZKEY),
    contribution_hash: contributionHash(log),
    seconds: (Date.now() - started) / 1000,
  };
  saveTranscript(transcript);
  console.log(`[ceremony] beacon applied: ${FINAL_ZKEY}`);
}

function finalize() {
  const transcript = loadTranscript();
  if (!transcript.beacon) throw new Error("apply the beacon first");
  const started = Date.now();
  const verification = snarkjs(["zkey", "verify", R1CS, PTAU, FINAL_ZKEY]);
  if (!/ZKey Ok!/.test(verification)) throw new Error(`zkey verification failed:\n${verification}`);
  snarkjs(["zkey", "export", "verificationkey", FINAL_ZKEY, VKEY]);
  const exported = path.join(BUILD, "vcp_v3_verifier.sol");
  snarkjs(["zkey", "export", "solidityverifier", FINAL_ZKEY, exported]);
  const solidity = fs
    .readFileSync(exported, "utf8")
    .replace(/contract Groth16Verifier/, "contract VCPv3Groth16Verifier")
    .replace(/pragma solidity [^;]+;/, "pragma solidity ^0.8.24;");
  fs.writeFileSync(VERIFIER, solidity);
  const contributors = transcript.phase2.filter((entry) => entry.kind === "contribution");
  transcript.final = {
    zkey_verified: true,
    verify_seconds: (Date.now() - started) / 1000,
    final_zkey_sha256: sha256File(FINAL_ZKEY),
    vkey_sha256: sha256File(VKEY),
    verifier_sol_sha256: sha256File(VERIFIER),
    contributors: contributors.map((entry) => entry.name),
    transcript_note:
      contributors.length >= 2
        ? `phase 2: ${contributors.length} contributions followed by a public beacon`
        : "phase 2: a single contribution followed by a public beacon; sound only if that " +
          "contributor erased its randomness. Further contributions can be appended with " +
          "`contribute` before a deployment re-applies the beacon.",
  };
  saveTranscript(transcript);
  fs.writeFileSync(
    METADATA,
    `${JSON.stringify(
      {
        schema: "TrustCircuit.VCPv3.Metadata.v1",
        circuit: transcript.circuit,
        circuit_sha256: transcript.circuit_sha256,
        r1cs_sha256: transcript.r1cs_sha256,
        r1cs_info: transcript.r1cs_info,
        ptau_sha256: transcript.phase1.sha256,
        final_zkey_sha256: transcript.final.final_zkey_sha256,
        final_zkey_bytes: fs.statSync(FINAL_ZKEY).size,
        vkey_sha256: transcript.final.vkey_sha256,
        vkey_bytes: fs.statSync(VKEY).size,
        verifier_solidity_sha256: transcript.final.verifier_sol_sha256,
        ceremony_transcript_sha256: sha256File(TRANSCRIPT),
        contributors: transcript.final.contributors,
        note: transcript.final.transcript_note,
      },
      null,
      2
    )}\n`
  );
  console.log(`[ceremony] verified and exported; verifier: ${VERIFIER}`);
}

function status() {
  const transcript = loadTranscript();
  for (const entry of transcript.phase2) {
    console.log(`#${entry.index} ${entry.kind} ${entry.name || ""} ${entry.output_sha256.slice(0, 16)}`);
  }
  console.log(`beacon: ${transcript.beacon ? transcript.beacon.source : "not applied"}`);
  console.log(`final: ${transcript.final ? transcript.final.transcript_note : "not finalized"}`);
}

const command = process.argv[2];
const commands = { build, init, contribute, beacon, finalize, status };
if (!commands[command]) {
  console.error(`usage: node zk/scripts/ceremony_v3.js <${Object.keys(commands).join("|")}>`);
  process.exit(2);
}
commands[command]();
