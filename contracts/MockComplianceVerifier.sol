// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract MockComplianceVerifier {
    event ProofSubmitted(
        bytes32 indexed requestId,
        bytes32 indexed assetId,
        bytes32 proofHash,
        bool accepted
    );

    error InvalidProof(bytes32 requestId);

    function submitProof(bytes32 requestId, bytes32 assetId, bytes32 proofHash, bool accepted) external returns (bool) {
        emit ProofSubmitted(requestId, assetId, proofHash, accepted);
        if (!accepted) revert InvalidProof(requestId);
        return true;
    }
}
