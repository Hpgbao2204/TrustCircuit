// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract DataRegistry {
    struct Asset {
        address owner;
        bytes32 metadataHash;
        bytes32 dataHash;
        bytes32 policyHash;
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

    error AssetAlreadyExists(bytes32 assetId);
    error AssetNotFound(bytes32 assetId);
    error NotAssetOwner(bytes32 assetId, address caller);

    function registerAsset(bytes32 assetId, bytes32 metadataHash, bytes32 dataHash, bytes32 policyHash) external {
        if (assets[assetId].owner != address(0)) revert AssetAlreadyExists(assetId);

        assets[assetId] = Asset({
            owner: msg.sender,
            metadataHash: metadataHash,
            dataHash: dataHash,
            policyHash: policyHash,
            active: true
        });

        emit AssetRegistered(assetId, msg.sender, metadataHash, dataHash, policyHash);
    }

    function getAsset(bytes32 assetId) external view returns (Asset memory) {
        Asset memory asset = assets[assetId];
        if (asset.owner == address(0)) revert AssetNotFound(assetId);
        return asset;
    }

    function requireOwner(bytes32 assetId, address caller) external view {
        Asset memory asset = assets[assetId];
        if (asset.owner == address(0)) revert AssetNotFound(assetId);
        if (asset.owner != caller) revert NotAssetOwner(assetId, caller);
    }
}
