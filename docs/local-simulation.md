# Local Simulation Guide

This scaffold can run without live sponsors by reading deterministic seeds through the same SDK provider boundaries that live integrations will replace.

## Seed Order

1. Load `data/snapshots/agents.seed.json`.
2. Replay `data/snapshots/gensyn-messages.seed.json`.
3. Resolve the winning agent storage reference from `data/snapshots/zerog-storage.seed.json`.
4. Attach the mock Uniswap quote from `data/snapshots/uniswap-quote.seed.json`.
5. Mint `HivemindINFT` locally with the winning agent fields.

## API-Driven Rehearsal

The FastAPI app is the canonical local surface for dashboard rehearsals:

- `POST /scenario` injects a typed scenario and broadcasts the new snapshot.
- `GET /state` returns the latest snapshot.
- `GET /leaderboard` returns the latest ranking.
- `GET /metrics/tiers` returns tier inference counters.
- `WS /ws/state` emits the initial snapshot and each scenario update.

Snapshots include `run_mode`, integration envelopes, run transcript fields, and proof placeholders for AXL, 0G Storage, iNFT, and Uniswap. Local transcripts are written under ignored `runs/YYYYMMDD-HHMMSS/` directories when the default API engine handles a scenario.

## Dashboard Modes

Set `VITE_HIVEMIND_API_URL=http://localhost:8000` before starting Vite to use the API/WebSocket stream. If the API URL is missing or the API is offline, the dashboard intentionally falls back to the deterministic mock stream and labels the state as `Mock fallback`.

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
