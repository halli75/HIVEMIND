from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hivemind_sdk import AxlMessage, append_jsonl, transcript_stats

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
COORDINATOR_NODE_ID = "axl-node-a"
EVALUATOR_NODE_ID = "axl-node-b"


def _encode(message: AxlMessage) -> bytes:
    return json.dumps(message.to_dict(), sort_keys=True).encode("utf-8") + b"\n"


async def _read_message(reader: asyncio.StreamReader) -> AxlMessage:
    line = await reader.readline()
    if not line:
        raise ConnectionError("peer closed the AXL stream")
    payload = json.loads(line.decode("utf-8"))
    return AxlMessage.from_dict(payload)


def _latency_ms(sent_at: float) -> float:
    return (time.perf_counter() - sent_at) * 1000


async def run_coordinator(
    *,
    host: str,
    port: int,
    transcript: Path,
    messages: int,
    node_id: str = COORDINATOR_NODE_ID,
) -> int:
    peer_done = asyncio.Event()
    result: dict[str, int] = {"messages": 0}

    async def handle_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_node = EVALUATOR_NODE_ID
        try:
            for index in range(messages):
                message_type = "SCENARIO_SHOCK" if index % 2 == 0 else "MARKET_SIGNAL"
                outbound = AxlMessage.create(
                    source_node=node_id,
                    target=peer_node,
                    message_type=message_type,
                    payload={
                        "scenario_id": f"local-axl-smoke-{index // 2:03d}",
                        "sequence": index + 1,
                        "signal_strength": round(0.45 + (index % 7) * 0.06, 3),
                    },
                )
                append_jsonl(transcript, outbound)
                sent_at = time.perf_counter()
                writer.write(_encode(outbound))
                await writer.drain()

                inbound = await _read_message(reader)
                inbound = AxlMessage.create(
                    source_node=inbound.source_node,
                    target=inbound.target,
                    message_type=inbound.type,
                    payload=inbound.payload,
                    timestamp=inbound.timestamp,
                    latency_ms=_latency_ms(sent_at),
                )
                append_jsonl(transcript, inbound)
                result["messages"] += 2
        except ConnectionError:
            failure = AxlMessage.create(
                source_node=node_id,
                target="broadcast",
                message_type="MARKET_SIGNAL",
                payload={"signal": "node_failure", "node_id": peer_node, "reason": "stream_closed"},
            )
            append_jsonl(transcript, failure)
        finally:
            writer.close()
            await writer.wait_closed()
            peer_done.set()

    server = await asyncio.start_server(handle_peer, host, port)
    async with server:
        await server.start_serving()
        await peer_done.wait()
        server.close()
        await server.wait_closed()

    return 0 if result["messages"] >= messages * 2 else 1


async def run_evaluator(
    *,
    host: str,
    port: int,
    node_id: str = EVALUATOR_NODE_ID,
) -> int:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        sequence = 0
        while True:
            try:
                inbound = await _read_message(reader)
            except ConnectionError:
                break
            response_type = "TRADE_INTENT" if sequence % 2 == 0 else "INFERENCE_RESULT"
            response = AxlMessage.create(
                source_node=node_id,
                target=inbound.source_node,
                message_type=response_type,
                payload={
                    "received_message_id": inbound.id,
                    "sequence": sequence + 1,
                    "decision": "hedge" if response_type == "TRADE_INTENT" else "rank_adjustment",
                    "confidence": round(0.61 + (sequence % 5) * 0.045, 3),
                    "payload_digest": inbound.payload_digest,
                },
            )
            writer.write(_encode(response))
            await writer.drain()
            sequence += 1
    finally:
        writer.close()
        await writer.wait_closed()
    return 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _subprocess_env() -> dict[str, str]:
    root = _repo_root()
    entries = [
        str(root / "packages" / "hivemind-sdk" / "src"),
        str(root / "apps" / "axl-node" / "src"),
    ]
    current = os.environ.get("PYTHONPATH")
    if current:
        entries.append(current)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def run_smoke(*, host: str, port: int, transcript: Path, messages: int) -> int:
    if transcript.exists():
        transcript.unlink()
    transcript.parent.mkdir(parents=True, exist_ok=True)

    env = _subprocess_env()
    coordinator = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hivemind_axl_node",
            "coordinator",
            "--host",
            host,
            "--port",
            str(port),
            "--transcript",
            str(transcript),
            "--messages",
            str(messages),
        ],
        cwd=_repo_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    time.sleep(0.35)
    if coordinator.poll() is not None:
        coordinator_stdout, coordinator_stderr = coordinator.communicate(timeout=5)
        sys.stderr.write(coordinator_stdout + coordinator_stderr)
        return 1

    evaluator = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hivemind_axl_node",
            "evaluator",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=_repo_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    coordinator_stdout, coordinator_stderr = coordinator.communicate(timeout=20)
    evaluator_stdout, evaluator_stderr = evaluator.communicate(timeout=20)
    if coordinator.returncode != 0 or evaluator.returncode != 0:
        sys.stderr.write(coordinator_stdout + coordinator_stderr + evaluator_stdout + evaluator_stderr)
        return 1

    stats = transcript_stats(transcript)
    print(json.dumps(stats.to_dict(), indent=2, sort_keys=True))
    if stats.messages < messages * 2:
        sys.stderr.write(f"expected at least {messages * 2} AXL messages, got {stats.messages}\n")
        return 1
    if stats.nodes_online < 2:
        sys.stderr.write(f"expected at least two AXL nodes online, got {stats.nodes_online}\n")
        return 1
    return 0


async def run_failure_smoke(
    *,
    host: str,
    port: int,
    transcript: Path,
    messages: int,
) -> int:
    if transcript.exists():
        transcript.unlink()
    transcript.parent.mkdir(parents=True, exist_ok=True)

    async def short_lived_evaluator() -> None:
        reader, writer = await asyncio.open_connection(host, port)
        inbound = await _read_message(reader)
        response = AxlMessage.create(
            source_node=EVALUATOR_NODE_ID,
            target=inbound.source_node,
            message_type="INFERENCE_RESULT",
            payload={
                "received_message_id": inbound.id,
                "sequence": 1,
                "decision": "partial_result",
                "confidence": 0.5,
            },
        )
        writer.write(_encode(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    coordinator_task = asyncio.create_task(
        run_coordinator(host=host, port=port, transcript=transcript, messages=messages)
    )
    await asyncio.sleep(0.1)
    await short_lived_evaluator()
    await coordinator_task
    stats = transcript_stats(transcript)
    print(json.dumps(stats.to_dict(), indent=2, sort_keys=True))
    return 0 if stats.failed_nodes and stats.nodes_online == 1 else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local HIVEMIND AXL-compatible nodes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    coordinator = subparsers.add_parser("coordinator", help="Start the coordinator TCP JSONL node.")
    coordinator.add_argument("--host", default=DEFAULT_HOST)
    coordinator.add_argument("--port", type=int, default=DEFAULT_PORT)
    coordinator.add_argument("--transcript", type=Path, default=Path("runs/axl/smoke.jsonl"))
    coordinator.add_argument("--messages", type=int, default=20)

    evaluator = subparsers.add_parser("evaluator", help="Start the evaluator TCP JSONL node.")
    evaluator.add_argument("--host", default=DEFAULT_HOST)
    evaluator.add_argument("--port", type=int, default=DEFAULT_PORT)

    smoke = subparsers.add_parser("smoke", help="Start both nodes and verify a transcript.")
    smoke.add_argument("--host", default=DEFAULT_HOST)
    smoke.add_argument("--port", type=int, default=DEFAULT_PORT)
    smoke.add_argument("--transcript", type=Path, default=Path("runs/axl/smoke.jsonl"))
    smoke.add_argument("--messages", type=int, default=20)

    failure = subparsers.add_parser("failure-smoke", help="Verify evaluator failure is captured.")
    failure.add_argument("--host", default=DEFAULT_HOST)
    failure.add_argument("--port", type=int, default=DEFAULT_PORT + 1)
    failure.add_argument("--transcript", type=Path, default=Path("runs/axl/failure-smoke.jsonl"))
    failure.add_argument("--messages", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.command == "coordinator":
        return asyncio.run(
            run_coordinator(
                host=args.host,
                port=args.port,
                transcript=args.transcript,
                messages=args.messages,
            )
        )
    if args.command == "evaluator":
        return asyncio.run(run_evaluator(host=args.host, port=args.port))
    if args.command == "smoke":
        return run_smoke(host=args.host, port=args.port, transcript=args.transcript, messages=args.messages)
    if args.command == "failure-smoke":
        return asyncio.run(
            run_failure_smoke(
                host=args.host,
                port=args.port,
                transcript=args.transcript,
                messages=args.messages,
            )
        )
    return 2
