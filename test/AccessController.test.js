const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AccessController", function () {
  async function deployAccessController() {
    const [provider, consumer] = await ethers.getSigners();
    const AccessController = await ethers.getContractFactory("AccessController");
    const access = await AccessController.deploy();
    return {
      access,
      provider,
      consumer,
      assetId: ethers.id("asset:healthcare:001"),
      requestId: ethers.id("request:001"),
      purposeHash: ethers.id("research:aggregate"),
      epsilon: 500_000n,
    };
  }

  it("creates and approves an access request", async function () {
    const { access, consumer, assetId, requestId, purposeHash, epsilon } = await deployAccessController();

    await expect(access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilon))
      .to.emit(access, "AccessRequested")
      .withArgs(requestId, assetId, consumer.address, purposeHash, epsilon);

    await expect(access.approveRequest(requestId))
      .to.emit(access, "AccessApproved")
      .withArgs(requestId, assetId);

    const stored = await access.getRequest(requestId);
    expect(stored.consumer).to.equal(consumer.address);
    expect(stored.status).to.equal(2);
  });

  it("rejects duplicate request ids", async function () {
    const { access, consumer, assetId, requestId, purposeHash, epsilon } = await deployAccessController();

    await access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilon);
    await expect(access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilon))
      .to.be.revertedWithCustomError(access, "RequestAlreadyExists");
  });

  it("completes only approved requests", async function () {
    const { access, consumer, assetId, requestId, purposeHash, epsilon } = await deployAccessController();

    await access.connect(consumer).requestAccess(requestId, assetId, purposeHash, epsilon);
    await expect(access.completeRequest(requestId))
      .to.be.revertedWithCustomError(access, "InvalidRequestState");

    await access.approveRequest(requestId);
    await expect(access.completeRequest(requestId))
      .to.emit(access, "AccessCompleted")
      .withArgs(requestId, assetId);
  });
});
