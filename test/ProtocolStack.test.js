const { expect } = require("chai");
const { ethers } = require("hardhat");
const S = require("../scripts/lib/v3_stack");

const ALLOW_P1F2 = [[1n, 1n], [0n, 1n]];
// sigma for epsilon_cal = 0.5, delta = 1e-5, Delta = 1 (Gaussian mechanism), fixed-point 1e6
const SIGMA_EPS05 = 9_689_610n;

describe("TrustCircuit stack (VCP v3, RDP ledger, validator quorum)", function () {
  this.timeout(600_000);
  let provider;
  let consumer;
  let other;
  let validators;

  before(async function () {
    [, provider, consumer, other] = await ethers.getSigners();
    validators = await S.makeValidators(ethers, 3);
  });

  async function tcStack(opts = {}) {
    return S.deployStack(ethers, "trustcircuit", {
      realVerifier: opts.realVerifier ?? false,
      threshold: opts.threshold ?? 2,
      validators,
    });
  }

  describe("ledger-enforced RDP accounting", function () {
    it("reserves an amount that bounds every settlement charge and matches the integer reference", async function () {
      const stack = await tcStack();
      const asset = await S.registerAsset(stack, provider, { name: "rdp-asset", matrix: ALLOW_P1F2, epsilonTotal: 50 });
      const sigmas = [96_896_100n, 48_448_050n, 24_224_025n, SIGMA_EPS05, 48_448_050n, 24_224_025n];
      let consumed = asset.orders.map(() => 0n);
      let used = 0n;
      for (let i = 0; i < sigmas.length; i += 1) {
        const request = await S.openRequest(stack, consumer, asset, {
          name: `rdp-${i}`, purposeId: 1, functionId: 2, sigmaFixed: sigmas[i],
        });
        const expectedReserve = S.enc.reservationAmount(asset.orders, asset.offsets, consumed, sigmas[i], 1_000_000n);
        expect(request.reserved).to.equal(expectedReserve);
        const bundle = await S.executeRequest(stack, request, { signers: validators.slice(0, 2) });
        await (await S.settleTrustCircuit(stack, request, bundle)).wait();
        const increments = asset.orders.map((a) => S.enc.rdpIncrement(a, sigmas[i], 1_000_000n));
        const next = consumed.map((v, k) => v + increments[k]);
        const charge = S.enc.conversion(next, asset.offsets) - S.enc.conversion(consumed, asset.offsets);
        expect(charge).to.be.lte(request.reserved);
        consumed = next;
        used += charge;
        const [, , onchainUsed] = await stack.budget.getBudget(asset.assetKey);
        expect(onchainUsed).to.equal(used);
        const state = await stack.budget.getRdpState(asset.assetKey);
        expect(state[2].map(BigInt)).to.deep.equal(consumed);
      }
      // U_t equals the conservative conversion of the consumed vector.
      expect(used).to.equal(S.enc.conversion(consumed, asset.offsets));
    });

    it("refuses a reservation that the remaining budget cannot cover", async function () {
      const stack = await tcStack();
      const asset = await S.registerAsset(stack, provider, { name: "small", matrix: ALLOW_P1F2, epsilonTotal: 0.8 });
      await S.openRequest(stack, consumer, asset, { name: "small-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 });
      await expect(
        S.openRequest(stack, consumer, asset, { name: "small-2", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 })
      ).to.be.revertedWithCustomError(stack.budget, "InsufficientBudget");
    });

    it("lets anyone release a reservation after its deadline", async function () {
      const stack = await tcStack();
      const asset = await S.registerAsset(stack, provider, { name: "expiry", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, {
        name: "expiry-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05, deadlineSeconds: 60,
      });
      await expect(stack.settlement.connect(other).releaseExpiredReservation(request.requestId))
        .to.be.revertedWithCustomError(stack.settlement, "RequestNotExpired");
      await ethers.provider.send("evm_increaseTime", [120]);
      await ethers.provider.send("evm_mine", []);
      await (await stack.settlement.connect(other).releaseExpiredReservation(request.requestId)).wait();
      const [, reserved] = await stack.budget.getBudget(asset.assetKey);
      expect(reserved).to.equal(0n);
    });
  });

  describe("validator quorum", function () {
    it("rejects a statement with fewer than k signatures, duplicates, or a revoked key", async function () {
      const stack = await tcStack({ threshold: 2 });
      const asset = await S.registerAsset(stack, provider, { name: "quorum", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, { name: "q-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 });
      const single = await S.executeRequest(stack, request, { signers: validators.slice(0, 1) });
      await expect(S.settleTrustCircuit(stack, request, single))
        .to.be.revertedWithCustomError(stack.validatorRegistry, "QuorumNotReached");
      const duplicate = await S.executeRequest(stack, request, { signers: [validators[0], validators[0]] });
      await expect(S.settleTrustCircuit(stack, request, duplicate))
        .to.be.revertedWithCustomError(stack.validatorRegistry, "ValidatorOrder");
      await (await stack.validatorRegistry.revokeValidator(validators[1].id)).wait();
      const revoked = await S.executeRequest(stack, request, { signers: validators.slice(0, 2) });
      await expect(S.settleTrustCircuit(stack, request, revoked))
        .to.be.revertedWithCustomError(stack.validatorRegistry, "ValidatorNotActive");
      const good = await S.executeRequest(stack, request, { signers: [validators[0], validators[2]] });
      await (await S.settleTrustCircuit(stack, request, good)).wait();
    });

    it("puts registry governance behind a timelocked multisignature account", async function () {
      const stack = await tcStack();
      const signers = await ethers.getSigners();
      const owners = [signers[5], signers[6], signers[7]];
      const Multisig = await ethers.getContractFactory("TimelockMultisig");
      const multisig = await Multisig.deploy(owners.map((o) => o.address), 2, 3600);
      await multisig.waitForDeployment();
      await (await stack.validatorRegistry.transferOwnership(await multisig.getAddress())).wait();
      await expect(stack.validatorRegistry.activateValidator(ethers.id("rogue"), signers[9].address))
        .to.be.revertedWithCustomError(stack.validatorRegistry, "NotOwner");
      const data = stack.validatorRegistry.interface.encodeFunctionData("activateValidator", [ethers.id("v4"), signers[9].address]);
      await (await multisig.connect(owners[0]).propose(await stack.validatorRegistry.getAddress(), data)).wait();
      await expect(multisig.connect(owners[0]).execute(0)).to.be.revertedWithCustomError(multisig, "NotEnoughApprovals");
      await (await multisig.connect(owners[1]).approve(0)).wait();
      await expect(multisig.connect(owners[0]).execute(0)).to.be.revertedWithCustomError(multisig, "TimelockActive");
      await ethers.provider.send("evm_increaseTime", [3601]);
      await ethers.provider.send("evm_mine", []);
      await (await multisig.connect(owners[2]).execute(0)).wait();
      expect((await stack.validatorRegistry.getValidator(ethers.id("v4"))).active).to.equal(true);
    });
  });

  describe("policy versioning", function () {
    it("rejects settlement after the provider updates the policy", async function () {
      const stack = await tcStack();
      const asset = await S.registerAsset(stack, provider, { name: "versioned", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, { name: "v-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 });
      const bundle = await S.executeRequest(stack, request);
      await S.updatePolicy(stack, provider, asset, [[1n, 0n], [0n, 1n]]);
      await expect(S.settleTrustCircuit(stack, request, bundle))
        .to.be.revertedWithCustomError(stack.settlement, "PolicyMismatch");
    });
  });

  describe("real Groth16 proofs (VCP v3)", function () {
    before(function () {
      if (!S.haveProvingArtifacts()) this.skip();
    });

    it("settles a real proof under a 2-of-3 quorum and rejects a replay", async function () {
      const stack = await tcStack({ realVerifier: true, threshold: 2 });
      const asset = await S.registerAsset(stack, provider, { name: "real", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, { name: "real-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 });
      const bundle = await S.executeRequest(stack, request, { prove: true, signers: validators.slice(0, 2) });
      const receipt = await (await S.settleTrustCircuit(stack, request, bundle)).wait();
      expect(receipt.status).to.equal(1);
      await expect(S.settleTrustCircuit(stack, request, bundle))
        .to.be.revertedWithCustomError(stack.settlement, "RequestNotReserved");
    });

    it("cannot produce a witness for a purpose that the hidden policy forbids", async function () {
      const stack = await tcStack({ realVerifier: true });
      const asset = await S.registerAsset(stack, provider, { name: "forbidden", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, { name: "forbid-1", purposeId: 2, functionId: 1, sigmaFixed: SIGMA_EPS05 });
      let failed = false;
      try {
        await S.executeRequest(stack, request, { prove: true });
      } catch (error) {
        failed = true;
      }
      expect(failed).to.equal(true);
    });

    it("rejects a processor that applied less noise than reserved", async function () {
      const stack = await tcStack({ realVerifier: true });
      const asset = await S.registerAsset(stack, provider, { name: "noise", matrix: ALLOW_P1F2 });
      const request = await S.openRequest(stack, consumer, asset, { name: "noise-1", purposeId: 1, functionId: 2, sigmaFixed: SIGMA_EPS05 });
      let failed = false;
      try {
        await S.executeRequest(stack, request, { prove: true, appliedSigmaFixed: SIGMA_EPS05 / 2n });
      } catch (error) {
        failed = true;
      }
      expect(failed).to.equal(true);
    });
  });
});
