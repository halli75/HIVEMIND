// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HivemindINFT
/// @notice Minimal ERC-721-compatible iNFT for HIVEMIND - records the winning
/// agent with encrypted strategy on 0G Storage. Keeps ERC-7857-style
/// transfer/clone/authorizeUsage hooks at hackathon level (proof arg accepted;
/// TEE/ZKP verification deferred).
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
    mapping(uint256 => address) private _tokenApprovals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    mapping(uint256 => IntelligenceRef) private _intelligenceRefs;
    mapping(uint256 => mapping(address => bool)) private _authorizations;

    bytes4 private constant _ERC165_INTERFACE_ID = 0x01ffc9a7;
    bytes4 private constant _ERC721_INTERFACE_ID = 0x80ac58cd;
    bytes4 private constant _ERC721_METADATA_INTERFACE_ID = 0x5b5e139f;
    bytes4 private constant _ERC721_RECEIVED = 0x150b7a02;

    // ERC-721 events
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
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
    error NotApprovedOrOwner();
    error ApprovalToCurrentOwner();
    error UnsafeRecipient();

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
        _mint(to, tokenId);
        _intelligenceRefs[tokenId] = IntelligenceRef({
            storageUri: storageUri,
            storageHash: storageHash,
            model: model,
            strategyDigest: strategyDigest,
            aiq: aiq,
            mintedAt: uint64(block.timestamp)
        });
        emit AgentCrystallized(tokenId, to, storageUri, storageHash, model, aiq);
        emit MetadataUpdated(tokenId, storageHash);
    }

    // -------------------------------------------------------------------------
    // ERC-165 / ERC-721 / ERC-721 Metadata
    // -------------------------------------------------------------------------

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == _ERC165_INTERFACE_ID
            || interfaceId == _ERC721_INTERFACE_ID
            || interfaceId == _ERC721_METADATA_INTERFACE_ID;
    }

    function approve(address to, uint256 tokenId) external {
        address owner = _ownerOfExisting(tokenId);
        if (to == owner) revert ApprovalToCurrentOwner();
        if (msg.sender != owner && !_operatorApprovals[owner][msg.sender]) revert NotApprovedOrOwner();

        _tokenApprovals[tokenId] = to;
        emit Approval(owner, to, tokenId);
    }

    function getApproved(uint256 tokenId) external view returns (address) {
        _ownerOfExisting(tokenId);
        return _tokenApprovals[tokenId];
    }

    function setApprovalForAll(address operator, bool approved) external {
        if (operator == msg.sender) revert ApprovalToCurrentOwner();
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function isApprovedForAll(address owner, address operator) external view returns (bool) {
        return _operatorApprovals[owner][operator];
    }

    function transferFrom(address from, address to, uint256 tokenId) public {
        if (!_isApprovedOrOwner(msg.sender, tokenId)) revert NotApprovedOrOwner();
        _transfer(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId) external {
        safeTransferFrom(from, to, tokenId, "");
    }

    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory data) public {
        transferFrom(from, to, tokenId);
        if (!_checkOnERC721Received(msg.sender, from, to, tokenId, data)) revert UnsafeRecipient();
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
        if (!_isApprovedOrOwner(msg.sender, tokenId)) revert NotApprovedOrOwner();
        _transfer(from, to, tokenId);

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
        _mint(to, newTokenId);
        _intelligenceRefs[newTokenId] = _intelligenceRefs[tokenId];

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
        return _ownerOfExisting(tokenId);
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

    function _ownerOfExisting(uint256 tokenId) private view returns (address owner) {
        owner = _owners[tokenId];
        if (owner == address(0)) revert TokenDoesNotExist();
    }

    function _isApprovedOrOwner(address spender, uint256 tokenId) private view returns (bool) {
        address owner = _ownerOfExisting(tokenId);
        return spender == owner
            || _tokenApprovals[tokenId] == spender
            || _operatorApprovals[owner][spender];
    }

    function _mint(address to, uint256 tokenId) private {
        if (to == address(0)) revert InvalidRecipient();

        _owners[tokenId] = to;
        _balances[to] += 1;
        emit Transfer(address(0), to, tokenId);
    }

    function _transfer(address from, address to, uint256 tokenId) private {
        if (to == address(0)) revert InvalidRecipient();
        address owner = _ownerOfExisting(tokenId);
        if (owner != from) revert NotTokenOwner();

        delete _tokenApprovals[tokenId];
        _owners[tokenId] = to;
        _balances[from] -= 1;
        _balances[to] += 1;

        emit Transfer(from, to, tokenId);
    }

    function _checkOnERC721Received(
        address operator,
        address from,
        address to,
        uint256 tokenId,
        bytes memory data
    ) private returns (bool) {
        if (to.code.length == 0) {
            return true;
        }

        (bool success, bytes memory returndata) = to.call(
            abi.encodeWithSelector(_ERC721_RECEIVED, operator, from, tokenId, data)
        );
        if (!success || returndata.length < 32) {
            return false;
        }

        return abi.decode(returndata, (bytes4)) == _ERC721_RECEIVED;
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
