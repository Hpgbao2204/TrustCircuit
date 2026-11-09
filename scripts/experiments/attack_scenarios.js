"use strict";

// Executable attack matrix. Each request-continuity failure is replayed
// against three designs deployed on fresh stacks with identical contracts:
//   stage  : stage-wise composition (StageWiseSettlement)
//   shs    : sign-and-hash settlement (SignAndHashSettlement)
//   tc     : TrustCircuit (TrustCircuitSettlement + real Groth16 VCP v3 proofs)
// An attack is "accepted" if the adversarial settlement transaction succeeds
// and "rejected" if it reverts or the adversary cannot construct its input.
//
//   F1 splice     : the execution evidence of request A settles request B
//   F2 stale      : a result settles after the provider withdrew consent
//   F3 budget     : two concurrent requests spend the same remaining budget
//   F4 forbidden  : a compromised validator quorum approves a purpose that the
//                   hidden policy forbids
//   R  replay     : a copied settlement transaction is submitted again by another account
//   N  noise      : the processor applied less noise than was reserved

const S = require("../lib/v3_stack");

const ALLOW = [[1n, 1n], [0n, 1n]]; // forbids (purpose 2, function 1)
const WITHDRAWN = [[0n, 0n], [0n, 1n]]; // consent for (1, 2) withdrawn
const SIGMA = 9_689_610n; // epsilon_cal = 0.5, delta = 1e-5, Delta = 1

async function outcome(action) {
  try {
    const tx = await action();
    if (tx && typeof tx.wait === "function") await tx.wait();
    return { result: "accepted", detail: "transaction succeeded" };
  } catch (error) {
    const message = String(error.shortMessage || error.message || error);
    const custom = message.match(/reverted with custom error '([^']+)'/);
    const reason = custom ? custom[1] : message.split("\n")[0].slice(0, 160);
    return { result: "rejected", detail: reason };
  }
}

async function runAttackMatrix(ethers, { log = () => {} } = {}) {
  const signers = await ethers.getSigners();
  const provider = signers[1];
  const consumer = signers[2];
  const attacker = signers[3];
  const validators = await S.makeValidators(ethers, 3);
  const compromised = validators.slice(0, 2); // k = 2 keys leak under E_val
  const rows = [];
  const record = (attack, design, res) => {
    rows.push({ attack, design, ...res });
    log(`${attack} ${design}: ${res.result} (${res.detail})`);
  };

  async function fresh(design) {
    return S.deployStack(ethers, design, {
      realVerifier: design === "trustcircuit",
      threshold: 2,
      validators,
    });
  }

  // ---------------- F1: evidence splicing ----------------
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await fresh(design);
    const asset = await S.registerAsset(stack, provider, { name: `f1-${design}`, matrix: ALLOW });
    const spec = { purposeId: 1, functionId: 2, sigmaFixed: SIGMA, stageAmount: 600_000 };
    const reqA = await S.openRequest(stack, consumer, asset, { ...spec, name: `f1-a-${design}` });
    const reqB = await S.openRequest(stack, consumer, asset, { ...spec, name: `f1-b-${design}` });
    if (design === "stage") {
      // Evidence of A's execution (its own execution id) settles B.
      const executionId = ethers.id(`execution:${reqA.requestId}`);
      record("F1", design, await outcome(() => S.settleStage(stack, reqB, executionId, 4242n)));
    } else {
      const bundleA = await S.executeRequest(stack, reqA, { prove: design === "trustcircuit" });
      const settle =
        design === "shs"
          ? () => S.settleShs(stack, reqB, bundleA)
          : () => S.settleTrustCircuit(stack, reqA, bundleA, { requestKey: reqB.requestId });
      // For SHS, settleShs uses reqB's key with A's statement and public signals.
      if (design === "shs") {
        record("F1", design, await outcome(() =>
          S.shsSignatures(stack, bundleA.built.publicSignals, 1, compromised).then(({ ids, sigs }) =>
            stack.settlement.connect(consumer).settle(reqB.requestId, S.evidenceOf(bundleA), bundleA.built.publicSignals, 1, ids, sigs)
          )
        ));
      } else {
        record("F1", design, await outcome(settle));
      }
    }
  }

  // ---------------- F2: stale-policy settlement ----------------
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await fresh(design);
    const asset = await S.registerAsset(stack, provider, { name: `f2-${design}`, matrix: ALLOW });
    const req = await S.openRequest(stack, consumer, asset, {
      name: `f2-${design}`, purposeId: 1, functionId: 2, sigmaFixed: SIGMA, stageAmount: 600_000,
    });
    if (design === "stage") {
      await S.updatePolicy(stack, provider, asset, WITHDRAWN);
      record("F2", design, await outcome(() => S.settleStage(stack, req, ethers.id("execution:f2"), 4242n)));
    } else {
      // Result computed before the withdrawal, settled after it.
      const bundle = await S.executeRequest(stack, req, { prove: design === "trustcircuit" });
      await S.updatePolicy(stack, provider, asset, WITHDRAWN);
      record("F2", design, await outcome(() =>
        design === "shs" ? S.settleShs(stack, req, bundle) : S.settleTrustCircuit(stack, req, bundle)
      ));
    }
  }

  // ---------------- F3: budget double counting ----------------
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await fresh(design);
    // Budget sized for one reservation only (b_req ~ 0.52 epsilon units).
    const asset = await S.registerAsset(stack, provider, {
      name: `f3-${design}`, matrix: ALLOW, epsilonTotal: 0.8, stageBudget: 800_000n,
    });
    const spec = { purposeId: 1, functionId: 2, sigmaFixed: SIGMA, stageAmount: 600_000 };
    let res;
    if (design === "stage") {
      const r1 = await S.openRequest(stack, consumer, asset, { ...spec, name: "f3-1-stage" });
      const r2 = await S.openRequest(stack, consumer, asset, { ...spec, name: "f3-2-stage" });
      await (await S.settleStage(stack, r1, ethers.id("execution:f3:1"), 1n)).wait();
      res = await outcome(() => S.settleStage(stack, r2, ethers.id("execution:f3:2"), 2n));
      const budget = await stack.settlement.budgets(asset.assetKey);
      res.detail += `; used ${budget.used} of total ${budget.total}`;
      if (res.result === "accepted" && budget.used <= budget.total) res.result = "rejected";
    } else {
      const r1 = await S.openRequest(stack, consumer, asset, { ...spec, name: `f3-1-${design}` });
      res = await outcome(() => S.openRequest(stack, consumer, asset, { ...spec, name: `f3-2-${design}` }));
      const b1 = await S.executeRequest(stack, r1, { prove: design === "trustcircuit" });
      await (await (design === "shs" ? S.settleShs(stack, r1, b1) : S.settleTrustCircuit(stack, r1, b1))).wait();
      const [total, reserved, used] = await stack.budget.getBudget(asset.assetKey);
      res.detail += `; used ${used} reserved ${reserved} of total ${total}`;
    }
    record("F3", design, res);
  }

  // ---------------- F4: forbidden purpose under validator compromise ----------------
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await fresh(design);
    const asset = await S.registerAsset(stack, provider, { name: `f4-${design}`, matrix: ALLOW });
    const req = await S.openRequest(stack, consumer, asset, {
      name: `f4-${design}`, purposeId: 2, functionId: 1, sigmaFixed: SIGMA, stageAmount: 600_000,
    });
    if (design === "stage") {
      record("F4", design, await outcome(() => S.settleStage(stack, req, ethers.id("execution:f4"), 4242n, compromised)));
    } else if (design === "shs") {
      // Compromised validators sign the context and a_Pi = 1 for the forbidden pair.
      const bundle = await S.executeRequest(stack, req, { signers: compromised });
      record("F4", design, await outcome(() => S.settleShs(stack, req, bundle, 1, compromised)));
    } else {
      // The adversary holds the compromised validator keys and the result, but
      // the circuit has no witness for a forbidden pair. Two attempts:
      // (a) honest proving of the forbidden statement; (b) a valid proof of an
      // admissible statement submitted with the forbidden request's signals.
      const proving = await outcome(() => S.executeRequest(stack, req, { prove: true, signers: compromised }));
      const allowed = await S.openRequest(stack, consumer, asset, {
        name: "f4-allowed", purposeId: 1, functionId: 2, sigmaFixed: SIGMA,
      });
      const allowedBundle = await S.executeRequest(stack, allowed, { prove: true, signers: compromised });
      const forged = await S.executeRequest(stack, req, { signers: compromised }); // signals only, no proof
      const substitution = await outcome(() =>
        S.settleTrustCircuit(stack, req, forged, { proof: allowedBundle.proof })
      );
      const res =
        proving.result === "rejected" && substitution.result === "rejected"
          ? { result: "rejected", detail: `proving: ${proving.detail}; proof substitution: ${substitution.detail}` }
          : { result: "accepted", detail: `proving: ${proving.result}; substitution: ${substitution.result}` };
      record("F4", design, res);
    }
  }

  // ---------------- R: replay / front-run copy ----------------
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await fresh(design);
    const asset = await S.registerAsset(stack, provider, { name: `r-${design}`, matrix: ALLOW });
    const req = await S.openRequest(stack, consumer, asset, {
      name: `r-${design}`, purposeId: 1, functionId: 2, sigmaFixed: SIGMA, stageAmount: 600_000,
    });
    if (design === "stage") {
      await (await S.settleStage(stack, req, ethers.id("execution:r"), 1n)).wait();
      record("R", design, await outcome(() => S.settleStage(stack, { ...req, consumer: attacker }, ethers.id("execution:r"), 1n)));
    } else {
      const bundle = await S.executeRequest(stack, req, { prove: design === "trustcircuit" });
      // Front-run copy by another account before the original lands.
      const copy = await outcome(() =>
        design === "shs"
          ? S.settleShs(stack, { ...req, consumer: attacker }, bundle)
          : S.settleTrustCircuit(stack, { ...req, consumer: attacker }, bundle)
      );
      await (await (design === "shs" ? S.settleShs(stack, req, bundle) : S.settleTrustCircuit(stack, req, bundle))).wait();
      const replay = await outcome(() =>
        design === "shs" ? S.settleShs(stack, req, bundle) : S.settleTrustCircuit(stack, req, bundle)
      );
      record("R", design, {
        result: copy.result === "rejected" && replay.result === "rejected" ? "rejected" : "accepted",
        detail: `copy: ${copy.detail}; replay: ${replay.detail}`,
      });
    }
  }

  // ---------------- N: less noise than reserved ----------------
  for (const design of ["shs", "trustcircuit"]) {
    const stack = await fresh(design);
    const asset = await S.registerAsset(stack, provider, { name: `n-${design}`, matrix: ALLOW });
    const req = await S.openRequest(stack, consumer, asset, {
      name: `n-${design}`, purposeId: 1, functionId: 2, sigmaFixed: SIGMA,
    });
    record("N", design, await outcome(async () => {
      const bundle = await S.executeRequest(stack, req, {
        prove: design === "trustcircuit",
        appliedSigmaFixed: SIGMA / 2n,
        signers: compromised,
      });
      return design === "shs" ? S.settleShs(stack, req, bundle) : S.settleTrustCircuit(stack, req, bundle);
    }));
  }
  rows.push({ attack: "N", design: "stage", result: "n/a", detail: "stage-wise settlement carries no expenditure statement" });

  return rows;
}

// Expected outcomes (Theorem "Separation" and Table "Settlement ablation").
const EXPECTED = {
  F1: { stage: "accepted", shs: "rejected", trustcircuit: "rejected" },
  F2: { stage: "accepted", shs: "rejected", trustcircuit: "rejected" },
  F3: { stage: "accepted", shs: "rejected", trustcircuit: "rejected" },
  F4: { stage: "accepted", shs: "accepted", trustcircuit: "rejected" },
  R: { stage: "rejected", shs: "rejected", trustcircuit: "rejected" },
  N: { stage: "n/a", shs: "rejected", trustcircuit: "rejected" },
};

module.exports = { EXPECTED, runAttackMatrix };
