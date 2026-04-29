#!/usr/bin/env python3
"""AXL pool throughput + latency benchmark.

Spins up N node processes, registers two pool clients (sender / receiver),
sends 1000 TRADE_INTENT and 1000 MARKET_SIGNAL messages between them, and
records throughput, p50/p95 round-trip latency, and per-process resident
memory. Result table is printed and the raw numbers persisted to
benchmark_results.json so the Gensyn submission can quote them verbatim.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = REPO_ROOT / "packages" / "hivemind-sdk" / "src"
NODE_SRC = REPO_ROOT / "apps" / "axl-node" / "src"
RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"

for entry in (str(SDK_SRC), str(NODE_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from hivemind_sdk import AXLPoolManager  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    entries = [str(SDK_SRC), str(NODE_SRC)]
    if env.get("PYTHONPATH"):
        entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


@dataclass
class _NodeProc:
    node_id: str
    port: int
    process: subprocess.Popen[str]


def _start_node(*, node_id: str, port: int, pool_id: str) -> _NodeProc:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hivemind_axl_node",
            "start-node",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--node-id",
            node_id,
            "--pool-id",
            pool_id,
            "--log-level",
            "WARNING",
        ],
        cwd=str(REPO_ROOT),
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return _NodeProc(node_id=node_id, port=port, process=proc)


async def _wait_for_listen(host: str, port: int, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            return
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.05)
    raise RuntimeError(f"node never came up on {host}:{port}")


def _process_rss_kb(pid: int) -> int:
    try:
        # ps reports RSS in kilobytes on Darwin and Linux
        out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip()
        return int(out) if out else 0
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return 0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


@dataclass
class _BenchOutcome:
    node_count: int
    messages_sent: int
    messages_received: int
    duration_s: float
    throughput_msgs_per_s: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_rss_kb: int
    max_rss_kb: int
    failed_nodes: list[str]


async def _run_once(
    *,
    node_count: int,
    pool_id: str,
    trade_intents: int,
    market_signals: int,
) -> _BenchOutcome:
    nodes: list[_NodeProc] = []
    for index in range(node_count):
        port = _free_port()
        nodes.append(_start_node(node_id=f"axl-bench-node-{index}", port=port, pool_id=pool_id))

    try:
        for node in nodes:
            await _wait_for_listen("127.0.0.1", node.port)

        urls = [f"tcp://127.0.0.1:{node.port}" for node in nodes]
        sender = AXLPoolManager(node_urls=urls, pool_id=pool_id, agent_id="bench-sender")
        receiver = AXLPoolManager(node_urls=urls, pool_id=pool_id, agent_id="bench-receiver")
        await sender.connect()
        await receiver.connect()

        # let registrations settle so the receiver is in every node's table
        await asyncio.sleep(0.2)

        total = trade_intents + market_signals
        send_times: dict[int, float] = {}
        latencies: list[float] = []
        received_count = 0

        async def drain_receiver() -> None:
            nonlocal received_count
            idle_iters = 0
            while received_count < total:
                messages = await receiver.receive(timeout=0.5)
                now = time.perf_counter()
                if not messages:
                    if all(node.process.poll() is not None for node in nodes):
                        return
                    idle_iters += 1
                    if idle_iters > 30:
                        return
                    continue
                idle_iters = 0
                for message in messages:
                    seq = message.payload.get("_bench_idx")
                    if isinstance(seq, int):
                        sent_at = send_times.pop(seq, None)
                        if sent_at is not None:
                            latencies.append((now - sent_at) * 1000)
                    received_count += 1

        drain_task = asyncio.create_task(drain_receiver())

        start = time.perf_counter()
        for index in range(trade_intents):
            payload = {
                "_bench_idx": index,
                "agent_id": "bench-sender",
                "scenario_id": f"bench-{index:04d}",
                "action": "buy" if index % 2 == 0 else "sell",
                "confidence": 0.5 + (index % 7) * 0.05,
                "size_usd": 250_000 + index,
            }
            send_times[index] = time.perf_counter()
            await sender.send("bench-receiver", "TRADE_INTENT", payload)

        for index in range(market_signals):
            seq = trade_intents + index
            payload = {
                "_bench_idx": seq,
                "scenario_id": f"bench-{index:04d}",
                "signal_strength": 0.4 + (index % 5) * 0.1,
                "direction": "buy" if index % 2 == 0 else "sell",
                "target_agent_id": "bench-receiver",
            }
            send_times[seq] = time.perf_counter()
            await sender.send("bench-receiver", "MARKET_SIGNAL", payload)
        send_done = time.perf_counter()

        try:
            await asyncio.wait_for(drain_task, timeout=20.0)
        except asyncio.TimeoutError:
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task

        end = time.perf_counter()
        duration = max(end - start, 1e-6)
        throughput = received_count / duration if duration else 0.0
        p50 = _percentile(latencies, 0.5)
        p95 = _percentile(latencies, 0.95)

        rss_samples = [_process_rss_kb(node.process.pid) for node in nodes]
        rss_samples = [v for v in rss_samples if v > 0]

        await sender.disconnect()
        await receiver.disconnect()

        failed = [
            node.node_id
            for node in nodes
            if node.process.poll() is not None
        ]

        return _BenchOutcome(
            node_count=node_count,
            messages_sent=total,
            messages_received=received_count,
            duration_s=round(duration, 4),
            throughput_msgs_per_s=round(throughput, 2),
            p50_latency_ms=round(p50, 3),
            p95_latency_ms=round(p95, 3),
            avg_rss_kb=int(round(statistics.mean(rss_samples))) if rss_samples else 0,
            max_rss_kb=max(rss_samples) if rss_samples else 0,
            failed_nodes=failed,
        )
    finally:
        for node in nodes:
            with contextlib.suppress(ProcessLookupError):
                node.process.terminate()
        for node in nodes:
            try:
                node.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    node.process.kill()


def _format_table(outcomes: list[_BenchOutcome]) -> str:
    headers = [
        "nodes",
        "msgs_sent",
        "msgs_recv",
        "duration_s",
        "msgs/sec",
        "p50_ms",
        "p95_ms",
        "avg_rss_mb",
        "max_rss_mb",
    ]
    rows: list[list[str]] = [headers]
    for outcome in outcomes:
        rows.append(
            [
                str(outcome.node_count),
                str(outcome.messages_sent),
                str(outcome.messages_received),
                f"{outcome.duration_s:.3f}",
                f"{outcome.throughput_msgs_per_s:.2f}",
                f"{outcome.p50_latency_ms:.3f}",
                f"{outcome.p95_latency_ms:.3f}",
                f"{outcome.avg_rss_kb / 1024:.1f}",
                f"{outcome.max_rss_kb / 1024:.1f}",
            ]
        )
    widths = [max(len(row[col]) for row in rows) for col in range(len(headers))]
    sep = "+".join("-" * (width + 2) for width in widths)
    sep = f"+{sep}+"
    lines = [sep]
    for index, row in enumerate(rows):
        cells = [f" {row[col].ljust(widths[col])} " for col in range(len(headers))]
        lines.append("|" + "|".join(cells) + "|")
        if index == 0:
            lines.append(sep)
    lines.append(sep)
    return "\n".join(lines)


def _outcome_to_dict(outcome: _BenchOutcome) -> dict[str, Any]:
    return {
        "node_count": outcome.node_count,
        "messages_sent": outcome.messages_sent,
        "messages_received": outcome.messages_received,
        "duration_s": outcome.duration_s,
        "throughput_msgs_per_s": outcome.throughput_msgs_per_s,
        "p50_latency_ms": outcome.p50_latency_ms,
        "p95_latency_ms": outcome.p95_latency_ms,
        "avg_rss_kb": outcome.avg_rss_kb,
        "max_rss_kb": outcome.max_rss_kb,
        "failed_nodes": outcome.failed_nodes,
    }


async def _run(node_counts: list[int], trade_intents: int, market_signals: int, pool_id: str) -> list[_BenchOutcome]:
    outcomes: list[_BenchOutcome] = []
    for count in node_counts:
        outcome = await _run_once(
            node_count=count,
            pool_id=pool_id,
            trade_intents=trade_intents,
            market_signals=market_signals,
        )
        outcomes.append(outcome)
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AXL pool benchmark.")
    parser.add_argument("--nodes", default="2,5", help="Comma-separated list of node counts to benchmark.")
    parser.add_argument("--trade-intents", type=int, default=1000)
    parser.add_argument("--market-signals", type=int, default=1000)
    parser.add_argument("--pool-id", default="hivemind-bench")
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    args = parser.parse_args(argv)

    node_counts = [int(value) for value in args.nodes.split(",") if value.strip()]
    outcomes = asyncio.run(
        _run(
            node_counts=node_counts,
            trade_intents=args.trade_intents,
            market_signals=args.market_signals,
            pool_id=args.pool_id,
        )
    )
    table = _format_table(outcomes)
    print(table)

    payload = {
        "schema": "hivemind.axl.benchmark.v1",
        "trade_intents_per_run": args.trade_intents,
        "market_signals_per_run": args.market_signals,
        "pool_id": args.pool_id,
        "results": [_outcome_to_dict(outcome) for outcome in outcomes],
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    with args.results.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"\nresults written to {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
