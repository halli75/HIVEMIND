# HIVEMIND Task Plan

## 0G Compute Integration Hardening

- [x] Make `HIVEMIND_USE_MOCK_0G` the canonical live 0G toggle and preserve the legacy inference flag as an alias.
- [x] Compose `run_mode` correctly for mock, local AXL, live 0G, and combined local AXL plus live 0G runs.
- [x] Replace private provider field access with structured hybrid inference metrics.
- [x] Record live 0G latency, fallback counts, and non-secret error context.
- [x] Tolerate common JSON response wrappers from live models.
- [x] Ignore and remove generated Python `*.egg-info/` artifacts.
- [x] Add API/SDK tests for env precedence, run mode, metrics, parsing, fallback, and latency behavior.
- [x] Verify Python tests and web build.

## 0G Compute Integration Hardening Review

- Canonicalized live 0G Compute configuration around `HIVEMIND_USE_MOCK_0G=false`; `HIVEMIND_MOCK_INFERENCE=false` remains a legacy alias when the canonical flag is absent.
- Added composed run modes for `live_0g` and `local_axl+live_0g`.
- Added structured hybrid inference metrics for attempted live calls, successful live calls, fallbacks, average latency, model, top-N, and last non-secret error.
- Hardened 0G response parsing for exact JSON and fenced JSON, preserved fallback details, and removed the non-ASCII rationale arrow.
- Added `*.egg-info/` to `.gitignore` and removed the generated egg-info directories from the working tree.
- Verified Python tests with a fresh writable temp directory: `27 passed`.
- Verified web build/typecheck with Vite after rerunning outside the sandbox due `spawn EPERM`.

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

## Phase 2 Live Gensyn Follow-Up

- [x] Re-check Docker Desktop and WSL integration after user enabled Docker Desktop.
- [x] Use the provided Hugging Face token only as a transient env var; do not write it to repo files or logs.
- [x] Clone or update RL Swarm in an external WSL workspace outside this repo.
- [x] Run official setup far enough to reach browser login, HF token, Docker, or current-network availability gate.
- [x] Capture non-secret evidence and update `docs/integrations/gensyn.md`.
- [x] Verify no secrets were committed and push documentation if changed.

## Phase 2 Live Gensyn Recovery

- [x] Snapshot current RL Swarm clone state and avoid committing external secrets or generated identity files.
- [x] Run isolated baseline, official dependency, SSR/account-kit, and script-path attempts in external WSL workspaces.
- [x] Capture non-secret logs for each patch variant, including modal login status and `swarm.pem` presence.
- [x] Continue the first successful login path until peer/testnet participation, official swarm-unavailable state, or a new concrete blocker.
- [x] Update Gensyn docs and this review with verified evidence.
- [ ] Verify no tracked secrets, no repo regressions, and no stale containers required for the demo path.

## Phase 2 Live Gensyn Recovery Review

- Baseline upstream RL Swarm commit `9c95410` still reproduces the modal-login `hasHydrated` HTTP 500 after a successful install/build.
- A one-line Account Kit `cookieStorage` patch preserves SSR, builds, and serves the modal at HTTP 200 on port 3103; this is now the preferred full-container promotion patch.
- A minimal Next 14 client-mount patch builds and serves the modal at HTTP 200 on port 3105.
- A larger official-dependency compatibility patch also serves HTTP 200 on port 3102 after Next 16, viem, webpack-build, Account Kit resolution, and async headers fixes.
- The non-Docker script path reaches the Ethereum Server Wallet login setup text but stalls in bounded Yarn dependency installation before serving the modal.
- Full CPU container promotion remains blocked: workspace mount permissions first killed the container, and the root-run retry destabilized WSL/Docker before a login page or `swarm.pem` could be verified.
- No live peer/testnet registration was proven; no `swarm.pem` contents were read or committed.

## Phase 2 Live Gensyn Container Promotion Retry

- [x] Re-check Docker Desktop, WSL, disk pressure, stale RL Swarm containers, and preferred patch workspace.
- [x] Remove stale RL Swarm container state and reclaim safe Docker cache.
- [x] Bake the `cookieStorage` patch and `setuptools<81` build constraint into the CPU image path.
- [x] Start the CPU container with transient credentials and bounded log capture.
- [x] Verify `http://localhost:3000` reaches the login page or capture the exact new blocker.
- [x] If login page is reachable, pause for browser login and verify `swarm.pem` exists without reading contents.
- [x] Continue to peer/testnet status, official swarm-unavailable state, or a concrete upstream/runtime blocker.
- [x] Update Gensyn docs, run secret/regression checks, commit evidence, and push if requested.

## Phase 2 Live Gensyn Container Promotion Retry Review

- Clean restart resolved the stale-container deletion hang, and the previous stale RL Swarm container was removed.
- Docker build cache was reclaimed without deleting volumes or unrelated named images.
- The external RL Swarm workspace was patched with the SSR-preserving `cookieStorage` fix, a shared `setuptools<81` requirements constraint, and a non-interactive prompt guard.
- The CPU image build passed modal-login build and Python dependency installation; the previous `pkg_resources` failure did not recur.
- Docker Desktop produced a snapshot/unpack issue for the newly named Compose image, but the usable `rl-swarm-swarm-cpu` image contained the modal fix and could run.
- The live container served `http://localhost:3000` with HTTP 200.
- Browser login completed, API key activation succeeded, and `swarm.pem` was generated in the ignored external workspace without reading or committing key contents.
- RL Swarm logged `Connected to Gensyn Testnet`.
- Final blocker moved to P2P bootstrap: all emitted bootnode ports on `38.101.215.15` failed from Windows, WSL, and container checks, and the runner exited with `failed to connect to bootstrap peers`.

## Phase 2 Live Gensyn Bootnode Reachability

- [x] Reconfirm Windows, WSL, and Docker baseline state before retrying RL Swarm.
- [x] Check current official Gensyn RL Swarm docs and known bootstrap-peer reports.
- [x] Run a Docker-isolated TCP probe against `38.101.215.15:30021-30023`.
- [x] Capture traceroute/tracert evidence for the emitted bootnode IP.
- [x] Audit local firewall/VPN/network state without changing security settings.
- [x] Use an alternate egress path, preferably a cloud VM, to distinguish local blocking from upstream bootnode unavailability.
- [x] Decide whether to rerun patched CPU RL Swarm based on raw TCP reachability.
- [x] Update Gensyn docs, verify no tracked secrets/regressions, and commit the diagnosis.

## Phase 2 Live Gensyn Bootnode Reachability Review

- Windows, WSL, and Docker all retained normal public egress controls, including successful checks to `1.1.1.1:443`.
- Windows, WSL, Docker, and an independent AWS `us-east-2` probe all failed to reach `38.101.215.15:30021-30023`.
- Windows and WSL route probes left the local network and failed at or after `38.104.98.199`; AWS traceroute reached the same network and then no longer progressed.
- The temporary AWS probe instance and security group were terminated and deleted after evidence capture.
- Official Gensyn docs currently label RL Swarm as deprecated and state there are no official swarms running right now.
- The patched CPU RL Swarm path was not rerun because raw TCP reachability failed from every tested egress path; rerunning would only reproduce the same bootstrap failure.
- Current root cause classification: upstream Gensyn bootnode availability/routing/filtering or no active official swarm, not a local Docker/WSL/login/identity problem.

## Phase 2 Live Gensyn Upstream Resolution

- [x] Capture the user correction as a lesson: upstream classification is not completion.
- [x] Query the current Gensyn testnet contract for live bootnodes and round state.
- [x] Test historical bootnodes from prior RL Swarm issues as a possible manual override.
- [x] Collect safe environment fields for a Gensyn escalation package.
- [x] Identify a current official/community replacement path for RL Swarm/CodeZero.
- [x] Submit or prepare a support/GitHub escalation with sanitized evidence.
- [x] If Gensyn provides reachable bootnodes or a community swarm, rerun the patched CPU RL Swarm path to live peer participation.

## Phase 2 Live Gensyn Upstream Resolution Review

- Current `origin/main` is `9c95410`; `v0.7.0` CodeZero tag exists at `992569c`, and both use the same official `SWARM_CONTRACT` address.
- Direct on-chain reads confirmed the live official contract still advertises only the three unreachable `38.101.215.15:30021-30023` bootnodes.
- Historical Gensyn bootnodes from older issue reports were also unreachable, so manual fallback to older peers is not viable.
- Open upstream work still describes missing active bootstrap servers / DHT bootstrap failure, so local dependency patching is not enough to produce live peer participation.
- Training bootnodes are contract-driven and overwrite Hydra/env initial-peer overrides, so a real community path needs either a compatible coordinator contract or an external RL Swarm code patch.
- Added `docs/integrations/gensyn-escalation.md` with a sanitized escalation draft and evidence list.

## Phase 2 Live Gensyn Self-Hosted Bootstrap

- [x] Identify two code-level bootnode injection sites: `manager.py:43` and `proposer_service.py:73`.
- [x] Add `HIVEMIND_INITIAL_PEERS` env-var override patches for both files.
- [x] Add `services/hivemind-bootnode/bootnode.py` using the existing swarm-cpu image.
- [x] Add `patches/rl-swarm/manager.patch` and `patches/rl-swarm/proposer_service.patch`.
- [x] Add `scripts/run-gensyn-self-hosted.sh` orchestration script.
- [x] Update `docs/integrations/gensyn.md` with self-hosted bootstrap resolution section.
- [x] Run `scripts/run-gensyn-self-hosted.sh` from WSL and verify success log evidence.
- [x] Verify no tracked secrets and push.

## Phase 2 Live Gensyn Self-Hosted Bootstrap Review

- Root cause confirmed: `manager.py:43` and `proposer_service.py:73` unconditionally overwrite `initial_peers` with dead contract-sourced Gensyn bootnodes after Hydra loads config.
- Fix: two-line `HIVEMIND_INITIAL_PEERS` env-var check applied dynamically to `/tmp/` copies and volume-mounted read-only; no image rebuild required.
- Self-hosted bootnode uses `hivemind.DHT(start=True, host_maddrs=["/ip4/0.0.0.0/tcp/30021"])` with the existing `matrix-cookie-storage-swarm-cpu` image (contains `hivemind==1.2.0.dev0`).
- Orchestration script connects bootnode and swarm-cpu via Docker named network `swarm-boot-net` using `/dns4/hivemind-bootnode/tcp/30021/p2p/PEER_ID` multiaddr.
- Target proof: single-node (`HIVEMIND_WORLD_SIZE=1`) DHT join without `failed to connect to bootstrap peers`; training begins.
- **VERIFIED 2026-04-27**: `bootnodes: ['/dns4/hivemind-bootnode/tcp/30021/p2p/12D3KooWE5...']`, `Joining CodeZero Swarm`, `Starting round: 28239`. No `P2PDaemonError`. Training running. Node: `jagged spotted mandrill` / `QmRAFupGJwJB8mGG6eNsAbo1CQeAGQeEWqZTvALybgBetc`.

## PR Review: Core HIVEMIND Engine

- [x] Confirmed review range: 9 commits on `dev` after `00b089a`, with `dev` tracking `origin/dev`.
- [x] Extracted and checked `HIVEMIND_Project_Proposal_v4.pdf` against the PR scope: swarm engine, visualization, crystallization, AXL P2P, and Uniswap execution.
- [x] Reviewed SDK/API/AXL, contracts/0G crystallization, Uniswap execution scripts, frontend visualization, and docs for merge readiness.
- [x] Applied small contained fixes: Sepolia chain guard in swap signing, explicit `HIVEMIND_ALLOW_TESTNET_SWAP` gate, env-driven Uniswap amount, mock-safe crystallization tx display, and lowercase quickstart actions.
- [x] Ran Python/API/AXL/execution tests, web build/audit, contract compile/test/deploy/audit, AXL smoke, quickstart smoke, compileall, `git diff --check`, and outgoing-diff secret scan.

## PR Review Notes

- Current `dev` is behind `main` by six 0G commits; merging as-is would delete the current 0G mint script, hardened 0G provider tests, and ERC-7857 contract hardening from `main`.
- The local AXL proof is strong: smoke run produced 40 typed messages across two OS processes with p50/p95 latency.
- The PR still needs a non-trivial rebase/merge of `main` before approval because the branch composition would regress Part A/Part B 0G work.

## Phase 3/4 Live Proof Rehearsal And Mint Hardening

- [x] Inspect current `/mint`, 0G Storage upload, and Uniswap execution code without overwriting existing E2E fixes.
- [x] Add or verify bounded retry/backoff for 0G Storage upload.
- [x] Ensure `/mint` returns a clear `storage_unavailable` status when the 0G Storage indexer returns 503 before minting.
- [x] Retry `POST /mint` against the local API and capture token/tx/storage proof if 0G Storage has recovered.
- [x] Run a full proof rehearsal: `/health`, `/scenario`, `/state`, `/mint`, Uniswap quote, and gated swap behavior.
- [x] Save non-secret evidence under ignored `runs/`.
- [x] Update `docs/integrations/0g.md`, `docs/integrations/uniswap.md`, `docs/integrations/gensyn.md`, `README.md`, and `FEEDBACK.md`.
- [x] Run Python, web, contracts, AXL, diff, and secret-scan checks before any commit.

## Phase 3/4 Live Proof Rehearsal Review

- Evidence saved under ignored `runs/proof-20260429-161627/`.
- `/scenario` succeeded with `run_mode=local_axl+live_0g`, 10 top-N 0G Compute attempts, 9 live completions, 1 HTTP 429 fallback, and a live Uniswap quote.
- `/mint` fetched winner `agent-014`, encrypted with AES-256-GCM, wrote the local demo key under ignored `contracts/runs/inft-keys/`, then stopped before chain mint because 0G Storage returned HTTP 503 for all 4 retry attempts.
- The patched `/mint` response is HTTP 503 with `detail.status="storage_unavailable"` instead of a generic 500.
- Uniswap quote-only rehearsal succeeded with `0.001 WETH -> 8.75588 USDC`; swap script refused to sign because `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled.

## Phase 3 Turbo 0G Storage Retry

- [x] Restart the API with `ZERO_G_STORAGE_INDEXER_URL=https://indexer-storage-testnet-turbo.0g.ai`.
- [x] Set extended retry controls: `MINT_STORAGE_MAX_ATTEMPTS=8`, `MINT_STORAGE_RETRY_BASE_MS=3000`.
- [x] Verify required env vars exist without printing secrets.
- [x] Verify deployer public address and OG testnet balance through `ZERO_G_RPC_URL`.
- [x] Retry `POST /mint` and capture either token/storage proof or sanitized failure evidence.
- [x] Update docs/tasks and commit only if tracked code or docs change.

## Phase 3 Turbo 0G Storage Retry Review

- Evidence saved under ignored `runs/proof-turbo-20260429-165426/`.
- Required env vars were present, and the deployer wallet `0xb9123E486471D366210318F9eEB80B934e770caA` had `1.990395423983191992 OG` on Galileo chain `16602`.
- Turbo indexer reached storage nodes and prepared upload data, so this was not the same standard-indexer HTTP 503 failure.
- Turbo failure: `Failed to submit transaction: ProviderError: execution reverted` on Flow address `0x22e03a6a89b950f1c82ec5e74f8eca321a105296`.
- Static call probe against `flow.submit` reverted with exact and 10 percent padded fee, so the failure is not obviously a missing balance or underpaid storage-fee issue.
- Added `docs/integrations/0g-escalation.md` with sanitized evidence for 0G support.

## Working Version Familiarization

- [x] Inspect current branch/status and preserve uncommitted SDK changes.
- [x] Review modified SDK files for behavior, performance, and API/UI contract impact.
- [x] Inspect recent commits and the web/API surfaces most likely affected by these changes.
- [x] Run focused verification where safe.
- [x] Summarize the current working state plus polish, performance, and UI opportunities.

## Working Version Familiarization Review

- Current branch is `dev`, aligned with `origin/dev`, with uncommitted SDK tuning in `engine.py`, `providers.py`, and `scoring.py`.
- The SDK changes move shared scenario market/memory builders into `providers.py`, make `LocalInferenceProvider` use archetype heuristics directly, and retune PnL/score weights for more differentiated strategy outcomes.
- Focused verification passed: Python SDK/API tests reported `34 passed`; web typecheck/build passed.
- A local 42-agent scenario probe produced differentiated actions across buy, hold, rebalance, arb, vote, and front_run, with a tighter leaderboard score range of about 11-43.
- Main polish targets identified: align the dashboard iNFT action with live `POST /mint`, improve graph rendering/perceived performance, and recalibrate UI score/risk displays for the new score distribution.

## PR Review: Complete Sprint Polish

- [x] Confirm the exact PR review range after fetching `origin/dev`.
- [x] Preserve existing uncommitted SDK tuning while reviewing the remote UI polish commit.
- [x] Review API, SDK, contracts, execution scripts, docs, and web UI diff line by line.
- [x] Apply small contained fixes directly when they are low-risk.
- [x] Record any large merge-blocking issues separately for follow-up.
- [x] Run focused verification after fixes.

## PR Review: Complete Sprint Polish Review

- Fast-forwarded local `dev` to `origin/dev` before review; preserved the existing uncommitted SDK tuning changes in `engine.py`, `providers.py`, and `scoring.py`.
- Fixed dashboard minting to use the live `/mint` endpoint, parse structured API errors, and avoid claiming readiness when `INFT_CONTRACT_ADDRESS` is not configured.
- Hardened `/mint` API responses by killing timed-out subprocesses and redacting subprocess output tails before returning them to clients.
- Fixed live integration truthfulness: Uniswap quote failures now report `mode=unavailable`, AXL pools with zero connected nodes no longer report `live_axl`, and the web badge renders unavailable integrations as offline.
- Fixed the direct 0G Storage fallback fee calculation and forced segment upload to reuse the already-indexed Flow log entry instead of retrying the old SDK submit ABI.
- Verification passed: Python/API/execution tests (`37 passed`), web build, contracts compile/test/deploy-local, AXL smoke, web audit, contracts audit, `git diff --check`, outgoing diff secret scan with only intentional placeholder/test-pattern matches, and `git merge-tree --write-tree origin/main HEAD` without conflicts.

## PR Merge-Ready: iNFT Proof And NFT Compatibility

- [x] Inspect current contract, tests, mint path, docs, and working tree without reverting existing review fixes.
- [x] Upgrade `HivemindINFT` from ERC-721-like to minimal ERC-165/ERC-721/ERC-721Metadata-compatible behavior while preserving ERC-7857-style sealed-key functions.
- [x] Add contract coverage for interfaces, approvals, transfers, safe transfers, approval clearing, and negative transfer cases.
- [x] Run a fresh `/health`, `/scenario`, `/state`, `/mint`, `/state` proof rehearsal and save non-secret raw evidence under ignored `runs/`.
- [x] Add tracked 0G/iNFT evidence only if the live mint succeeds; otherwise keep docs explicitly blocked.
- [x] Update README and 0G docs to use truthful "ERC-721-compatible with ERC-7857-style private metadata functions" wording and documented verifier limitations.
- [x] Run Python/API/execution tests, web build, contracts compile/test/deploy-local/audit, AXL smoke, secret scan, `git diff --check`, and merge-tree verification.

## PR Merge-Ready: iNFT Proof And NFT Compatibility Review

- Upgraded `contracts/contracts/HivemindINFT.sol` to expose ERC-165, ERC-721, and ERC-721 metadata compatibility while preserving `mintAgent`, `intelligenceRef`, `updateIntelligenceRef`, `authorizeUsage`, `isAuthorized`, `clone`, and sealed-key transfer behavior.
- Added approval/operator state, `Approval` and `ApprovalForAll` events, `transferFrom`, both `safeTransferFrom` overloads, approval clearing on transfer, and ERC-721 receiver safety checks.
- Updated sealed-key `transfer(from,to,tokenId,sealedKey,proof)` so token owners, approved token spenders, and operators can transfer while still emitting `PublishedSealedKey`; verifier proof validation remains explicitly deferred.
- Added `contracts/contracts/ERC721ReceiverMock.sol` and expanded contract tests to 11 passing cases covering interfaces, metadata, approvals, operator transfer, safe transfers, unauthorized/wrong-from/zero-recipient/nonexistent/unsafe receiver failures, clone, and usage authorization.
- Aligned the SDK crystallization Web3 wrapper with the current six-argument `mintAgent` and `AgentCrystallized` event shape.
- Fresh proof rehearsal saved raw non-secret evidence under ignored `runs/proof-20260501-184559/`: `/health`, `/scenario`, `/state`, `/mint`, and `/state` after mint.
- Live proof succeeded: scenario `merge-proof-20260501-184559`, winner `agent-018`, Galileo token `5`, contract `0x55924a84BD2A5f5e4C63885a2d8f4c129E897A36`, chain `16602`, mint tx `0x8710be02581198e1b5e8e1787cf99b40cd55c829483fd2adc3961ad76c5c1862`, storage root `0xc753be4f5c0d891138e488a0d17099d5e15162cc4ebd0b5b010e44e3b22b9765`.
- Added tracked non-secret proof summary at `docs/evidence/0g-inft-mint-2026-05-01.md`.
- Updated README, 0G docs, 0G escalation history, and contracts README from blocked/ERC-721-like wording to the verified ERC-721-compatible iNFT proof state.
- Verification passed: `npm run compile && npm test` in `contracts` (`11` contract tests); Python/API/AXL/execution pytest (`39 passed`); web build/typecheck; contracts deploy-local; contracts audit high; web audit moderate; AXL smoke (`40` messages, 2 nodes); `git diff --check`; secret scan with only exact redaction-test fixtures allowlisted; `git fetch origin main && git merge-tree --write-tree origin/main HEAD` returned tree `1dc4455bcb2e59e2c543ea61c5f4c744d3b02d0b`.
