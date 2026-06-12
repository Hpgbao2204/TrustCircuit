// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IGroth16Verifier
 * @notice Minimal interface to the snarkjs-exported Groth16 verifier
 *         (contracts/ComplianceGroth16Verifier.sol, contract Groth16Verifier).
 *         The public-signal arity (7) must match the compliance circuit
 *         (zk/circuits/compliance_check.circom).
 */
interface IGroth16Verifier {
    function verifyProof(
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[7] calldata pubSignals
    ) external view returns (bool);
}

/**
 * @title ComplianceVerifier
 * @notice On-chain adapter for the TrustCircuit Verifiable Compliance Protocol.
 *
 * This contract turns the standalone Groth16 verifier into a request-bound
 * compliance gate. It enforces, in one atomic transaction:
 *
 *   1. Public-input binding   - the proof's public signals must equal the
 *                               values the data owner registered for the
 *                               request (asset, consumer, request, policy).
 *   2. Budget ceiling         - the proven epsilon cost must not exceed the
 *                               fixed-point budget registered for the request.
 *   3. Nullifier replay guard - each proof nullifier can be consumed once.
 *   4. Cryptographic validity - the Groth16 proof must verify against the
 *                               exported verification key.
 *
 * Public-signal layout (must match the circuit's `public [...]` order):
 *   [0] assetId        [1] consumerId   [2] requestId   [3] policyHash
 *   [4] epsilonCost    [5] nullifier    [6] attestationHash
 *
 * Raw data, private witness, and unnoised outputs never touch this contract;
 * it only sees field-element commitments that the circuit has already bound.
 */
contract ComplianceVerifier {
    // ---- public-signal indices ----
    uint256 internal constant IDX_ASSET = 0;
    uint256 internal constant IDX_CONSUMER = 1;
    uint256 internal constant IDX_REQUEST = 2;
    uint256 internal constant IDX_POLICY = 3;
    uint256 internal constant IDX_EPSILON = 4;
    uint256 internal constant IDX_NULLIFIER = 5;
    uint256 internal constant IDX_ATTESTATION = 6;

    /// @notice BN254 scalar field modulus; every public signal must be reduced.
    uint256 internal constant SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    IGroth16Verifier public immutable verifier;
    address public owner;

    struct Expectation {
        uint256 assetId;
        uint256 consumerId;
        uint256 policyHash;
        uint256 maxEpsilon; // fixed-point (1e6) budget ceiling for this request
        bool registered;
        bool verified;
        uint256 epsilonUsed;
        uint256 nullifier;
        uint256 attestationHash;
    }

    /// @dev keyed by the on-chain requestId (bytes32). The uint256 request public
    ///      signal must equal uint256(requestId) reduced into the scalar field.
    mapping(bytes32 => Expectation) private expectations;
    /// @notice spent nullifiers across all requests (global replay guard).
    mapping(uint256 => bool) public nullifierUsed;

    event ExpectationRegistered(
        bytes32 indexed requestId,
        uint256 assetId,
        uint256 consumerId,
        uint256 policyHash,
        uint256 maxEpsilon
    );
    event ComplianceVerified(
        bytes32 indexed requestId,
        uint256 indexed nullifier,
        uint256 epsilonCost,
        uint256 attestationHash
    );

    error NotOwner();
    error ZeroVerifier();
    error AlreadyRegistered(bytes32 requestId);
    error NotRegistered(bytes32 requestId);
    error AlreadyVerified(bytes32 requestId);
    error FieldOverflow(uint256 index);
    error RequestIdMismatch(bytes32 requestId, uint256 signal);
    error PublicInputMismatch(uint256 index);
    error BudgetExceeded(uint256 epsilonCost, uint256 maxEpsilon);
    error NullifierAlreadyUsed(uint256 nullifier);
    error InvalidProof(bytes32 requestId);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address verifierAddress) {
        if (verifierAddress == address(0)) revert ZeroVerifier();
        verifier = IGroth16Verifier(verifierAddress);
        owner = msg.sender;
    }

    /**
     * @notice Register the expected compliance commitments for a request.
     * @dev Called by the data owner during negotiation, before any proof is
     *      submitted. `maxEpsilon` is the fixed-point (1e6) budget ceiling that
     *      the proven epsilon cost must respect.
     */
    function registerExpectation(
        bytes32 requestId,
        uint256 assetId,
        uint256 consumerId,
        uint256 policyHash,
        uint256 maxEpsilon
    ) external onlyOwner {
        if (expectations[requestId].registered) revert AlreadyRegistered(requestId);
        if (assetId >= SCALAR_FIELD) revert FieldOverflow(IDX_ASSET);
        if (consumerId >= SCALAR_FIELD) revert FieldOverflow(IDX_CONSUMER);
        if (policyHash >= SCALAR_FIELD) revert FieldOverflow(IDX_POLICY);

        expectations[requestId] = Expectation({
            assetId: assetId,
            consumerId: consumerId,
            policyHash: policyHash,
            maxEpsilon: maxEpsilon,
            registered: true,
            verified: false,
            epsilonUsed: 0,
            nullifier: 0,
            attestationHash: 0
        });

        emit ExpectationRegistered(requestId, assetId, consumerId, policyHash, maxEpsilon);
    }

    /**
     * @notice Submit a Groth16 compliance proof for a registered request.
     * @dev Performs public-input binding, budget-ceiling enforcement, nullifier
     *      replay protection, and cryptographic verification atomically. Reverts
     *      on any failed check; succeeds and records the proof otherwise.
     */
    function submitCompliance(
        bytes32 requestId,
        uint256[2] calldata a,
        uint256[2][2] calldata b,
        uint256[2] calldata c,
        uint256[7] calldata pubSignals
    ) external returns (bool) {
        Expectation storage exp = expectations[requestId];
        if (!exp.registered) revert NotRegistered(requestId);
        if (exp.verified) revert AlreadyVerified(requestId);

        // (1) public-input binding against the registered request commitments.
        if (pubSignals[IDX_REQUEST] != uint256(requestId) % SCALAR_FIELD) {
            revert RequestIdMismatch(requestId, pubSignals[IDX_REQUEST]);
        }
        if (pubSignals[IDX_ASSET] != exp.assetId) revert PublicInputMismatch(IDX_ASSET);
        if (pubSignals[IDX_CONSUMER] != exp.consumerId) revert PublicInputMismatch(IDX_CONSUMER);
        if (pubSignals[IDX_POLICY] != exp.policyHash) revert PublicInputMismatch(IDX_POLICY);

        // (2) budget ceiling: proven epsilon cost must fit the registered budget.
        uint256 epsilonCost = pubSignals[IDX_EPSILON];
        if (epsilonCost > exp.maxEpsilon) revert BudgetExceeded(epsilonCost, exp.maxEpsilon);

        // (3) replay guard: each nullifier is single-use across all requests.
        uint256 nullifier = pubSignals[IDX_NULLIFIER];
        if (nullifierUsed[nullifier]) revert NullifierAlreadyUsed(nullifier);

        // (4) cryptographic verification via the exported Groth16 verifier.
        if (!verifier.verifyProof(a, b, c, pubSignals)) revert InvalidProof(requestId);

        // commit state only after every check passes.
        nullifierUsed[nullifier] = true;
        exp.verified = true;
        exp.epsilonUsed = epsilonCost;
        exp.nullifier = nullifier;
        exp.attestationHash = pubSignals[IDX_ATTESTATION];

        emit ComplianceVerified(requestId, nullifier, epsilonCost, pubSignals[IDX_ATTESTATION]);
        return true;
    }

    function getExpectation(bytes32 requestId) external view returns (Expectation memory) {
        Expectation memory exp = expectations[requestId];
        if (!exp.registered) revert NotRegistered(requestId);
        return exp;
    }

    function isVerified(bytes32 requestId) external view returns (bool) {
        return expectations[requestId].verified;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }
}
