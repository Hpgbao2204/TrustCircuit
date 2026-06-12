// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * SotaSystems reproduces a *representative per-access on-chain workflow* for
 * each related-work system class, so their EVM settlement cost can be measured
 * and decomposed under the identical compiler/network configuration as
 * TrustCircuit. Rather than three identical primitives, each system is
 * calibrated to the on-chain operations described in its paper via a profile
 * (persistent slots written, in-circuit hashes, policy comparisons). This
 * yields a differentiated, reproducible gas gradient instead of a flat bar.
 *
 * The cost decomposes into:
 *   storage settlement  - cold SSTOREs that persist the system's on-chain state,
 *   protocol logic      - keccak commitments and policy evaluation,
 *   proof verification   - measured separately for ZK systems (Groth16 verify).
 *
 * settle(id, slots, hashes, checks) writes `slots` cold storage words, performs
 * `hashes` keccak rounds, and `checks` policy comparisons, emitting one event.
 */
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
