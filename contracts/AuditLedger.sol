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

    function recordAudit(bytes32 requestId, bytes32 assetId, AuditStage stage, bytes32 evidenceHash) external {
        emit AuditRecorded(requestId, assetId, stage, evidenceHash, block.timestamp);
    }
}
