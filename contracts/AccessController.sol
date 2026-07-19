// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AccessController {
    enum RequestStatus {
        None,
        Pending,
        Approved,
        Rejected,
        Completed
    }

    struct AccessRequest {
        bytes32 assetId;
        address consumer;
        uint256 consumerIdField;
        bytes32 purposeHash;
        bytes32 policyHash;
        uint64 policyVersion;
        uint32 functionId;
        uint256 epsilonRequested;
        RequestStatus status;
    }

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
    event AccessCompleted(bytes32 indexed requestId, bytes32 indexed assetId);
    event AccessContextBound(
        bytes32 indexed requestId,
        uint256 consumerIdField,
        bytes32 policyHash,
        uint64 policyVersion,
        uint32 functionId
    );

    error RequestAlreadyExists(bytes32 requestId);
    error RequestNotFound(bytes32 requestId);
    error InvalidRequestState(bytes32 requestId, RequestStatus status);
    error InvalidAmount();
    error InvalidConsumerId();
    error InvalidPolicyVersion();
    error InvalidFunctionId();

    function requestAccess(bytes32 requestId, bytes32 assetId, bytes32 purposeHash, uint256 epsilonRequested) external {
        if (epsilonRequested == 0) revert InvalidAmount();
        if (requests[requestId].status != RequestStatus.None) revert RequestAlreadyExists(requestId);

        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            consumerIdField: uint256(uint160(msg.sender)),
            purposeHash: purposeHash,
            policyHash: bytes32(0),
            policyVersion: 1,
            functionId: 0,
            epsilonRequested: epsilonRequested,
            status: RequestStatus.Pending
        });

        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
    }

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
        if (epsilonRequested == 0) revert InvalidAmount();
        if (consumerIdField == 0) revert InvalidConsumerId();
        if (policyVersion == 0) revert InvalidPolicyVersion();
        if (functionId != 1 && functionId != 2) revert InvalidFunctionId();
        if (requests[requestId].status != RequestStatus.None) revert RequestAlreadyExists(requestId);

        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            consumerIdField: consumerIdField,
            purposeHash: purposeHash,
            policyHash: policyHash,
            policyVersion: policyVersion,
            functionId: functionId,
            epsilonRequested: epsilonRequested,
            status: RequestStatus.Pending
        });
        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
        emit AccessContextBound(
            requestId,
            consumerIdField,
            policyHash,
            policyVersion,
            functionId
        );
    }

    function approveRequest(bytes32 requestId) external {
        AccessRequest storage accessRequest = _requestOf(requestId);
        if (accessRequest.status != RequestStatus.Pending) {
            revert InvalidRequestState(requestId, accessRequest.status);
        }

        accessRequest.status = RequestStatus.Approved;
        emit AccessApproved(requestId, accessRequest.assetId);
    }

    function rejectRequest(bytes32 requestId, bytes32 reasonHash) external {
        AccessRequest storage accessRequest = _requestOf(requestId);
        if (accessRequest.status != RequestStatus.Pending) {
            revert InvalidRequestState(requestId, accessRequest.status);
        }

        accessRequest.status = RequestStatus.Rejected;
        emit AccessRejected(requestId, accessRequest.assetId, reasonHash);
    }

    function completeRequest(bytes32 requestId) external {
        AccessRequest storage accessRequest = _requestOf(requestId);
        if (accessRequest.status != RequestStatus.Approved) {
            revert InvalidRequestState(requestId, accessRequest.status);
        }

        accessRequest.status = RequestStatus.Completed;
        emit AccessCompleted(requestId, accessRequest.assetId);
    }

    function getRequest(bytes32 requestId) external view returns (AccessRequest memory) {
        return _requestOf(requestId);
    }

    function getRequestContext(bytes32 requestId)
        external
        view
        returns (
            bytes32 assetId,
            address consumer,
            uint256 consumerIdField,
            bytes32 policyHash,
            uint64 policyVersion,
            uint32 functionId,
            uint256 epsilonRequested,
            RequestStatus status
        )
    {
        AccessRequest storage accessRequest = _requestOf(requestId);
        return (
            accessRequest.assetId,
            accessRequest.consumer,
            accessRequest.consumerIdField,
            accessRequest.policyHash,
            accessRequest.policyVersion,
            accessRequest.functionId,
            accessRequest.epsilonRequested,
            accessRequest.status
        );
    }

    function _requestOf(bytes32 requestId) private view returns (AccessRequest storage accessRequest) {
        accessRequest = requests[requestId];
        if (accessRequest.status == RequestStatus.None) revert RequestNotFound(requestId);
    }
}
