# HIVEMIND

DeFi Swarm Intelligence Engine for the ETHGlobal OpenAgents hackathon.

HIVEMIND simulates a DeFi swarm, crystallizes the winning strategy into an iNFT-backed agent, and executes a real Uniswap trade.

## Target Integrations

- 0G: Compute, Storage, Chain, iNFTs, and `hivemind-sdk`.
- Gensyn AXL: cross-process agent communication.
- Uniswap: Sepolia quote and swap execution through the Uniswap API.

## Status

Phase 1 local vertical slice is live:

- `packages/hivemind-sdk`: deterministic swarm engine, provider adapter boundaries, seed replay, tier metrics, scenario injection, and transcript output.
- `apps/api`: FastAPI REST and WebSocket API as the canonical scenario/state surface.
- `apps/web`: React/Vite dashboard backed by the API/WebSocket stream with mock fallback.
- `contracts`: Hardhat scaffold with a minimal `HivemindINFT` contract shape for 0G iNFT proof work.
- `data`: deterministic seed snapshots for local simulation.
- `docs`: architecture and integration notes for 0G, Gensyn AXL, and Uniswap.

## Quickstart

Use `npm.cmd` on Windows PowerShell if `npm.ps1` is blocked by execution policy.

### SDK and API Tests

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src'
C:\Python313\python.exe -m pytest packages/hivemind-sdk/tests apps/api/tests -q
```

### API Server

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src'
C:\Python313\python.exe -m uvicorn hivemind_api.app:app --reload --host localhost --port 8000
```

The API loads deterministic seed snapshots from `data/snapshots` and writes local run transcripts under ignored `runs/YYYYMMDD-HHMMSS/` directories.

### Web Dashboard

```powershell
cd apps/web
& "$env:ProgramFiles\nodejs\npm.cmd" install
$env:VITE_HIVEMIND_API_URL='http://localhost:8000'
& "$env:ProgramFiles\nodejs\npm.cmd" run dev
```

If `VITE_HIVEMIND_API_URL` is missing or the API is offline, the dashboard falls back to its deterministic mock stream and labels that state visibly.

### Local Scenario Smoke

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src'
C:\Python313\python.exe -m uvicorn hivemind_api.app:app --host localhost --port 8000
```

In a second PowerShell:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/scenario -Method Post -ContentType 'application/json' -Body '{"scenario_id":"readme-smoke","label":"README smoke","volatility":0.6,"liquidity_delta":-0.2,"sentiment":0.1,"gas_pressure":0.3,"signal_strength":0.7}'
```

### Contracts

```powershell
cd contracts
& "$env:ProgramFiles\nodejs\npm.cmd" install
& "$env:ProgramFiles\nodejs\npm.cmd" run compile
& "$env:ProgramFiles\nodejs\npm.cmd" test
```

## Current Boundaries

Phase 1 is local/mock-first with deterministic replay proofs. It does not yet claim live Gensyn AXL, 0G Compute/Storage, iNFT testnet minting, or Uniswap API execution. ENS, KeeperHub, breeding, marketplace, LP management, live GraphRAG, and mainnet execution remain off the critical path.
