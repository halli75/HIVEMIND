# Local Simulation Guide

This scaffold can run without live sponsors by reading deterministic seeds.

## Seed Order

1. Load `data/snapshots/agents.seed.json`.
2. Replay `data/snapshots/gensyn-messages.seed.json`.
3. Resolve the winning agent storage reference from `data/snapshots/zerog-storage.seed.json`.
4. Attach the mock Uniswap quote from `data/snapshots/uniswap-quote.seed.json`.
5. Mint `HivemindINFT` locally with the winning agent fields.

## Contract Smoke Path

```bash
cd contracts
npm install
npm test
npm run deploy:local
```

## Expected Demo Claims

Allowed with seeds:

- local swarm simulation;
- typed cross-node message replay;
- iNFT mint shape with storage and intelligence reference;
- mocked Sepolia quote response.

Requires live evidence before claiming:

- actual 0G Compute inference;
- actual 0G Storage write/readback;
- actual Gensyn cross-process transport;
- actual Uniswap API quote, swap transaction, and receipt.
