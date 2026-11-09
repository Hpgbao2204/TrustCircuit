// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ComplianceVerifier.sol";
import "./SettlementCore.sol";

/// @notice Atomic settlement for the VCP relation.
/// Every bytes32 public value is matched as two uint128 limbs without modular
/// reduction. Native evidence validation remains off-chain; a k-of-n validator
/// quorum, the arithmetic context, expiry, Groth16 proof, ledger-computed RDP
/// charge, nullifier, request terminal state, and audit insertion are checked
/// or applied in one EVM transaction.
contract TrustCircuitSettlement is SettlementCore {
    ComplianceVerifier public immutable complianceVerifier;

    constructor(
        address registryAddress,
        address accessAddress,
        address budgetAddress,
        address complianceAddress,
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
    {
        if (complianceAddress == address(0)) revert ZeroDependency();
        complianceVerifier = ComplianceVerifier(complianceAddress);
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
            _checkCurrentState(requestKey, pubSignals);
        bytes32 attestationHash = _checkEvidence(evidence, pubSignals);
        complianceVerifier.submitCompliance(requestKey, a, b, c, pubSignals);
        _finalize(requestKey, request, attestationHash, pubSignals);
        return true;
    }
}
