
"use strict";

const crypto = require("crypto");

const N = 115792089237316195423570985008687907852837564279074904382605163141518161494337n;

function mod(a, m = N) {
  return ((a % m) + m) % m;
}

function randScalar() {
  while (true) {
    const x = mod(BigInt("0x" + crypto.randomBytes(32).toString("hex")));
    if (x !== 0n) return x;
  }
}

function inv(a, m = N) {
  let [old_r, r] = [mod(a, m), m];
  let [old_s, s] = [1n, 0n];
  while (r !== 0n) {
    const q = old_r / r;
    [old_r, r] = [r, old_r - q * r];
    [old_s, s] = [s, old_s - q * s];
  }
  return mod(old_s, m);
}

function polyEval(coeffs, x) {
  let acc = 0n;
  for (let i = coeffs.length - 1; i >= 0; i--) {
    acc = mod(acc * x + coeffs[i]);
  }
  return acc;
}

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

function thresholdOf(node) {
  if (node.type === "and") return node.children.length;
  if (node.type === "or") return 1;
  if (node.type === "thr") return node.k;
  throw new Error(`unknown gate ${node.type}`);
}

function distribute(node, secret, out) {
  if (node.type === "leaf") {
    out.push({ pid: node._pid, attr: node.attr, share: mod(secret) });
    return;
  }
  const t = thresholdOf(node);
  const coeffs = [mod(secret)];
  for (let i = 1; i < t; i++) coeffs.push(randScalar());
  for (const child of node.children) {
    distribute(child, polyEval(coeffs, child.x), out);
  }
}

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

function annotate(node, pid = "r") {
  node._pid = pid;
  if (node.type !== "leaf") {
    node.children.forEach((c, i) => {
      c.x = BigInt(i + 1);
      annotate(c, `${pid}.${i}`);
    });
  }
}

function hkdf(secret, info, len = 32) {
  return Buffer.from(crypto.hkdfSync("sha256", secret, Buffer.alloc(0), Buffer.from(info), len));
}

function eciesEncrypt(attrPubKey, plaintext32) {
  const eph = crypto.createECDH("secp256k1");
  eph.generateKeys();
  const shared = eph.computeSecret(attrPubKey);
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
  const shared = dh.computeSecret(Buffer.from(blob.epk, "hex"));
  const key = hkdf(shared, "tc-abe-leaf");
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(blob.iv, "hex"));
  decipher.setAuthTag(Buffer.from(blob.tag, "hex"));
  return Buffer.concat([decipher.update(Buffer.from(blob.ct, "hex")), decipher.final()]);
}

function scalarToBuf(s) {
  return Buffer.from(mod(s).toString(16).padStart(64, "0"), "hex");
}
function bufToScalar(b) {
  return mod(BigInt("0x" + Buffer.from(b).toString("hex")));
}


class Authority {
  constructor() {
    this._attrs = new Map();
  }

  _ensure(attr) {
    if (!this._attrs.has(attr)) {
      const ecdh = crypto.createECDH("secp256k1");
      ecdh.generateKeys();
      this._attrs.set(attr, { pub: ecdh.getPublicKey(), sec: ecdh.getPrivateKey() });
    }
    return this._attrs.get(attr);
  }

  publicKeysFor(attrs) {
    const pp = {};
    for (const a of attrs) pp[a] = this._ensure(a).pub.toString("hex");
    return pp;
  }

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

function encrypt(pp, policy, data) {
  annotate(policy);
  const s = randScalar();
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
    payload,
    iv: iv.toString("hex"),
    tag: tag.toString("hex"),
  };
}

function decrypt(consumerKey, ct) {
  const leafValues = new Map();
  for (const [pid, leaf] of Object.entries(ct.leafCts)) {
    const sec = consumerKey.keys[leaf.attr];
    if (!sec) continue;
    try {
      const shareBuf = eciesDecrypt(Buffer.from(sec, "hex"), leaf.blob);
      leafValues.set(pid, bufToScalar(shareBuf));
    } catch (_) {
    }
  }

  const s = recover(ct.policy, leafValues);
  if (s === null) return null;

  const aesKey = hkdf(scalarToBuf(s), "tc-abe-payload");
  try {
    const decipher = crypto.createDecipheriv("aes-256-gcm", aesKey, Buffer.from(ct.iv, "hex"));
    decipher.setAuthTag(Buffer.from(ct.tag, "hex"));
    const payloadBuf = Buffer.isBuffer(ct.payload) ? ct.payload : Buffer.from(ct.payload, "hex");
    return Buffer.concat([decipher.update(payloadBuf), decipher.final()]);
  } catch (_) {
    return null;
  }
}

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
