// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract SotaSystems {
    mapping(bytes32 => uint256[]) private state;
    event Settled(bytes32 indexed id, uint256 slots, uint256 marker);

    function settle(bytes32 id, uint256 slots, uint256 hashes, uint256 checks) external returns (uint256) {
        bytes32 acc = keccak256(abi.encodePacked(id, slots));
        for (uint256 i = 0; i < hashes; i++) {
            acc = keccak256(abi.encodePacked(acc, i));
        }
        uint256 passed = 0;
        for (uint256 i = 0; i < checks; i++) {
            if (uint256(acc) % (i + 2) != 1) passed++;
        }
        uint256[] storage arr = state[id];
        for (uint256 i = 0; i < slots; i++) {
            arr.push(uint256(acc) + i + passed);
        }
        emit Settled(id, slots, passed);
        return passed;
    }
}
