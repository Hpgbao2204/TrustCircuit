// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./AccessController.sol";
import "./LifecycleRoles.sol";
import "./ValidatorRegistry.sol";

/// @notice Stage-wise composition harness (comparison design).
/// Each stage verifies its own evidence under its own identifier:
///   * admission checks the authorization record of the request and an
///     aggregate per-asset budget counter, but reserves nothing;
///   * execution evidence is a validator-quorum statement about an execution
///     identifier and a result commitment, not about the request;
///   * settlement decrements the aggregate counter checked at admission and
///     does not re-check the policy version.
/// Used only to execute failures F1-F3 against a design without
/// a shared request interface. It is not part of the TrustCircuit protocol.
contract StageWiseSettlement is LifecycleRoles {
    bytes32 public constant EXEC_TYPEHASH = keccak256(
        "StageWiseExecution(bytes32 executionId,uint256 resultCommitment)"
    );

    struct AssetBudget {
        uint256 total;
        uint256 used;
    }

    struct Admission {
        bytes32 assetId;
        uint256 amount;
        bool admitted;
        bool settled;
    }

    struct ExecutionStatement {
        bytes32 executionId;
        uint256 resultCommitment;
        bytes32[] validatorIds;
        bytes[] signatures;
    }

    AccessController public immutable accessController;
    ValidatorRegistry public immutable validatorRegistry;
    mapping(bytes32 => AssetBudget) public budgets;
    mapping(bytes32 => Admission) public admissions;

    event Admitted(bytes32 indexed requestId, bytes32 indexed assetId, uint256 amount);
    event Settled(
        bytes32 indexed requestId,
        bytes32 indexed executionId,
        uint256 resultCommitment,
        uint256 usedAfter,
        uint256 total
    );

    error NotAuthorized(bytes32 requestId);
    error InsufficientBudget(uint256 requested, uint256 remaining);
    error NotAdmitted(bytes32 requestId);
    error AlreadySettled(bytes32 requestId);

    constructor(address accessAddress, address validatorRegistryAddress) {
        accessController = AccessController(accessAddress);
        validatorRegistry = ValidatorRegistry(validatorRegistryAddress);
    }

    function registerBudget(bytes32 assetId, uint256 total) external onlyCoordinator {
        budgets[assetId] = AssetBudget(total, 0);
    }

    function admit(bytes32 requestId, uint256 amount) external onlyCoordinator {
        AccessController.AccessRequest memory request = accessController.getRequest(requestId);
        if (request.status != AccessController.RequestStatus.Authorized) {
            revert NotAuthorized(requestId);
        }
        AssetBudget storage budget = budgets[request.assetId];
        uint256 remaining = budget.total - budget.used;
        if (amount > remaining) revert InsufficientBudget(amount, remaining);
        admissions[requestId] = Admission(request.assetId, amount, true, false);
        emit Admitted(requestId, request.assetId, amount);
    }

    function settle(bytes32 requestId, ExecutionStatement calldata statement) external {
        Admission storage admission = admissions[requestId];
        if (!admission.admitted) revert NotAdmitted(requestId);
        if (admission.settled) revert AlreadySettled(requestId);
        validatorRegistry.requireQuorumOn(
            keccak256(abi.encode(EXEC_TYPEHASH, statement.executionId, statement.resultCommitment)),
            statement.validatorIds,
            statement.signatures
        );
        AssetBudget storage budget = budgets[admission.assetId];
        budget.used += admission.amount;
        admission.settled = true;
        emit Settled(
            requestId,
            statement.executionId,
            statement.resultCommitment,
            budget.used,
            budget.total
        );
    }
}
