const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("BudgetLedger", function () {
  const totalBudget = 1_000_000n;
  const reserveAmount = 500_000n;

  async function deployLedger() {
    const BudgetLedger = await ethers.getContractFactory("BudgetLedger");
    const ledger = await BudgetLedger.deploy();
    const assetId = ethers.id("asset:healthcare:001");
    const requestId = ethers.id("request:001");
    return { ledger, assetId, requestId };
  }

  it("registers and reserves budget", async function () {
    const { ledger, assetId, requestId } = await deployLedger();

    await expect(ledger.registerBudget(assetId, totalBudget))
      .to.emit(ledger, "BudgetRegistered")
      .withArgs(assetId, totalBudget);

    await expect(ledger.reserveBudget(assetId, requestId, reserveAmount))
      .to.emit(ledger, "BudgetReserved")
      .withArgs(assetId, requestId, reserveAmount);

    expect(await ledger.remaining(assetId)).to.equal(totalBudget - reserveAmount);
  });

  it("rejects overspending", async function () {
    const { ledger, assetId, requestId } = await deployLedger();

    await ledger.registerBudget(assetId, totalBudget);
    await expect(ledger.reserveBudget(assetId, requestId, totalBudget + 1n))
      .to.be.revertedWithCustomError(ledger, "InsufficientBudget");
  });

  it("consumes a reservation once", async function () {
    const { ledger, assetId, requestId } = await deployLedger();

    await ledger.registerBudget(assetId, totalBudget);
    await ledger.reserveBudget(assetId, requestId, reserveAmount);
    await expect(ledger.consumeBudget(assetId, requestId, reserveAmount))
      .to.emit(ledger, "BudgetConsumed")
      .withArgs(assetId, requestId, reserveAmount);

    const budget = await ledger.getBudget(assetId);
    expect(budget.used).to.equal(reserveAmount);
    expect(budget.reserved).to.equal(0);

    await expect(ledger.consumeBudget(assetId, requestId, reserveAmount))
      .to.be.revertedWithCustomError(ledger, "InvalidReservationState");
  });

  it("releases a reservation once", async function () {
    const { ledger, assetId, requestId } = await deployLedger();

    await ledger.registerBudget(assetId, totalBudget);
    await ledger.reserveBudget(assetId, requestId, reserveAmount);
    await expect(ledger.releaseBudget(assetId, requestId))
      .to.emit(ledger, "BudgetReleased")
      .withArgs(assetId, requestId, reserveAmount);

    expect(await ledger.remaining(assetId)).to.equal(totalBudget);
    await expect(ledger.releaseBudget(assetId, requestId))
      .to.be.revertedWithCustomError(ledger, "InvalidReservationState");
  });
});
