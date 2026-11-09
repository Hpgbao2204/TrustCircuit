// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./LifecycleRoles.sol";

/// @notice Authorized ECDSA validator keys for canonical attestation statements.
/// Native platform evidence remains off-chain. This registry authenticates the
/// validator's compact bridge statement, its arithmetic context, and expiry.
contract ValidatorRegistry is LifecycleRoles {
    bytes32 public constant ATTESTATION_TYPEHASH = keccak256(
        "TrustCircuitValidatedAttestation(bytes32 validatorId,bytes32 nativeDigest,uint256 contextCommitment,uint64 expiresAtUnixMs,uint256 chainId,address registry)"
    );
    uint256 private constant SECP256K1_HALF_N =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    struct ValidatorKey {
        address signer;
        uint64 activatedAt;
        uint64 revokedAt;
        bool active;
    }

    struct ValidatedAttestation {
        bytes32 validatorId;
        bytes32 nativeDigest;
        uint256 contextCommitment;
        uint64 expiresAtUnixMs;
        bytes signature;
    }

    /// @notice k-of-n validator statement. Every listed
    /// validator signs its own payload over the same native digest, arithmetic
    /// context, and expiry; ids must be strictly increasing, so they are distinct.
    struct QuorumAttestation {
        bytes32 nativeDigest;
        uint256 contextCommitment;
        uint64 expiresAtUnixMs;
        bytes32[] validatorIds;
        bytes[] signatures;
    }

    mapping(bytes32 => ValidatorKey) private validators;
    /// @notice Number k of distinct active validator signatures a statement needs.
    uint256 public threshold = 1;

    event ValidatorActivated(bytes32 indexed validatorId, address indexed signer);
    event ValidatorRevoked(bytes32 indexed validatorId, address indexed signer);
    event ThresholdUpdated(uint256 threshold);

    error InvalidValidatorId();
    error InvalidSigner();
    error ValidatorAlreadyActive(bytes32 validatorId);
    error ValidatorNotActive(bytes32 validatorId);
    error StaleAttestation(uint256 currentUnixMs, uint256 expiresAtUnixMs);
    error InvalidValidatorSignature(bytes32 validatorId);
    error InvalidSignatureLength();
    error InvalidSignatureS();
    error InvalidSignatureV();
    error InvalidThreshold();
    error QuorumNotReached(uint256 provided, uint256 required);
    error ValidatorOrder(uint256 index);
    error LengthMismatch();

    function setThreshold(uint256 newThreshold) external onlyOwner {
        if (newThreshold == 0) revert InvalidThreshold();
        threshold = newThreshold;
        emit ThresholdUpdated(newThreshold);
    }

    function activateValidator(bytes32 validatorId, address signer) external onlyOwner {
        if (validatorId == bytes32(0)) revert InvalidValidatorId();
        if (signer == address(0)) revert InvalidSigner();
        if (validators[validatorId].active) revert ValidatorAlreadyActive(validatorId);
        validators[validatorId] = ValidatorKey({
            signer: signer,
            activatedAt: uint64(block.timestamp),
            revokedAt: 0,
            active: true
        });
        emit ValidatorActivated(validatorId, signer);
    }

    function revokeValidator(bytes32 validatorId) external onlyOwner {
        ValidatorKey storage validator = validators[validatorId];
        if (!validator.active) revert ValidatorNotActive(validatorId);
        validator.active = false;
        validator.revokedAt = uint64(block.timestamp);
        emit ValidatorRevoked(validatorId, validator.signer);
    }

    function getValidator(bytes32 validatorId) external view returns (ValidatorKey memory) {
        return validators[validatorId];
    }

    function statementPayload(ValidatedAttestation calldata statement)
        public
        view
        returns (bytes32)
    {
        return keccak256(
            abi.encode(
                ATTESTATION_TYPEHASH,
                statement.validatorId,
                statement.nativeDigest,
                statement.contextCommitment,
                statement.expiresAtUnixMs,
                block.chainid,
                address(this)
            )
        );
    }

    function statementDigest(ValidatedAttestation calldata statement)
        public
        view
        returns (bytes32)
    {
        return keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                statementPayload(statement)
            )
        );
    }

    function statementHash(ValidatedAttestation calldata statement)
        public
        pure
        returns (bytes32)
    {
        return keccak256(
            abi.encode(
                statement.validatorId,
                statement.nativeDigest,
                statement.contextCommitment,
                statement.expiresAtUnixMs,
                statement.signature
            )
        );
    }

    function requireValid(ValidatedAttestation calldata statement)
        external
        view
        returns (address signer)
    {
        ValidatorKey memory validator = validators[statement.validatorId];
        if (!validator.active) revert ValidatorNotActive(statement.validatorId);
        uint256 currentUnixMs = block.timestamp * 1000;
        if (currentUnixMs > statement.expiresAtUnixMs) {
            revert StaleAttestation(currentUnixMs, statement.expiresAtUnixMs);
        }
        signer = _recover(statementDigest(statement), statement.signature);
        if (signer != validator.signer) {
            revert InvalidValidatorSignature(statement.validatorId);
        }
    }

    /// @notice Per-validator payload of a quorum statement. It has the same
    /// layout as statementPayload, so a k = 1 quorum signs the v2 message.
    function quorumPayload(
        bytes32 validatorId,
        bytes32 nativeDigest,
        uint256 contextCommitment,
        uint64 expiresAtUnixMs
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                ATTESTATION_TYPEHASH,
                validatorId,
                nativeDigest,
                contextCommitment,
                expiresAtUnixMs,
                block.chainid,
                address(this)
            )
        );
    }

    /// @notice Audit commitment ah of a quorum statement (public VCP input).
    function quorumHash(QuorumAttestation calldata statement)
        external
        pure
        returns (bytes32)
    {
        return keccak256(
            abi.encode(
                statement.nativeDigest,
                statement.contextCommitment,
                statement.expiresAtUnixMs,
                statement.validatorIds,
                statement.signatures
            )
        );
    }

    /// @notice Requires at least `threshold` distinct, currently active
    /// validators to have signed the statement before it expires.
    function requireQuorum(QuorumAttestation calldata statement) external view {
        uint256 currentUnixMs = block.timestamp * 1000;
        if (currentUnixMs > statement.expiresAtUnixMs) {
            revert StaleAttestation(currentUnixMs, statement.expiresAtUnixMs);
        }
        uint256 count = statement.validatorIds.length;
        if (count != statement.signatures.length) revert LengthMismatch();
        for (uint256 i = 0; i < count; i++) {
            bytes32 validatorId = statement.validatorIds[i];
            if (i > 0 && uint256(validatorId) <= uint256(statement.validatorIds[i - 1])) {
                revert ValidatorOrder(i);
            }
            bytes32 payload = quorumPayload(
                validatorId,
                statement.nativeDigest,
                statement.contextCommitment,
                statement.expiresAtUnixMs
            );
            _requireSigned(validatorId, payload, statement.signatures[i]);
        }
        if (count < threshold) revert QuorumNotReached(count, threshold);
    }

    /// @notice Generic k-of-n check over an arbitrary message, used by the
    /// sign-and-hash and stage-wise comparison designs. Validator i signs
    /// keccak256(abi.encode(message, validatorId, chainId, registry)).
    function requireQuorumOn(
        bytes32 message,
        bytes32[] calldata validatorIds,
        bytes[] calldata signatures
    ) external view {
        uint256 count = validatorIds.length;
        if (count != signatures.length) revert LengthMismatch();
        for (uint256 i = 0; i < count; i++) {
            if (i > 0 && uint256(validatorIds[i]) <= uint256(validatorIds[i - 1])) {
                revert ValidatorOrder(i);
            }
            bytes32 payload = keccak256(
                abi.encode(message, validatorIds[i], block.chainid, address(this))
            );
            _requireSigned(validatorIds[i], payload, signatures[i]);
        }
        if (count < threshold) revert QuorumNotReached(count, threshold);
    }

    function _requireSigned(bytes32 validatorId, bytes32 payload, bytes calldata signature)
        private
        view
    {
        ValidatorKey memory validator = validators[validatorId];
        if (!validator.active) revert ValidatorNotActive(validatorId);
        bytes32 digest = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", payload)
        );
        if (_recover(digest, signature) != validator.signer) {
            revert InvalidValidatorSignature(validatorId);
        }
    }

    function _recover(bytes32 digest, bytes calldata signature)
        private
        pure
        returns (address signer)
    {
        if (signature.length != 65) revert InvalidSignatureLength();
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) > SECP256K1_HALF_N) revert InvalidSignatureS();
        if (v != 27 && v != 28) revert InvalidSignatureV();
        signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert InvalidValidatorSignature(bytes32(0));
    }
}
