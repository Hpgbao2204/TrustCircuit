// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./AccessController.sol";
import "./AuditLedger.sol";
import "./BudgetLedger.sol";
import "./DataRegistry.sol";
import "./LifecycleRoles.sol";
import "./ValidatorRegistry.sol";

/// @notice Guards shared by TrustCircuit settlement and the sign-and-hash
/// comparison design: request state, current policy version and commitment,
/// dataset snapshot, ledger-computed RDP reservation and charge, k-of-n
/// validator quorum, context and attestation binding, and audit insertion.
/// Concrete settlements differ only in how they accept the policy decision.
abstract contract SettlementCore is LifecycleRoles {
    uint8 private constant REQUEST_AUTHORIZED = 2;
    uint8 private constant REQUEST_RESERVED = 4;

    uint256 internal constant IDX_REQUEST_LO = 0;
    uint256 internal constant IDX_ASSET_LO = 2;
    uint256 internal constant IDX_CONSUMER_LO = 4;
    uint256 internal constant IDX_POLICY = 6;
    uint256 internal constant IDX_POLICY_VERSION = 7;
    uint256 internal constant IDX_PURPOSE = 8;
    uint256 internal constant IDX_FUNCTION = 9;
    uint256 internal constant IDX_DATA_LO = 10;
    uint256 internal constant IDX_DP_CONFIG_LO = 12;
    uint256 internal constant IDX_FRESHNESS_LO = 14;
    uint256 internal constant IDX_RESERVED = 16;
    uint256 internal constant IDX_ACTUAL = 17;
    uint256 internal constant IDX_NULLIFIER = 18;
    uint256 internal constant IDX_CONTEXT = 19;
    uint256 internal constant IDX_ATTESTATION_LO = 20;
    uint256 internal constant IDX_RESULT = 22;
    uint256 internal constant IDX_AUDIT = 23;

    struct SettlementEvidence {
        uint256 resultCommitment;
        uint256 auditDigest;
        ValidatorRegistry.QuorumAttestation attestation;
    }

    DataRegistry public immutable registry;
    AccessController public immutable accessController;
    BudgetLedger public immutable budgetLedger;
    AuditLedger public immutable auditLedger;
    ValidatorRegistry public immutable validatorRegistry;

    event ReservationForwarded(
        bytes32 indexed requestKey,
        bytes32 indexed assetKey,
        uint256 amount
    );
    event ReservationReleased(
        bytes32 indexed requestKey,
        bytes32 indexed assetKey,
        uint256 amount
    );
    event RequestSettled(
        bytes32 indexed requestKey,
        bytes32 indexed assetKey,
        address indexed consumer,
        uint256 charge,
        uint256 nullifier,
        uint256 contextCommitment,
        bytes32 attestationHash,
        uint256 resultCommitment,
        uint256 auditDigest
    );

    error ZeroDependency();
    error RequestNotAuthorized(bytes32 requestKey);
    error RequestNotReserved(bytes32 requestKey);
    error LegacyRequest(bytes32 requestKey);
    error WrongConsumer(address expected, address actual);
    error InactiveAsset(bytes32 assetKey);
    error LegacyAsset(bytes32 assetKey);
    error PolicyMismatch();
    error RequestExpired(uint256 currentUnixMs, uint256 deadlineUnixMs);
    error RequestNotExpired(bytes32 requestKey);
    error ContextMismatch(uint256 index);
    error PrivacyCostExceedsReservation(uint256 actualCost, uint256 reservedCost);

    constructor(
        address registryAddress,
        address accessAddress,
        address budgetAddress,
        address auditAddress,
        address validatorRegistryAddress
    ) {
        if (
            registryAddress == address(0) ||
            accessAddress == address(0) ||
            budgetAddress == address(0) ||
            auditAddress == address(0) ||
            validatorRegistryAddress == address(0)
        ) revert ZeroDependency();
        registry = DataRegistry(registryAddress);
        accessController = AccessController(accessAddress);
        budgetLedger = BudgetLedger(budgetAddress);
        auditLedger = AuditLedger(auditAddress);
        validatorRegistry = ValidatorRegistry(validatorRegistryAddress);
    }

    /// @notice The asset owner fixes the RDP budget, order set, and offsets.
    function registerRdpBudget(
        bytes32 assetKey,
        uint256 totalBudget,
        uint8[] calldata orders,
        uint64[] calldata offsets
    ) external {
        registry.requireOwner(assetKey, msg.sender);
        budgetLedger.registerRdpBudget(assetKey, totalBudget, orders, offsets);
    }

    function reserveBudgetForRequest(bytes32 requestKey)
        external
        onlyCoordinator
        returns (uint256 amount)
    {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_AUTHORIZED) {
            revert RequestNotAuthorized(requestKey);
        }
        if (!request.rdp) revert LegacyRequest(requestKey);
        amount = budgetLedger.reserveRdp(
            request.assetId,
            requestKey,
            request.sigmaFixed,
            request.sensitivityFixed
        );
        accessController.markReserved(requestKey);
        emit ReservationForwarded(requestKey, request.assetId, amount);
    }

    function releaseBudgetForRequest(bytes32 requestKey) external onlyCoordinator {
        _release(requestKey);
    }

    /// @notice Anyone may release a reservation whose settlement deadline has
    /// passed, so an abandoned request cannot lock budget indefinitely.
    function releaseExpiredReservation(bytes32 requestKey) external {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (block.timestamp * 1000 <= request.deadlineUnixMs) {
            revert RequestNotExpired(requestKey);
        }
        _release(requestKey);
    }

    /// @dev Effects of an accepted settlement, applied atomically.
    function _finalize(
        bytes32 requestKey,
        AccessController.AccessRequest memory request,
        bytes32 attestationHash,
        uint256[24] calldata pubSignals
    ) internal {
        uint256 charge = budgetLedger.consumeRdp(request.assetId, requestKey);
        accessController.completeRequest(requestKey);
        auditLedger.recordVCPSettlement(
            requestKey,
            request.assetId,
            request.consumer,
            request.policyVersion,
            charge,
            pubSignals[IDX_NULLIFIER],
            pubSignals[IDX_AUDIT]
        );
        emit RequestSettled(
            requestKey,
            request.assetId,
            request.consumer,
            charge,
            pubSignals[IDX_NULLIFIER],
            pubSignals[IDX_CONTEXT],
            attestationHash,
            pubSignals[IDX_RESULT],
            pubSignals[IDX_AUDIT]
        );
    }

    /// @dev Current_t: the public statement must equal the reserved request,
    /// the current policy commitment and version, and the dataset snapshot.
    function _checkCurrentState(bytes32 requestKey, uint256[24] calldata pubSignals)
        internal
        view
        returns (AccessController.AccessRequest memory request)
    {
        request = accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_RESERVED) {
            revert RequestNotReserved(requestKey);
        }
        if (!request.rdp) revert LegacyRequest(requestKey);
        if (request.consumer != msg.sender) {
            revert WrongConsumer(request.consumer, msg.sender);
        }
        uint256 currentUnixMs = block.timestamp * 1000;
        if (currentUnixMs > request.deadlineUnixMs) {
            revert RequestExpired(currentUnixMs, request.deadlineUnixMs);
        }

        DataRegistry.Asset memory asset = registry.getAsset(request.assetId);
        if (!asset.active) revert InactiveAsset(request.assetId);
        if (!asset.vcpV2) revert LegacyAsset(request.assetId);
        if (
            asset.policyCommitment != request.policyCommitment ||
            asset.policyVersion != request.policyVersion
        ) revert PolicyMismatch();

        _matchBytes32(pubSignals, IDX_REQUEST_LO, requestKey);
        _matchBytes32(pubSignals, IDX_ASSET_LO, request.assetId);
        _matchBytes32(pubSignals, IDX_CONSUMER_LO, request.consumerId);
        _match(pubSignals[IDX_POLICY], asset.policyCommitment, IDX_POLICY);
        _match(pubSignals[IDX_POLICY_VERSION], asset.policyVersion, IDX_POLICY_VERSION);
        _match(pubSignals[IDX_PURPOSE], request.purposeId, IDX_PURPOSE);
        _match(pubSignals[IDX_FUNCTION], request.functionId, IDX_FUNCTION);
        _matchBytes32(pubSignals, IDX_DATA_LO, asset.dataHash);
        _matchBytes32(pubSignals, IDX_DP_CONFIG_LO, request.dpConfigHash);
        _matchBytes32(pubSignals, IDX_FRESHNESS_LO, request.freshnessNonce);

        (, uint256 reserved, ) = budgetLedger.getReservation(requestKey);
        _match(pubSignals[IDX_RESERVED], reserved, IDX_RESERVED);
        if (pubSignals[IDX_ACTUAL] == 0 || pubSignals[IDX_ACTUAL] > reserved) {
            revert PrivacyCostExceedsReservation(pubSignals[IDX_ACTUAL], reserved);
        }
    }

    /// @dev ValidStmt_t for a k-of-n quorum, c_zk equality, and ah binding.
    function _checkEvidence(
        SettlementEvidence calldata evidence,
        uint256[24] calldata pubSignals
    ) internal view returns (bytes32 attestationHash) {
        validatorRegistry.requireQuorum(evidence.attestation);
        _match(pubSignals[IDX_CONTEXT], evidence.attestation.contextCommitment, IDX_CONTEXT);
        attestationHash = validatorRegistry.quorumHash(evidence.attestation);
        _matchBytes32(pubSignals, IDX_ATTESTATION_LO, attestationHash);
        _match(pubSignals[IDX_RESULT], evidence.resultCommitment, IDX_RESULT);
        _match(pubSignals[IDX_AUDIT], evidence.auditDigest, IDX_AUDIT);
    }

    function _release(bytes32 requestKey) private {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_RESERVED) {
            revert RequestNotReserved(requestKey);
        }
        (, uint256 amount, ) = budgetLedger.getReservation(requestKey);
        budgetLedger.releaseBudget(request.assetId, requestKey);
        accessController.releaseRequest(requestKey);
        emit ReservationReleased(requestKey, request.assetId, amount);
    }

    function _matchBytes32(
        uint256[24] calldata pubSignals,
        uint256 loIndex,
        bytes32 expected
    ) private pure {
        (uint256 lo, uint256 hi) = _split(expected);
        _match(pubSignals[loIndex], lo, loIndex);
        _match(pubSignals[loIndex + 1], hi, loIndex + 1);
    }

    function _split(bytes32 value) private pure returns (uint256 lo, uint256 hi) {
        uint256 integer = uint256(value);
        lo = uint128(integer);
        hi = integer >> 128;
    }

    function _match(uint256 actual, uint256 expected, uint256 index) private pure {
        if (actual != expected) revert ContextMismatch(index);
    }
}
