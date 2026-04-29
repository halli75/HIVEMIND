// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HivemindINFT
/// @notice ERC-7857-style intelligent NFT for crystallized swarm winners.
///         Stores an on-chain pointer to the encrypted intelligence blob (0G Storage)
///         plus an ERC-721-compatible metadata URI and EIP-2981 royalties.
///         Owner-only mint. Not a full ERC-721 — keeps the demo surface narrow.
contract HivemindINFT {
    string public constant name = "HIVEMIND iNFT";
    string public constant symbol = "HIVEAI";

    address public owner;
    uint256 public nextTokenId = 1;
    uint96 public defaultRoyaltyBps;

    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => string) public intelligenceRef;
    mapping(uint256 => string) private _tokenURIs;
    mapping(uint256 => uint96) private _royaltyBps;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event AgentMinted(uint256 indexed tokenId, address indexed agentOwner, string intelligenceRef);

    error NotOwner();
    error InvalidRecipient();
    error TokenDoesNotExist();
    error EmptyIntelligenceRef();
    error RoyaltyTooHigh();

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert InvalidRecipient();
        owner = initialOwner;
        emit OwnershipTransferred(address(0), initialOwner);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidRecipient();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function mintAgent(
        address to,
        string calldata intelligenceRef_,
        string calldata metadataURI,
        uint96 royaltyBps
    ) external onlyOwner returns (uint256 tokenId) {
        if (to == address(0)) revert InvalidRecipient();
        if (bytes(intelligenceRef_).length == 0) revert EmptyIntelligenceRef();
        if (royaltyBps > 10000) revert RoyaltyTooHigh();

        tokenId = nextTokenId++;
        _owners[tokenId] = to;
        _balances[to] += 1;
        intelligenceRef[tokenId] = intelligenceRef_;
        _tokenURIs[tokenId] = metadataURI;
        _royaltyBps[tokenId] = royaltyBps;

        emit Transfer(address(0), to, tokenId);
        emit AgentMinted(tokenId, to, intelligenceRef_);
    }

    function ownerOf(uint256 tokenId) external view returns (address) {
        address tokenOwner = _owners[tokenId];
        if (tokenOwner == address(0)) revert TokenDoesNotExist();
        return tokenOwner;
    }

    function balanceOf(address account) external view returns (uint256) {
        if (account == address(0)) revert InvalidRecipient();
        return _balances[account];
    }

    function tokenURI(uint256 tokenId) external view returns (string memory) {
        if (_owners[tokenId] == address(0)) revert TokenDoesNotExist();
        return _tokenURIs[tokenId];
    }

    /// @notice EIP-2981 royalty info. Returns the token owner as the receiver.
    function royaltyInfo(uint256 tokenId, uint256 salePrice)
        external
        view
        returns (address receiver, uint256 royaltyAmount)
    {
        address tokenOwner = _owners[tokenId];
        if (tokenOwner == address(0)) revert TokenDoesNotExist();
        receiver = tokenOwner;
        royaltyAmount = (salePrice * _royaltyBps[tokenId]) / 10000;
    }

    /// @notice ERC-165: supports ERC-721 metadata + EIP-2981 royalty interface.
    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return
            interfaceId == 0x01ffc9a7 || // ERC-165
            interfaceId == 0x80ac58cd || // ERC-721
            interfaceId == 0x5b5e139f || // ERC-721 Metadata
            interfaceId == 0x2a55205a;   // EIP-2981
    }
}
