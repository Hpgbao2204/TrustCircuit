// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AuditLedger {
    enum AuditStage {
        Registered,
        Requested,
        BudgetReserved,
        Computed,
        ProofVerified,
        BudgetConsumed,
        Completed,
        Failed
    }

    event AuditRecorded(
        bytes32 indexed requestId,
        bytes32 indexed assetId,
        AuditStage indexed stage,
        bytes32 evidenceHash,
        uint256 timestamp
    );

    event SettlementAuditRecorded(
        bytes32 indexed requestId,
        bytes32 indexed assetId,
        address indexed consumer,
        uint256 consumerIdField,
        bytes32 policyHash,
        uint64 policyVersion,
        uint32 functionId,
        bytes32 resultHash,
        uint256 privacyCostFixed,
        uint256 nullifier,
        bytes32 transcriptHash,
        bytes32 attestationDigest,
        uint256 timestamp
    );

    function recordAudit(bytes32 requestId, bytes32 assetId, AuditStage stage, bytes32 evidenceHash) external {
        emit AuditRecorded(requestId, assetId, stage, evidenceHash, block.timestamp);
    }

    function recordSettlement(
        bytes32 requestId,
        bytes32 assetId,
        address consumer,
        uint256 consumerIdField,
        bytes32 policyHash,
        uint64 policyVersion,
        uint32 functionId,
        bytes32 resultHash,
        uint256 privacyCostFixed,
        uint256 nullifier,
        bytes32 transcriptHash,
        bytes32 attestationDigest
    ) external {
        emit SettlementAuditRecorded(
            requestId,
            assetId,
            consumer,
            consumerIdField,
            policyHash,
            policyVersion,
            functionId,
            resultHash,
            privacyCostFixed,
            nullifier,
            transcriptHash,
            attestationDigest,
            block.timestamp
        );
    }
}
