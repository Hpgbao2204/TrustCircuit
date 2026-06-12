/*
 * Benchmark for the TrustCircuit hybrid attribute-based access module.
 *
 * Measures, as a function of policy size (number of attributes / leaves):
 *   - key-encapsulation encrypt time (CP-ABE-style share + per-leaf ECIES)
 *   - authorized decrypt time (leaf ECIES + LSSS reconstruction)
 *   - key-encapsulation size (bytes of the per-leaf ciphertexts)
 *   - AES-256-GCM bulk encrypt time for a fixed payload
 *
 * Output:
 *   results/raw/abe_benchmark.csv
 *   results/summary/abe_summary.csv
 *   results/summary/abe_config.json
 *
 * Usage: node crypto/abe_benchmark.js [--reps 30] [--payload-kib 64]
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const abe = require("./abe_hybrid");

const ROOT = path.resolve(__dirname, "..");
const RAW = path.join(ROOT, "results", "raw", "abe_benchmark.csv");
const SUMMARY = path.join(ROOT, "results", "summary", "abe_summary.csv");
const CONFIG = path.join(ROOT, "results", "summary", "abe_config.json");

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i !== -1 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const REPS = Number(arg("--reps", "30"));
const PAYLOAD_KIB = Number(arg("--payload-kib", "64"));
const POLICY_SIZES = [1, 2, 4, 8, 16, 24, 32];

function mean(a) {
  return a.reduce((s, x) => s + x, 0) / a.length;
}
function std(a) {
  if (a.length < 2) return 0;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / a.length);
}
function pctl(a, p) {
  const s = [...a].sort((x, y) => x - y);
  const idx = (s.length - 1) * (p / 100);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

// Build a balanced threshold policy with `n` leaves that requires ceil(n/2)
// of them: a representative non-trivial monotone access structure.
function buildPolicy(n) {
  const leaves = Array.from({ length: n }, (_, i) => abe.leaf(`attr:${i}`));
  if (n === 1) return leaves[0];
  const k = Math.ceil(n / 2);
  return abe.THR(k, ...leaves);
}

// An attribute set that satisfies the ceil(n/2)-of-n policy.
function satisfyingSet(n) {
  const k = n === 1 ? 1 : Math.ceil(n / 2);
  return Array.from({ length: k }, (_, i) => `attr:${i}`);
}

function ksize(ct) {
  // total bytes of the per-leaf key-encapsulation ciphertexts
  let bytes = 0;
  for (const leaf of Object.values(ct.leafCts)) {
    bytes += leaf.blob.epk.length / 2 + leaf.blob.iv.length / 2 + leaf.blob.ct.length / 2 + leaf.blob.tag.length / 2;
  }
  return bytes;
}

function main() {
  fs.mkdirSync(path.dirname(RAW), { recursive: true });
  fs.mkdirSync(path.dirname(SUMMARY), { recursive: true });

  const payload = crypto.randomBytes(PAYLOAD_KIB * 1024);
  const rawRows = [];
  const sumRows = [];

  for (const n of POLICY_SIZES) {
    const policy = buildPolicy(n);
    const authority = new abe.Authority();
    const attrs = [...abe.collectLeafAttrs(policy, new Set())];
    const pp = authority.publicKeysFor(attrs);
    const userKey = authority.issueKey(satisfyingSet(n));

    const encT = [];
    const decT = [];
    let kencBytes = 0;
    let ok = true;

    for (let r = 0; r < REPS; r++) {
      const t0 = process.hrtime.bigint();
      const ct = abe.encrypt(pp, JSON.parse(JSON.stringify(policy)), payload);
      const t1 = process.hrtime.bigint();
      const pt = abe.decrypt(userKey, ct);
      const t2 = process.hrtime.bigint();

      encT.push(Number(t1 - t0) / 1e6);
      decT.push(Number(t2 - t1) / 1e6);
      kencBytes = ksize(ct);
      if (!pt || !pt.equals(payload)) ok = false;

      rawRows.push({
        policy_leaves: n,
        threshold_k: n === 1 ? 1 : Math.ceil(n / 2),
        rep: r,
        encrypt_ms: (Number(t1 - t0) / 1e6).toFixed(4),
        decrypt_ms: (Number(t2 - t1) / 1e6).toFixed(4),
        kenc_bytes: kencBytes,
        payload_kib: PAYLOAD_KIB,
        decrypt_ok: ok,
      });
    }

    sumRows.push({
      policy_leaves: n,
      threshold_k: n === 1 ? 1 : Math.ceil(n / 2),
      encrypt_ms_mean: mean(encT).toFixed(4),
      encrypt_ms_std: std(encT).toFixed(4),
      encrypt_ms_p95: pctl(encT, 95).toFixed(4),
      decrypt_ms_mean: mean(decT).toFixed(4),
      decrypt_ms_std: std(decT).toFixed(4),
      decrypt_ms_p95: pctl(decT, 95).toFixed(4),
      kenc_bytes: kencBytes,
      payload_kib: PAYLOAD_KIB,
      reps: REPS,
      correctness: ok,
    });

    console.log(`leaves=${n} k=${n === 1 ? 1 : Math.ceil(n / 2)} enc=${mean(encT).toFixed(2)}ms dec=${mean(decT).toFixed(2)}ms kenc=${kencBytes}B ok=${ok}`);
  }

  const writeCsv = (file, rows) => {
    const headers = Object.keys(rows[0]);
    fs.writeFileSync(file, [headers.join(","), ...rows.map((r) => headers.map((h) => r[h]).join(","))].join("\n") + "\n");
  };
  writeCsv(RAW, rawRows);
  writeCsv(SUMMARY, sumRows);
  fs.writeFileSync(
    CONFIG,
    JSON.stringify(
      {
        scheme: "LSSS access-tree + secp256k1 ECIES + AES-256-GCM hybrid",
        group: "secp256k1 (native Node crypto ECDH)",
        field: "GF(secp256k1 order)",
        policy_sizes: POLICY_SIZES,
        policy_model: "ceil(n/2)-of-n threshold",
        reps: REPS,
        payload_kib: PAYLOAD_KIB,
        node: process.version,
        platform: `${os.platform()} ${os.release()}`,
        cpus: os.cpus().length,
        note: "Software access-structure layer; pairing-based collusion resistance is the production target.",
      },
      null,
      2
    )
  );

  console.log(RAW);
  console.log(SUMMARY);
}

main();
