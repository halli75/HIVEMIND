from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .node import AxlNodeServer


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a HIVEMIND AXL pool node.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--pool-id", default=None, help="Optional pool id to enforce on REGISTER frames.")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(message)s")
    server = AxlNodeServer(node_id=args.node_id, host=args.host, port=args.port, pool_id=args.pool_id)
    try:
        asyncio.run(server.serve_forever())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
