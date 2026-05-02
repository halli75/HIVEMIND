# Repository Guidelines

## Project Structure & Module Organization

HIVEMIND is a local-first ETHGlobal OpenAgents prototype. The Python SDK is in `packages/hivemind-sdk/src/hivemind_sdk`, with tests in `packages/hivemind-sdk/tests`. The FastAPI service lives in `apps/api/src/hivemind_api`, API tests in `apps/api/tests`, and the local AXL runner in `apps/axl-node`. Uniswap execution helpers are under `apps/execution`. The React/Vite dashboard is in `apps/web/src`. Solidity contracts, Hardhat config, scripts, and tests live in `contracts/`. Seed data is in `data/`, integration notes and proof summaries are in `docs/`, and active task notes are in `tasks/`.

## Build, Test, and Development Commands

Use Windows PowerShell examples unless your shell differs.

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src;apps/axl-node/src'
C:\Python313\python.exe -m pytest packages/hivemind-sdk/tests apps/api/tests apps/axl-node/tests apps/execution/tests -q
```

Runs Python SDK, API, AXL, and execution tests.

```powershell
cd apps/web; & "$env:ProgramFiles\nodejs\npm.cmd" run build
cd contracts; & "$env:ProgramFiles\nodejs\npm.cmd" test
```

Builds the dashboard and runs Hardhat contract tests. Use `npm.cmd` on PowerShell when `npm.ps1` is blocked.

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/axl-node/src'
C:\Python313\python.exe -m hivemind_axl_node smoke --messages 20 --transcript runs/axl/smoke.jsonl
```

Runs a two-node AXL smoke and writes ignored transcript evidence.

## Coding Style & Naming Conventions

Python uses type hints, dataclasses, protocols, snake_case modules/functions, and provider boundaries in `providers.py`. React/TypeScript uses PascalCase components, camelCase variables, and shared types in `apps/web/src/types.ts`. Solidity contracts use PascalCase contract names and camelCase fields. Prefer ASCII, focused files, and explicit mock/live labels.

## Testing Guidelines

Tests use `pytest` for Python and Node's built-in runner through Hardhat for contracts. Add tests beside the changed surface: SDK tests in `packages/hivemind-sdk/tests`, API tests in `apps/api/tests`, AXL tests in `apps/axl-node/tests`, execution tests in `apps/execution/tests`, and contract specs in `contracts/test/*.spec.ts`. Keep generated run evidence under ignored `runs/`.

## Commit & Pull Request Guidelines

Use Conventional Commits, for example `feat(inft): prove mint and add nft compatibility` or `docs(gensyn): record live swarm setup gate`. PRs should include a concise summary, verification commands/results, affected modules, screenshots for dashboard changes, and explicit mock vs live sponsor behavior.

## Security & Configuration Tips

Copy `.env.example` to `.env` locally. Never commit secrets, private keys, bearer tokens, `HF_TOKEN`, generated keyfiles, or `swarm.pem`. Live integration claims require proof: logs, readbacks, transaction hashes, or tracked non-secret evidence in `docs/evidence/`.
