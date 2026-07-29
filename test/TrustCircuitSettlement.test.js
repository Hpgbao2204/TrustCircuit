const { expect } = require("chai");
const { ethers } = require("hardhat");
const { buildPoseidon } = require("circomlibjs");
const {
  buildProofInput,
  identifierDigest,
} = require("../scripts/lib/phase7_encoding");

describe("TrustCircuitSettlement VCP v2", function () {
  let poseidon;

  before(async function () {
    poseidon = await buildPoseidon();
  });

  function proof() {
    return {
      a: [0n, 0n],
      b: [[0n, 0n], [0n, 0n]],
      c: [0n, 0n],
    };
  }

  async function deployContext() {
    const [provider, consumer, validator, stranger] = await ethers.getSigners();
    const Registry = await ethers.getContractFactory("DataRegistry");
    const Access = await ethers.getContractFactory("AccessController");
    const Budget = await ethers.getContractFactory("BudgetLedger");
    const Audit = await ethers.getContractFactory("AuditLedger");
    const Native = await ethers.getContractFactory("MockVCPGroth16Verifier");
    const Validator = await ethers.getContractFactory("ValidatorRegistry");

    const registry = await Registry.deploy();
    const access = await Access.deploy();
    const budget = await Budget.deploy();
    const audit = await Audit.deploy();
    const native = await Native.deploy();
    const validatorRegistry = await Validator.deploy();
    await Promise.all([
      registry.waitForDeployment(),
      access.waitForDeployment(),
      budget.waitForDeployment(),
      audit.waitForDeployment(),
      native.waitForDeployment(),
      validatorRegistry.waitForDeployment(),
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
      await audit.getAddress(),
      await validatorRegistry.getAddress()
    );
    await settlement.waitForDeployment();

    const settlementAddress = await settlement.getAddress();
    await access.setCoordinator(settlementAddress, true);
    await budget.setCoordinator(settlementAddress, true);
    await audit.setCoordinator(settlementAddress, true);
    await adapter.setCoordinator(settlementAddress, true);

    const validatorId = ethers.id("validator:vcp:v2");
    await validatorRegistry.activateValidator(validatorId, validator.address);
    const latest = await ethers.provider.getBlock("latest");
    const expiresAtUnixMs = BigInt(latest.timestamp + 3600) * 1000n;

    const request = {
      request_id: "request-vcp-v2",
      asset_id: "asset-vcp-v2",
      consumer_id: "consumer-vcp-v2",
      policy_version: 1,
      purpose_id: 1,
      function_id: 2,
      data_hash: ethers.id("dataset").slice(2),
      dp_config_hash: ethers.id("dp-config").slice(2),
      freshness_nonce: ethers.id("freshness").slice(2),
      epsilon_requested_fixed: 500_000,
    };
    const execution = {
      ok: true,
      request_id: request.request_id,
      actual_privacy_cost_fixed: 400_000,
      result_fixed: 42,
      enclave_identity: ethers.id("enclave-measurement").slice(2),
      attestation_evidence: {
        validator_id: validatorId,
        native_digest: ethers.id("native-evidence"),
        expires_at_unix_ms: expiresAtUnixMs,
        signature: "00",
      },
    };
    const witness = {
      policyMatrix: [[1n, 1n], [0n, 1n]],
      resultOpening: 987654321n,
    };

    const unsignedProof = buildProofInput(request, execution, poseidon, witness);
    const unsignedStatement = {
      validatorId,
      nativeDigest: ethers.id("native-evidence"),
      contextCommitment: unsignedProof.values.contextCommitment,
      expiresAtUnixMs,
      signature: "0x",
    };
    const payload = await validatorRegistry.statementPayload(unsignedStatement);
    const statement = {
      ...unsignedStatement,
      signature: await validator.signMessage(ethers.getBytes(payload)),
    };
    const proofInput = buildProofInput(request, execution, poseidon, {
      ...witness,
      attestationStatement: statement,
    });

    const requestKey = ethers.hexlify(
      identifierDigest("request_id", request.request_id)
    );
    const assetKey = ethers.hexlify(
      identifierDigest("asset_id", request.asset_id)
    );
    const consumerKey = ethers.hexlify(
      identifierDigest("consumer_id", request.consumer_id)
    );
    const dataHash = `0x${request.data_hash}`;
    const dpConfigHash = `0x${request.dp_config_hash}`;
    const freshnessNonce = `0x${request.freshness_nonce}`;

    await registry.connect(provider).registerAssetVCP(
      assetKey,
      ethers.id("metadata"),
      dataHash,
      proofInput.values.policyCommitment,
      request.policy_version
    );
    await budget.registerBudget(assetKey, 5_000_000n);
    await access.connect(consumer).requestAccessVCP(
      requestKey,
      assetKey,
      consumerKey,
      ethers.id("research-purpose"),
      request.purpose_id,
      proofInput.values.policyCommitment,
      request.policy_version,
      request.function_id,
      dpConfigHash,
      freshnessNonce,
      request.epsilon_requested_fixed,
      expiresAtUnixMs
    );
    await access.approveRequest(requestKey);
    await settlement.reserveBudgetForRequest(requestKey);

    return {
      provider,
      consumer,
      validator,
      stranger,
      registry,
      access,
      budget,
      audit,
      native,
      validatorRegistry,
      adapter,
      settlement,
      requestKey,
      assetKey,
      proofInput,
      statement,
      proof: proof(),
      evidence: {
        resultCommitment: proofInput.values.resultCommitment,
        auditDigest: proofInput.values.auditDigest,
        attestation: statement,
      },
    };
  }

  function settle(context, overrides = {}) {
    const evidence = {
      ...context.evidence,
      ...(overrides.evidence || {}),
    };
    return context.settlement
      .connect(overrides.signer || context.consumer)
      .settle(
        context.requestKey,
        evidence,
        context.proof.a,
        context.proof.b,
        context.proof.c,
        overrides.signals || context.proofInput.publicSignals
      );
  }

  it("settles validator, proof, budget, nullifier, request, and audit atomically", async function () {
    const context = await deployContext();
    await expect(settle(context))
      .to.emit(context.audit, "VCPSettlementAuditRecorded")
      .and.to.emit(context.settlement, "RequestSettled");
    const budget = await context.budget.getBudget(context.assetKey);
    const request = await context.access.getRequest(context.requestKey);
    expect(budget.reserved).to.equal(0n);
    expect(budget.used).to.equal(400_000n);
    expect(request.status).to.equal(5n);
    expect(
      await context.adapter.nullifierUsed(context.proofInput.values.nullifier)
    ).to.equal(true);
  });

  it("rejects a caller other than the bound consumer", async function () {
    const context = await deployContext();
    await expect(settle(context, { signer: context.stranger }))
      .to.be.revertedWithCustomError(context.settlement, "WrongConsumer");
  });

  it("rejects substitution of either request-id limb", async function () {
    const context = await deployContext();
    const signals = [...context.proofInput.publicSignals];
    signals[1] = (BigInt(signals[1]) ^ 1n).toString();
    await expect(settle(context, { signals }))
      .to.be.revertedWithCustomError(context.settlement, "ContextMismatch")
      .withArgs(1);
  });

  it("rejects a validator signature from an unauthorized key", async function () {
    const context = await deployContext();
    const unsigned = { ...context.statement, signature: "0x" };
    const payload = await context.validatorRegistry.statementPayload(unsigned);
    const forged = {
      ...unsigned,
      signature: await context.stranger.signMessage(ethers.getBytes(payload)),
    };
    await expect(
      settle(context, {
        evidence: {
          ...context.evidence,
          attestation: forged,
        },
      })
    ).to.be.revertedWithCustomError(
      context.validatorRegistry,
      "InvalidValidatorSignature"
    );
  });

  it("rejects a revoked validator", async function () {
    const context = await deployContext();
    await context.validatorRegistry.revokeValidator(context.statement.validatorId);
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.validatorRegistry,
      "ValidatorNotActive"
    );
  });

  it("rolls back all downstream state when proof verification fails", async function () {
    const context = await deployContext();
    await context.native.setAccepted(false);
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.adapter,
      "InvalidProof"
    );
    const budget = await context.budget.getBudget(context.assetKey);
    const request = await context.access.getRequest(context.requestKey);
    expect(budget.reserved).to.equal(500_000n);
    expect(budget.used).to.equal(0n);
    expect(request.status).to.equal(4n);
    expect(
      await context.adapter.nullifierUsed(context.proofInput.values.nullifier)
    ).to.equal(false);
  });

  it("rejects replay after the request reaches a terminal state", async function () {
    const context = await deployContext();
    await settle(context);
    await expect(settle(context)).to.be.revertedWithCustomError(
      context.settlement,
      "RequestNotReserved"
    );
  });
});
