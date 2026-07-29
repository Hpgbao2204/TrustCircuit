// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract MockVCPGroth16Verifier {
    bool public accepted = true;

    function setAccepted(bool value) external {
        accepted = value;
    }

    function verifyProof(
        uint256[2] calldata,
        uint256[2][2] calldata,
        uint256[2] calldata,
        uint256[24] calldata
    ) external view returns (bool) {
        return accepted;
    }
}
