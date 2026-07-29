// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./LifecycleRoles.sol";

interface IVCPGroth16Verifier {
    function verifyProof(
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[24] calldata pubSignals
    ) external view returns (bool);
}

/// @notice Thin verifier adapter for the paper-aligned VCP v2 relation.
/// Request-state matching and validator authentication live in atomic settlement;
/// this adapter enforces proof validity and global nullifier uniqueness.
contract ComplianceVerifier is LifecycleRoles {
    uint256 public constant SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    uint256 internal constant IDX_REQUEST_LO = 0;
    uint256 internal constant IDX_REQUEST_HI = 1;
    uint256 internal constant IDX_RESERVED = 16;
    uint256 internal constant IDX_ACTUAL = 17;
    uint256 internal constant IDX_NULLIFIER = 18;
    uint256 internal constant IDX_RESULT = 22;
    uint256 internal constant IDX_AUDIT = 23;

    IVCPGroth16Verifier public immutable verifier;
    mapping(uint256 => bool) public nullifierUsed;
    mapping(bytes32 => bool) public requestVerified;

    event ComplianceVerified(
        bytes32 indexed requestKey,
        uint256 indexed nullifier,
        uint256 reservedCost,
        uint256 actualCost,
        uint256 resultCommitment,
        uint256 auditDigest
    );

    error ZeroVerifier();
    error RequestAlreadyVerified(bytes32 requestKey);
    error RequestIdMismatch(bytes32 requestKey);
    error FieldOverflow(uint256 index);
    error InvalidPrivacyCost();
    error NullifierAlreadyUsed(uint256 nullifier);
    error InvalidProof(bytes32 requestKey);

    constructor(address verifierAddress) {
        if (verifierAddress == address(0)) revert ZeroVerifier();
        verifier = IVCPGroth16Verifier(verifierAddress);
    }

    function submitCompliance(
        bytes32 requestKey,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[24] calldata pubSignals
    ) external onlyCoordinator returns (bool) {
        if (requestVerified[requestKey]) revert RequestAlreadyVerified(requestKey);

        (uint256 requestLo, uint256 requestHi) = _split(requestKey);
        if (
            pubSignals[IDX_REQUEST_LO] != requestLo ||
            pubSignals[IDX_REQUEST_HI] != requestHi
        ) revert RequestIdMismatch(requestKey);

        for (uint256 index = 0; index < pubSignals.length; index++) {
            if (pubSignals[index] >= SCALAR_FIELD) revert FieldOverflow(index);
        }

        uint256 reservedCost = pubSignals[IDX_RESERVED];
        uint256 actualCost = pubSignals[IDX_ACTUAL];
        if (actualCost == 0 || actualCost > reservedCost) revert InvalidPrivacyCost();

        uint256 nullifier = pubSignals[IDX_NULLIFIER];
        if (nullifier == 0 || nullifierUsed[nullifier]) {
            revert NullifierAlreadyUsed(nullifier);
        }
        if (!verifier.verifyProof(a, b, c, pubSignals)) {
            revert InvalidProof(requestKey);
        }

        nullifierUsed[nullifier] = true;
        requestVerified[requestKey] = true;
        emit ComplianceVerified(
            requestKey,
            nullifier,
            reservedCost,
            actualCost,
            pubSignals[IDX_RESULT],
            pubSignals[IDX_AUDIT]
        );
        return true;
    }

    function _split(bytes32 value) private pure returns (uint256 lo, uint256 hi) {
        uint256 integer = uint256(value);
        lo = uint128(integer);
        hi = integer >> 128;
    }
}
