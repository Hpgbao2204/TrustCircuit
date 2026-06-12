const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("MockComplianceVerifier", function () {
  async function deployVerifier() {
    const Verifier = await ethers.getContractFactory("MockComplianceVerifier");
    const verifier = await Verifier.deploy();
    return {
      verifier,
      requestId: ethers.id("request:001"),
      assetId: ethers.id("asset:healthcare:001"),
      proofHash: ethers.id("mock-proof:001"),
    };
  }

  it("accepts a mock proof", async function () {
    const { verifier, requestId, assetId, proofHash } = await deployVerifier();

    await expect(verifier.submitProof(requestId, assetId, proofHash, true))
      .to.emit(verifier, "ProofSubmitted")
      .withArgs(requestId, assetId, proofHash, true);
  });

  it("rejects a failed mock proof", async function () {
    const { verifier, requestId, assetId, proofHash } = await deployVerifier();

    await expect(verifier.submitProof(requestId, assetId, proofHash, false))
      .to.be.revertedWithCustomError(verifier, "InvalidProof");
  });
});
