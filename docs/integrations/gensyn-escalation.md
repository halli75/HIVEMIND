# Gensyn RL Swarm Escalation Draft

Subject: `RL Swarm connects to Gensyn Testnet, then fails P2P bootstrap to bootnodes 38.101.215.15:30021-30023`

Hi Gensyn team,

I am trying to run RL Swarm in CPU Docker mode from commit `9c95410` on Windows 11 with WSL2 Ubuntu 22.04.5. The login/build path is working, the node authenticates, `swarm.pem` is generated locally, and the runner logs `Connected to Gensyn Testnet`. The remaining blocker is Hivemind P2P bootstrap: all emitted bootnode ports appear unreachable.

Environment:

- Host OS: Windows 11, 64-bit.
- CPU/RAM: Intel Core Ultra 7 155H, 16 cores / 22 logical processors, 16.5 GB physical RAM.
- WSL: Ubuntu 22.04.5 LTS, kernel `6.6.87.2-microsoft-standard-WSL2`.
- Docker: server `28.4.0`, Compose `v2.39.4-desktop.1`, CPU container mode.
- RL Swarm commit: `9c95410`.
- Docker image: `rl-swarm-swarm-cpu:latest`, image id `sha256:901949d93dffeb95ff8dc8c5dde0494d7bacbe421903fe6df03af3fb45dee886`.
- Identity: `swarm.pem` exists locally, contents not shared.
- GPU: `nvidia-smi` in WSL currently fails with `Failed to initialize NVML: N/A`.

What works:

- Modal login patch serves the Gensyn Testnet login page with HTTP 200.
- Browser login completed.
- API key activated.
- `swarm.pem` was generated.
- Runner logged `Connected to Gensyn Testnet`.
- Direct contract reads against `https://gensyn-testnet.g.alchemy.com/public` work: chain id `685685`, current round `28239`, stage `0`, `getBootnodesCount() == 3`.

Failure:

The contract and runner emit these bootnodes:

- `/ip4/38.101.215.15/tcp/30021/p2p/QmQ2gEXoPJg6iMBSUFWGzAabS2VhnzuS782Y637hGjfsRJ`
- `/ip4/38.101.215.15/tcp/30022/p2p/QmWhiaLrx3HRZfgXc2i7KW5nMUNK7P9tRc71yFJdGEZKkC`
- `/ip4/38.101.215.15/tcp/30023/p2p/QmQa1SCfYTxx7RvU7qJJRo79Zm1RAwPpkeLueDVJuBBmFp`

The runner then fails with:

```text
hivemind.p2p.p2p_daemon_bindings.utils.P2PDaemonError: Daemon failed to start: 2026/04/27 04:21:20 failed to connect to bootstrap peers
```

Reachability checks:

- Windows TCP checks to `38.101.215.15:30021-30023`: failed.
- WSL checks: `No route to host`.
- Docker container checks: timeout.
- Independent AWS `us-east-2` probe: `No route to host` to all three ports; traceroute reached `38.104.98.199` and did not reach the bootnode.
- Historical bootnodes observed in older RL Swarm reports, including `38.101.215.12:30011`, `38.101.215.13:30012`, `38.101.215.14:30013`, `38.101.215.14:31111`, `38.101.215.14:31222`, `38.101.215.14:31333`, and `38.101.215.13:30002`, also failed TCP checks.

This no longer looks like a local Docker, WSL, modal-login, browser auth, Hugging Face, or identity issue. Can you confirm whether the on-chain bootnodes are currently expected to be reachable, whether an active official or community-owned swarm endpoint should be used instead, or whether CodeZero requires a replacement bootstrap configuration?

Non-secret evidence files available locally:

- `/root/hivemind-live/gensyn/matrix-cookie-storage/logs/hivemind-retry/live-run.log`
- `/root/hivemind-live/gensyn/matrix-cookie-storage/logs/hivemind-retry/evidence-summary.txt`
- HIVEMIND docs summary: `docs/integrations/gensyn.md`
