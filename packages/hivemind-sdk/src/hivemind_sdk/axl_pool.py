from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .axl import AXL_MESSAGE_TYPES, AxlMessage, AxlMessageType

logger = logging.getLogger(__name__)


@dataclass
class _NodeConn:
    url: str
    host: str
    port: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    node_id: str
    reader_task: asyncio.Task[None] | None = None
    alive: bool = True


def _parse_tcp_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme != "tcp":
        raise ValueError(f"AXL pool node url must use tcp:// scheme: {url}")
    if parsed.hostname is None or parsed.port is None:
        raise ValueError(f"AXL pool node url must include host and port: {url}")
    return parsed.hostname, parsed.port


class AXLPoolManager:
    """Maintains TCP connections to a pool of AXL nodes and exposes
    broadcast / send / receive primitives backed by the typed
    ``AxlMessage`` shape used elsewhere in the SDK.

    Each agent connects to every node so any node can fan a broadcast
    out to every locally-registered agent in the pool. Receivers may
    therefore see the same message via multiple nodes; ``receive`` dedupes
    by ``AxlMessage.id`` so callers see each logical message once.
    """

    def __init__(
        self,
        *,
        node_urls: list[str],
        pool_id: str,
        agent_id: str,
        timeout: float = 10.0,
    ) -> None:
        if not node_urls:
            raise ValueError("AXLPoolManager requires at least one node url")
        self._node_urls = list(node_urls)
        self._pool_id = pool_id
        self._agent_id = agent_id
        self._timeout = timeout
        self._connections: dict[str, _NodeConn] = {}
        self._inbox: deque[AxlMessage] = deque()
        self._inbox_event = asyncio.Event()
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=4096)
        self._message_count = 0
        self._closed = False

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def pool_id(self) -> str:
        return self._pool_id

    @property
    def connected_node_ids(self) -> list[str]:
        return [conn.node_id for conn in self._connections.values() if conn.alive]

    @property
    def failed_node_urls(self) -> list[str]:
        return [url for url in self._node_urls if url not in self._connections]

    async def connect(self) -> None:
        for url in self._node_urls:
            try:
                host, port = _parse_tcp_url(url)
            except ValueError as exc:
                logger.warning("AXLPoolManager skipping bad url %s: %s", url, exc)
                continue
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=self._timeout
                )
            except (OSError, asyncio.TimeoutError) as exc:
                logger.warning("AXLPoolManager could not connect to %s: %s", url, exc)
                continue

            register = (
                json.dumps(
                    {"op": "REGISTER", "agent_id": self._agent_id, "pool_id": self._pool_id},
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            try:
                writer.write(register)
                await asyncio.wait_for(writer.drain(), timeout=self._timeout)
                ack_line = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            except (OSError, asyncio.TimeoutError) as exc:
                logger.warning("AXLPoolManager register handshake with %s failed: %s", url, exc)
                writer.close()
                continue

            if not ack_line:
                logger.warning("AXLPoolManager handshake with %s ended early", url)
                writer.close()
                continue
            try:
                ack = json.loads(ack_line.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("AXLPoolManager handshake with %s returned malformed json", url)
                writer.close()
                continue
            if ack.get("op") != "REGISTERED":
                logger.warning("AXLPoolManager handshake with %s returned %s", url, ack)
                writer.close()
                continue

            node_id = str(ack.get("node_id") or url)
            conn = _NodeConn(url=url, host=host, port=port, reader=reader, writer=writer, node_id=node_id)
            conn.reader_task = asyncio.create_task(self._read_loop(conn), name=f"axl-pool-read-{node_id}")
            self._connections[url] = conn
            logger.info("AXLPoolManager connected to %s as %s on %s", url, self._agent_id, node_id)

    async def _read_loop(self, conn: _NodeConn) -> None:
        try:
            while True:
                line = await conn.reader.readline()
                if not line:
                    break
                try:
                    frame = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if frame.get("op") != "MESSAGE":
                    continue
                payload = frame.get("message")
                if not isinstance(payload, dict):
                    continue
                try:
                    message = AxlMessage.from_dict(payload)
                except (KeyError, TypeError, ValueError):
                    continue
                if message.id in self._seen_ids:
                    continue
                self._seen_ids.add(message.id)
                self._seen_order.append(message.id)
                if len(self._seen_order) == self._seen_order.maxlen:
                    # opportunistic prune: drop oldest from the set
                    oldest = self._seen_order[0]
                    if oldest != message.id:
                        self._seen_ids.discard(oldest)
                self._inbox.append(message)
                self._inbox_event.set()
        except (ConnectionError, OSError):
            pass
        finally:
            conn.alive = False
            try:
                conn.writer.close()
            except (ConnectionError, OSError):
                pass

    def _build_message(self, *, target: str, message_type: AxlMessageType, payload: dict[str, Any]) -> AxlMessage:
        if message_type not in AXL_MESSAGE_TYPES:
            raise ValueError(f"unsupported AXL message type: {message_type}")
        return AxlMessage.create(
            source_node=self._agent_id,
            target=target,
            message_type=message_type,
            payload=payload,
        )

    async def _send_to_node(self, conn: _NodeConn, message: AxlMessage) -> bool:
        frame = (json.dumps({"op": "SEND", "message": message.to_dict()}, sort_keys=True) + "\n").encode("utf-8")
        try:
            conn.writer.write(frame)
            await conn.writer.drain()
            return True
        except (ConnectionError, OSError) as exc:
            logger.warning("AXLPoolManager send to %s failed: %s", conn.url, exc)
            conn.alive = False
            return False

    async def broadcast(self, message_type: AxlMessageType, payload: dict[str, Any]) -> AxlMessage:
        message = self._build_message(target="broadcast", message_type=message_type, payload=payload)
        delivered = 0
        for conn in list(self._connections.values()):
            if not conn.alive:
                continue
            if await self._send_to_node(conn, message):
                delivered += 1
        if delivered == 0:
            logger.warning("AXLPoolManager broadcast had no live nodes")
        else:
            self._message_count += 1
        return message

    async def send(
        self,
        target_agent_id: str,
        message_type: AxlMessageType,
        payload: dict[str, Any],
    ) -> AxlMessage:
        message = self._build_message(target=target_agent_id, message_type=message_type, payload=payload)
        delivered = False
        for conn in list(self._connections.values()):
            if not conn.alive:
                continue
            if await self._send_to_node(conn, message):
                delivered = True
                break
        if not delivered:
            logger.warning("AXLPoolManager send to %s had no live nodes", target_agent_id)
        else:
            self._message_count += 1
        return message

    async def receive(self, *, timeout: float = 1.0) -> list[AxlMessage]:
        if not self._inbox:
            try:
                await asyncio.wait_for(self._inbox_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return []
        messages: list[AxlMessage] = []
        while self._inbox:
            messages.append(self._inbox.popleft())
        self._inbox_event.clear()
        return messages

    async def disconnect(self) -> None:
        if self._closed:
            return
        self._closed = True
        for conn in list(self._connections.values()):
            try:
                conn.writer.close()
            except (ConnectionError, OSError):
                pass
        tasks = [conn.reader_task for conn in self._connections.values() if conn.reader_task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, ConnectionError, OSError):
                pass
        for conn in list(self._connections.values()):
            try:
                await conn.writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        self._connections.clear()

    async def __aenter__(self) -> "AXLPoolManager":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.disconnect()
