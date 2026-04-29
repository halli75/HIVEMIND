# hivemind-axl-node

Local cross-process AXL-compatible runner for HIVEMIND. Provides:

- Coordinator + evaluator pair (the original 2-node smoke test).
- Multi-agent **pool nodes** that route typed AXL messages between an
  arbitrary number of registered agents.
- A **benchmark** that drives the pool through 1k TRADE_INTENT and
  1k MARKET_SIGNAL messages and emits the numbers Gensyn expects in
  the AXL prize submission.

## Starting pool nodes

Each node is a single TCP process. Agents connect to every node so any
node can fan a broadcast out to all locally-registered peers; nodes do
not gossip with each other.

```bash
python -m hivemind_axl_node start-node --port 7001 --node-id axl-1 --pool-id hivemind-main
python -m hivemind_axl_node start-node --port 7002 --node-id axl-2 --pool-id hivemind-main
python -m hivemind_axl_node start-node --port 7003 --node-id axl-3 --pool-id hivemind-main
```

Three to five processes is the recommended range for the benchmark and
for the demo `SwarmEngine` integration.

Connect from Python:

```python
from hivemind_sdk import AXLPoolManager

pool = AXLPoolManager(
    node_urls=["tcp://127.0.0.1:7001", "tcp://127.0.0.1:7002", "tcp://127.0.0.1:7003"],
    pool_id="hivemind-main",
    agent_id="agent-001",
)
await pool.connect()
await pool.broadcast("TRADE_INTENT", {"action": "buy", "size_usd": 250_000})
inbox = await pool.receive(timeout=1.0)
await pool.disconnect()
```

`SwarmEngine` accepts `axl_node_urls=[...]`; when set, every Tier‑1 tick
broadcasts both `TRADE_INTENT` and `INFERENCE_RESULT` to the pool, and
incoming `MARKET_SIGNAL` payloads boost the urgency of the targeted
agent on the next tick.

## Running the benchmark

```bash
python apps/axl-node/benchmark.py --nodes 2,5
```

Defaults: 1000 TRADE_INTENT + 1000 MARKET_SIGNAL per run. Results are
written to `apps/axl-node/benchmark_results.json` and printed as a
table.

## AXL message types

| # | Type               | Purpose                                                           |
|---|--------------------|-------------------------------------------------------------------|
| 1 | `SCENARIO_SHOCK`   | Coordinator broadcast announcing a new scenario / market shock.   |
| 2 | `MARKET_SIGNAL`    | Directional signal that boosts urgency of a targeted agent.       |
| 3 | `TRADE_INTENT`     | Active-tier agent declaring an intended trade for the scenario.   |
| 4 | `INFERENCE_RESULT` | Active-tier agent reporting the score / confidence of a decision. |
| 5 | `POOL_STATE`       | Snapshot of a pool's tick / sqrt price / liquidity / TVL.         |
| 6 | `COALITION_INVITE` | Proposal for one agent to join another's coalition.               |
| 7 | `GOVERNANCE_SIGNAL`| Vote / abstain signal carried as part of a governance proposal.   |

## Benchmark results

Filled in by `benchmark.py` after each run. Latest snapshot:

| nodes | msgs sent | msgs recv | duration (s) | msgs/sec | p50 (ms) | p95 (ms) | avg RSS (MB) | max RSS (MB) |
|------:|----------:|----------:|-------------:|---------:|---------:|---------:|-------------:|-------------:|
| 2     | _tbd_     | _tbd_     | _tbd_        | _tbd_    | _tbd_    | _tbd_    | _tbd_        | _tbd_        |
| 5     | _tbd_     | _tbd_     | _tbd_        | _tbd_    | _tbd_    | _tbd_    | _tbd_        | _tbd_        |

(Run `python apps/axl-node/benchmark.py --nodes 2,5` and paste the
printed table here for the Gensyn submission.)
