// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IPhase7Groth16Verifier {
    function verifyProof(
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[11] calldata pubSignals
    ) external view returns (bool);
}

/**
 * @title ComplianceVerifier
 * @notice Request-bound adapter for the Phase 7 VCP Groth16 verifier.
 *
 * Canonical public-signal order:
 *   0 requestId, 1 assetId, 2 consumerId, 3 policyHash,
 *   4 policyVersion, 5 functionId, 6 resultHash, 7 epsilonCost,
 *   8 nullifier, 9 transcriptHash, 10 attestationDigest.
 *
 * Native Windows evidence is validated outside the EVM. This adapter binds the
 * digest and validity interval of that validated statement; it does not claim
 * that Solidity validates the native VBS report or its certificate chain.
 */
contract ComplianceVerifier {
    uint256 internal constant IDX_REQUEST = 0;
    uint256 internal constant IDX_ASSET = 1;
    uint256 internal constant IDX_CONSUMER = 2;
    uint256 internal constant IDX_POLICY = 3;
    uint256 internal constant IDX_POLICY_VERSION = 4;
    uint256 internal constant IDX_FUNCTION = 5;
    uint256 internal constant IDX_RESULT = 6;
    uint256 internal constant IDX_EPSILON = 7;
    uint256 internal constant IDX_NULLIFIER = 8;
    uint256 internal constant IDX_TRANSCRIPT = 9;
    uint256 internal constant IDX_ATTESTATION = 10;

    uint256 public constant SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    struct ExpectationInput {
        uint256 requestId;
        uint256 assetId;
        uint256 consumerId;
        uint256 policyHash;
        uint256 policyVersion;
        uint256 functionId;
        uint256 resultHash;
        uint256 maxEpsilon;
        uint256 transcriptHash;
        uint256 attestationDigest;
        uint64 attestationExpiresAtUnixMs;
    }

    struct Expectation {
        uint256 requestId;
        uint256 assetId;
        uint256 consumerId;
        uint256 policyHash;
        uint256 policyVersion;
        uint256 functionId;
        uint256 resultHash;
        uint256 maxEpsilon;
        uint256 transcriptHash;
        uint256 attestationDigest;
        uint64 attestationExpiresAtUnixMs;
        bool registered;
        bool verified;
        uint256 epsilonUsed;
        uint256 nullifier;
    }

    IPhase7Groth16Verifier public immutable verifier;
    address public owner;
    mapping(bytes32 => Expectation) private expectations;
    mapping(uint256 => bool) public nullifierUsed;

    event ExpectationRegistered(
        bytes32 indexed requestKey,
        uint256 indexed requestId,
        uint256 indexed assetId,
        uint256 consumerId,
        uint256 policyHash,
        uint256 policyVersion,
        uint256 functionId,
        uint256 resultHash,
        uint256 maxEpsilon,
        uint256 transcriptHash,
        uint256 attestationDigest,
        uint64 attestationExpiresAtUnixMs
    );
    event ComplianceVerified(
        bytes32 indexed requestKey,
        uint256 indexed nullifier,
        uint256 epsilonCost,
        uint256 resultHash,
        uint256 transcriptHash,
        uint256 attestationDigest
    );

    error NotOwner();
    error ZeroVerifier();
    error AlreadyRegistered(bytes32 requestKey);
    error NotRegistered(bytes32 requestKey);
    error AlreadyVerified(bytes32 requestKey);
    error FieldOverflow(uint256 index);
    error RequestIdMismatch(bytes32 requestKey, uint256 signal);
    error PublicInputMismatch(uint256 index);
    error BudgetExceeded(uint256 epsilonCost, uint256 maxEpsilon);
    error InvalidPrivacyCost();
    error NullifierAlreadyUsed(uint256 nullifier);
    error StaleAttestation(uint256 currentUnixMs, uint256 expiresAtUnixMs);
    error InvalidProof(bytes32 requestKey);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address verifierAddress) {
        if (verifierAddress == address(0)) revert ZeroVerifier();
        verifier = IPhase7Groth16Verifier(verifierAddress);
        owner = msg.sender;
    }

    function registerExpectation(bytes32 requestKey, ExpectationInput calldata input)
        external
        onlyOwner
    {
        if (expectations[requestKey].registered) revert AlreadyRegistered(requestKey);
        if (input.requestId != uint256(requestKey) % SCALAR_FIELD) {
            revert RequestIdMismatch(requestKey, input.requestId);
        }
        _requireField(input.requestId, IDX_REQUEST);
        _requireField(input.assetId, IDX_ASSET);
        _requireField(input.consumerId, IDX_CONSUMER);
        _requireField(input.policyHash, IDX_POLICY);
        _requireField(input.policyVersion, IDX_POLICY_VERSION);
        _requireField(input.functionId, IDX_FUNCTION);
        _requireField(input.resultHash, IDX_RESULT);
        _requireField(input.transcriptHash, IDX_TRANSCRIPT);
        _requireField(input.attestationDigest, IDX_ATTESTATION);
        if (input.policyVersion == 0 || (input.functionId != 1 && input.functionId != 2)) {
            revert PublicInputMismatch(IDX_FUNCTION);
        }
        if (input.maxEpsilon == 0) revert InvalidPrivacyCost();

        expectations[requestKey] = Expectation({
            requestId: input.requestId,
            assetId: input.assetId,
            consumerId: input.consumerId,
            policyHash: input.policyHash,
            policyVersion: input.policyVersion,
            functionId: input.functionId,
            resultHash: input.resultHash,
            maxEpsilon: input.maxEpsilon,
            transcriptHash: input.transcriptHash,
            attestationDigest: input.attestationDigest,
            attestationExpiresAtUnixMs: input.attestationExpiresAtUnixMs,
            registered: true,
            verified: false,
            epsilonUsed: 0,
            nullifier: 0
        });
        emit ExpectationRegistered(
            requestKey,
            input.requestId,
            input.assetId,
            input.consumerId,
            input.policyHash,
            input.policyVersion,
            input.functionId,
            input.resultHash,
            input.maxEpsilon,
            input.transcriptHash,
            input.attestationDigest,
            input.attestationExpiresAtUnixMs
        );
    }

    function submitCompliance(
        bytes32 requestKey,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[11] calldata pubSignals
    ) external returns (bool) {
        Expectation storage expected = expectations[requestKey];
        if (!expected.registered) revert NotRegistered(requestKey);
        if (expected.verified) revert AlreadyVerified(requestKey);
        if (pubSignals[IDX_REQUEST] != uint256(requestKey) % SCALAR_FIELD) {
            revert RequestIdMismatch(requestKey, pubSignals[IDX_REQUEST]);
        }
        _match(pubSignals[IDX_REQUEST], expected.requestId, IDX_REQUEST);
        _match(pubSignals[IDX_ASSET], expected.assetId, IDX_ASSET);
        _match(pubSignals[IDX_CONSUMER], expected.consumerId, IDX_CONSUMER);
        _match(pubSignals[IDX_POLICY], expected.policyHash, IDX_POLICY);
        _match(pubSignals[IDX_POLICY_VERSION], expected.policyVersion, IDX_POLICY_VERSION);
        _match(pubSignals[IDX_FUNCTION], expected.functionId, IDX_FUNCTION);
        _match(pubSignals[IDX_RESULT], expected.resultHash, IDX_RESULT);
        _match(pubSignals[IDX_TRANSCRIPT], expected.transcriptHash, IDX_TRANSCRIPT);
        _match(pubSignals[IDX_ATTESTATION], expected.attestationDigest, IDX_ATTESTATION);

        uint256 epsilonCost = pubSignals[IDX_EPSILON];
        if (epsilonCost == 0) revert InvalidPrivacyCost();
        if (epsilonCost > expected.maxEpsilon) {
            revert BudgetExceeded(epsilonCost, expected.maxEpsilon);
        }
        uint256 currentUnixMs = block.timestamp * 1000;
        if (currentUnixMs > expected.attestationExpiresAtUnixMs) {
            revert StaleAttestation(currentUnixMs, expected.attestationExpiresAtUnixMs);
        }
        uint256 nullifier = pubSignals[IDX_NULLIFIER];
        if (nullifierUsed[nullifier]) revert NullifierAlreadyUsed(nullifier);
        if (!verifier.verifyProof(a, b, c, pubSignals)) revert InvalidProof(requestKey);

        nullifierUsed[nullifier] = true;
        expected.verified = true;
        expected.epsilonUsed = epsilonCost;
        expected.nullifier = nullifier;
        emit ComplianceVerified(
            requestKey,
            nullifier,
            epsilonCost,
            expected.resultHash,
            expected.transcriptHash,
            expected.attestationDigest
        );
        return true;
    }

    function getExpectation(bytes32 requestKey) external view returns (Expectation memory) {
        Expectation memory expected = expectations[requestKey];
        if (!expected.registered) revert NotRegistered(requestKey);
        return expected;
    }

    function isVerified(bytes32 requestKey) external view returns (bool) {
        return expectations[requestKey].verified;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }

    function _requireField(uint256 value, uint256 index) private pure {
        if (value >= SCALAR_FIELD) revert FieldOverflow(index);
    }

    function _match(uint256 actual, uint256 expected, uint256 index) private pure {
        if (actual != expected) revert PublicInputMismatch(index);
    }
}
