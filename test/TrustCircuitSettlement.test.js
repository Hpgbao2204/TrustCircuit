const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
  artifactsExist,
  loadPhase7Fixture,
} = require("./helpers/phase7_fixture");

const describePhase7 = artifactsExist() ? describe : describe.skip;

describePhase7("TrustCircuitSettlement atomic Phase 7 flow", function () {
  let fixture;

  before(async function () {
    this.timeout(120_000);
    fixture = await loadPhase7Fixture();
  });

  function bytes32(value) {
    return ethers.zeroPadValue(ethers.toBeHex(value), 32);
  }

  async function deployContext(overrides = {}) {
    const [provider, consumer, stranger] = await ethers.getSigners();
    const Registry = await ethers.getContractFactory("DataRegistry");
    const Access = await ethers.getContractFactory("AccessController");
    const Budget = await ethers.getContractFactory("BudgetLedger");
    const Audit = await ethers.getContractFactory("AuditLedger");
    const Native = await ethers.getContractFactory("Phase7Groth16Verifier");
    const registry = await Registry.deploy();
    const access = await Access.deploy();
    const budget = await Budget.deploy();
    const audit = await Audit.deploy();
    const native = await Native.deploy();
    await Promise.all([
      registry.waitForDeployment(),
      access.waitForDeployment(),
      budget.waitForDeployment(),
      audit.waitForDeployment(),
      native.waitForDeployment(),
    ]);
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await native.getAddress());
    await adapter.waitForDeployment();
    const Settlement = await ethers.getContractFactory("TrustCircuitSettlement");
    const settlement = await Settlement.deploy(
      await registry.getAddress(),
      await access.getAddress(),
      await budget.getAddress(),
      await adapter.getAddress(),
      await audit.getAddress()
    );
    await settlement.waitForDeployment();

    const chain = {
      requestKey: bytes32(fixture.values.requestId),
      assetKey: bytes32(overrides.assetKey ?? fixture.values.assetId),
      consumerId: overrides.consumerId ?? fixture.values.consumerId,
      policyHash: bytes32(overrides.policyHash ?? fixture.values.policyHash),
      policyVersion: overrides.policyVersion ?? fixture.values.policyVersion,
      functionId: overrides.functionId ?? fixture.values.functionId,
      epsilonRequested: overrides.epsilonRequested ?? fixture.values.epsilonCost,
      dataHash: bytes32(999n),
      resultHash: bytes32(overrides.resultHash ?? fixture.values.resultHash),
      transcriptHash: bytes32(
        overrides.transcriptHash ?? fixture.values.transcriptHash
      ),
      attestationDigest: bytes32(
        overrides.attestationDigest ?? fixture.values.attestationDigest
      ),
      expiry: overrides.expiry ?? 4_102_444_800_000n,
    };
    await registry.registerAssetV2(
      chain.assetKey,
      bytes32(123n),
      chain.dataHash,
      chain.policyHash,
      chain.policyVersion
    );
    await budget.registerBudget(chain.assetKey, fixture.values.epsilonCost * 10n);
    await access.connect(consumer).requestAccessV2(
      chain.requestKey,
      chain.assetKey,
      chain.consumerId,
      bytes32(321n),
      chain.policyHash,
      chain.policyVersion,
      chain.functionId,
      chain.epsilonRequested
    );
    await access.approveRequest(chain.requestKey);
    await settlement.reserveBudgetForRequest(chain.requestKey);
    await adapter.registerExpectation(chain.requestKey, {
      requestId: fixture.values.requestId,
      assetId: fixture.values.assetId,
      consumerId: fixture.values.consumerId,
      policyHash: fixture.values.policyHash,
      policyVersion: fixture.values.policyVersion,
      functionId: fixture.values.functionId,
      resultHash: fixture.values.resultHash,
      maxEpsilon: fixture.values.epsilonCost,
      transcriptHash: fixture.values.transcriptHash,
      attestationDigest: fixture.values.attestationDigest,
      attestationExpiresAtUnixMs: chain.expiry,
    });
    return {
      provider,
      consumer,
      stranger,
      registry,
      access,
      budget,
      audit,
      adapter,
      settlement,
      chain,
      evidence: {
        dataHash: chain.dataHash,
        resultHash: chain.resultHash,
        transcriptHash: chain.transcriptHash,
        attestationDigest: chain.attestationDigest,
      },
    };
  }

  function settle(context, signer = context.consumer, proofA = fixture.a) {
    return context.settlement.connect(signer).settle(
      context.chain.requestKey,
      context.evidence,
      proofA,
      fixture.b,
      fixture.c,
      fixture.signals
    );
  }

  async function expectAtomicRollback(context) {
    const budgetState = await context.budget.getBudget(context.chain.assetKey);
    const requestState = await context.access.getRequest(context.chain.requestKey);
    const expectation = await context.adapter.getExpectation(context.chain.requestKey);
    expect(budgetState.reserved).to.equal(context.chain.epsilonRequested);
    expect(budgetState.used).to.equal(0n);
    expect(requestState.status).to.equal(2n);
    expect(expectation.verified).to.equal(false);
    expect(await context.adapter.nullifierUsed(fixture.values.nullifier)).to.equal(false);
  }

  it("settles proof, budget, nullifier, request, and audit atomically", async function () {
    const context = await deployContext();
    await expect(settle(context))
      .to.emit(context.audit, "SettlementAuditRecorded")
      .and.to.emit(context.settlement, "RequestSettled");
    const budgetState = await context.budget.getBudget(context.chain.assetKey);
    const requestState = await context.access.getRequest(context.chain.requestKey);
    expect(budgetState.reserved).to.equal(0n);
    expect(budgetState.used).to.equal(fixture.values.epsilonCost);
    expect(requestState.status).to.equal(4n);
    expect(await context.adapter.nullifierUsed(fixture.values.nullifier)).to.equal(true);
  });

  it("rejects a wrong request", async function () {
    const context = await deployContext();
    const wrongRequest = bytes32(fixture.values.requestId + 1n);
    await expect(
      context.settlement.connect(context.consumer).settle(
        wrongRequest,
        context.evidence,
        fixture.a,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    ).to.be.reverted;
    await expectAtomicRollback(context);
  });

  it("rejects a wrong asset", async function () {
    const context = await deployContext({ assetKey: fixture.values.assetId + 1n });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(1);
    await expectAtomicRollback(context);
  });

  it("rejects a wrong consumer address", async function () {
    const context = await deployContext();
    await expect(settle(context, context.stranger)).to.be.revertedWithCustomError(
      context.settlement,
      "WrongConsumer"
    );
    await expectAtomicRollback(context);
  });

  it("rejects a wrong consumer identifier", async function () {
    const context = await deployContext({ consumerId: fixture.values.consumerId + 1n });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(2);
    await expectAtomicRollback(context);
  });

  it("rejects a wrong policy", async function () {
    const context = await deployContext({ policyHash: fixture.values.policyHash + 1n });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(3);
    await expectAtomicRollback(context);
  });

  it("rejects a wrong result", async function () {
    const context = await deployContext({ resultHash: fixture.values.resultHash + 1n });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(6);
    await expectAtomicRollback(context);
  });

  it("rejects an over-budget settlement", async function () {
    const context = await deployContext({
      epsilonRequested: fixture.values.epsilonCost - 1n,
    });
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.settlement,
      "PrivacyCostExceedsReservation"
    );
    await expectAtomicRollback(context);
  });

  it("rejects an altered transcript", async function () {
    const context = await deployContext({
      transcriptHash: fixture.values.transcriptHash + 1n,
    });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(9);
    await expectAtomicRollback(context);
  });

  it("rejects altered attestation evidence", async function () {
    const context = await deployContext({
      attestationDigest: fixture.values.attestationDigest + 1n,
    });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(10);
    await expectAtomicRollback(context);
  });

  it("rejects stale attestation and rolls back proof state", async function () {
    const context = await deployContext({ expiry: 1n });
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.adapter,
      "StaleAttestation"
    );
    await expectAtomicRollback(context);
  });

  it("rejects function/policy context substitution", async function () {
    const context = await deployContext({ functionId: 1n });
    await expect(settle(context))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(5);
    await expectAtomicRollback(context);
  });

  it("rejects a tampered proof and rolls back all downstream state", async function () {
    const context = await deployContext();
    const tamperedA = [...fixture.a];
    tamperedA[0] = (BigInt(tamperedA[0]) ^ 1n).toString();
    await expect(settle(context, context.consumer, tamperedA)).to.be.revertedWithCustomError(
      context.adapter,
      "InvalidProof"
    );
    await expectAtomicRollback(context);
  });

  it("rejects replay after a completed settlement", async function () {
    const context = await deployContext();
    await settle(context);
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.settlement,
      "RequestNotApproved"
    );
  });
});

