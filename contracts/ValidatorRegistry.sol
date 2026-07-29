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

    mapping(bytes32 => ValidatorKey) private validators;

    event ValidatorActivated(bytes32 indexed validatorId, address indexed signer);
    event ValidatorRevoked(bytes32 indexed validatorId, address indexed signer);

    error InvalidValidatorId();
    error InvalidSigner();
    error ValidatorAlreadyActive(bytes32 validatorId);
    error ValidatorNotActive(bytes32 validatorId);
    error StaleAttestation(uint256 currentUnixMs, uint256 expiresAtUnixMs);
    error InvalidValidatorSignature(bytes32 validatorId);
    error InvalidSignatureLength();
    error InvalidSignatureS();
    error InvalidSignatureV();

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
