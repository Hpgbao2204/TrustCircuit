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
        bytes32 purposeHash;
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

    error RequestAlreadyExists(bytes32 requestId);
    error RequestNotFound(bytes32 requestId);
    error InvalidRequestState(bytes32 requestId, RequestStatus status);
    error InvalidAmount();

    function requestAccess(bytes32 requestId, bytes32 assetId, bytes32 purposeHash, uint256 epsilonRequested) external {
        if (epsilonRequested == 0) revert InvalidAmount();
        if (requests[requestId].status != RequestStatus.None) revert RequestAlreadyExists(requestId);

        requests[requestId] = AccessRequest({
            assetId: assetId,
            consumer: msg.sender,
            purposeHash: purposeHash,
            epsilonRequested: epsilonRequested,
            status: RequestStatus.Pending
        });

        emit AccessRequested(requestId, assetId, msg.sender, purposeHash, epsilonRequested);
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

    function _requestOf(bytes32 requestId) private view returns (AccessRequest storage accessRequest) {
        accessRequest = requests[requestId];
        if (accessRequest.status == RequestStatus.None) revert RequestNotFound(requestId);
    }
}
