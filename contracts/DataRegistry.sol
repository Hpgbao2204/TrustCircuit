// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract DataRegistry {
    uint256 public constant SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    struct Asset {
        address owner;
        bytes32 metadataHash;
        bytes32 dataHash;
        // Legacy SHA/Keccak policy digest retained for historical records.
        bytes32 policyHash;
        // Canonical VCP v2 Poseidon commitment. It is already an Fr element,
        // so no bytes32-to-field reduction occurs at settlement.
        uint256 policyCommitment;
        uint64 policyVersion;
        bool active;
        bool vcpV2;
    }

    mapping(bytes32 => Asset) private assets;

    event AssetRegistered(
        bytes32 indexed assetId,
        address indexed owner,
        bytes32 metadataHash,
        bytes32 dataHash,
        bytes32 policyHash
    );
    event AssetContextBound(
        bytes32 indexed assetId,
        bytes32 indexed policyHash,
        uint64 policyVersion
    );
    event VCPPolicyBound(
        bytes32 indexed assetId,
        uint256 indexed policyCommitment,
        uint64 policyVersion
    );

    error AssetAlreadyExists(bytes32 assetId);
    error AssetNotFound(bytes32 assetId);
    error NotAssetOwner(bytes32 assetId, address caller);
    error InvalidPolicyVersion();
    error InvalidPolicyCommitment();

    function registerAsset(bytes32 assetId, bytes32 metadataHash, bytes32 dataHash, bytes32 policyHash) external {
        _registerAsset(assetId, metadataHash, dataHash, policyHash, 1);
    }

    function registerAssetV2(
        bytes32 assetId,
        bytes32 metadataHash,
        bytes32 dataHash,
        bytes32 policyHash,
        uint64 policyVersion
    ) external {
        if (policyVersion == 0) revert InvalidPolicyVersion();
        _registerAsset(assetId, metadataHash, dataHash, policyHash, policyVersion);
    }

    function registerAssetVCP(
        bytes32 assetId,
        bytes32 metadataHash,
        bytes32 dataHash,
        uint256 policyCommitment,
        uint64 policyVersion
    ) external {
        if (policyVersion == 0) revert InvalidPolicyVersion();
        if (policyCommitment == 0 || policyCommitment >= SCALAR_FIELD) {
            revert InvalidPolicyCommitment();
        }
        if (assets[assetId].owner != address(0)) revert AssetAlreadyExists(assetId);
        assets[assetId] = Asset({
            owner: msg.sender,
            metadataHash: metadataHash,
            dataHash: dataHash,
            policyHash: bytes32(policyCommitment),
            policyCommitment: policyCommitment,
            policyVersion: policyVersion,
            active: true,
            vcpV2: true
        });
        emit AssetRegistered(
            assetId,
            msg.sender,
            metadataHash,
            dataHash,
            bytes32(policyCommitment)
        );
        emit VCPPolicyBound(assetId, policyCommitment, policyVersion);
    }

    function _registerAsset(
        bytes32 assetId,
        bytes32 metadataHash,
        bytes32 dataHash,
        bytes32 policyHash,
        uint64 policyVersion
    ) private {
        if (assets[assetId].owner != address(0)) revert AssetAlreadyExists(assetId);

        assets[assetId] = Asset({
            owner: msg.sender,
            metadataHash: metadataHash,
            dataHash: dataHash,
            policyHash: policyHash,
            policyCommitment: 0,
            policyVersion: policyVersion,
            active: true,
            vcpV2: false
        });

        emit AssetRegistered(assetId, msg.sender, metadataHash, dataHash, policyHash);
        emit AssetContextBound(assetId, policyHash, policyVersion);
    }

    function getAsset(bytes32 assetId) external view returns (Asset memory) {
        Asset memory asset = assets[assetId];
        if (asset.owner == address(0)) revert AssetNotFound(assetId);
        return asset;
    }

    function getAssetContext(bytes32 assetId)
        external
        view
        returns (
            address assetOwner,
            bytes32 dataHash,
            bytes32 policyHash,
            uint64 policyVersion,
            bool active
        )
    {
        Asset memory asset = assets[assetId];
        if (asset.owner == address(0)) revert AssetNotFound(assetId);
        return (
            asset.owner,
            asset.dataHash,
            asset.policyHash,
            asset.policyVersion,
            asset.active
        );
    }

    function requireOwner(bytes32 assetId, address caller) external view {
        Asset memory asset = assets[assetId];
        if (asset.owner == address(0)) revert AssetNotFound(assetId);
        if (asset.owner != caller) revert NotAssetOwner(assetId, caller);
    }
}
