const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("ValidatorRegistry", function () {
  async function deploy() {
    const [owner, validator, attacker] = await ethers.getSigners();
    const Registry = await ethers.getContractFactory("ValidatorRegistry");
    const registry = await Registry.deploy();
    await registry.waitForDeployment();
    return {
      owner,
      validator,
      attacker,
      registry,
      validatorId: ethers.id("validator:vcp:v1"),
    };
  }

  async function signedStatement(context, signer = context.validator, overrides = {}) {
    const block = await ethers.provider.getBlock("latest");
    const unsigned = {
      validatorId: context.validatorId,
      nativeDigest: ethers.id("native-attestation-evidence"),
      contextCommitment: 123456n,
      expiresAtUnixMs: BigInt(block.timestamp + 3600) * 1000n,
      signature: "0x",
      ...overrides,
    };
    const payload = await context.registry.statementPayload(unsigned);
    return {
      ...unsigned,
      signature: await signer.signMessage(ethers.getBytes(payload)),
    };
  }

  it("accepts an active validator signature", async function () {
    const context = await deploy();
    await context.registry.activateValidator(
      context.validatorId,
      context.validator.address
    );
    const statement = await signedStatement(context);
    expect(await context.registry.requireValid.staticCall(statement)).to.equal(
      context.validator.address
    );
  });

  it("rejects signatures from a different key", async function () {
    const context = await deploy();
    await context.registry.activateValidator(
      context.validatorId,
      context.validator.address
    );
    await expect(
      context.registry.requireValid(await signedStatement(context, context.attacker))
    ).to.be.revertedWithCustomError(context.registry, "InvalidValidatorSignature");
  });

  it("rejects revoked validator keys", async function () {
    const context = await deploy();
    await context.registry.activateValidator(
      context.validatorId,
      context.validator.address
    );
    const statement = await signedStatement(context);
    await context.registry.revokeValidator(context.validatorId);
    await expect(context.registry.requireValid(statement))
      .to.be.revertedWithCustomError(context.registry, "ValidatorNotActive");
  });

  it("rejects expired statements", async function () {
    const context = await deploy();
    await context.registry.activateValidator(
      context.validatorId,
      context.validator.address
    );
    const statement = await signedStatement(context, context.validator, {
      expiresAtUnixMs: 1n,
    });
    await expect(context.registry.requireValid(statement))
      .to.be.revertedWithCustomError(context.registry, "StaleAttestation");
  });
});
