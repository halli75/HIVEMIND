#!/usr/bin/env bash
# Run RL Swarm with a self-hosted Hivemind bootnode to bypass dead Gensyn official bootnodes.
# Usage (from WSL): bash /path/to/HIVEMIND/scripts/run-gensyn-self-hosted.sh
set -euo pipefail

RL_SWARM=/root/hivemind-live/gensyn/matrix-cookie-storage
HIVEMIND_REPO=/root/hivemind-live/gensyn/matrix-cookie-storage  # same workspace
IMAGE=matrix-cookie-storage-swarm-cpu
NETWORK=swarm-boot-net
BOOTNODE_PORT=30021
BOOTNODE_NAME=hivemind-bootnode
ADDR_FILE=/tmp/bootnode_addr.txt
BOOTNODE_SCRIPT="$(dirname "$0")/../services/hivemind-bootnode/bootnode.py"

# Resolve to absolute path in case caller used a relative path
BOOTNODE_SCRIPT=$(realpath "$BOOTNODE_SCRIPT")

echo "==> 1. Ensuring Docker named network: $NETWORK"
docker network inspect "$NETWORK" >/dev/null 2>&1 \
  || docker network create "$NETWORK"

echo "==> 2. Applying patches to temp copies of RL Swarm source"
PATCHED_MANAGER=$(mktemp /tmp/manager_XXXXXX.py)
PATCHED_PROPOSER=$(mktemp /tmp/proposer_XXXXXX.py)
cp "$RL_SWARM/code_gen_exp/src/manager.py" "$PATCHED_MANAGER"
cp "$RL_SWARM/code_gen_exp/src/proposer_service.py" "$PATCHED_PROPOSER"
# World-readable so the container's gensyn user (uid 1001) can read them
chmod 644 "$PATCHED_MANAGER" "$PATCHED_PROPOSER"

python3 - "$PATCHED_MANAGER" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path).read()
needle = (
    "        initial_peers = coordinator.get_bootnodes()\n"
    "        communication_kwargs['initial_peers'] = initial_peers"
)
replacement = (
    "        _env = os.environ.get(\"HIVEMIND_INITIAL_PEERS\", \"\")\n"
    "        initial_peers = [p for p in _env.split(\",\") if p] or coordinator.get_bootnodes()\n"
    "        communication_kwargs['initial_peers'] = initial_peers"
)
assert needle in src, "manager.py patch target not found — check line content"
open(path, 'w').write(src.replace(needle, replacement))
print(f"  patched: {path}")
PYEOF

python3 - "$PATCHED_PROPOSER" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path).read()
# Add 'import os' after 'from dataclasses import dataclass'
src = src.replace(
    "from dataclasses import dataclass\nimport logging",
    "from dataclasses import dataclass\nimport os\nimport logging",
    1
)
needle = (
    "        initial_peers = coordinator.get_bootnodes() if coordinator is not None else None"
)
replacement = (
    "        _env = os.environ.get(\"HIVEMIND_INITIAL_PEERS\", \"\")\n"
    "        initial_peers = [p for p in _env.split(\",\") if p] or (coordinator.get_bootnodes() if coordinator is not None else None)"
)
assert needle in src, "proposer_service.py patch target not found — check line content"
open(path, 'w').write(src.replace(needle, replacement))
print(f"  patched: {path}")
PYEOF

echo "==> 3. Starting self-hosted bootnode container"
# Clean up any stale bootnode container
docker rm -f "$BOOTNODE_NAME" 2>/dev/null || true
rm -f "$ADDR_FILE"

docker run -d --rm \
  --name "$BOOTNODE_NAME" \
  --network "$NETWORK" \
  -e BOOTNODE_PORT="$BOOTNODE_PORT" \
  -e BOOTNODE_SERVICE_NAME="$BOOTNODE_NAME" \
  -e BOOTNODE_ADDR_FILE=/tmp/bootnode_addr.txt \
  -v /tmp:/tmp \
  -v "$BOOTNODE_SCRIPT":/bootnode.py:ro \
  "$IMAGE" \
  python /bootnode.py

echo "==> 4. Waiting for bootnode multiaddr (up to 15s)"
for i in $(seq 1 15); do
  if [[ -f "$ADDR_FILE" ]]; then break; fi
  sleep 1
done

if [[ ! -f "$ADDR_FILE" ]]; then
  echo "ERROR: bootnode did not write address file after 15s"
  echo "  Container logs:"
  docker logs "$BOOTNODE_NAME" 2>&1 | tail -20
  exit 1
fi

BOOTNODE_ADDR=$(cat "$ADDR_FILE")
echo "  Bootnode multiaddr: $BOOTNODE_ADDR"

echo "==> 5. Generating docker-compose.run.yml override"
cat > /tmp/docker-compose.run.yml <<EOF
services:
  swarm-cpu:
    environment:
      HIVEMIND_INITIAL_PEERS: "$BOOTNODE_ADDR"
      HIVEMIND_NONINTERACTIVE: "1"
    volumes:
      - $PATCHED_MANAGER:/home/gensyn/rl_swarm/code_gen_exp/src/manager.py:ro
      - $PATCHED_PROPOSER:/home/gensyn/rl_swarm/code_gen_exp/src/proposer_service.py:ro
    networks:
      - default
      - $NETWORK
networks:
  $NETWORK:
    external: true
EOF

echo "  Override written to /tmp/docker-compose.run.yml"

echo "==> 6. Launching RL Swarm CPU container"
echo "  Watch for: bootnodes: ['/dns4/hivemind-bootnode/...']"
echo "  Watch for: Successfully joined the DHT"
echo "  Watch for absence of: failed to connect to bootstrap peers"
echo ""

cd "$RL_SWARM"
docker compose -f docker-compose.yaml -f /tmp/docker-compose.run.yml --profile swarm up swarm-cpu
