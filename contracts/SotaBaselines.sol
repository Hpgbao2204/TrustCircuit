// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract SotaBaselines {
    event AccessGranted(bytes32 indexed consumer, bytes32 indexed asset, bool granted);
    event CommitmentRecorded(bytes32 indexed key, bytes32 commitment);

    mapping(bytes32 => bool) public grants;
    mapping(bytes32 => bytes32) public commitments;

    function plaintextGrant(bytes32 consumer, bytes32 asset, bool granted) external returns (bool) {
        bytes32 key = keccak256(abi.encodePacked(consumer, asset));
        grants[key] = granted;
        emit AccessGranted(consumer, asset, granted);
        return granted;
    }

    function recordCommitment(bytes32 key, bytes32 policyHash, bytes32 attestationHash, uint256 epsilonCost)
        external
        returns (bytes32)
    {
        bytes32 commitment = keccak256(abi.encodePacked(policyHash, attestationHash, epsilonCost));
        commitments[key] = commitment;
        emit CommitmentRecorded(key, commitment);
        return commitment;
    }

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
