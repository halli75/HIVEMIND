from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from hivemind_sdk import AxlMessage

logger = logging.getLogger("hivemind_axl_node")


@dataclass
class _AgentConn:
    agent_id: str
    pool_id: str
    writer: asyncio.StreamWriter
    inbox_seq: int = 0
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def write(self, frame: bytes) -> None:
        async with self._send_lock:
            try:
                self.writer.write(frame)
                await self.writer.drain()
            except (ConnectionError, OSError):
                pass


def _encode_op(op: str, **fields: Any) -> bytes:
    return (json.dumps({"op": op, **fields}, sort_keys=True) + "\n").encode("utf-8")


class AxlNodeServer:
    """Multi-agent TCP routing node for the AXL pool.

    Wire protocol is line-delimited JSON. Frames:
      {"op":"REGISTER","agent_id":..., "pool_id":...}
      {"op":"SEND","message":<AxlMessage dict>}
      {"op":"REGISTERED","node_id":...}
      {"op":"MESSAGE","message":<AxlMessage dict>}
      {"op":"ERROR","reason":...}
    """

    def __init__(self, *, node_id: str, host: str, port: int, pool_id: str | None = None) -> None:
        self.node_id = node_id
        self.host = host
        self.port = port
        self.pool_id = pool_id
        self._agents: dict[str, _AgentConn] = {}
        self._lock = asyncio.Lock()
        self._server: asyncio.base_events.Server | None = None
        self.message_count = 0

    async def serve_forever(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        sockets = self._server.sockets or []
        for sock in sockets:
            logger.info("axl node %s listening on %s", self.node_id, sock.getsockname())
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        agent: _AgentConn | None = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    frame = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    writer.write(_encode_op("ERROR", reason="malformed_json"))
                    await writer.drain()
                    continue

                op = frame.get("op")
                if op == "REGISTER":
                    agent = await self._register(frame, writer)
                    if agent is None:
                        return
                elif op == "SEND":
                    if agent is None:
                        writer.write(_encode_op("ERROR", reason="not_registered"))
                        await writer.drain()
                        continue
                    await self._route(frame, agent)
                else:
                    writer.write(_encode_op("ERROR", reason=f"unknown_op:{op}"))
                    await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            if agent is not None:
                async with self._lock:
                    if self._agents.get(agent.agent_id) is agent:
                        del self._agents[agent.agent_id]
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _register(self, frame: dict[str, Any], writer: asyncio.StreamWriter) -> _AgentConn | None:
        agent_id = frame.get("agent_id")
        pool_id = frame.get("pool_id")
        if not agent_id:
            writer.write(_encode_op("ERROR", reason="missing_agent_id"))
            await writer.drain()
            return None
        if self.pool_id is not None and pool_id != self.pool_id:
            writer.write(_encode_op("ERROR", reason=f"pool_mismatch:{pool_id}"))
            await writer.drain()
            return None

        conn = _AgentConn(agent_id=agent_id, pool_id=pool_id or "", writer=writer)
        async with self._lock:
            existing = self._agents.get(agent_id)
            if existing is not None:
                try:
                    existing.writer.close()
                except (ConnectionError, OSError):
                    pass
            self._agents[agent_id] = conn
        writer.write(_encode_op("REGISTERED", node_id=self.node_id, pool_id=self.pool_id or pool_id or ""))
        await writer.drain()
        logger.info("axl node %s registered agent %s", self.node_id, agent_id)
        return conn

    async def _route(self, frame: dict[str, Any], sender: _AgentConn) -> None:
        message_dict = frame.get("message")
        if not isinstance(message_dict, dict):
            return
        try:
            message = AxlMessage.from_dict(message_dict)
        except (KeyError, TypeError, ValueError):
            await sender.write(_encode_op("ERROR", reason="invalid_message"))
            return

        self.message_count += 1
        target = message.target
        out = _encode_op("MESSAGE", message=message.to_dict())

        if target in {"broadcast", "all", "*"}:
            async with self._lock:
                recipients = [conn for conn in self._agents.values() if conn.agent_id != sender.agent_id]
        else:
            async with self._lock:
                recipient = self._agents.get(target)
                recipients = [recipient] if recipient is not None else []

        for recipient in recipients:
            await recipient.write(out)
