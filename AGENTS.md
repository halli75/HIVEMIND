# Repository Guidelines

## Project Structure & Module Organization

HIVEMIND is a local-first ETHGlobal OpenAgents prototype. The Python SDK lives in `packages/hivemind-sdk/src/hivemind_sdk`, with tests in `packages/hivemind-sdk/tests`. The FastAPI service is in `apps/api/src/hivemind_api` and tests are in `apps/api/tests`. The local cross-process AXL runner is in `apps/axl-node`. The React/Vite dashboard is in `apps/web/src`. Solidity contracts, Hardhat config, deployment scripts, and contract tests live under `contracts/`. Seed snapshots are in `data/snapshots`, integration notes are in `docs/`, and active task notes are in `tasks/`.

## Build, Test, and Development Commands

Use Windows PowerShell examples unless your shell differs.

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src;apps/axl-node/src'
C:\Python313\python.exe -m pytest packages/hivemind-sdk/tests apps/api/tests apps/axl-node/tests -q
```

Runs SDK, API, and AXL tests.

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/axl-node/src'
C:\Python313\python.exe -m hivemind_axl_node smoke --messages 20 --transcript runs/axl/smoke.jsonl
```

Starts two local AXL node processes and writes ignored transcript evidence.

```powershell
cd apps/web; & "$env:ProgramFiles\nodejs\npm.cmd" run build
cd contracts; & "$env:ProgramFiles\nodejs\npm.cmd" test
```

Builds the dashboard and runs Hardhat contract tests.

## Coding Style & Naming Conventions

Python uses type hints, dataclasses, protocols, and snake_case modules/functions. Keep provider boundaries in `providers.py` rather than wiring sponsor APIs directly into the engine. React/TypeScript uses PascalCase components, camelCase variables, and explicit shared types in `apps/web/src/types.ts`. Solidity contracts use PascalCase contract names and camelCase fields. Prefer ASCII, small focused files, and clear mock/live mode labels.

## Testing Guidelines

Tests use `pytest` for Python and Node's built-in test runner through Hardhat for contracts. Add tests beside the surface changed: SDK behavior in `packages/hivemind-sdk/tests`, API behavior in `apps/api/tests`, AXL process behavior in `apps/axl-node/tests`, and contract behavior in `contracts/test/*.spec.ts`. Keep smoke artifacts under ignored `runs/`.

## Commit & Pull Request Guidelines

Follow the existing history style: Conventional Commits such as `feat(axl): add cross-process message runner` or `docs(gensyn): record live swarm setup gate`. PRs should include a short summary, verification commands/results, affected modules, screenshots for dashboard changes, and explicit notes for mock vs live sponsor behavior.

## Security & Configuration Tips

Copy `.env.example` to `.env` locally and never commit secrets, private keys, `HF_TOKEN`, or generated `swarm.pem`. Live integrations must remain opt-in. Do not claim live 0G, Gensyn, or Uniswap success unless logs, readbacks, or transaction evidence prove it.
