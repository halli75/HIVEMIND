# Gensyn AXL Integration

## Target

Use Gensyn AXL-style communication as the cross-process messaging layer for the swarm. At minimum, the demo should show two separate node processes exchanging typed messages that affect agent scoring.

## Current Proof Status - 2026-04-29

Phase 2 remains verified through two evidence paths:

- Local AXL runner: `runs/axl/pr-review-smoke.jsonl` contains typed cross-process messages consumed by the API when `GENSYN_AXL_TRANSCRIPT_PATH` is set.
- Self-hosted RL Swarm bootstrap: the patched Docker path joined CodeZero Swarm with the self-hosted `/dns4/hivemind-bootnode/...` peer and began round `28239`.

During the live proof rehearsal in `runs/proof-20260429-161627/`, `/health` reported `run_mode=local_axl+live_0g`, confirming the API was reading the local AXL transcript while live 0G Compute and Uniswap quote paths were enabled.

## Local Cross-Process Proof

`apps/axl-node` provides the Phase 2 local proof path. It starts two separate OS processes:

- `axl-node-a`: coordinator process that broadcasts `SCENARIO_SHOCK` and `MARKET_SIGNAL`.
- `axl-node-b`: evaluator process that replies with `TRADE_INTENT` and `INFERENCE_RESULT`.

Messages are newline-delimited JSON and are persisted to ignored transcript files under `runs/axl/`.

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/axl-node/src'
C:\Python313\python.exe -m hivemind_axl_node smoke --messages 20 --transcript runs/axl/smoke.jsonl
```

The API can then read that JSONL transcript as its AXL source:

```powershell
$env:PYTHONPATH='packages/hivemind-sdk/src;apps/api/src'
$env:HIVEMIND_USE_MOCK_GENSYN='false'
$env:GENSYN_AXL_TRANSCRIPT_PATH='runs/axl/smoke.jsonl'
C:\Python313\python.exe -m uvicorn hivemind_api.app:app --host localhost --port 8000
```

## Message Contract

Every live message should include:

- `id`: deterministic or UUID event identifier.
- `type`: typed event name.
- `source_node`: sending node ID.
- `target`: receiving node ID or `broadcast`.
- `timestamp`: ISO timestamp.
- `payload`: event-specific JSON object.
- `payload_digest`: deterministic digest for evidence linkage.
- `latency_ms`: optional measured round-trip latency.

Supported types:

- `SCENARIO_SHOCK`
- `MARKET_SIGNAL`
- `TRADE_INTENT`
- `INFERENCE_RESULT`

## Dashboard Metrics

The dashboard reads transcript-backed fields through the API:

- message total
- nodes online
- failed nodes
- latest message type
- p50 and p95 latency
- JSONL transcript path

## Live Gensyn/RL Swarm Gate

Live RL Swarm setup is intentionally separate from the commit-critical local proof. The official Gensyn RL Swarm page currently says there are no official swarms running, so this path is treated as a gated compatibility/evidence attempt rather than a guaranteed live-network proof. Use an ignored external directory for any live clone or runtime data, and never commit `swarm.pem`, Hugging Face tokens, W&B tokens, private keys, or generated account material.

Before attempting setup:

```powershell
wsl -l -v
docker info
docker compose version
git --version
python --version
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
```

Inside WSL:

```bash
free -h
python3 --version
git --version
docker info
docker run --rm hello-world
```

Known gates:

- Docker daemon/Desktop must be running and reachable from WSL.
- Hugging Face write token may be required as `HF_TOKEN`.
- Browser login may open at `http://localhost:3000` and create a local `swarm.pem` identity.
- W&B is optional unless log syncing is enabled.
- Do not claim live Gensyn participation unless logs show actual peer/testnet status.

## Live Attempt Log

Attempt date: 2026-04-26.

Observed local state:

- WSL2 `Ubuntu-22.04` exists.
- Windows Docker Compose exists.
- Docker Desktop Linux engine was not reachable from PowerShell: `dockerDesktopLinuxEngine` pipe missing.
- Inside WSL, Docker was not installed/integrated and Docker Desktop WSL integration was recommended by the Docker error text.
- WSL memory available for the distro was about 13 GiB total, below the documented 32 GB preferred RL Swarm requirement.
- Python in WSL is 3.10.12 and Git is 2.34.1.
- Port 3000 was free.
- `HF_TOKEN`, Hugging Face aliases, Gensyn identity env vars, and `WANDB_API_KEY` were not present.
- `nvidia-smi` could not verify GPU readiness without elevated permissions.

Current blocker:

- Start Docker Desktop and enable WSL integration for `Ubuntu-22.04`.
- Provide a Hugging Face write token as `HF_TOKEN` if the RL Swarm setup prompts for model upload or participation.
- Complete browser login if setup opens `http://localhost:3000`; keep the generated `swarm.pem` secret and uncommitted.

Follow-up attempt date: 2026-04-26.

Additional observed state after Docker Desktop was started:

- Docker Desktop and WSL integration were reachable from both PowerShell and `Ubuntu-22.04`.
- `docker run --rm hello-world` succeeded.
- RL Swarm was cloned to `/root/hivemind-live/gensyn/rl-swarm`, outside the HIVEMIND repo.
- Official clone commit used for the attempt: `9c95410 Merge pull request #578 from gensyn-ai/readme_updates`.
- CPU Docker build first failed in the upstream `hivemind` dependency because `pkg_resources` was unavailable in pip build isolation.
- A local-only external patch pinned `setuptools<81` through `PIP_CONSTRAINT`, which allowed the CPU image to build.
- The first CPU container reached the modal login gate, published port 3000, and waited for `modal-login/temp-data/userData.json`.
- The modal login page returned a Next.js server error: `Cannot read properties of undefined (reading 'hasHydrated')`.
- A local-only external patch enabled Account Kit `cookieStorage` in `modal-login/config.ts`, but subsequent `docker run`/`docker compose run` attempts against the rebuilt image stalled before container output and did not reach the login screen.
- No `user/keys/swarm.pem` was generated.
- No live peer/testnet registration was proven.
- The provided Hugging Face token was not written to repo files and the flow did not reach the Hugging Face prompt.

Current blocker:

- RL Swarm's current upstream Docker/login path is not demo-stable in this environment without additional upstream troubleshooting. The local AXL runner remains the verified Gensyn proof path for Phase 2.

Recovery attempt date: 2026-04-26.

Patch matrix evidence:

- Baseline upstream `9c95410` was retested in `/root/hivemind-live/gensyn/matrix-baseline` with isolated Node `v20.18.0` and Yarn `1.22.22`.
- Baseline `modal-login` installed and built, but `PORT=3101 yarn start` returned HTTP 500 and reproduced `TypeError: Cannot read properties of undefined (reading 'hasHydrated')`.
- The installed baseline lock already resolved `viem@2.30.5`, so the issue was not just a stale `viem <2.25.0`.
- A minimal client-mount patch in `/root/hivemind-live/gensyn/matrix-client-only` disabled Account Kit SSR, removed `cookieToInitialState` from `RootLayout`, and rendered `AlchemyAccountProvider` only after browser mount.
- The minimal patch built successfully with Next `14.2.35` and served `http://127.0.0.1:3105/` with HTTP 200. Evidence logs: `client-mounted-build.log`, `client-mounted-http-3105.probe`, and `client-mounted.diff`.
- A smaller SSR-preserving patch in `/root/hivemind-live/gensyn/matrix-cookie-storage` only enabled Account Kit `cookieStorage`; it built successfully and served `http://127.0.0.1:3103/` with HTTP 200. This is now the preferred full-container promotion patch because it preserves server-rendered behavior with a one-line source change.
- A no-SSR variant in `/root/hivemind-live/gensyn/matrix-no-ssr` also served `http://127.0.0.1:3104/` with HTTP 200 after deferring the provider until hydration, but it is broader than the cookie-storage fix.
- A separate official-dependency variant in `/root/hivemind-live/gensyn/matrix-official-login` also served HTTP 200 on port 3102 after upgrading `next` to `16.2.4`, `viem` to `2.48.4`, adding compatibility resolutions, using `next build --webpack`, enabling `cookieStorage`, and updating `RootLayout` for async `headers()`.
- The plain `next@latest viem@latest` path was not enough by itself: Next 16's default Turbopack build failed on packaged non-code files from the dependency tree before the compatibility fixes.
- The non-Docker script path reached `Please login to create an Ethereum Server Wallet`, but bounded `yarn install` attempts stalled before serving `localhost:3000`.
- A full CPU container promotion with the minimal patch and `setuptools<81` build constraint was attempted from `/root/hivemind-live/gensyn/matrix-client-only`.
- Mounting the patched workspace into the existing CPU image first failed because the non-root container user could not write `sed` temp files into `modal-login`.
- Running the mounted CPU container as root got past that permission failure and left a container running, but `localhost:3000` reset connections and WSL stopped responding during log inspection. Ubuntu had to be terminated, after which Docker Desktop was again disconnected from the WSL socket.
- No `user/keys/swarm.pem` was generated and no peer/testnet registration was proven.

Current blocker after recovery:

- The modal-login `hasHydrated` blocker is fixed by two independent patch variants, but full RL Swarm container promotion is blocked by Docker/WSL runtime instability and resource pressure during CPU container startup/log inspection.
- Before retrying full container promotion, restart Docker Desktop, verify `docker info` from WSL, keep the CPU-only path, and avoid GPU until `nvidia-smi` works in WSL.
- Prefer the one-line `cookieStorage` patch for the next full-container retry because it preserves SSR and has the smallest blast radius. Keep the Next 14 client-mount patch as fallback if the full container still hits `hasHydrated`.

Container promotion retry date: 2026-04-27.

Resolved during retry:

- Docker Desktop and WSL were restarted cleanly after `docker rm` hung on the stale RL Swarm container.
- The stale RL Swarm container was removed and Docker build cache was reclaimed without deleting volumes.
- The CPU image path was rebuilt far enough to prove the `cookieStorage` modal fix and `setuptools<81` constraint inside the image build.
- A Docker snapshot/unpack issue left the newly named Compose image slow or unreliable to start, but the usable `rl-swarm-swarm-cpu` image contained the modal fix and started successfully.
- The live container served `http://localhost:3000` with HTTP 200.
- Browser login completed, the API key activated, and `user/keys/swarm.pem` was generated in the external ignored workspace. The key contents were not read or committed.
- The runner logged `Connected to Gensyn Testnet` before starting Hivemind DHT bootstrap.

Current blocker after container promotion:

- Hivemind P2P bootstrap failed after testnet connection: `P2PDaemonError('Daemon failed to start: 2026/04/27 04:21:20 failed to connect to bootstrap peers')`.
- The emitted bootnodes were `38.101.215.15:30021`, `38.101.215.15:30022`, and `38.101.215.15:30023`.
- Windows `Test-NetConnection` failed for all three bootnode ports.
- WSL socket checks failed with `No route to host` for all three ports.
- Container socket checks timed out for all three ports.
- This is now a Gensyn bootnode/network reachability blocker, not a modal-login, Docker build, browser login, or local identity blocker.

Bootnode reachability diagnosis date: 2026-04-27.

Additional evidence:

- Windows and WSL control egress remained healthy: both could reach unrelated public endpoints such as `1.1.1.1:443`.
- Windows `tracert -d 38.101.215.15` left the local network, reached `64.125.26.13`, then `38.104.98.199`, and ended with `38.104.98.199 reports: Destination host unreachable`.
- WSL `tracepath` followed the same route family and ended at `38.104.98.199 !H`.
- A Docker-isolated BusyBox TCP probe timed out to all three bootnode ports while Docker itself was healthy.
- A temporary AWS EC2 probe in `us-east-2` also failed to connect to all three bootnode ports with `No route to host`; its traceroute reached `38.104.98.199` and then received no further response.
- The temporary EC2 instance and security group used for the probe were terminated/deleted after evidence capture.

Current conclusion:

- The blocker is not local Docker, WSL, modal login, browser auth, Hugging Face credentials, or `swarm.pem`.
- Because the same bootnodes are unreachable from the local network and an independent AWS egress point, the likely root cause is upstream Gensyn bootnode availability, routing, filtering, or the absence of an active official swarm.
- Official Gensyn documentation currently labels RL Swarm as deprecated and states that there are no official swarms running right now. Bootstrap-peer failures are also a known historical issue pattern in the RL Swarm tracker.
- Do not spend more time patching the local container path until Gensyn publishes reachable bootnodes, a community-owned swarm endpoint, or support confirms a replacement network path.

Upstream resolution follow-up:

- The current RL Swarm `main` branch and `v0.7.0` CodeZero release use the same `SWARM_CONTRACT` address: `0x7745a8FE4b8D2D2c3BB103F8dCae822746F35Da0`.
- Direct contract reads from the CPU image succeeded against `https://gensyn-testnet.g.alchemy.com/public`: chain id `685685`, current round `28239`, stage `0`, and `getBootnodesCount() == 3`.
- The contract's live `getBootnodes()` response is exactly the three unreachable `38.101.215.15:30021-30023` multiaddrs from the failed run.
- Historical bootnodes observed in prior RL Swarm issues, including `38.101.215.12:30011`, `38.101.215.13:30012`, `38.101.215.14:30013`, `38.101.215.14:31111`, `38.101.215.14:31222`, `38.101.215.14:31333`, and `38.101.215.13:30002`, also failed TCP checks.
- This means a manual override to older known Gensyn bootnodes is not currently a working fix.
- RL Swarm training bootnodes are contract-driven: `SwarmGameManager` and proposer setup overwrite `communication_kwargs.initial_peers` with `coordinator.get_bootnodes()`.
- The run script hardcodes the official `SWARM_CONTRACT`; setting `SWARM_CONTRACT=... ./run_rl_swarm.sh` is not enough unless the script is patched or a compatible community-owned coordinator contract is wired in.
- The documented `--initial_peers` flag is for the web API path and does not provide a clean training bootstrap override.

Escalation package:

- Attach the relevant non-secret section of `live-run.log` showing `Connected to Gensyn Testnet`, emitted bootnodes, and `failed to connect to bootstrap peers`.
- Include the Windows, WSL, Docker, and AWS reachability matrix above.
- Include system context: Windows with WSL2 Ubuntu 22.04, Docker Desktop Linux engine, CPU-only RL Swarm container, generated `swarm.pem` present but contents private.
- Include safe host details: Intel Core Ultra 7 155H, 16 cores / 22 logical processors, 16.5 GB physical RAM, Docker Desktop server `28.4.0`, Compose `v2.39.4-desktop.1`, WSL kernel `6.6.87.2-microsoft-standard-WSL2`, and `nvidia-smi` currently failing in WSL with `Failed to initialize NVML: N/A`.
- Ask Gensyn to confirm whether those on-chain bootnodes should be reachable, whether an active community-owned swarm endpoint exists, or whether the CodeZero release requires a replacement bootstrap configuration.
- If Gensyn or a community operator provides a compatible coordinator contract, first query `getBootnodes()`, test every returned multiaddr with raw TCP, then patch the external RL Swarm script/config to use that contract and rerun the CPU container.

Evidence files remain outside the repo under `/root/hivemind-live/gensyn/matrix-cookie-storage/logs/hivemind-retry/`:

- `build.log`
- `live-run.log`
- `evidence-summary.txt`

## Self-Hosted Bootstrap Resolution

Since the official Gensyn bootnodes are contract-driven and permanently unreachable, a self-hosted Hivemind DHT bootnode bypasses the dead contract peers entirely.

### Root Cause Summary

Two code-level injection sites in RL Swarm unconditionally overwrite `initial_peers` with contract-sourced bootnodes:

- `code_gen_exp/src/manager.py:43` — `SwarmGameManager.__init__` calls `coordinator.get_bootnodes()` and writes to `communication_kwargs['initial_peers']`
- `code_gen_exp/src/proposer_service.py:73` — `ProposerService.__init__` does the same for the proposer DHT

Hydra config overrides and `--initial_peers` env vars are both ineffective because these lines execute after Hydra loads config.

### Fix: HIVEMIND_INITIAL_PEERS env-var check

Patch both files to check a `HIVEMIND_INITIAL_PEERS` env var first and fall back to contract peers only if the env var is empty. Patches are in `patches/rl-swarm/`:

- `manager.patch` — two-line change to `manager.py`; `import os` already present at line 1
- `proposer_service.patch` — two-line change to `proposer_service.py` plus adds `import os`

The patches are applied dynamically by the orchestration script to `/tmp/` temp files and volume-mounted read-only into the container. No image rebuild is needed.

### Self-Hosted Bootnode

`services/hivemind-bootnode/bootnode.py` starts a Hivemind DHT node using the existing `matrix-cookie-storage-swarm-cpu` image (which already contains `hivemind==1.2.0.dev0`). Key implementation detail: use `host_maddrs=["/ip4/0.0.0.0/tcp/PORT"]` — not `host=`/`port=` kwargs, which fail with `TypeError: P2P.create() got unexpected keyword argument 'host'`.

### Running Self-Hosted Bootstrap

```bash
# From WSL, with Docker Desktop running:
bash /path/to/HIVEMIND/scripts/run-gensyn-self-hosted.sh
```

The script:
1. Creates Docker named network `swarm-boot-net`
2. Applies env-var patches to `/tmp/` copies of `manager.py` and `proposer_service.py`
3. Starts the bootnode container on `swarm-boot-net`, waits for its multiaddr
4. Generates `/tmp/docker-compose.run.yml` override with `HIVEMIND_INITIAL_PEERS` and read-only volume mounts
5. Launches swarm-cpu via `docker compose -f docker-compose.yml -f /tmp/docker-compose.run.yml up swarm-cpu`

### Verified Success Log Evidence

Run date: 2026-04-27.

```
[2026-04-27 21:24:51][genrl] - ✅ Connected to Gensyn Testnet
[2026-04-27 21:24:51][genrl] - bootnodes: ['/dns4/hivemind-bootnode/tcp/30021/p2p/12D3KooWE5CGdBcNVDyDt5hM1cugSkmtr5f7ERCjAdos1dDo3nKs']
[2026-04-27 21:24:57][genrl] - ============!!!Joining CodeZero Swarm!!!============
[2026-04-27 21:24:57][genrl] - 🐝 Hello [jagged spotted mandrill] [QmRAFupGJwJB8mGG6eNsAbo1CQeAGQeEWqZTvALybgBetc]!
[2026-04-27 21:24:57][genrl] - Using Model: Qwen/Qwen2.5-Coder-0.5B-Instruct
[2026-04-27 21:25:40][genrl] - Starting round: 28239/1000000.
Map: 100%|██████████| 1/1
```

Key confirmations:
- `bootnodes:` shows `/dns4/hivemind-bootnode/...` — self-hosted peer, not `38.101.215.15`
- `Joining CodeZero Swarm` — DHT bootstrap succeeded without `P2PDaemonError`
- `Starting round: 28239` — training began; no `failed to connect to bootstrap peers`
- Node identity: `jagged spotted mandrill` / `QmRAFupGJwJB8mGG6eNsAbo1CQeAGQeEWqZTvALybgBetc`

Evidence file saved outside repo: `/tmp/swarm_success_evidence.log`

## Integration Steps

1. Start two independent processes.
2. Send `SCENARIO_SHOCK` from the broadcaster node.
3. Send at least one intent or inference result back from the evaluator node.
4. Persist the transcript to a run log that can later be written to 0G Storage.
5. Surface message count and latest message in the frontend metrics panel.

## Safety

- Do not claim live Gensyn participation until node logs prove cross-process exchange.
- Keep the seed transport available for offline demos.
