// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IDataRegistryPhase7 {
    struct Asset {
        address owner;
        bytes32 metadataHash;
        bytes32 dataHash;
        bytes32 policyHash;
        uint64 policyVersion;
        bool active;
    }

    function getAsset(bytes32 assetId) external view returns (Asset memory);
}

interface IAccessControllerPhase7 {
    struct AccessRequest {
        bytes32 assetId;
        address consumer;
        uint256 consumerIdField;
        bytes32 purposeHash;
        bytes32 policyHash;
        uint64 policyVersion;
        uint32 functionId;
        uint256 epsilonRequested;
        uint8 status;
    }

    function getRequest(bytes32 requestId) external view returns (AccessRequest memory);
    function completeRequest(bytes32 requestId) external;
}

interface IBudgetLedgerPhase7 {
    function reserveBudget(bytes32 assetId, bytes32 requestId, uint256 amount) external;
    function consumeBudget(bytes32 assetId, bytes32 requestId, uint256 actualAmount) external;
}

interface IComplianceVerifierPhase7 {
    function submitCompliance(
        bytes32 requestKey,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[11] calldata pubSignals
    ) external returns (bool);
}

interface IAuditLedgerPhase7 {
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
    ) external;
}

/**
 * @title TrustCircuitSettlement
 * @notice Atomic Phase 7 transition from verified evidence to consumed budget.
 *
 * Budget reservation is deliberately a pre-computation transaction. The final
 * `settle` call performs Groth16 verification/nullifier consumption, privacy
 * budget consumption, access completion, and audit emission atomically. A
 * revert in any downstream contract rolls the whole state transition back.
 */
contract TrustCircuitSettlement {
    uint256 private constant SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;
    uint8 private constant REQUEST_APPROVED = 2;

    uint256 private constant IDX_REQUEST = 0;
    uint256 private constant IDX_ASSET = 1;
    uint256 private constant IDX_CONSUMER = 2;
    uint256 private constant IDX_POLICY = 3;
    uint256 private constant IDX_POLICY_VERSION = 4;
    uint256 private constant IDX_FUNCTION = 5;
    uint256 private constant IDX_RESULT = 6;
    uint256 private constant IDX_EPSILON = 7;
    uint256 private constant IDX_NULLIFIER = 8;
    uint256 private constant IDX_TRANSCRIPT = 9;
    uint256 private constant IDX_ATTESTATION = 10;

    struct SettlementEvidence {
        bytes32 dataHash;
        bytes32 resultHash;
        bytes32 transcriptHash;
        bytes32 attestationDigest;
    }

    IDataRegistryPhase7 public immutable registry;
    IAccessControllerPhase7 public immutable accessController;
    IBudgetLedgerPhase7 public immutable budgetLedger;
    IComplianceVerifierPhase7 public immutable complianceVerifier;
    IAuditLedgerPhase7 public immutable auditLedger;
    address public owner;

    event ReservationForwarded(
        bytes32 indexed requestKey,
        bytes32 indexed assetKey,
        uint256 amount
    );
    event RequestSettled(
        bytes32 indexed requestKey,
        bytes32 indexed assetKey,
        address indexed consumer,
        uint256 privacyCostFixed,
        uint256 nullifier,
        bytes32 transcriptHash,
        bytes32 attestationDigest
    );

    error NotOwner();
    error ZeroDependency();
    error RequestNotApproved(bytes32 requestKey);
    error AssetMismatch(bytes32 expected, bytes32 actual);
    error WrongConsumer(address expected, address actual);
    error InactiveAsset(bytes32 assetKey);
    error PolicyMismatch();
    error ContextMismatch(uint256 index);
    error DataHashMismatch();
    error PrivacyCostExceedsReservation(uint256 actualCost, uint256 reservedCost);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(
        address registryAddress,
        address accessAddress,
        address budgetAddress,
        address complianceAddress,
        address auditAddress
    ) {
        if (
            registryAddress == address(0) ||
            accessAddress == address(0) ||
            budgetAddress == address(0) ||
            complianceAddress == address(0) ||
            auditAddress == address(0)
        ) revert ZeroDependency();
        registry = IDataRegistryPhase7(registryAddress);
        accessController = IAccessControllerPhase7(accessAddress);
        budgetLedger = IBudgetLedgerPhase7(budgetAddress);
        complianceVerifier = IComplianceVerifierPhase7(complianceAddress);
        auditLedger = IAuditLedgerPhase7(auditAddress);
        owner = msg.sender;
    }

    function reserveBudgetForRequest(bytes32 requestKey) external onlyOwner {
        IAccessControllerPhase7.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (request.status != REQUEST_APPROVED) revert RequestNotApproved(requestKey);
        budgetLedger.reserveBudget(
            request.assetId,
            requestKey,
            request.epsilonRequested
        );
        emit ReservationForwarded(requestKey, request.assetId, request.epsilonRequested);
    }

    function settle(
        bytes32 requestKey,
        SettlementEvidence calldata evidence,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[11] calldata pubSignals
    ) external returns (bool) {
        IAccessControllerPhase7.AccessRequest memory request =
            accessController.getRequest(requestKey);
        if (request.status != REQUEST_APPROVED) revert RequestNotApproved(requestKey);
        if (request.consumer != msg.sender) {
            revert WrongConsumer(request.consumer, msg.sender);
        }

        IDataRegistryPhase7.Asset memory asset = registry.getAsset(request.assetId);
        if (!asset.active) revert InactiveAsset(request.assetId);
        if (asset.dataHash != evidence.dataHash) revert DataHashMismatch();
        if (
            asset.policyHash != request.policyHash ||
            asset.policyVersion != request.policyVersion
        ) revert PolicyMismatch();

        _match(pubSignals[IDX_REQUEST], uint256(requestKey) % SCALAR_FIELD, IDX_REQUEST);
        _match(pubSignals[IDX_ASSET], uint256(request.assetId) % SCALAR_FIELD, IDX_ASSET);
        _match(pubSignals[IDX_CONSUMER], request.consumerIdField, IDX_CONSUMER);
        _match(pubSignals[IDX_POLICY], uint256(asset.policyHash) % SCALAR_FIELD, IDX_POLICY);
        _match(pubSignals[IDX_POLICY_VERSION], asset.policyVersion, IDX_POLICY_VERSION);
        _match(pubSignals[IDX_FUNCTION], request.functionId, IDX_FUNCTION);
        _match(pubSignals[IDX_RESULT], uint256(evidence.resultHash) % SCALAR_FIELD, IDX_RESULT);
        _match(
            pubSignals[IDX_TRANSCRIPT],
            uint256(evidence.transcriptHash) % SCALAR_FIELD,
            IDX_TRANSCRIPT
        );
        _match(
            pubSignals[IDX_ATTESTATION],
            uint256(evidence.attestationDigest) % SCALAR_FIELD,
            IDX_ATTESTATION
        );
        if (pubSignals[IDX_EPSILON] > request.epsilonRequested) {
            revert PrivacyCostExceedsReservation(
                pubSignals[IDX_EPSILON],
                request.epsilonRequested
            );
        }

        complianceVerifier.submitCompliance(requestKey, a, b, c, pubSignals);
        budgetLedger.consumeBudget(request.assetId, requestKey, pubSignals[IDX_EPSILON]);
        accessController.completeRequest(requestKey);
        _recordSettlement(requestKey, request, evidence, pubSignals);
        return true;
    }

    function _recordSettlement(
        bytes32 requestKey,
        IAccessControllerPhase7.AccessRequest memory request,
        SettlementEvidence calldata evidence,
        uint256[11] calldata pubSignals
    ) private {
        auditLedger.recordSettlement(
            requestKey,
            request.assetId,
            request.consumer,
            request.consumerIdField,
            request.policyHash,
            request.policyVersion,
            request.functionId,
            evidence.resultHash,
            pubSignals[IDX_EPSILON],
            pubSignals[IDX_NULLIFIER],
            evidence.transcriptHash,
            evidence.attestationDigest
        );
        emit RequestSettled(
            requestKey,
            request.assetId,
            request.consumer,
            pubSignals[IDX_EPSILON],
            pubSignals[IDX_NULLIFIER],
            evidence.transcriptHash,
            evidence.attestationDigest
        );
    }

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }

    function _match(uint256 actual, uint256 expected, uint256 index) private pure {
        if (actual != expected) revert ContextMismatch(index);
    }
}
