const { expect } = require("chai");
const { ethers } = require("hardhat");
const S = require("../scripts/lib/v3_stack");

// Settlement guards of the revised stack (quorum statement, ledger RDP charge).
// The Groth16 verifier is mocked here; real proofs are exercised in
// RevisionV3.test.js and scripts/revision/run_attack_matrix.js.
describe("TrustCircuitSettlement (revised stack)", function () {
  const SIGMA = 9_689_610n;
  let provider;
  let consumer;
  let stranger;
  let validators;

  before(async function () {
    [, provider, consumer, stranger] = await ethers.getSigners();
    validators = await S.makeValidators(ethers, 2);
  });

  async function context() {
    const stack = await S.deployStack(ethers, "trustcircuit", { threshold: 1, validators: validators.slice(0, 1) });
    const asset = await S.registerAsset(stack, provider, { name: "asset-settlement", matrix: [[1n, 1n], [0n, 1n]] });
    const request = await S.openRequest(stack, consumer, asset, { name: "request-settlement", purposeId: 1, functionId: 2, sigmaFixed: SIGMA });
    const bundle = await S.executeRequest(stack, request);
    return { stack, asset, request, bundle };
  }

  it("settles validator, proof, budget, nullifier, request, and audit atomically", async function () {
    const { stack, asset, request, bundle } = await context();
    const tx = await S.settleTrustCircuit(stack, request, bundle);
    await expect(tx).to.emit(stack.settlement, "RequestSettled");
    await expect(tx).to.emit(stack.audit, "VCPSettlementAuditRecorded");
    expect((await stack.access.getRequest(request.requestId)).status).to.equal(5n);
    expect(await stack.adapter.nullifierUsed(bundle.built.values.nullifier)).to.equal(true);
    const [, reserved, used] = await stack.budget.getBudget(asset.assetKey);
    expect(reserved).to.equal(0n);
    expect(used).to.be.gt(0n);
    expect(used).to.be.lte(request.reserved);
  });

  it("rejects a caller other than the bound consumer", async function () {
    const { stack, request, bundle } = await context();
    await expect(S.settleTrustCircuit(stack, { ...request, consumer: stranger }, bundle))
      .to.be.revertedWithCustomError(stack.settlement, "WrongConsumer");
  });

  it("rejects substitution of either request-id limb", async function () {
    const { stack, request, bundle } = await context();
    for (const index of [0, 1]) {
      const signals = [...bundle.built.publicSignals];
      signals[index] = (BigInt(signals[index]) ^ 1n).toString();
      await expect(S.settleTrustCircuit(stack, request, bundle, { publicSignals: signals }))
        .to.be.revertedWithCustomError(stack.settlement, "ContextMismatch")
        .withArgs(index);
    }
  });

  it("rejects a validator signature from an unauthorized key", async function () {
    const { stack, request } = await context();
    const rogue = { id: validators[0].id, wallet: stranger };
    const bundle = await S.executeRequest(stack, request, { signers: [rogue] });
    await expect(S.settleTrustCircuit(stack, request, bundle))
      .to.be.revertedWithCustomError(stack.validatorRegistry, "InvalidValidatorSignature");
  });

  it("rejects a revoked validator", async function () {
    const { stack, request, bundle } = await context();
    await (await stack.validatorRegistry.revokeValidator(validators[0].id)).wait();
    await expect(S.settleTrustCircuit(stack, request, bundle))
      .to.be.revertedWithCustomError(stack.validatorRegistry, "ValidatorNotActive");
  });

  it("rolls back all downstream state when proof verification fails", async function () {
    const { stack, asset, request, bundle } = await context();
    await (await stack.verifier.setAccepted(false)).wait();
    await expect(S.settleTrustCircuit(stack, request, bundle))
      .to.be.revertedWithCustomError(stack.adapter, "InvalidProof");
    expect((await stack.access.getRequest(request.requestId)).status).to.equal(4n);
    const [, reserved, used] = await stack.budget.getBudget(asset.assetKey);
    expect(reserved).to.equal(request.reserved);
    expect(used).to.equal(0n);
    expect(await stack.adapter.nullifierUsed(bundle.built.values.nullifier)).to.equal(false);
  });

  it("rejects replay after the request reaches a terminal state", async function () {
    const { stack, request, bundle } = await context();
    await (await S.settleTrustCircuit(stack, request, bundle)).wait();
    await expect(S.settleTrustCircuit(stack, request, bundle))
      .to.be.revertedWithCustomError(stack.settlement, "RequestNotReserved");
  });

  it("rejects an expired request even with valid evidence", async function () {
    const { stack, request, bundle } = await context();
    await ethers.provider.send("evm_increaseTime", [7200]);
    await ethers.provider.send("evm_mine", []);
    await expect(S.settleTrustCircuit(stack, request, bundle)).to.be.reverted;
  });
});
