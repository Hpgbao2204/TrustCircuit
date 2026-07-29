pragma circom 2.1.6;

// Frozen historical circuit used only to reproduce the recorded Phase-8
// eleven-public-input measurements. It is not the canonical VCP relation.
include "poseidon.circom";
include "comparators.circom";

template ComplianceCheck(nRules, budgetBits) {
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

    signal input allowedPolicyHash;
    signal input maxBudget;
    signal input secretNonce;
    signal input policyField[nRules];

    policyHash === allowedPolicyHash;

    component le = LessEqThan(budgetBits);
    le.in[0] <== epsilonCost;
    le.in[1] <== maxBudget;
    le.out === 1;

    component policyVersionBits = Num2Bits(64);
    policyVersionBits.in <== policyVersion;
    component policyVersionIsZero = IsZero();
    policyVersionIsZero.in <== policyVersion;
    policyVersionIsZero.out === 0;
    (functionId - 1) * (functionId - 2) === 0;

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

component main {public [
    requestId,
    assetId,
    consumerId,
    policyHash,
    policyVersion,
    functionId,
    resultHash,
    epsilonCost,
    nullifier,
    transcriptHash,
    attestationDigest
]} = ComplianceCheck(2, 64);
