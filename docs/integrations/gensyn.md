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

## Integration Steps

1. Start two independent processes.
2. Send `SCENARIO_SHOCK` from the broadcaster node.
3. Send at least one intent or inference result back from the evaluator node.
4. Persist the transcript to a run log that can later be written to 0G Storage.
5. Surface message count and latest message in the frontend metrics panel.

## Safety

- Do not claim live Gensyn participation until node logs prove cross-process exchange.
- Keep the seed transport available for offline demos.
