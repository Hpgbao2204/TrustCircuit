// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract DataRegistry {
    struct Asset {
        address owner;
        bytes32 metadataHash;
        bytes32 dataHash;
        bytes32 policyHash;
        uint64 policyVersion;
        bool active;
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

    error AssetAlreadyExists(bytes32 assetId);
    error AssetNotFound(bytes32 assetId);
    error NotAssetOwner(bytes32 assetId, address caller);
    error InvalidPolicyVersion();

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
            policyVersion: policyVersion,
            active: true
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
