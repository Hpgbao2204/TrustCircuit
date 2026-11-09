// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal k-of-n multisignature account with a timelock. It owns
/// registry governance (validator activation and revocation, threshold changes,
/// coordinator roles) so that no single key can admit a rogue validator, and
/// every change is visible for `delay` seconds before it takes effect.
contract TimelockMultisig {
    struct Proposal {
        address target;
        bytes data;
        uint64 eta;
        uint32 approvals;
        bool executed;
    }

    mapping(address => bool) public isOwner;
    address[] public owners;
    uint256 public immutable threshold;
    uint256 public immutable delay;
    Proposal[] private proposals;
    mapping(uint256 => mapping(address => bool)) public approved;

    event Proposed(uint256 indexed id, address indexed proposer, address target, uint64 eta);
    event Approved(uint256 indexed id, address indexed owner, uint32 approvals);
    event Executed(uint256 indexed id);

    error NotOwner();
    error InvalidConfiguration();
    error AlreadyApproved();
    error UnknownProposal();
    error AlreadyExecuted();
    error NotEnoughApprovals(uint256 approvals, uint256 required);
    error TimelockActive(uint256 eta);
    error CallFailed(bytes reason);

    constructor(address[] memory owners_, uint256 threshold_, uint256 delay_) {
        if (threshold_ == 0 || threshold_ > owners_.length) revert InvalidConfiguration();
        for (uint256 i = 0; i < owners_.length; i++) {
            address owner = owners_[i];
            if (owner == address(0) || isOwner[owner]) revert InvalidConfiguration();
            isOwner[owner] = true;
            owners.push(owner);
        }
        threshold = threshold_;
        delay = delay_;
    }

    modifier onlyOwner() {
        if (!isOwner[msg.sender]) revert NotOwner();
        _;
    }

    function propose(address target, bytes calldata data) external onlyOwner returns (uint256 id) {
        id = proposals.length;
        uint64 eta = uint64(block.timestamp + delay);
        proposals.push(Proposal(target, data, eta, 1, false));
        approved[id][msg.sender] = true;
        emit Proposed(id, msg.sender, target, eta);
        emit Approved(id, msg.sender, 1);
    }

    function approve(uint256 id) external onlyOwner {
        if (id >= proposals.length) revert UnknownProposal();
        if (approved[id][msg.sender]) revert AlreadyApproved();
        approved[id][msg.sender] = true;
        Proposal storage proposal = proposals[id];
        proposal.approvals += 1;
        emit Approved(id, msg.sender, proposal.approvals);
    }

    function execute(uint256 id) external onlyOwner returns (bytes memory result) {
        if (id >= proposals.length) revert UnknownProposal();
        Proposal storage proposal = proposals[id];
        if (proposal.executed) revert AlreadyExecuted();
        if (proposal.approvals < threshold) {
            revert NotEnoughApprovals(proposal.approvals, threshold);
        }
        if (block.timestamp < proposal.eta) revert TimelockActive(proposal.eta);
        proposal.executed = true;
        bool ok;
        (ok, result) = proposal.target.call(proposal.data);
        if (!ok) revert CallFailed(result);
        emit Executed(id);
    }

    function proposalCount() external view returns (uint256) {
        return proposals.length;
    }

    function getProposal(uint256 id) external view returns (Proposal memory) {
        return proposals[id];
    }
}
