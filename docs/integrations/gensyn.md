# Gensyn Integration Plan

## Target

Use Gensyn AXL-style communication as the cross-process messaging layer for the swarm. At minimum, the demo should show two separate node processes exchanging typed messages that affect agent scoring.

## Current Scaffold

- Seeded typed messages live in `data/snapshots/gensyn-messages.seed.json`.
- The architecture expects separate process IDs such as `node-a` and `node-b`.
- Message types are intentionally explicit: `ScenarioInjected` and `StrategyScoreSubmitted`.

## Official Reference Points

Gensyn describes a decentralized ML protocol with execution, verification, peer-to-peer communication, and coordination layers. Its RL Swarm materials show agents cooperating over the internet, exchanging answers, feedback, and critiques with peers.

References:

- https://docs.gensyn.ai/
- https://docs.gensyn.ai/the-gensyn-protocol
- https://docs.gensyn.ai/testnet/rl-swarm

## Message Contract

Every live message should include:

- `id`: deterministic or UUID event identifier.
- `type`: typed event name.
- `from`: sending node ID.
- `to`: receiving node ID or `broadcast`.
- `timestamp`: ISO timestamp.
- `payload`: event-specific JSON object.

## Integration Steps

1. Start two independent processes.
2. Send `ScenarioInjected` from the broadcaster node.
3. Send at least one scoring or critique message back from the evaluator node.
4. Persist the transcript to a run log that can later be written to 0G Storage.
5. Surface message count and latest message in the frontend metrics panel.

## Safety

- Do not claim live Gensyn participation until node logs prove cross-process exchange.
- Keep the seed transport available for offline demos.
