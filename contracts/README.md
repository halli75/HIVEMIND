# HIVEMIND Contracts

Hardhat-style scaffold for the HIVEMIND iNFT milestone.

The current `HivemindINFT` contract is intentionally minimal and mock/testnet-safe:

- records the selected swarm winner as an owner-addressed token;
- stores a 0G Storage URI, content hash, model name, strategy digest, AIQ score, and mint timestamp;
- exposes ERC-721-like `ownerOf`, `balanceOf`, and `tokenURI` read methods for demos;
- avoids live secrets and production mainnet assumptions.

## Local Commands

```bash
cd contracts
npm install
npm run compile
npm test
npm run deploy:local
```

## 0G Galileo Deployment

1. Copy `.env.example` from the repo root to `.env`.
2. Set `ZERO_G_RPC_URL` to the Galileo RPC endpoint or an approved provider RPC.
3. Set `DEPLOYER_PRIVATE_KEY` to a funded testnet wallet only.
4. Run:

```bash
cd contracts
npm run deploy:0g:galileo
```

This contract is not audited and should not be used for autonomous mainnet execution.
