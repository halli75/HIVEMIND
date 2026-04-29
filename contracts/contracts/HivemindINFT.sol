// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HivemindINFT
/// @notice Minimal ERC-7857 iNFT for HIVEMIND - records the winning agent with
/// encrypted strategy on 0G Storage. Implements ERC-7857 transfer/clone/authorizeUsage
/// at hackathon level (proof arg accepted; TEE/ZKP verification deferred).
contract HivemindINFT {
    struct IntelligenceRef {
        string storageUri;
        bytes32 storageHash;
        string model;
        string strategyDigest;
        uint64 aiq;
        uint64 mintedAt;
    }

    string public constant name = "HIVEMIND iNFT";
    string public constant symbol = "HIVEAI";

    address public immutable minter;
    uint256 public nextTokenId = 1;

    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => IntelligenceRef) private _intelligenceRefs;
    mapping(uint256 => mapping(address => bool)) private _authorizations;

    // ERC-721-like events
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event AgentCrystallized(
        uint256 indexed tokenId,
        address indexed owner,
        string storageUri,
        bytes32 storageHash,
        string model,
        uint64 aiq
    );
    event IntelligenceRefUpdated(
        uint256 indexed tokenId,
        string storageUri,
        bytes32 storageHash,
        string strategyDigest,
        uint64 aiq
    );

    // ERC-7857 events
    event MetadataUpdated(uint256 indexed tokenId, bytes32 newHash);
    event PublishedSealedKey(uint256 indexed tokenId, bytes sealedKey);
    event UsageAuthorized(uint256 indexed tokenId, address indexed executor);

    error NotMinter();
    error NotTokenOwner();
    error TokenDoesNotExist();
    error InvalidRecipient();
    error EmptyStorageUri();

    constructor(address initialMinter) {
        if (initialMinter == address(0)) revert InvalidRecipient();
        minter = initialMinter;
    }

    // -------------------------------------------------------------------------
    // Core mint (HIVEMIND entry point)
    // -------------------------------------------------------------------------

    function mintAgent(
        address to,
        string calldata storageUri,
        bytes32 storageHash,
        string calldata model,
        string calldata strategyDigest,
        uint64 aiq
    ) external returns (uint256 tokenId) {
        if (msg.sender != minter) revert NotMinter();
        if (to == address(0)) revert InvalidRecipient();
        if (bytes(storageUri).length == 0) revert EmptyStorageUri();

        tokenId = nextTokenId++;
        _owners[tokenId] = to;
        _balances[to] += 1;
        _intelligenceRefs[tokenId] = IntelligenceRef({
            storageUri: storageUri,
            storageHash: storageHash,
            model: model,
            strategyDigest: strategyDigest,
            aiq: aiq,
            mintedAt: uint64(block.timestamp)
        });

        emit Transfer(address(0), to, tokenId);
        emit AgentCrystallized(tokenId, to, storageUri, storageHash, model, aiq);
        emit MetadataUpdated(tokenId, storageHash);
    }

    // -------------------------------------------------------------------------
    // ERC-7857 functions
    // -------------------------------------------------------------------------

    /// @notice Transfer token with sealed key re-encryption proof.
    /// proof arg is accepted for interface compliance; TEE/ZKP verification is deferred.
    function transfer(
        address from,
        address to,
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata /*proof*/
    ) external {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        if (msg.sender != from) revert NotTokenOwner();
        if (_owners[tokenId] != from) revert NotTokenOwner();
        if (to == address(0)) revert InvalidRecipient();

        _owners[tokenId] = to;
        _balances[from] -= 1;
        _balances[to] += 1;

        emit Transfer(from, to, tokenId);
        emit PublishedSealedKey(tokenId, sealedKey);
    }

    /// @notice Clone token to a new recipient with sealed key.
    function clone(
        address to,
        uint256 tokenId,
        bytes calldata sealedKey,
        bytes calldata /*proof*/
    ) external returns (uint256 newTokenId) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        if (_owners[tokenId] != msg.sender) revert NotTokenOwner();
        if (to == address(0)) revert InvalidRecipient();

        newTokenId = nextTokenId++;
        _owners[newTokenId] = to;
        _balances[to] += 1;
        _intelligenceRefs[newTokenId] = _intelligenceRefs[tokenId];

        emit Transfer(address(0), to, newTokenId);
        emit MetadataUpdated(newTokenId, _intelligenceRefs[newTokenId].storageHash);
        emit PublishedSealedKey(newTokenId, sealedKey);
    }

    /// @notice Grant usage permission to an executor without ownership transfer.
    function authorizeUsage(
        uint256 tokenId,
        address executor,
        bytes calldata /*permissions*/
    ) external {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        if (_owners[tokenId] != msg.sender) revert NotTokenOwner();

        _authorizations[tokenId][executor] = true;
        emit UsageAuthorized(tokenId, executor);
    }

    // -------------------------------------------------------------------------
    // Existing write functions
    // -------------------------------------------------------------------------

    function updateIntelligenceRef(
        uint256 tokenId,
        string calldata storageUri,
        bytes32 storageHash,
        string calldata strategyDigest,
        uint64 aiq
    ) external {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        if (msg.sender != _owners[tokenId]) revert NotTokenOwner();
        if (bytes(storageUri).length == 0) revert EmptyStorageUri();

        IntelligenceRef storage ref = _intelligenceRefs[tokenId];
        ref.storageUri = storageUri;
        ref.storageHash = storageHash;
        ref.strategyDigest = strategyDigest;
        ref.aiq = aiq;

        emit IntelligenceRefUpdated(tokenId, storageUri, storageHash, strategyDigest, aiq);
        emit MetadataUpdated(tokenId, storageHash);
    }

    // -------------------------------------------------------------------------
    // Read functions
    // -------------------------------------------------------------------------

    function ownerOf(uint256 tokenId) external view returns (address) {
        address owner = _owners[tokenId];
        if (owner == address(0)) revert TokenDoesNotExist();
        return owner;
    }

    function balanceOf(address owner) external view returns (uint256) {
        if (owner == address(0)) revert InvalidRecipient();
        return _balances[owner];
    }

    function intelligenceRef(uint256 tokenId) external view returns (IntelligenceRef memory) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        return _intelligenceRefs[tokenId];
    }

    function isAuthorized(uint256 tokenId, address user) external view returns (bool) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        return _authorizations[tokenId][user];
    }

    function tokenURI(uint256 tokenId) external view returns (string memory) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        return string.concat("hivemind://inft/", _toString(tokenId));
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    function _toString(uint256 value) private pure returns (string memory) {
        if (value == 0) {
            return "0";
        }

        uint256 temp = value;
        uint256 digits;
        while (temp != 0) {
            digits++;
            temp /= 10;
        }

        bytes memory buffer = new bytes(digits);
        while (value != 0) {
            digits -= 1;
            buffer[digits] = bytes1(uint8(48 + uint256(value % 10)));
            value /= 10;
        }

        return string(buffer);
    }
}
