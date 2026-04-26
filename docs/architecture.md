# HIVEMIND Architecture Scaffold

HIVEMIND simulates a DeFi swarm, crystallizes the winning strategy into an iNFT-backed agent, and executes a real Uniswap trade.

## Core Flow

1. Scenario injection creates a market event for the swarm.
2. Gensyn AXL-style node processes exchange typed scenario, score, and critique messages.
3. The inference tier ranks agents using 0G Compute when configured, with local mock inference as a fallback.
4. The winning agent state and strategy digest are written to 0G Storage or represented by deterministic local seeds.
5. `HivemindINFT` mints a token on local Hardhat or 0G Galileo testnet with a storage URI, content hash, model name, strategy digest, and AIQ score.
6. The execution layer requests a Uniswap quote, checks approval when needed, and signs a Sepolia swap only after operator review.

## Boundaries

- Mainnet execution is out of scope.
- Private keys, API keys, bearer tokens, and provider secrets stay outside source control.
- Seed files are safe placeholders and should be replaced with verified run artifacts as integrations land.
- The iNFT contract is a placeholder for demo wiring, not an audited token implementation.

## Data Contracts

- Agent snapshots use `hivemind.agents.snapshot.v0`.
- AXL-style messages use `hivemind.gensyn.messages.v0`.
- 0G storage references use `hivemind.0g.storage.snapshot.v0`.
- Uniswap quote snapshots use `hivemind.uniswap.quote.v0`.

## Implementation Readiness

The scaffold is designed so each integration worker can replace mock adapters one at a time while preserving the demo narrative:

- SDK/API: `InferenceProvider`, `StorageProvider`, `MessageBus`, and `ExecutionProvider` define the adapter boundary used by the local engine and API snapshots.
- 0G worker: replace seeded storage URIs with write/readback proofs and use 0G Compute for active inference.
- Gensyn worker: replace mock transport with two real node processes and capture message logs.
- Uniswap worker: replace mock quote with API quote, approval, swap, and transaction receipt.

## Phase 1 Runtime Surface

The local vertical slice is API-driven:

- `POST /scenario` is the canonical scenario injection point.
- `GET /state`, `GET /leaderboard`, and `GET /metrics/tiers` expose the latest run state.
- `WS /ws/state` streams the initial snapshot and scenario updates to the dashboard.
- Snapshots carry explicit run mode and proof fields so the UI can distinguish mock, replay, and future live integration evidence.
- Local run transcripts are written under ignored `runs/` directories for demo rehearsal evidence.
