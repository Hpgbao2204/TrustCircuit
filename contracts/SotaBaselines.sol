// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * SotaBaselines reproduces the *on-chain verification primitive* of the main
 * related-work categories so their EVM settlement cost can be measured under
 * an identical compiler/network configuration as TrustCircuit. Each function
 * is intentionally minimal: it captures the dominant on-chain mechanism of a
 * system class rather than its full feature set.
 *
 *   plaintextGrant   - access-control ledgers (Zyskind et al., MedRec, Ancile,
 *                      Daidone et al.): record/emit an access decision.
 *   recordCommitment - provenance/consent markets (ProMark) and TEE-anchored
 *                      contracts (Ekiden, FastKitten): persist a hash
 *                      commitment / attestation anchor with no privacy proof.
 *   verifyMerklePolicy - allowlist / selective-disclosure membership proofs:
 *                      verify a Merkle branch on-chain.
 *
 * The zk-SNARK / PLONK / fflonk compliance verifiers measured elsewhere
 * (scripts/zk_schemes_gas.js) represent the Hawk / zkLedger / TrustCircuit
 * verifiable-compliance category.
 */
contract SotaBaselines {
    event AccessGranted(bytes32 indexed consumer, bytes32 indexed asset, bool granted);
    event CommitmentRecorded(bytes32 indexed key, bytes32 commitment);

    mapping(bytes32 => bool) public grants;
    mapping(bytes32 => bytes32) public commitments;

    // Access-control ledger: persist + emit an access decision.
    function plaintextGrant(bytes32 consumer, bytes32 asset, bool granted) external returns (bool) {
        bytes32 key = keccak256(abi.encodePacked(consumer, asset));
        grants[key] = granted;
        emit AccessGranted(consumer, asset, granted);
        return granted;
    }

    // Provenance/consent or attestation anchor: persist a hash commitment.
    function recordCommitment(bytes32 key, bytes32 policyHash, bytes32 attestationHash, uint256 epsilonCost)
        external
        returns (bytes32)
    {
        bytes32 commitment = keccak256(abi.encodePacked(policyHash, attestationHash, epsilonCost));
        commitments[key] = commitment;
        emit CommitmentRecorded(key, commitment);
        return commitment;
    }

    // Allowlist / selective-disclosure: verify a Merkle membership branch.
    function verifyMerklePolicy(bytes32 leaf, bytes32[] calldata proof, bytes32 root) external pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            if (computed <= p) {
                computed = keccak256(abi.encodePacked(computed, p));
            } else {
                computed = keccak256(abi.encodePacked(p, computed));
            }
        }
        return computed == root;
    }
}
