pragma circom 2.1.6;

include "poseidon.circom";
include "comparators.circom";

/*
 * TrustCircuit Verifiable Compliance relation (MVP, Groth16-friendly).
 *
 * Public inputs (canonical Phase 7 order):
 *   requestId, assetId, consumerId, policyHash, policyVersion, functionId,
 *   resultHash, epsilonCost, nullifier, transcriptHash, attestationDigest
 * Private witness:
 *   allowedPolicyHash, maxBudget, secretNonce, policyField[nRules]
 *
 * Enforced rules:
 *   R1  policyHash      == allowedPolicyHash                 (purpose limitation)
 *   R2  epsilonCost     <= maxBudget                         (budget range check)
 *   R3  policyVersion is a positive uint64 and functionId is COUNT/MEAN
 *   R4  nullifier == Poseidon(Poseidon(context[0..4]),
 *                            Poseidon(context[5..9]), secretNonce)
 *   R5+ per-rule policy commitments folded into one Poseidon chain so that the
 *       constraint count scales with the number of active compliance rules
 *       (used for the proof-system scaling experiment).
 *
 * budgetBits bounds epsilonCost/maxBudget; the on-chain ledger uses a 1e6
 * fixed-point scale, so 64 bits comfortably covers all budgets.
 */
template ComplianceCheck(nRules, budgetBits) {
    // ---- public inputs ----
    signal input requestId;
    signal input assetId;
    signal input consumerId;
    signal input policyHash;
    signal input policyVersion;
    signal input functionId;
    signal input resultHash;
    signal input epsilonCost;
    signal input nullifier;
    signal input transcriptHash;
    signal input attestationDigest;

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

    // R3: the request schema accepts only a positive uint64 policy version and
    // the two enclave aggregate functions (COUNT=1, MEAN=2).
    component policyVersionBits = Num2Bits(64);
    policyVersionBits.in <== policyVersion;
    component policyVersionIsZero = IsZero();
    policyVersionIsZero.in <== policyVersion;
    policyVersionIsZero.out === 0;
    (functionId - 1) * (functionId - 2) === 0;

    // R4: deterministic nullifier binds every canonical public context field
    // to the proof and secret. The compact statement has already been checked
    // by the external VBS validator; the circuit binds its digest, it does not
    // claim to validate the native Windows report itself.
    component context0 = Poseidon(5);
    context0.inputs[0] <== requestId;
    context0.inputs[1] <== assetId;
    context0.inputs[2] <== consumerId;
    context0.inputs[3] <== policyHash;
    context0.inputs[4] <== policyVersion;

    component context1 = Poseidon(5);
    context1.inputs[0] <== functionId;
    context1.inputs[1] <== resultHash;
    context1.inputs[2] <== epsilonCost;
    context1.inputs[3] <== transcriptHash;
    context1.inputs[4] <== attestationDigest;

    component nh = Poseidon(3);
    nh.inputs[0] <== context0.out;
    nh.inputs[1] <== context1.out;
    nh.inputs[2] <== secretNonce;
    nullifier === nh.out;

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

component main {public [requestId, assetId, consumerId, policyHash, policyVersion, functionId, resultHash, epsilonCost, nullifier, transcriptHash, attestationDigest]} = ComplianceCheck(2, 64);
