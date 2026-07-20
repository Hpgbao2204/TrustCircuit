/*
 * One process-isolated AES-256-GCM measurement.
 * Stdout is exactly one JSON object; diagnostics belong on stderr.
 */
"use strict";

const crypto = require("crypto");

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

const variant = argument("--variant", "full_buffer");
const payloadMiB = Number(argument("--payload-mib", "1"));
const chunkMiB = Number(argument("--chunk-mib", "4"));

if (!["full_buffer", "chunked"].includes(variant)) throw new Error("invalid --variant");
if (!Number.isInteger(payloadMiB) || payloadMiB <= 0) throw new Error("invalid --payload-mib");
if (!Number.isInteger(chunkMiB) || chunkMiB <= 0) throw new Error("invalid --chunk-mib");

const MIB = 1024 * 1024;
const payloadBytes = payloadMiB * MIB;
const chunkBytes = Math.min(chunkMiB * MIB, payloadBytes);

function elapsedMs(start, end) {
  return Number(end - start) / 1e6;
}

function rssMiB() {
  return process.memoryUsage.rss() / MIB;
}

function warmup() {
  const key = Buffer.alloc(32, 0x41);
  const iv = Buffer.alloc(12, 0x42);
  const input = Buffer.alloc(64 * 1024, 0x43);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(input), cipher.final()]);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(cipher.getAuthTag());
  const recovered = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  if (!recovered.equals(input)) throw new Error("warm-up correctness failure");
}

function fullBuffer() {
  const key = crypto.randomBytes(32);
  const iv = crypto.randomBytes(12);
  let peak = rssMiB();
  const sample = () => { peak = Math.max(peak, rssMiB()); };
  const plaintext = Buffer.alloc(payloadBytes, 0x54);
  sample();

  const encryptStart = process.hrtime.bigint();
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  const encryptEnd = process.hrtime.bigint();
  sample();

  const decryptStart = process.hrtime.bigint();
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  const recovered = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  const decryptEnd = process.hrtime.bigint();
  sample();

  return {
    encrypt_ms: elapsedMs(encryptStart, encryptEnd),
    decrypt_ms: elapsedMs(decryptStart, decryptEnd),
    peak_rss_mib: peak,
    success: recovered.equals(plaintext),
  };
}

function chunked() {
  const key = crypto.randomBytes(32);
  const iv = crypto.randomBytes(12);
  const source = Buffer.alloc(chunkBytes, 0x54);
  let peak = rssMiB();
  let encryptNs = 0n;
  let decryptNs = 0n;
  let success = true;
  const sample = () => { peak = Math.max(peak, rssMiB()); };

  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  let offset = 0;
  let iteration = 0;
  while (offset < payloadBytes) {
    const length = Math.min(chunkBytes, payloadBytes - offset);
    const plaintext = length === source.length ? source : source.subarray(0, length);

    const encryptStart = process.hrtime.bigint();
    const ciphertext = cipher.update(plaintext);
    const encryptEnd = process.hrtime.bigint();
    encryptNs += encryptEnd - encryptStart;

    const decryptStart = process.hrtime.bigint();
    const recovered = decipher.update(ciphertext);
    const decryptEnd = process.hrtime.bigint();
    decryptNs += decryptEnd - decryptStart;
    success = success && recovered.equals(plaintext);
    sample();

    offset += length;
    iteration += 1;
    if (global.gc && iteration % 16 === 0) global.gc();
  }

  let start = process.hrtime.bigint();
  const finalCiphertext = cipher.final();
  let end = process.hrtime.bigint();
  encryptNs += end - start;
  decipher.setAuthTag(cipher.getAuthTag());
  start = process.hrtime.bigint();
  const finalPlaintext = Buffer.concat([decipher.update(finalCiphertext), decipher.final()]);
  end = process.hrtime.bigint();
  decryptNs += end - start;
  success = success && finalPlaintext.length === 0;
  sample();

  return {
    encrypt_ms: Number(encryptNs) / 1e6,
    decrypt_ms: Number(decryptNs) / 1e6,
    peak_rss_mib: peak,
    success,
  };
}

warmup();
if (global.gc) global.gc();
const idleRssMiB = rssMiB();
const result = variant === "full_buffer" ? fullBuffer() : chunked();
process.stdout.write(JSON.stringify({
  variant,
  payload_mib: payloadMiB,
  chunk_mib: variant === "chunked" ? chunkMiB : 0,
  idle_rss_mib: idleRssMiB,
  ...result,
}) + "\n");
