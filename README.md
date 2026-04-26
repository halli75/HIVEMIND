# HIVEMIND

DeFi Swarm Intelligence Engine for the ETHGlobal OpenAgents hackathon.

HIVEMIND simulates a DeFi swarm, crystallizes the winning strategy into an iNFT-backed agent, and executes a real Uniswap trade.

## Target Integrations

- 0G: Compute, Storage, Chain, iNFTs, and `hivemind-sdk`.
- Gensyn AXL: cross-process agent communication.
- Uniswap: Sepolia quote and swap execution through the Uniswap API.

## Status

Initial local-first scaffold is live:

- `packages/hivemind-sdk`: deterministic mock swarm engine, tier metrics, scenario injection, and leaderboard.
- `apps/api`: FastAPI REST and WebSocket API over the mock swarm.
- `apps/web`: React/Vite dashboard shell with scenario input, swarm visualization, metrics, and leaderboard.
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

### Web Dashboard

```powershell
cd apps/web
& "$env:ProgramFiles\nodejs\npm.cmd" install
& "$env:ProgramFiles\nodejs\npm.cmd" run dev
```

### Contracts

```powershell
cd contracts
& "$env:ProgramFiles\nodejs\npm.cmd" install
& "$env:ProgramFiles\nodejs\npm.cmd" run compile
& "$env:ProgramFiles\nodejs\npm.cmd" test
```

## Current Boundaries

The scaffold is local/mock-first. It proves the product shape before sponsor credentials are wired in. ENS, KeeperHub, breeding, marketplace, LP management, live GraphRAG, and mainnet execution remain off the critical path.
