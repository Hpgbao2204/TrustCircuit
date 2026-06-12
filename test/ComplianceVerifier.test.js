const fs = require("fs");
const path = require("path");
const { expect } = require("chai");
const { ethers } = require("hardhat");

/**
 * Integration tests for the real ZK compliance adapter.
 *
 * These use the actual Groth16 proof/calldata produced by the benchmark
 * (`npm run zk:benchmark` -> zk/build/compliance_2_calldata.txt) against the
 * exported verifier (contracts/ComplianceGroth16Verifier.sol). The public
 * signal order is:
 *   [0] assetId [1] consumerId [2] requestId [3] policyHash
 *   [4] epsilonCost [5] nullifier [6] attestationHash
 */
const CALLDATA_PATH = path.join(__dirname, "..", "zk", "build", "compliance_2_calldata.txt");

function loadCalldata() {
  if (!fs.existsSync(CALLDATA_PATH)) return null;
  const raw = fs.readFileSync(CALLDATA_PATH, "utf8").trim();
  const [a, b, c, input] = JSON.parse(`[${raw}]`);
  return { a, b, c, input };
}

const cd = loadCalldata();
const describeOrSkip = cd ? describe : describe.skip;

describeOrSkip("ComplianceVerifier (real Groth16 integration)", function () {
  // Public-signal values baked into the benchmark proof.
  const ASSET = BigInt(cd ? cd.input[0] : 0); // 111
  const CONSUMER = BigInt(cd ? cd.input[1] : 0); // 222
  const REQUEST_SIGNAL = BigInt(cd ? cd.input[2] : 0); // 333
  const POLICY = BigInt(cd ? cd.input[3] : 0); // 444
  const EPSILON = BigInt(cd ? cd.input[4] : 0); // 500000
  const NULLIFIER = BigInt(cd ? cd.input[5] : 0);
  const ATTESTATION = BigInt(cd ? cd.input[6] : 0);

  // bytes32 requestId whose field reduction equals the proof's request signal.
  const REQUEST_ID = ethers.zeroPadValue(ethers.toBeHex(REQUEST_SIGNAL), 32);

  async function deploy(maxEpsilon = EPSILON) {
    const [owner, stranger] = await ethers.getSigners();
    const Groth16 = await ethers.getContractFactory("Groth16Verifier");
    const groth16 = await Groth16.deploy();
    await groth16.waitForDeployment();

    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await groth16.getAddress());
    await adapter.waitForDeployment();

    await adapter.registerExpectation(REQUEST_ID, ASSET, CONSUMER, POLICY, maxEpsilon);
    return { adapter, groth16, owner, stranger };
  }

  it("rejects a zero verifier address", async function () {
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    await expect(Adapter.deploy(ethers.ZeroAddress)).to.be.revertedWithCustomError(
      Adapter,
      "ZeroVerifier"
    );
  });

  it("accepts a valid proof and binds it to the request", async function () {
    const { adapter } = await deploy();

    await expect(adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, cd.input))
      .to.emit(adapter, "ComplianceVerified")
      .withArgs(REQUEST_ID, NULLIFIER, EPSILON, ATTESTATION);

    expect(await adapter.isVerified(REQUEST_ID)).to.equal(true);
    expect(await adapter.nullifierUsed(NULLIFIER)).to.equal(true);

    const exp = await adapter.getExpectation(REQUEST_ID);
    expect(exp.verified).to.equal(true);
    expect(exp.epsilonUsed).to.equal(EPSILON);
    expect(exp.attestationHash).to.equal(ATTESTATION);
  });

  it("rejects a second submission for the same request (replay)", async function () {
    const { adapter } = await deploy();
    await adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, cd.input);

    await expect(
      adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, cd.input)
    ).to.be.revertedWithCustomError(adapter, "AlreadyVerified");
  });

  it("rejects a proof for an unregistered request", async function () {
    const { adapter } = await deploy();
    const other = ethers.zeroPadValue(ethers.toBeHex(999n), 32);
    await expect(
      adapter.submitCompliance(other, cd.a, cd.b, cd.c, cd.input)
    ).to.be.revertedWithCustomError(adapter, "NotRegistered");
  });

  it("rejects a request-id / public-signal mismatch", async function () {
    const [owner] = await ethers.getSigners();
    const Groth16 = await ethers.getContractFactory("Groth16Verifier");
    const groth16 = await Groth16.deploy();
    await groth16.waitForDeployment();
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await groth16.getAddress());
    await adapter.waitForDeployment();

    // Register a request whose key does NOT match the proof's request signal.
    const wrongRequestId = ethers.zeroPadValue(ethers.toBeHex(REQUEST_SIGNAL + 1n), 32);
    await adapter.registerExpectation(wrongRequestId, ASSET, CONSUMER, POLICY, EPSILON);

    await expect(
      adapter.submitCompliance(wrongRequestId, cd.a, cd.b, cd.c, cd.input)
    ).to.be.revertedWithCustomError(adapter, "RequestIdMismatch");
  });

  it("rejects a mismatched bound public input (wrong asset)", async function () {
    const [owner] = await ethers.getSigners();
    const Groth16 = await ethers.getContractFactory("Groth16Verifier");
    const groth16 = await Groth16.deploy();
    await groth16.waitForDeployment();
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await groth16.getAddress());
    await adapter.waitForDeployment();

    // Register with a different assetId than the proof commits to.
    await adapter.registerExpectation(REQUEST_ID, ASSET + 1n, CONSUMER, POLICY, EPSILON);

    await expect(
      adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, cd.input)
    ).to.be.revertedWithCustomError(adapter, "PublicInputMismatch");
  });

  it("rejects when the proven epsilon exceeds the registered budget", async function () {
    const { adapter } = await deploy(EPSILON - 1n); // ceiling below proven cost
    await expect(
      adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, cd.input)
    ).to.be.revertedWithCustomError(adapter, "BudgetExceeded");
  });

  it("rejects a tampered proof", async function () {
    const { adapter } = await deploy();
    const tampered = [...cd.input];
    // flip the attestation hash so the proof no longer verifies
    tampered[6] = "0x" + (ATTESTATION ^ 1n).toString(16);
    await expect(
      adapter.submitCompliance(REQUEST_ID, cd.a, cd.b, cd.c, tampered)
    ).to.be.reverted; // PublicInputMismatch is not hit (idx6 unbound); proof fails
  });

  it("restricts registerExpectation to the owner", async function () {
    const { adapter, stranger } = await deploy();
    const newReq = ethers.zeroPadValue(ethers.toBeHex(1234n), 32);
    await expect(
      adapter.connect(stranger).registerExpectation(newReq, ASSET, CONSUMER, POLICY, EPSILON)
    ).to.be.revertedWithCustomError(adapter, "NotOwner");
  });
});
