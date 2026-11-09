// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SettlementCore.sol";

/// @notice Sign-and-hash settlement (SHS) comparison design.
/// It keeps every TrustCircuit contract guard, salted commitment, validator
/// quorum, ledger-computed RDP charge, nullifier uniqueness, and audit
/// insertion, but replaces the Groth16 proof by a validator-quorum signature
/// over the public statement x and the validators' own evaluation a_Pi of the
/// hidden policy. The contract cannot evaluate a hidden policy, so it accepts
/// whatever a compromised quorum signs (failure F4).
contract SignAndHashSettlement is SettlementCore {
    bytes32 public constant SHS_TYPEHASH = keccak256(
        "TrustCircuitSignAndHash(bytes32 statementHash,uint8 admissible)"
    );

    mapping(uint256 => bool) public nullifierUsed;

    error NotAdmissible();
    error NullifierAlreadyUsed(uint256 nullifier);

    constructor(
        address registryAddress,
        address accessAddress,
        address budgetAddress,
        address auditAddress,
        address validatorRegistryAddress
    )
        SettlementCore(
            registryAddress,
            accessAddress,
            budgetAddress,
            auditAddress,
            validatorRegistryAddress
        )
    {}

    function shsMessage(uint256[24] calldata pubSignals, uint8 admissible)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(SHS_TYPEHASH, keccak256(abi.encode(pubSignals)), admissible));
    }

    function settle(
        bytes32 requestKey,
        SettlementEvidence calldata evidence,
        uint256[24] calldata pubSignals,
        uint8 admissible,
        bytes32[] calldata shsValidatorIds,
        bytes[] calldata shsSignatures
    ) external returns (bool) {
        AccessController.AccessRequest memory request =
            _checkCurrentState(requestKey, pubSignals);
        bytes32 attestationHash = _checkEvidence(evidence, pubSignals);
        if (admissible != 1) revert NotAdmissible();
        validatorRegistry.requireQuorumOn(
            shsMessage(pubSignals, admissible),
            shsValidatorIds,
            shsSignatures
        );
        uint256 nullifier = pubSignals[IDX_NULLIFIER];
        if (nullifier == 0 || nullifierUsed[nullifier]) revert NullifierAlreadyUsed(nullifier);
        nullifierUsed[nullifier] = true;
        _finalize(requestKey, request, attestationHash, pubSignals);
        return true;
    }
}
