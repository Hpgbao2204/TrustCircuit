const { expect } = require("chai");
const crypto = require("crypto");
const {
  Authority,
  encrypt,
  decrypt,
  collectLeafAttrs,
  leaf,
  AND,
  OR,
  THR,
} = require("../crypto/abe_hybrid");

describe("CP-ABE-style hybrid encryption (LSSS + ECIES + AES-256-GCM)", function () {
  function setup(policy) {
    const authority = new Authority();
    const attrs = [...collectLeafAttrs(policy, new Set())];
    const pp = authority.publicKeysFor(attrs);
    return { authority, pp };
  }

  it("authorized attribute set decrypts (AND + OR policy)", function () {
    // (role:doctor) AND (dept:cardiology OR dept:research)
    const policy = AND(leaf("role:doctor"), OR(leaf("dept:cardiology"), leaf("dept:research")));
    const { authority, pp } = setup(policy);
    const data = Buffer.from("patient-record: confidential payload \u2764", "utf8");

    const ct = encrypt(pp, policy, data);

    const k1 = authority.issueKey(["role:doctor", "dept:cardiology"]);
    const k2 = authority.issueKey(["role:doctor", "dept:research"]);

    expect(decrypt(k1, ct).equals(data)).to.equal(true);
    expect(decrypt(k2, ct).equals(data)).to.equal(true);
  });

  it("rejects a consumer missing a required AND attribute", function () {
    const policy = AND(leaf("role:doctor"), OR(leaf("dept:cardiology"), leaf("dept:research")));
    const { authority, pp } = setup(policy);
    const ct = encrypt(pp, policy, Buffer.from("secret"));

    // has the OR branch but not the required role
    const bad = authority.issueKey(["dept:cardiology"]);
    expect(decrypt(bad, ct)).to.equal(null);
  });

  it("rejects a consumer that satisfies neither OR branch", function () {
    const policy = AND(leaf("role:doctor"), OR(leaf("dept:cardiology"), leaf("dept:research")));
    const { authority, pp } = setup(policy);
    const ct = encrypt(pp, policy, Buffer.from("secret"));

    const bad = authority.issueKey(["role:doctor"]); // OR unsatisfied
    expect(decrypt(bad, ct)).to.equal(null);
  });

  it("enforces k-of-n threshold gates", function () {
    const policy = THR(2, leaf("a"), leaf("b"), leaf("c"));
    const { authority, pp } = setup(policy);
    const data = Buffer.from("threshold-protected");
    const ct = encrypt(pp, policy, data);

    expect(decrypt(authority.issueKey(["a", "b"]), ct).equals(data)).to.equal(true);
    expect(decrypt(authority.issueKey(["b", "c"]), ct).equals(data)).to.equal(true);
    expect(decrypt(authority.issueKey(["a", "b", "c"]), ct).equals(data)).to.equal(true);
    expect(decrypt(authority.issueKey(["a"]), ct)).to.equal(null);
  });

  it("rejects a tampered payload via the GCM auth tag", function () {
    const policy = OR(leaf("x"), leaf("y"));
    const { authority, pp } = setup(policy);
    const ct = encrypt(pp, policy, Buffer.from("authentic"));

    // flip a byte of the ciphertext payload
    const buf = Buffer.isBuffer(ct.payload) ? Buffer.from(ct.payload) : Buffer.from(ct.payload, "hex");
    buf[0] ^= 0xff;
    ct.payload = buf;

    const k = authority.issueKey(["x"]);
    expect(decrypt(k, ct)).to.equal(null);
  });

  it("a consumer key for the wrong attribute cannot read a leaf share", function () {
    const policy = AND(leaf("p"), leaf("q"));
    const { authority, pp } = setup(policy);
    const ct = encrypt(pp, policy, Buffer.from("data"));

    // attacker holds a key for an unrelated attribute issued by the authority
    const attacker = authority.issueKey(["p", "z"]); // has p, lacks q
    expect(decrypt(attacker, ct)).to.equal(null);
  });

  it("supports large payloads (hybrid AES-256-GCM bulk path)", function () {
    const policy = OR(leaf("tier:gold"), leaf("tier:platinum"));
    const { authority, pp } = setup(policy);
    const data = crypto.randomBytes(256 * 1024); // 256 KiB
    const ct = encrypt(pp, policy, data);
    const k = authority.issueKey(["tier:platinum"]);
    expect(decrypt(k, ct).equals(data)).to.equal(true);
  });
});
