#!/usr/bin/env bash
# stop_cluster.sh — terminate every AXL node started by start_cluster.sh.
#
# Reads .axl_cluster.pids, sends SIGTERM to each pid (then SIGKILL after a
# short grace period if needed), and removes the pid file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.axl_cluster.pids"

if [[ ! -f "$PID_FILE" ]]; then
  echo "no $PID_FILE — nothing to stop"
  exit 0
fi

echo "stopping AXL cluster..."
while read -r pid node_id port; do
  [[ -z "${pid:-}" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    echo "  $node_id  pid=$pid  port=$port  -> SIGTERM"
    kill "$pid" 2>/dev/null || true
  else
    echo "  $node_id  pid=$pid  port=$port  -> already gone"
  fi
done < "$PID_FILE"

# Grace period, then force-kill any holdouts.
sleep 1
while read -r pid node_id port; do
  [[ -z "${pid:-}" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    echo "  $node_id  pid=$pid  -> SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
done < "$PID_FILE"

rm -f "$PID_FILE"
echo "cluster stopped."
