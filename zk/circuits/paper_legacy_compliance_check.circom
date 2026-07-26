pragma circom 2.1.6;

include "poseidon.circom";
include "comparators.circom";

template PaperLegacyComplianceCheck(nRules, budgetBits) {
    signal input assetId;
    signal input consumerId;
    signal input requestId;
    signal input policyHash;
    signal input epsilonCost;
    signal input nullifier;
    signal input attestationHash;

    signal input allowedPolicyHash;
    signal input maxBudget;
    signal input secretNonce;
    signal input policyField[nRules];

    policyHash === allowedPolicyHash;

    component le = LessEqThan(budgetBits);
    le.in[0] <== epsilonCost;
    le.in[1] <== maxBudget;
    le.out === 1;

    component nh = Poseidon(3);
    nh.inputs[0] <== consumerId;
    nh.inputs[1] <== requestId;
    nh.inputs[2] <== secretNonce;
    nullifier === nh.out;

    component ah = Poseidon(4);
    ah.inputs[0] <== assetId;
    ah.inputs[1] <== requestId;
    ah.inputs[2] <== policyHash;
    ah.inputs[3] <== epsilonCost;
    attestationHash === ah.out;

    component rule[nRules];
    signal acc[nRules + 1];
    acc[0] <== allowedPolicyHash;
    for (var i = 0; i < nRules; i++) {
        rule[i] = Poseidon(2);
        rule[i].inputs[0] <== acc[i];
        rule[i].inputs[1] <== policyField[i];
        acc[i + 1] <== rule[i].out;
    }
    signal ruleDigest;
    ruleDigest <== acc[nRules];
}

component main {public [assetId, consumerId, requestId, policyHash, epsilonCost, nullifier, attestationHash]} = PaperLegacyComplianceCheck(2, 64);
