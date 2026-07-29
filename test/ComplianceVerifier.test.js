const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("ComplianceVerifier VCP v2 adapter", function () {
  const RESERVED = 500_000n;
  const ACTUAL = 400_000n;
  const NULLIFIER = 123456n;

  function split(value) {
    const integer = BigInt(value);
    return [integer & ((1n << 128n) - 1n), integer >> 128n];
  }

  function proof() {
    return {
      a: [0n, 0n],
      b: [[0n, 0n], [0n, 0n]],
      c: [0n, 0n],
    };
  }

  function signals(requestKey, overrides = {}) {
    const values = Array(24).fill(0n);
    [values[0], values[1]] = split(requestKey);
    values[16] = RESERVED;
    values[17] = ACTUAL;
    values[18] = NULLIFIER;
    values[22] = 456n;
    values[23] = 789n;
    for (const [index, value] of Object.entries(overrides)) {
      values[Number(index)] = BigInt(value);
    }
    return values;
  }

  async function deploy() {
    const [owner, stranger] = await ethers.getSigners();
    const Native = await ethers.getContractFactory("MockVCPGroth16Verifier");
    const native = await Native.deploy();
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await native.getAddress());
    await Promise.all([native.waitForDeployment(), adapter.waitForDeployment()]);
    return {
      owner,
      stranger,
      native,
      adapter,
      requestKey: ethers.id("vcp-v2-request"),
      proof: proof(),
    };
  }

  it("rejects a zero verifier address", async function () {
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    await expect(Adapter.deploy(ethers.ZeroAddress)).to.be.revertedWithCustomError(
      Adapter,
      "ZeroVerifier"
    );
  });

  it("accepts a 24-signal proof and consumes its nullifier", async function () {
    const context = await deploy();
    const publicSignals = signals(context.requestKey);
    await expect(
      context.adapter.submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        publicSignals
      )
    )
      .to.emit(context.adapter, "ComplianceVerified")
      .withArgs(
        context.requestKey,
        NULLIFIER,
        RESERVED,
        ACTUAL,
        456n,
        789n
      );
    expect(await context.adapter.nullifierUsed(NULLIFIER)).to.equal(true);
    expect(await context.adapter.requestVerified(context.requestKey)).to.equal(true);
  });

  it("rejects a caller without the coordinator role", async function () {
    const context = await deploy();
    await expect(
      context.adapter.connect(context.stranger).submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        signals(context.requestKey)
      )
    ).to.be.revertedWithCustomError(context.adapter, "NotCoordinator");
  });

  it("rejects a non-injective request substitution", async function () {
    const context = await deploy();
    await expect(
      context.adapter.submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        signals(context.requestKey, { 0: 1n })
      )
    ).to.be.revertedWithCustomError(context.adapter, "RequestIdMismatch");
  });

  it("rejects invalid budget values", async function () {
    const context = await deploy();
    await expect(
      context.adapter.submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        signals(context.requestKey, { 17: RESERVED + 1n })
      )
    ).to.be.revertedWithCustomError(context.adapter, "InvalidPrivacyCost");
  });

  it("rejects a replay", async function () {
    const context = await deploy();
    const publicSignals = signals(context.requestKey);
    await context.adapter.submitCompliance(
      context.requestKey,
      context.proof.a,
      context.proof.b,
      context.proof.c,
      publicSignals
    );
    await expect(
      context.adapter.submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        publicSignals
      )
    ).to.be.revertedWithCustomError(context.adapter, "RequestAlreadyVerified");
  });

  it("rejects a failed Groth16 verification", async function () {
    const context = await deploy();
    await context.native.setAccepted(false);
    await expect(
      context.adapter.submitCompliance(
        context.requestKey,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        signals(context.requestKey)
      )
    ).to.be.revertedWithCustomError(context.adapter, "InvalidProof");
  });
});
