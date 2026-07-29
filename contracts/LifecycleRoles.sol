// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal role control shared by the request lifecycle modules.
/// The deployer is the initial owner and coordinator. A deployment must grant
/// coordinator status to TrustCircuitSettlement before transferring ownership.
abstract contract LifecycleRoles {
    address public owner;
    mapping(address => bool) public isCoordinator;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event CoordinatorUpdated(address indexed coordinator, bool active);

    error NotOwner();
    error NotCoordinator();
    error ZeroAddress();

    constructor() {
        owner = msg.sender;
        isCoordinator[msg.sender] = true;
        emit CoordinatorUpdated(msg.sender, true);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyCoordinator() {
        if (!isCoordinator[msg.sender]) revert NotCoordinator();
        _;
    }

    function setCoordinator(address coordinator, bool active) external onlyOwner {
        if (coordinator == address(0)) revert ZeroAddress();
        isCoordinator[coordinator] = active;
        emit CoordinatorUpdated(coordinator, active);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        address previousOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }
}
