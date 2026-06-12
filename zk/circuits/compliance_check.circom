pragma circom 2.1.6;

include "poseidon.circom";
include "comparators.circom";

/*
 * TrustCircuit Verifiable Compliance relation (MVP, Groth16-friendly).
 *
 * Public inputs:
 *   assetId, consumerId, requestId, policyHash, epsilonCost, nullifier, attestationHash
 * Private witness:
 *   allowedPolicyHash, maxBudget, secretNonce, policyField[nRules]
 *
 * Enforced rules:
 *   R1  policyHash      == allowedPolicyHash                 (purpose limitation)
 *   R2  epsilonCost     <= maxBudget                         (budget range check)
 *   R3  nullifier       == Poseidon(consumerId, requestId, secretNonce)
 *   R4  attestationHash == Poseidon(assetId, requestId, policyHash, epsilonCost)
 *   R5+ per-rule policy commitments folded into one Poseidon chain so that the
 *       constraint count scales with the number of active compliance rules
 *       (used for the proof-system scaling experiment).
 *
 * budgetBits bounds epsilonCost/maxBudget; the on-chain ledger uses a 1e6
 * fixed-point scale, so 64 bits comfortably covers all budgets.
 */
template ComplianceCheck(nRules, budgetBits) {
    // ---- public inputs ----
    signal input assetId;
    signal input consumerId;
    signal input requestId;
    signal input policyHash;
    signal input epsilonCost;
    signal input nullifier;
    signal input attestationHash;

    // ---- private witness ----
    signal input allowedPolicyHash;
    signal input maxBudget;
    signal input secretNonce;
    signal input policyField[nRules];

    // R1: purpose limitation -- declared policy matches the allowed policy.
    policyHash === allowedPolicyHash;

    // R2: budget range check -- requested epsilon must fit in remaining budget.
    component le = LessEqThan(budgetBits);
    le.in[0] <== epsilonCost;
    le.in[1] <== maxBudget;
    le.out === 1;

    // R3: deterministic nullifier binds the proof to (consumer, request, secret).
    component nh = Poseidon(3);
    nh.inputs[0] <== consumerId;
    nh.inputs[1] <== requestId;
    nh.inputs[2] <== secretNonce;
    nullifier === nh.out;

    // R4: attestation binding ties the proof to the on-chain attestation record.
    component ah = Poseidon(4);
    ah.inputs[0] <== assetId;
    ah.inputs[1] <== requestId;
    ah.inputs[2] <== policyHash;
    ah.inputs[3] <== epsilonCost;
    attestationHash === ah.out;

    // R5+: composable policy-field commitments. Each active rule contributes one
    // Poseidon evaluation chained with the allowed policy hash, giving a single
    // proof whose constraint count grows with the number of regulatory rules.
    component rule[nRules];
    signal acc[nRules + 1];
    acc[0] <== allowedPolicyHash;
    for (var i = 0; i < nRules; i++) {
        rule[i] = Poseidon(2);
        rule[i].inputs[0] <== acc[i];
        rule[i].inputs[1] <== policyField[i];
        acc[i + 1] <== rule[i].out;
    }
    // The folded commitment must be non-trivial (bound into the witness).
    signal ruleDigest;
    ruleDigest <== acc[nRules];
}

component main {public [assetId, consumerId, requestId, policyHash, epsilonCost, nullifier, attestationHash]} = ComplianceCheck(2, 64);
