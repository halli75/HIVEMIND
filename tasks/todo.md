# HIVEMIND Task Plan

## Current Setup Task

- [x] Create project directory.
- [x] Add project-specific `AGENTS.md`.
- [x] Initialize local Git repository.
- [x] Create GitHub repository.
- [x] Verify remote configuration.

## Initial Implementation Pass

- [x] Scaffold `packages/hivemind-sdk` with mock swarm engine, archetypes, tier metrics, scenario injection, and tests.
- [x] Scaffold `apps/api` with FastAPI REST and WebSocket endpoints over the mock swarm.
- [x] Scaffold `apps/web` with the dashboard shell, metrics panel, scenario input, swarm visualization, and leaderboard.
- [x] Scaffold `contracts` with minimal iNFT contract shape for storage/intelligence references.
- [x] Add seed data snapshots under `data`.
- [x] Add 0G, Gensyn AXL, and Uniswap integration docs.
- [x] Add `.env.example` and Uniswap `FEEDBACK.md`.
- [x] Verify SDK/API tests.
- [x] Verify frontend build or static type check.
- [x] Verify contracts compile or identify missing dependency setup.
- [x] Update README with setup commands and current status.
- [x] Commit and push the scaffold.

## Review

- Local project scaffold created at `C:\Users\arnav\arnav\HIVEMIND`.
- GitHub repository created as `halli75/HIVEMIND`.
- `origin/main` verified with `git ls-remote`.
- Initial implementation scaffold verified with Python tests, web build/audit, contracts compile/test/deploy-local/audit, JSON validation, secret scan, and `git diff --check`.

## Phase 1: Local Vertical Slice Hardening

- [x] Inspect current SDK/API/frontend surfaces and keep integration scope to local MVD.
- [x] Add SDK adapter boundaries for inference, storage, message bus, and execution providers.
- [x] Add typed run mode, replayable seed snapshots, and ignored local run transcripts.
- [x] Make `POST /scenario`, `GET /state`, `GET /leaderboard`, `GET /metrics/tiers`, and `WS /ws/state` drive the canonical app state.
- [x] Replace the frontend's primary data source with an API/WebSocket swarm stream and keep `useMockSwarm` as offline fallback.
- [x] Add dashboard connection badges and run transcript proof fields for AXL, 0G, iNFT, and Uniswap mock/local outputs.
- [x] Update `.env.example`, README/docs, and this task review with the verified commands and current boundaries.
- [x] Verify Python SDK/API tests.
- [x] Verify web build and audit.
- [x] Smoke test API health, scenario injection, and WebSocket snapshot emission.
- [x] Smoke test dashboard against API-backed data.
- [x] Commit and push as `feat: wire dashboard to api swarm stream`.

## Phase 1 Review

- Added provider interfaces and local replay providers in `hivemind-sdk`.
- API now defaults to seed replay, writes ignored local transcripts under `runs/`, exposes CORS for local Vite, and keeps REST/WebSocket state canonical.
- Dashboard now uses `useSwarmStream` against the API/WebSocket source, falls back to `useMockSwarm`, renders 100+ visual agents from backend snapshots, and shows transcript/proof fields.
- Verified `C:\Python313\python.exe -m pytest packages/hivemind-sdk/tests apps/api/tests -q`: 7 passed.
- Verified `apps/web` build and audit: build passed, 0 moderate vulnerabilities.
- Verified API process smoke: `/health`, `POST /scenario`, `/state`, and `WS /ws/state` emitted expected snapshots with transcript output.
- Verified dashboard browser smoke against local API and Vite: API connected, AXL replay, 0G replay, 250 visual agents, iNFT placeholder, and seeded Uniswap quote rendered.
- Verified contracts compile, test, deploy-local, and audit.

## Phase 2: Cross-Process AXL Runner + Live Gensyn Attempt

- [x] Add local AXL message schema, transcript parser, and deterministic payload digest helpers.
- [x] Add `apps/axl-node` coordinator, evaluator, and smoke CLI.
- [x] Verify two separate OS processes exchange at least 20 typed messages and write a JSONL transcript.
- [x] Wire transcript-backed `local_axl` metrics into SDK/API snapshots.
- [x] Surface local AXL node count, latest message type, and latency metrics in the dashboard.
- [x] Document local AXL proof commands and live Gensyn/RL Swarm setup gate.
- [x] Attempt live Gensyn/RL Swarm setup until credential/login/environment gate.
- [x] Verify Python tests, web build/audit, AXL smoke, API/WebSocket smoke, dashboard smoke, and contract checks.
- [x] Commit and push as `feat: add cross-process axl message runner`.

## Phase 2 Review

- Added `hivemind_sdk.axl` message helpers with deterministic payload digests, JSONL append/read support, transcript stats, node failure detection, and latency percentiles.
- Added `apps/axl-node` with coordinator/evaluator subprocess roles, a `smoke` command, and a `failure-smoke` command.
- Wired `LocalAxlMessageBus` into `SwarmEngine` and the API when `HIVEMIND_USE_MOCK_GENSYN=false` and `GENSYN_AXL_TRANSCRIPT_PATH` points to a JSONL transcript.
- Dashboard now labels transcript-backed AXL as `AXL live` and renders node count, failed node count, latest message type, latency metrics, and transcript path.
- Verified Python tests: `C:\Python313\python.exe -m pytest packages/hivemind-sdk/tests apps/api/tests apps/axl-node/tests -q` passed with 15 tests.
- Verified AXL smoke: `C:\Python313\python.exe -m hivemind_axl_node smoke --messages 20 --transcript runs/axl/smoke.jsonl` produced 40 messages, 2 nodes online, latest `INFERENCE_RESULT`, and p50/p95 latency.
- Verified API/WebSocket smoke with `HIVEMIND_USE_MOCK_GENSYN=false`: `/health`, `POST /scenario`, and `WS /ws/state` all reported `run_mode=local_axl`, 40 AXL messages, and 2 nodes online.
- Verified dashboard browser smoke against API-backed local AXL data: rendered `API WebSocket connected`, `AXL live`, AXL node/latency rows, transcript path, and 40 messages.
- Verified web build/typecheck and audit: build passed and audit found 0 moderate vulnerabilities.
- Verified contracts sequentially after avoiding a Hardhat cache race from parallel commands: compile, test, deploy-local, and audit passed.
- Live Gensyn/RL Swarm setup attempt reached an environment/credential gate: Docker Desktop Linux engine was unavailable, Docker was not integrated inside WSL, WSL memory was below the documented 32 GB target, GPU readiness could not be verified without elevation, and no Hugging Face/Gensyn/W&B env vars were present.
