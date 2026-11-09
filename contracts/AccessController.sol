// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./LifecycleRoles.sol";

contract AccessController is LifecycleRoles {
    enum RequestStatus {
        None,
        Requested,
        Authorized,
        Rejected,
        Reserved,
        Consumed,
        Released
    }

    struct AccessRequest {
        bytes32 assetId;
        address consumer;
        // Legacy field retained only for decoding historical request records.
        uint256 consumerIdField;
        bytes32 consumerId;
        bytes32 purposeHash;
        uint32 purposeId;
        uint256 policyCommitment;
        uint64 policyVersion;
        uint32 functionId;
        bytes32 dpConfigHash;
        bytes32 freshnessNonce;
        uint256 epsilonRequested;
        uint64 deadlineUnixMs;
        RequestStatus status;
        bool vcpV2;
        // Public Gaussian-mechanism parameters charged on-chain.
        uint64 sigmaFixed;
        uint64 sensitivityFixed;
        bool rdp;
    }

    /// @notice Request with ledger-enforced RDP accounting (VCP v3). The DP
    /// configuration commitment theta_h is derived here from the public
    /// mechanism parameters, so the attested context binds the charged noise.
    struct RdpRequest {
        bytes32 requestId;
        bytes32 assetId;
        bytes32 consumerId;
        bytes32 purposeHash;
        uint32 purposeId;
        uint256 policyCommitment;
        uint64 policyVersion;
        uint32 functionId;
        uint64 sigmaFixed;
        uint64 sensitivityFixed;
        bytes32 mechanismHash;
        bytes32 freshnessNonce;
        uint64 deadlineUnixMs;
    }

    bytes32 public constant DP_CONFIG_TYPEHASH = keccak256(
        "TrustCircuitRdpConfig(uint64 sigmaFixed,uint64 sensitivityFixed,bytes32 mechanismHash)"
    );

    mapping(bytes32 => AccessRequest) private requests;

    event AccessRequested(
        bytes32 indexed requestId,
        bytes32 indexed assetId,
        address indexed consumer,
        bytes32 purposeHash,
        uint256 epsilonRequested
    );
    event AccessApproved(bytes32 indexed requestId, bytes32 indexed assetId);
    event AccessRejected(bytes32 indexed requestId, bytes32 indexed assetId, bytes32 reasonHash);
    event AccessReserved(bytes32 indexed requestId, bytes32 indexed assetId);
    event AccessCompleted(bytes32 indexed requestId, bytes32 indexed assetId);
    event AccessReleased(bytes32 indexed requestId, bytes32 indexed assetId);
    event AccessContextBound(
        bytes32 indexed requestId,
        bytes32 indexed consumerId,
        uint256 policyCommitment,
        uint64 policyVersion,
        uint32 purposeId,
        uint32 functionId,
        bytes32 dpConfigHash,
        bytes32 freshnessNonce,
        uint64 deadlineUnixMs
    );

    error RequestAlreadyExists(bytes32 requestId);
    error RequestNotFound(bytes32 requestId);
    error InvalidRequestState(bytes32 requestId, RequestStatus status);
    error InvalidAmount();
    error InvalidConsumerId();
    error InvalidPolicyCommitment();
    error InvalidPolicyVersion();
    error InvalidPurposeId();
    error InvalidFunctionId();
    error InvalidDeadline();

    /// @dev Legacy request entrypoint retained for historical benchmark scripts.
    function requestAccess(
        bytes32 requestId,
        bytes32 assetId,
        bytes32 purposeHash,
        uint256 epsilonRequested
    ) external {
        _requireNew(requestId, epsilonRequested);
        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            consumerIdField: uint256(uint160(msg.sender)),
            consumerId: bytes32(uint256(uint160(msg.sender))),
            purposeHash: purposeHash,
            purposeId: 0,
            policyCommitment: 0,
            policyVersion: 1,
            functionId: 0,
            dpConfigHash: bytes32(0),
            freshnessNonce: bytes32(0),
            epsilonRequested: epsilonRequested,
            deadlineUnixMs: type(uint64).max,
            status: RequestStatus.Requested,
            vcpV2: false,
            sigmaFixed: 0,
            sensitivityFixed: 0,
            rdp: false
        });
        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
    }

    /// @dev Legacy Phase-7 entrypoint. New deployments should use requestAccessVCP.
    function requestAccessV2(
        bytes32 requestId,
        bytes32 assetId,
        uint256 consumerIdField,
        bytes32 purposeHash,
        bytes32 policyHash,
        uint64 policyVersion,
        uint32 functionId,
        uint256 epsilonRequested
    ) external {
        _requireNew(requestId, epsilonRequested);
        if (consumerIdField == 0) revert InvalidConsumerId();
        if (policyVersion == 0) revert InvalidPolicyVersion();
        if (functionId == 0) revert InvalidFunctionId();
        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            consumerIdField: consumerIdField,
            consumerId: bytes32(consumerIdField),
            purposeHash: purposeHash,
            purposeId: 0,
            policyCommitment: uint256(policyHash),
            policyVersion: policyVersion,
            functionId: functionId,
            dpConfigHash: bytes32(0),
            freshnessNonce: bytes32(0),
            epsilonRequested: epsilonRequested,
            deadlineUnixMs: type(uint64).max,
            status: RequestStatus.Requested,
            vcpV2: false,
            sigmaFixed: 0,
            sensitivityFixed: 0,
            rdp: false
        });
        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
    }

    function requestAccessVCP(
        bytes32 requestId,
        bytes32 assetId,
        bytes32 consumerId,
        bytes32 purposeHash,
        uint32 purposeId,
        uint256 policyCommitment,
        uint64 policyVersion,
        uint32 functionId,
        bytes32 dpConfigHash,
        bytes32 freshnessNonce,
        uint256 epsilonRequested,
        uint64 deadlineUnixMs
    ) external {
        _requireNew(requestId, epsilonRequested);
        if (consumerId == bytes32(0)) revert InvalidConsumerId();
        if (policyCommitment == 0) revert InvalidPolicyCommitment();
        if (policyVersion == 0) revert InvalidPolicyVersion();
        if (purposeId == 0) revert InvalidPurposeId();
        if (functionId == 0) revert InvalidFunctionId();
        if (deadlineUnixMs <= block.timestamp * 1000) revert InvalidDeadline();

        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            consumerIdField: 0,
            consumerId: consumerId,
            purposeHash: purposeHash,
            purposeId: purposeId,
            policyCommitment: policyCommitment,
            policyVersion: policyVersion,
            functionId: functionId,
            dpConfigHash: dpConfigHash,
            freshnessNonce: freshnessNonce,
            epsilonRequested: epsilonRequested,
            deadlineUnixMs: deadlineUnixMs,
            status: RequestStatus.Requested,
            vcpV2: true,
            sigmaFixed: 0,
            sensitivityFixed: 0,
            rdp: false
        });
        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
        emit AccessContextBound(
            requestId,
            consumerId,
            policyCommitment,
            policyVersion,
            purposeId,
            functionId,
            dpConfigHash,
            freshnessNonce,
            deadlineUnixMs
        );
    }

    function requestAccessRDP(RdpRequest calldata r) external {
        if (r.requestId == bytes32(0)) revert RequestNotFound(r.requestId);
        if (requests[r.requestId].status != RequestStatus.None) {
            revert RequestAlreadyExists(r.requestId);
        }
        if (r.consumerId == bytes32(0)) revert InvalidConsumerId();
        if (r.policyCommitment == 0) revert InvalidPolicyCommitment();
        if (r.policyVersion == 0) revert InvalidPolicyVersion();
        if (r.purposeId == 0) revert InvalidPurposeId();
        if (r.functionId == 0) revert InvalidFunctionId();
        if (r.sigmaFixed == 0 || r.sensitivityFixed == 0) revert InvalidAmount();
        if (r.deadlineUnixMs <= block.timestamp * 1000) revert InvalidDeadline();

        bytes32 dpConfigHash = rdpConfigHash(r.sigmaFixed, r.sensitivityFixed, r.mechanismHash);
        AccessRequest storage stored = requests[r.requestId];
        stored.assetId = r.assetId;
        stored.consumer = msg.sender;
        stored.consumerId = r.consumerId;
        stored.purposeHash = r.purposeHash;
        stored.purposeId = r.purposeId;
        stored.policyCommitment = r.policyCommitment;
        stored.policyVersion = r.policyVersion;
        stored.functionId = r.functionId;
        stored.dpConfigHash = dpConfigHash;
        stored.freshnessNonce = r.freshnessNonce;
        stored.deadlineUnixMs = r.deadlineUnixMs;
        stored.status = RequestStatus.Requested;
        stored.vcpV2 = true;
        stored.sigmaFixed = r.sigmaFixed;
        stored.sensitivityFixed = r.sensitivityFixed;
        stored.rdp = true;
        emit AccessRequested(r.requestId, r.assetId, msg.sender, r.purposeHash, 0);
        emit AccessContextBound(
            r.requestId,
            r.consumerId,
            r.policyCommitment,
            r.policyVersion,
            r.purposeId,
            r.functionId,
            dpConfigHash,
            r.freshnessNonce,
            r.deadlineUnixMs
        );
    }

    function rdpConfigHash(uint64 sigmaFixed, uint64 sensitivityFixed, bytes32 mechanismHash)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(DP_CONFIG_TYPEHASH, sigmaFixed, sensitivityFixed, mechanismHash));
    }

    function approveRequest(bytes32 requestId) external onlyCoordinator {
        AccessRequest storage accessRequest = _requestOf(requestId);
        _requireState(requestId, accessRequest.status, RequestStatus.Requested);
        accessRequest.status = RequestStatus.Authorized;
        emit AccessApproved(requestId, accessRequest.assetId);
    }

    function rejectRequest(bytes32 requestId, bytes32 reasonHash)
        external
        onlyCoordinator
    {
        AccessRequest storage accessRequest = _requestOf(requestId);
        _requireState(requestId, accessRequest.status, RequestStatus.Requested);
        accessRequest.status = RequestStatus.Rejected;
        emit AccessRejected(requestId, accessRequest.assetId, reasonHash);
    }

    function markReserved(bytes32 requestId) external onlyCoordinator {
        AccessRequest storage accessRequest = _requestOf(requestId);
        _requireState(requestId, accessRequest.status, RequestStatus.Authorized);
        accessRequest.status = RequestStatus.Reserved;
        emit AccessReserved(requestId, accessRequest.assetId);
    }

    function completeRequest(bytes32 requestId) external onlyCoordinator {
        AccessRequest storage accessRequest = _requestOf(requestId);
        _requireState(requestId, accessRequest.status, RequestStatus.Reserved);
        accessRequest.status = RequestStatus.Consumed;
        emit AccessCompleted(requestId, accessRequest.assetId);
    }

    function releaseRequest(bytes32 requestId) external onlyCoordinator {
        AccessRequest storage accessRequest = _requestOf(requestId);
        _requireState(requestId, accessRequest.status, RequestStatus.Reserved);
        accessRequest.status = RequestStatus.Released;
        emit AccessReleased(requestId, accessRequest.assetId);
    }

    function getRequest(bytes32 requestId) external view returns (AccessRequest memory) {
        return _requestOf(requestId);
    }

    function _requireNew(bytes32 requestId, uint256 epsilonRequested) private view {
        if (epsilonRequested == 0) revert InvalidAmount();
        if (requests[requestId].status != RequestStatus.None) {
            revert RequestAlreadyExists(requestId);
        }
    }

    function _requireState(
        bytes32 requestId,
        RequestStatus actual,
        RequestStatus expected
    ) private pure {
        if (actual != expected) revert InvalidRequestState(requestId, actual);
    }

    function _requestOf(bytes32 requestId)
        private
        view
        returns (AccessRequest storage accessRequest)
    {
        accessRequest = requests[requestId];
        if (accessRequest.status == RequestStatus.None) revert RequestNotFound(requestId);
    }
}
