/*
 * TrustCircuit hybrid attribute-based access module.
 *
 * This implements the *access-structure layer* of the CP-ABE + AES-256-GCM
 * hybrid encryption described in the paper, using primitives that are real and
 * verifiable on a stock Node.js install (no pairing library required):
 *
 *   - Bulk confidentiality : AES-256-GCM over the payload (authenticated).
 *   - Key encapsulation     : the symmetric key is derived from a secret s in
 *                             GF(n), shared across a monotone access tree
 *                             (AND / OR / k-of-n threshold gates) using
 *                             Shamir secret sharing (a Linear Secret Sharing
 *                             Scheme, the same access-structure model as
 *                             CP-ABE's (M, rho)).
 *   - Attribute gating      : each policy leaf encrypts its share to the
 *                             attribute's public key with ECIES over
 *                             secp256k1 (ephemeral ECDH + HKDF + AES-256-GCM).
 *                             Only a consumer holding that attribute's secret
 *                             key can recover the leaf share.
 *
 * Semantics enforced (and tested in test/abe_hybrid.test.js):
 *   - A consumer whose attribute set SATISFIES the policy reconstructs s,
 *     re-derives the AES key, and decrypts the payload.
 *   - A consumer whose attribute set does NOT satisfy the policy cannot
 *     recover enough shares; reconstruction yields a wrong key and the
 *     AES-256-GCM authentication tag rejects the ciphertext.
 *
 * Honest limitation: full CP-ABE collusion resistance (two users pooling
 * disjoint attribute keys must not jointly decrypt) requires per-user
 * randomisation in a bilinear group. This software construction enforces the
 * access structure and per-attribute key gating, but does not by itself
 * provide pairing-based collusion resistance. The hardware/pairing deployment
 * is left as the production target, matching the TEE-simulator caveat.
 */

"use strict";

const crypto = require("crypto");

// secp256k1 group order (prime). Shamir arithmetic is done in GF(N).
const N = 115792089237316195423570985008687907852837564279074904382605163141518161494337n;

// ---------------------------------------------------------------------------
// Field arithmetic in GF(N)
// ---------------------------------------------------------------------------
function mod(a, m = N) {
  return ((a % m) + m) % m;
}

function randScalar() {
  // rejection sampling for a uniform non-zero scalar < N
  while (true) {
    const x = mod(BigInt("0x" + crypto.randomBytes(32).toString("hex")));
    if (x !== 0n) return x;
  }
}

function inv(a, m = N) {
  // extended Euclid
  let [old_r, r] = [mod(a, m), m];
  let [old_s, s] = [1n, 0n];
  while (r !== 0n) {
    const q = old_r / r;
    [old_r, r] = [r, old_r - q * r];
    [old_s, s] = [s, old_s - q * s];
  }
  return mod(old_s, m);
}

// Evaluate polynomial (coeffs low->high) at x in GF(N).
function polyEval(coeffs, x) {
  let acc = 0n;
  for (let i = coeffs.length - 1; i >= 0; i--) {
    acc = mod(acc * x + coeffs[i]);
  }
  return acc;
}

// Lagrange interpolation at 0 from points [{x, y}] in GF(N).
function lagrangeAtZero(points) {
  let secret = 0n;
  for (let i = 0; i < points.length; i++) {
    let num = 1n;
    let den = 1n;
    for (let j = 0; j < points.length; j++) {
      if (i === j) continue;
      num = mod(num * mod(-points[j].x));
      den = mod(den * mod(points[i].x - points[j].x));
    }
    const li = mod(num * inv(den));
    secret = mod(secret + points[i].y * li);
  }
  return secret;
}

// ---------------------------------------------------------------------------
// Access tree: { type: 'leaf', attr } | { type: 'and'|'or'|'thr', k?, children: [...] }
// Each node is assigned a secret; leaves carry a share of the root secret.
// AND = n-of-n, OR = 1-of-n, thr = k-of-n (threshold via degree k-1 poly).
// ---------------------------------------------------------------------------
function thresholdOf(node) {
  if (node.type === "and") return node.children.length;
  if (node.type === "or") return 1;
  if (node.type === "thr") return node.k;
  throw new Error(`unknown gate ${node.type}`);
}

// Distribute `secret` over the (already annotated) tree; fills `out` with
// {pid, attr, share} for every leaf. Relies on annotate() having set each
// node's `x` (per-gate child index) and `_pid` (stable path id).
function distribute(node, secret, out) {
  if (node.type === "leaf") {
    out.push({ pid: node._pid, attr: node.attr, share: mod(secret) });
    return;
  }
  const t = thresholdOf(node);
  // random polynomial of degree t-1 with constant term = secret
  const coeffs = [mod(secret)];
  for (let i = 1; i < t; i++) coeffs.push(randScalar());
  for (const child of node.children) {
    distribute(child, polyEval(coeffs, child.x), out);
  }
}

// Try to recover the secret of `node` given recovered leaf shares keyed by a
// stable path id. Returns the secret (BigInt) or null if unsatisfiable.
function recover(node, leafValues) {
  if (node.type === "leaf") {
    const v = leafValues.get(node._pid);
    return v === undefined ? null : v;
  }
  const t = thresholdOf(node);
  const recovered = [];
  for (const child of node.children) {
    const s = recover(child, leafValues);
    if (s !== null) recovered.push({ x: child.x, y: s });
    if (recovered.length === t) break;
  }
  if (recovered.length < t) return null;
  return lagrangeAtZero(recovered.slice(0, t));
}

// Assign stable path ids and per-gate child x indices to every node so that
// encrypt/decrypt agree on indices independent of which attributes a user has.
function annotate(node, pid = "r") {
  node._pid = pid;
  if (node.type !== "leaf") {
    node.children.forEach((c, i) => {
      c.x = BigInt(i + 1);
      annotate(c, `${pid}.${i}`);
    });
  }
}

// ---------------------------------------------------------------------------
// ECIES per attribute (secp256k1 ephemeral ECDH + HKDF + AES-256-GCM)
// ---------------------------------------------------------------------------
function hkdf(secret, info, len = 32) {
  return Buffer.from(crypto.hkdfSync("sha256", secret, Buffer.alloc(0), Buffer.from(info), len));
}

function eciesEncrypt(attrPubKey, plaintext32) {
  const eph = crypto.createECDH("secp256k1");
  eph.generateKeys();
  const shared = eph.computeSecret(attrPubKey); // e * A
  const key = hkdf(shared, "tc-abe-leaf");
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(plaintext32), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    epk: eph.getPublicKey("hex"),
    iv: iv.toString("hex"),
    ct: ct.toString("hex"),
    tag: tag.toString("hex"),
  };
}

function eciesDecrypt(attrSecKey, blob) {
  const dh = crypto.createECDH("secp256k1");
  dh.setPrivateKey(attrSecKey);
  const shared = dh.computeSecret(Buffer.from(blob.epk, "hex")); // a * E
  const key = hkdf(shared, "tc-abe-leaf");
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(blob.iv, "hex"));
  decipher.setAuthTag(Buffer.from(blob.tag, "hex"));
  return Buffer.concat([decipher.update(Buffer.from(blob.ct, "hex")), decipher.final()]);
}

// scalar (BigInt < N) <-> fixed 32-byte buffer
function scalarToBuf(s) {
  return Buffer.from(mod(s).toString(16).padStart(64, "0"), "hex");
}
function bufToScalar(b) {
  return mod(BigInt("0x" + Buffer.from(b).toString("hex")));
}

// ---------------------------------------------------------------------------
// High-level CP-ABE-style hybrid API
// ---------------------------------------------------------------------------

// Attribute authority: owns one secp256k1 keypair per attribute. Public keys
// are used by data owners to encrypt; secret keys are issued to consumers.
class Authority {
  constructor() {
    this._attrs = new Map(); // attr -> { ecdh, pub(Buffer), sec(Buffer) }
  }

  _ensure(attr) {
    if (!this._attrs.has(attr)) {
      const ecdh = crypto.createECDH("secp256k1");
      ecdh.generateKeys();
      this._attrs.set(attr, { pub: ecdh.getPublicKey(), sec: ecdh.getPrivateKey() });
    }
    return this._attrs.get(attr);
  }

  // Public parameters a data owner needs to encrypt under a policy.
  publicKeysFor(attrs) {
    const pp = {};
    for (const a of attrs) pp[a] = this._ensure(a).pub.toString("hex");
    return pp;
  }

  // Issue a consumer key: secret keys for exactly the granted attribute set.
  issueKey(attributes) {
    const keys = {};
    for (const a of attributes) keys[a] = this._ensure(a).sec.toString("hex");
    return { attributes: [...attributes], keys };
  }
}

function collectLeafAttrs(node, acc) {
  if (node.type === "leaf") acc.add(node.attr);
  else node.children.forEach((c) => collectLeafAttrs(c, acc));
  return acc;
}

// Encrypt `data` (Buffer) under `policy` using attribute public keys `pp`.
// Returns a self-contained ciphertext object.
function encrypt(pp, policy, data) {
  annotate(policy);
  const s = randScalar();
  // symmetric key bound to the shared secret s
  const aesKey = hkdf(scalarToBuf(s), "tc-abe-payload");

  const leaves = [];
  distribute(policy, s, leaves);

  const leafCts = {};
  for (const leaf of leaves) {
    const pubHex = pp[leaf.attr];
    if (!pubHex) throw new Error(`missing public key for attribute ${leaf.attr}`);
    leafCts[leaf.pid] = {
      attr: leaf.attr,
      blob: eciesEncrypt(Buffer.from(pubHex, "hex"), scalarToBuf(leaf.share)),
    };
  }

  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", aesKey, iv);
  const payload = Buffer.concat([cipher.update(data), cipher.final()]);
  const tag = cipher.getAuthTag();

  return {
    policy,
    leafCts,
    // Bulk payload kept as a Buffer so large (>256 MB) payloads avoid Node's
    // max hex-string length. Small fields stay hex for easy serialisation.
    payload,
    iv: iv.toString("hex"),
    tag: tag.toString("hex"),
  };
}

// Decrypt with a consumer key (from Authority.issueKey). Returns the plaintext
// Buffer if the consumer's attributes satisfy the policy, else null.
function decrypt(consumerKey, ct) {
  const leafValues = new Map();
  for (const [pid, leaf] of Object.entries(ct.leafCts)) {
    const sec = consumerKey.keys[leaf.attr];
    if (!sec) continue; // consumer lacks this attribute
    try {
      const shareBuf = eciesDecrypt(Buffer.from(sec, "hex"), leaf.blob);
      leafValues.set(pid, bufToScalar(shareBuf));
    } catch (_) {
      // wrong key / tampered leaf -> treat as unavailable
    }
  }

  const s = recover(ct.policy, leafValues);
  if (s === null) return null; // access structure not satisfied

  const aesKey = hkdf(scalarToBuf(s), "tc-abe-payload");
  try {
    const decipher = crypto.createDecipheriv("aes-256-gcm", aesKey, Buffer.from(ct.iv, "hex"));
    decipher.setAuthTag(Buffer.from(ct.tag, "hex"));
    const payloadBuf = Buffer.isBuffer(ct.payload) ? ct.payload : Buffer.from(ct.payload, "hex");
    return Buffer.concat([decipher.update(payloadBuf), decipher.final()]);
  } catch (_) {
    return null; // reconstructed key wrong -> GCM tag rejects
  }
}

// Convenience policy builders.
const leaf = (attr) => ({ type: "leaf", attr });
const AND = (...children) => ({ type: "and", children });
const OR = (...children) => ({ type: "or", children });
const THR = (k, ...children) => ({ type: "thr", k, children });

module.exports = {
  N,
  mod,
  randScalar,
  inv,
  polyEval,
  lagrangeAtZero,
  annotate,
  distribute,
  recover,
  eciesEncrypt,
  eciesDecrypt,
  scalarToBuf,
  bufToScalar,
  hkdf,
  Authority,
  encrypt,
  decrypt,
  collectLeafAttrs,
  leaf,
  AND,
  OR,
  THR,
};
