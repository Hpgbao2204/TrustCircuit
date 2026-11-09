pragma circom 2.1.6;

include "poseidon.circom";
include "comparators.circom";

// Canonical variable-length Poseidon encoding:
//   H_domain(v[0..n-1]) = fold(Poseidon(2), Poseidon(domain, n), v)
// Including the domain and arity prevents cross-relation and prefix ambiguity.
template DomainHash(n, domain) {
    signal input values[n];
    signal output digest;

    component init = Poseidon(2);
    init.inputs[0] <== domain;
    init.inputs[1] <== n;

    component absorb[n];
    signal state[n + 1];
    state[0] <== init.out;
    for (var i = 0; i < n; i++) {
        absorb[i] = Poseidon(2);
        absorb[i].inputs[0] <== state[i];
        absorb[i].inputs[1] <== values[i];
        state[i + 1] <== absorb[i].out;
    }
    digest <== state[n];
}

template RangeCheck(bits) {
    signal input value;
    component decomposition = Num2Bits(bits);
    decomposition.in <== value;
}

// VCP v3 relation. Identical public interface to v2 (24
// signals); the policy and execution-context commitments are now salted with
// private field elements so that low-entropy values (a 2x2 consent matrix, an
// enclave measurement from a short allowlist) cannot be recovered by
// enumeration. The result commitment was already salted by resultOpening.
// 256-bit EVM values are represented as (lo, hi) uint128 limbs; no bytes32
// value is reduced modulo Fr.

template ComplianceCheckV3(purposes, functions, budgetBits) {
    // Public request header zeta.
    signal input requestIdLo;
    signal input requestIdHi;
    signal input assetIdLo;
    signal input assetIdHi;
    signal input consumerIdLo;
    signal input consumerIdHi;
    signal input policyCommitment;
    signal input policyVersion;

    // Public admission descriptor beta.
    signal input purposeId;
    signal input functionId;
    signal input dataHashLo;
    signal input dataHashHi;
    signal input dpConfigHashLo;
    signal input dpConfigHashHi;
    signal input freshnessNonceLo;
    signal input freshnessNonceHi;

    // Public budget, proof, attestation, result, and audit bindings.
    signal input reservedCost;
    signal input actualCost;
    signal input nullifier;
    signal input contextCommitment;
    signal input attestationHashLo;
    signal input attestationHashHi;
    signal input resultCommitment;
    signal input auditDigest;

    // Private policy and selector witnesses.
    signal input policyMatrix[purposes][functions];
    signal input purposeSelector[purposes];
    signal input functionSelector[functions];

    // Private result/context openings. Native attestation validity is checked
    // by the validator registry and is intentionally outside this circuit.
    signal input releasedResult;
    signal input resultOpening;
    signal input enclaveMeasurementLo;
    signal input enclaveMeasurementHi;

    // Private commitment randomness (v3). policySalt is held by the provider,
    // contextSalt is sampled by the processor for each execution.
    signal input policySalt;
    signal input contextSalt;

    // Limb range checks make the 256-bit encoding injective.
    component limbs[14];
    limbs[0] = RangeCheck(128); limbs[0].value <== requestIdLo;
    limbs[1] = RangeCheck(128); limbs[1].value <== requestIdHi;
    limbs[2] = RangeCheck(128); limbs[2].value <== assetIdLo;
    limbs[3] = RangeCheck(128); limbs[3].value <== assetIdHi;
    limbs[4] = RangeCheck(128); limbs[4].value <== consumerIdLo;
    limbs[5] = RangeCheck(128); limbs[5].value <== consumerIdHi;
    limbs[6] = RangeCheck(128); limbs[6].value <== dataHashLo;
    limbs[7] = RangeCheck(128); limbs[7].value <== dataHashHi;
    limbs[8] = RangeCheck(128); limbs[8].value <== dpConfigHashLo;
    limbs[9] = RangeCheck(128); limbs[9].value <== dpConfigHashHi;
    limbs[10] = RangeCheck(128); limbs[10].value <== freshnessNonceLo;
    limbs[11] = RangeCheck(128); limbs[11].value <== freshnessNonceHi;
    limbs[12] = RangeCheck(128); limbs[12].value <== attestationHashLo;
    limbs[13] = RangeCheck(128); limbs[13].value <== attestationHashHi;

    component measurementLo = RangeCheck(128);
    component measurementHi = RangeCheck(128);
    measurementLo.value <== enclaveMeasurementLo;
    measurementHi.value <== enclaveMeasurementHi;

    component versionRange = RangeCheck(64);
    component purposeRange = RangeCheck(32);
    component functionRange = RangeCheck(32);
    component reservedRange = RangeCheck(budgetBits);
    component actualRange = RangeCheck(budgetBits);
    versionRange.value <== policyVersion;
    purposeRange.value <== purposeId;
    functionRange.value <== functionId;
    reservedRange.value <== reservedCost;
    actualRange.value <== actualCost;

    component versionZero = IsZero();
    component actualZero = IsZero();
    versionZero.in <== policyVersion;
    actualZero.in <== actualCost;
    versionZero.out === 0;
    actualZero.out === 0;

    // R_pol: commit the complete fixed-dimension policy matrix.
    // ph = Com(tag_pol, (P, F, vec(M)); r_pol): the salt is the last absorbed value.
    component policyHash = DomainHash(3 + purposes * functions, 1);
    policyHash.values[0] <== purposes;
    policyHash.values[1] <== functions;
    for (var p = 0; p < purposes; p++) {
        for (var f = 0; f < functions; f++) {
            policyMatrix[p][f] * (policyMatrix[p][f] - 1) === 0;
            policyHash.values[2 + p * functions + f] <== policyMatrix[p][f];
        }
    }
    policyHash.values[2 + purposes * functions] <== policySalt;
    policyHash.digest === policyCommitment;

    // One-hot selectors are bound to the public purpose/function identifiers.
    signal purposeSum[purposes + 1];
    signal functionSum[functions + 1];
    signal purposeBinding[purposes + 1];
    signal functionBinding[functions + 1];
    purposeSum[0] <== 0;
    functionSum[0] <== 0;
    purposeBinding[0] <== 0;
    functionBinding[0] <== 0;
    for (var p = 0; p < purposes; p++) {
        purposeSelector[p] * (purposeSelector[p] - 1) === 0;
        purposeSum[p + 1] <== purposeSum[p] + purposeSelector[p];
        purposeBinding[p + 1] <==
            purposeBinding[p] + (p + 1) * purposeSelector[p];
    }
    for (var f = 0; f < functions; f++) {
        functionSelector[f] * (functionSelector[f] - 1) === 0;
        functionSum[f + 1] <== functionSum[f] + functionSelector[f];
        functionBinding[f + 1] <==
            functionBinding[f] + (f + 1) * functionSelector[f];
    }
    purposeSum[purposes] === 1;
    functionSum[functions] === 1;
    purposeBinding[purposes] === purposeId;
    functionBinding[functions] === functionId;

    signal selectedByPurpose[functions];
    signal policyRowAcc[functions][purposes + 1];
    signal admissibleTerms[functions];
    signal admissibleAcc[functions + 1];
    admissibleAcc[0] <== 0;
    for (var f = 0; f < functions; f++) {
        policyRowAcc[f][0] <== 0;
        for (var p = 0; p < purposes; p++) {
            policyRowAcc[f][p + 1] <==
                policyRowAcc[f][p] + purposeSelector[p] * policyMatrix[p][f];
        }
        selectedByPurpose[f] <== policyRowAcc[f][purposes];
        admissibleTerms[f] <== selectedByPurpose[f] * functionSelector[f];
        admissibleAcc[f + 1] <== admissibleAcc[f] + admissibleTerms[f];
    }
    admissibleAcc[functions] === 1;

    component functionHash = DomainHash(1, 2);
    functionHash.values[0] <== functionId;

    // R_bud: conservative positive actual cost within the reservation.
    component budgetBound = LessEqThan(budgetBits);
    budgetBound.in[0] <== actualCost;
    budgetBound.in[1] <== reservedCost;
    budgetBound.out === 1;

    // R_ctx result opening.
    component resultHash = DomainHash(2, 4);
    resultHash.values[0] <== releasedResult;
    resultHash.values[1] <== resultOpening;
    resultHash.digest === resultCommitment;

    // R_nul binds the immutable request header and admission descriptor.
    component nullifierHash = DomainHash(15, 3);
    nullifierHash.values[0] <== assetIdLo;
    nullifierHash.values[1] <== assetIdHi;
    nullifierHash.values[2] <== consumerIdLo;
    nullifierHash.values[3] <== consumerIdHi;
    nullifierHash.values[4] <== requestIdLo;
    nullifierHash.values[5] <== requestIdHi;
    nullifierHash.values[6] <== policyVersion;
    nullifierHash.values[7] <== purposeId;
    nullifierHash.values[8] <== functionId;
    nullifierHash.values[9] <== dataHashLo;
    nullifierHash.values[10] <== dataHashHi;
    nullifierHash.values[11] <== dpConfigHashLo;
    nullifierHash.values[12] <== dpConfigHashHi;
    nullifierHash.values[13] <== freshnessNonceLo;
    nullifierHash.values[14] <== freshnessNonceHi;
    nullifierHash.digest === nullifier;

    // R_ctx binds the same request, execution, budget, result, and measurement.
    // c_zk = Poseidon(tag_ctx, Enc_F(chi_i)), where chi_i now carries r_ctx.
    component contextHash = DomainHash(22, 5);
    contextHash.values[0] <== assetIdLo;
    contextHash.values[1] <== assetIdHi;
    contextHash.values[2] <== consumerIdLo;
    contextHash.values[3] <== consumerIdHi;
    contextHash.values[4] <== requestIdLo;
    contextHash.values[5] <== requestIdHi;
    contextHash.values[6] <== policyCommitment;
    contextHash.values[7] <== policyVersion;
    contextHash.values[8] <== dataHashLo;
    contextHash.values[9] <== dataHashHi;
    contextHash.values[10] <== functionHash.digest;
    contextHash.values[11] <== dpConfigHashLo;
    contextHash.values[12] <== dpConfigHashHi;
    contextHash.values[13] <== resultCommitment;
    contextHash.values[14] <== reservedCost;
    contextHash.values[15] <== actualCost;
    contextHash.values[16] <== enclaveMeasurementLo;
    contextHash.values[17] <== enclaveMeasurementHi;
    contextHash.values[18] <== freshnessNonceLo;
    contextHash.values[19] <== freshnessNonceHi;
    contextHash.values[20] <== purposeId;
    contextHash.values[21] <== contextSalt;
    contextHash.digest === contextCommitment;

    // R_aud is a request-indexed receipt digest over the complete shared interface.
    component auditHash = DomainHash(22, 6);
    auditHash.values[0] <== assetIdLo;
    auditHash.values[1] <== assetIdHi;
    auditHash.values[2] <== consumerIdLo;
    auditHash.values[3] <== consumerIdHi;
    auditHash.values[4] <== requestIdLo;
    auditHash.values[5] <== requestIdHi;
    auditHash.values[6] <== policyCommitment;
    auditHash.values[7] <== policyVersion;
    auditHash.values[8] <== purposeId;
    auditHash.values[9] <== functionId;
    auditHash.values[10] <== dataHashLo;
    auditHash.values[11] <== dataHashHi;
    auditHash.values[12] <== dpConfigHashLo;
    auditHash.values[13] <== dpConfigHashHi;
    auditHash.values[14] <== freshnessNonceLo;
    auditHash.values[15] <== freshnessNonceHi;
    auditHash.values[16] <== reservedCost;
    auditHash.values[17] <== actualCost;
    auditHash.values[18] <== nullifier;
    auditHash.values[19] <== attestationHashLo;
    auditHash.values[20] <== attestationHashHi;
    auditHash.values[21] <== resultCommitment;
    auditHash.digest === auditDigest;
}

component main {public [
    requestIdLo,
    requestIdHi,
    assetIdLo,
    assetIdHi,
    consumerIdLo,
    consumerIdHi,
    policyCommitment,
    policyVersion,
    purposeId,
    functionId,
    dataHashLo,
    dataHashHi,
    dpConfigHashLo,
    dpConfigHashHi,
    freshnessNonceLo,
    freshnessNonceHi,
    reservedCost,
    actualCost,
    nullifier,
    contextCommitment,
    attestationHashLo,
    attestationHashHi,
    resultCommitment,
    auditDigest
]} = ComplianceCheckV3(2, 2, 64);
