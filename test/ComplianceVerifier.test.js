const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
  artifactsExist,
  loadPhase7Fixture,
} = require("./helpers/phase7_fixture");

const describePhase7 = artifactsExist() ? describe : describe.skip;

describePhase7("ComplianceVerifier Phase 7 adapter", function () {
  let fixture;

  before(async function () {
    this.timeout(120_000);
    fixture = await loadPhase7Fixture();
  });

  function bytes32(value) {
    return ethers.zeroPadValue(ethers.toBeHex(value), 32);
  }

  function expected(overrides = {}) {
    const value = fixture.values;
    return {
      requestId: value.requestId,
      assetId: value.assetId,
      consumerId: value.consumerId,
      policyHash: value.policyHash,
      policyVersion: value.policyVersion,
      functionId: value.functionId,
      resultHash: value.resultHash,
      maxEpsilon: value.epsilonCost,
      transcriptHash: value.transcriptHash,
      attestationDigest: value.attestationDigest,
      attestationExpiresAtUnixMs: 4_102_444_800_000n,
      ...overrides,
    };
  }

  async function deploy(overrides = {}) {
    const Native = await ethers.getContractFactory("Phase7Groth16Verifier");
    const native = await Native.deploy();
    await native.waitForDeployment();
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    const adapter = await Adapter.deploy(await native.getAddress());
    await adapter.waitForDeployment();
    const requestKey = bytes32(fixture.values.requestId);
    await adapter.registerExpectation(requestKey, expected(overrides));
    return { adapter, requestKey };
  }

  it("rejects a zero verifier address", async function () {
    const Adapter = await ethers.getContractFactory("ComplianceVerifier");
    await expect(Adapter.deploy(ethers.ZeroAddress)).to.be.revertedWithCustomError(
      Adapter,
      "ZeroVerifier"
    );
  });

  it("accepts the real 11-signal proof and records all bindings", async function () {
    const { adapter, requestKey } = await deploy();
    await expect(
      adapter.submitCompliance(
        requestKey,
        fixture.a,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    )
      .to.emit(adapter, "ComplianceVerified")
      .withArgs(
        requestKey,
        fixture.values.nullifier,
        fixture.values.epsilonCost,
        fixture.values.resultHash,
        fixture.values.transcriptHash,
        fixture.values.attestationDigest
      );
    const state = await adapter.getExpectation(requestKey);
    expect(state.verified).to.equal(true);
    expect(state.epsilonUsed).to.equal(fixture.values.epsilonCost);
    expect(await adapter.nullifierUsed(fixture.values.nullifier)).to.equal(true);
  });

  for (const [name, field, index] of [
    ["wrong asset", "assetId", 1],
    ["wrong consumer", "consumerId", 2],
    ["wrong policy", "policyHash", 3],
    ["wrong result", "resultHash", 6],
    ["altered transcript", "transcriptHash", 9],
    ["altered attestation", "attestationDigest", 10],
  ]) {
    it(`rejects ${name}`, async function () {
      const { adapter, requestKey } = await deploy({
        [field]: fixture.values[field] + 1n,
      });
      await expect(
        adapter.submitCompliance(
          requestKey,
          fixture.a,
          fixture.b,
          fixture.c,
          fixture.signals
        )
      )
        .to.be.revertedWithCustomError(adapter, "PublicInputMismatch")
        .withArgs(index);
    });
  }

  it("rejects over-budget settlement", async function () {
    const { adapter, requestKey } = await deploy({
      maxEpsilon: fixture.values.epsilonCost - 1n,
    });
    await expect(
      adapter.submitCompliance(
        requestKey,
        fixture.a,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    ).to.be.revertedWithCustomError(adapter, "BudgetExceeded");
  });

  it("rejects stale attestation", async function () {
    const { adapter, requestKey } = await deploy({ attestationExpiresAtUnixMs: 1n });
    await expect(
      adapter.submitCompliance(
        requestKey,
        fixture.a,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    ).to.be.revertedWithCustomError(adapter, "StaleAttestation");
  });

  it("rejects a replay", async function () {
    const { adapter, requestKey } = await deploy();
    await adapter.submitCompliance(
      requestKey,
      fixture.a,
      fixture.b,
      fixture.c,
      fixture.signals
    );
    await expect(
      adapter.submitCompliance(
        requestKey,
        fixture.a,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    ).to.be.revertedWithCustomError(adapter, "AlreadyVerified");
  });

  it("rejects a tampered Groth16 proof", async function () {
    const { adapter, requestKey } = await deploy();
    const tamperedA = [...fixture.a];
    tamperedA[0] = (BigInt(tamperedA[0]) ^ 1n).toString();
    await expect(
      adapter.submitCompliance(
        requestKey,
        tamperedA,
        fixture.b,
        fixture.c,
        fixture.signals
      )
    ).to.be.revertedWithCustomError(adapter, "InvalidProof");
  });
});
