# Gensyn AXL Integration Plan

## Target

Use Gensyn AXL-style communication as the cross-process messaging layer for the swarm. At minimum, the demo should show two separate node processes exchanging typed messages that affect agent scoring.

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

## Integration Steps

1. Start two independent processes.
2. Send `SCENARIO_SHOCK` from the broadcaster node.
3. Send at least one intent or inference result back from the evaluator node.
4. Persist the transcript to a run log that can later be written to 0G Storage.
5. Surface message count and latest message in the frontend metrics panel.

## Safety

- Do not claim live Gensyn participation until node logs prove cross-process exchange.
- Keep the seed transport available for offline demos.
