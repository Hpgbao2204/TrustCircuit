// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./AccessController.sol";
import "./AuditLedger.sol";
import "./BudgetLedger.sol";
import "./ComplianceVerifier.sol";
import "./DataRegistry.sol";
import "./LifecycleRoles.sol";
import "./ValidatorRegistry.sol";

/// @notice Atomic settlement for the paper-aligned VCP v2 relation.
/// Every bytes32 public value is matched as two uint128 limbs without modular
/// reduction. Native evidence validation remains off-chain, while validator
/// authorization, signature, context, expiry, proof, budget, nullifier, request
/// terminal state, and audit insertion are checked in one EVM transaction.
contract TrustCircuitSettlement is LifecycleRoles {
    uint8 private constant REQUEST_AUTHORIZED = 2;
    uint8 private constant REQUEST_RESERVED = 4;

    uint256 private constant IDX_REQUEST_LO = 0;
    uint256 private constant IDX_REQUEST_HI = 1;
    uint256 private constant IDX_ASSET_LO = 2;
    uint256 private constant IDX_ASSET_HI = 3;
    uint256 private constant IDX_CONSUMER_LO = 4;
    uint256 private constant IDX_CONSUMER_HI = 5;
    uint256 private constant IDX_POLICY = 6;
    uint256 private constant IDX_POLICY_VERSION = 7;
    uint256 private constant IDX_PURPOSE = 8;
    uint256 private constant IDX_FUNCTION = 9;
    uint256 private constant IDX_DATA_LO = 10;
    uint256 private constant IDX_DATA_HI = 11;
    uint256 private constant IDX_DP_CONFIG_LO = 12;
    uint256 private constant IDX_DP_CONFIG_HI = 13;
    uint256 private constant IDX_FRESHNESS_LO = 14;
    uint256 private constant IDX_FRESHNESS_HI = 15;
    uint256 private constant IDX_RESERVED = 16;
    uint256 private constant IDX_ACTUAL = 17;
    uint256 private constant IDX_NULLIFIER = 18;
    uint256 private constant IDX_CONTEXT = 19;
    uint256 private constant IDX_ATTESTATION_LO = 20;
    uint256 private constant IDX_ATTESTATION_HI = 21;
    uint256 private constant IDX_RESULT = 22;
    uint256 private constant IDX_AUDIT = 23;

    struct SettlementEvidence {
        uint256 resultCommitment;
        uint256 auditDigest;
        ValidatorRegistry.ValidatedAttestation attestation;
    }

    DataRegistry public immutable registry;
    AccessController public immutable accessController;
    BudgetLedger public immutable budgetLedger;
    ComplianceVerifier public immutable complianceVerifier;
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
        uint256 actualCost,
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
    error ContextMismatch(uint256 index);
    error PrivacyCostExceedsReservation(uint256 actualCost, uint256 reservedCost);

    constructor(
        address registryAddress,
        address accessAddress,
        address budgetAddress,
        address complianceAddress,
        address auditAddress,
        address validatorRegistryAddress
    ) {
        if (
            registryAddress == address(0) ||
            accessAddress == address(0) ||
            budgetAddress == address(0) ||
            complianceAddress == address(0) ||
            auditAddress == address(0) ||
            validatorRegistryAddress == address(0)
        ) revert ZeroDependency();
        registry = DataRegistry(registryAddress);
        accessController = AccessController(accessAddress);
        budgetLedger = BudgetLedger(budgetAddress);
        complianceVerifier = ComplianceVerifier(complianceAddress);
        auditLedger = AuditLedger(auditAddress);
        validatorRegistry = ValidatorRegistry(validatorRegistryAddress);
    }

    function reserveBudgetForRequest(bytes32 requestKey) external onlyCoordinator {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_AUTHORIZED) {
            revert RequestNotAuthorized(requestKey);
        }
        if (!request.vcpV2) revert LegacyRequest(requestKey);
        budgetLedger.reserveBudget(
            request.assetId,
            requestKey,
            request.epsilonRequested
        );
        accessController.markReserved(requestKey);
        emit ReservationForwarded(requestKey, request.assetId, request.epsilonRequested);
    }

    function releaseBudgetForRequest(bytes32 requestKey) external onlyCoordinator {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_RESERVED) {
            revert RequestNotReserved(requestKey);
        }
        budgetLedger.releaseBudget(request.assetId, requestKey);
        accessController.releaseRequest(requestKey);
        emit ReservationReleased(requestKey, request.assetId, request.epsilonRequested);
    }

    function settle(
        bytes32 requestKey,
        SettlementEvidence calldata evidence,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[24] calldata pubSignals
    ) external returns (bool) {
        AccessController.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (uint8(request.status) != REQUEST_RESERVED) {
            revert RequestNotReserved(requestKey);
        }
        if (!request.vcpV2) revert LegacyRequest(requestKey);
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
        _match(pubSignals[IDX_RESERVED], request.epsilonRequested, IDX_RESERVED);
        if (
            pubSignals[IDX_ACTUAL] == 0 ||
            pubSignals[IDX_ACTUAL] > request.epsilonRequested
        ) {
            revert PrivacyCostExceedsReservation(
                pubSignals[IDX_ACTUAL],
                request.epsilonRequested
            );
        }

        validatorRegistry.requireValid(evidence.attestation);
        _match(
            pubSignals[IDX_CONTEXT],
            evidence.attestation.contextCommitment,
            IDX_CONTEXT
        );
        bytes32 attestationHash = validatorRegistry.statementHash(evidence.attestation);
        _matchBytes32(pubSignals, IDX_ATTESTATION_LO, attestationHash);
        _match(pubSignals[IDX_RESULT], evidence.resultCommitment, IDX_RESULT);
        _match(pubSignals[IDX_AUDIT], evidence.auditDigest, IDX_AUDIT);

        complianceVerifier.submitCompliance(requestKey, a, b, c, pubSignals);
        budgetLedger.consumeBudget(
            request.assetId,
            requestKey,
            pubSignals[IDX_ACTUAL]
        );
        accessController.completeRequest(requestKey);
        auditLedger.recordVCPSettlement(
            requestKey,
            request.assetId,
            request.consumer,
            request.policyVersion,
            pubSignals[IDX_ACTUAL],
            pubSignals[IDX_NULLIFIER],
            pubSignals[IDX_AUDIT]
        );
        emit RequestSettled(
            requestKey,
            request.assetId,
            request.consumer,
            pubSignals[IDX_ACTUAL],
            pubSignals[IDX_NULLIFIER],
            pubSignals[IDX_CONTEXT],
            attestationHash,
            pubSignals[IDX_RESULT],
            pubSignals[IDX_AUDIT]
        );
        return true;
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
