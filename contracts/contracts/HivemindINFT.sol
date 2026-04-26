// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HivemindINFT
/// @notice Minimal iNFT placeholder for mock/testnet demos. It records the winning
/// agent owner plus immutable-looking storage and intelligence references, but it is
/// not a production ERC-721 implementation.
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

    error NotMinter();
    error NotTokenOwner();
    error TokenDoesNotExist();
    error InvalidRecipient();
    error EmptyStorageUri();

    constructor(address initialMinter) {
        if (initialMinter == address(0)) revert InvalidRecipient();
        minter = initialMinter;
    }

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
    }

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
    }

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

    function tokenURI(uint256 tokenId) external view returns (string memory) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        return string.concat("hivemind://inft/", _toString(tokenId));
    }

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
