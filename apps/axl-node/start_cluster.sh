#!/usr/bin/env bash
# start_cluster.sh — boot N AXL node processes in the background.
#
# Usage:
#   ./start_cluster.sh [N]
#
# N must be 2, 3, or 5 (the supported cluster sizes for the benchmark
# and the demo SwarmEngine integration). Defaults to 3 if omitted.
#
# Each node listens on TCP port 7000+i (so N=5 uses 7001..7005), logs to
# logs/axl-<i>.log, and its PID is recorded in .axl_cluster.pids so that
# stop_cluster.sh can shut the cluster down cleanly.

set -euo pipefail

N="${1:-3}"

case "$N" in
  2|3|5) ;;
  *)
    echo "error: N must be 2, 3, or 5 (got '$N')" >&2
    echo "usage: $0 [2|3|5]" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$SCRIPT_DIR/.axl_cluster.pids"
LOG_DIR="$SCRIPT_DIR/logs"
POOL_ID="${HIVEMIND_AXL_POOL_ID:-hivemind-main}"

if [[ -f "$PID_FILE" ]]; then
  echo "error: $PID_FILE already exists — run ./stop_cluster.sh first" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$REPO_ROOT/packages/hivemind-sdk/src:$REPO_ROOT/apps/axl-node/src"

PYTHON_BIN="${HIVEMIND_PYTHON:-python3}"

echo "starting $N AXL node(s) (pool=$POOL_ID)..."
: > "$PID_FILE"

for i in $(seq 1 "$N"); do
  PORT=$((7000 + i))
  NODE_ID="axl-$i"
  LOG_FILE="$LOG_DIR/axl-$i.log"

  "$PYTHON_BIN" -m hivemind_axl_node start-node \
    --port "$PORT" \
    --node-id "$NODE_ID" \
    --pool-id "$POOL_ID" \
    >"$LOG_FILE" 2>&1 &

  PID=$!
  echo "$PID $NODE_ID $PORT" >> "$PID_FILE"
  echo "  $NODE_ID  pid=$PID  port=$PORT  log=$LOG_FILE"
done

echo "all $N nodes booted. stop with ./stop_cluster.sh"
