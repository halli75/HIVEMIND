from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, Literal, TypedDict

AxlMessageType = Literal[
    "SCENARIO_SHOCK",
    "MARKET_SIGNAL",
    "TRADE_INTENT",
    "INFERENCE_RESULT",
    "POOL_STATE",
    "COALITION_INVITE",
    "GOVERNANCE_SIGNAL",
]
AXL_MESSAGE_TYPES: set[str] = {
    "SCENARIO_SHOCK",
    "MARKET_SIGNAL",
    "TRADE_INTENT",
    "INFERENCE_RESULT",
    "POOL_STATE",
    "COALITION_INVITE",
    "GOVERNANCE_SIGNAL",
}


class PoolStatePayload(TypedDict):
    pool_address: str
    token0: str
    token1: str
    fee_tier: int
    tick: int
    sqrt_price_x96: str
    liquidity: str
    tvl_usd: float


class CoalitionInvitePayload(TypedDict):
    coalition_id: str
    proposer_agent_id: str
    target_agent_id: str
    objective: str
    expires_at: str
    minimum_stake: float


class GovernanceSignalPayload(TypedDict):
    proposal_id: str
    voter_agent_id: str
    vote: Literal["for", "against", "abstain"]
    voting_power: float
    rationale: str


class TradeIntentPayload(TypedDict):
    agent_id: str
    archetype: str
    scenario_id: str
    action: str
    confidence: float
    size_usd_est: float


class MarketSignalPayload(TypedDict, total=False):
    """Coordinator-broadcast market view consumed by Degen / urgency boost.

    `total=False` because the field set varies between the runner smoke (which
    emits `signal_strength` / `sequence` / `scenario_id`) and the failure
    handler (which emits `signal` / `node_id` / `reason` to record dead nodes).
    """
    agent_id: str
    target_agent_id: str
    signal_type: str
    asset: str
    confidence: float
    signal_strength: float
    timestamp: str
    sequence: int
    scenario_id: str
    signal: str
    node_id: str
    reason: str


class InferenceResultPayload(TypedDict):
    agent_id: str
    scenario_id: str
    action: str
    confidence: float
    score: float
    aiq: float


class ScenarioShockPayload(TypedDict, total=False):
    """SCENARIO_SHOCK is broadcast by both the local AXL coordinator (smoke)
    and `LocalAxlMessageBus.broadcast_scenario` (engine). The two emitters
    use overlapping but not identical field sets, so the typed view is a
    superset and `total=False`.
    """
    scenario_id: str
    label: str
    shock_type: str
    magnitude: float
    asset: str
    injected_at: str
    sequence: int
    signal_strength: float
    volatility: float
    liquidity_delta: float
    sentiment: float
    gas_pressure: float


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def parse_timestamp(timestamp: str) -> datetime:
    value = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class AxlMessage:
    id: str
    source_node: str
    target: str
    type: AxlMessageType
    timestamp: str
    payload: dict[str, Any]
    payload_digest: str
    latency_ms: float | None = None

    @classmethod
    def create(
        cls,
        *,
        source_node: str,
        target: str,
        message_type: AxlMessageType,
        payload: dict[str, Any],
        timestamp: str | None = None,
        latency_ms: float | None = None,
    ) -> "AxlMessage":
        if message_type not in AXL_MESSAGE_TYPES:
            raise ValueError(f"unsupported AXL message type: {message_type}")
        emitted_at = timestamp or utc_now_iso()
        digest = payload_digest(payload)
        message_id = sha256(
            f"{source_node}:{target}:{message_type}:{emitted_at}:{digest}".encode("utf-8")
        ).hexdigest()[:16]
        return cls(
            id=f"axl-{message_id}",
            source_node=source_node,
            target=target,
            type=message_type,
            timestamp=emitted_at,
            payload=payload,
            payload_digest=digest,
            latency_ms=latency_ms,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AxlMessage":
        message_type = str(payload.get("type", ""))
        if message_type not in AXL_MESSAGE_TYPES:
            raise ValueError(f"unsupported AXL message type: {message_type}")
        message_payload = payload.get("payload", {})
        if not isinstance(message_payload, dict):
            raise ValueError("AXL message payload must be an object")
        return cls(
            id=str(payload["id"]),
            source_node=str(payload["source_node"]),
            target=str(payload["target"]),
            type=message_type,  # type: ignore[arg-type]
            timestamp=str(payload["timestamp"]),
            payload=message_payload,
            payload_digest=str(payload.get("payload_digest") or payload_digest(message_payload)),
            latency_ms=float(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "source_node": self.source_node,
            "target": self.target,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "payload_digest": self.payload_digest,
        }
        if self.latency_ms is not None:
            value["latency_ms"] = round(self.latency_ms, 3)
        return value


@dataclass(frozen=True)
class AxlTranscriptStats:
    mode: str
    messages: int
    nodes_online: int
    failed_nodes: tuple[str, ...]
    last_message_type: str | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    transcript_path: str | None
    transcript: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "messages": self.messages,
            "nodes_online": self.nodes_online,
            "failed_nodes": list(self.failed_nodes),
            "last_message_type": self.last_message_type,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "transcript_path": self.transcript_path,
            "transcript": list(self.transcript),
        }


def append_jsonl(path: str | Path, message: AxlMessage) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message.to_dict(), sort_keys=True))
        handle.write("\n")


def read_transcript(path: str | Path) -> tuple[AxlMessage, ...]:
    target = Path(path)
    if not target.exists():
        return ()
    messages: list[AxlMessage] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                messages.append(AxlMessage.from_dict(json.loads(stripped)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid AXL transcript line {line_number} in {target}") from exc
    return tuple(messages)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def transcript_stats(
    path: str | Path,
    *,
    mode: str = "local_axl",
    tail: int = 20,
) -> AxlTranscriptStats:
    messages = read_transcript(path)
    failed_nodes = {
        str(message.payload["node_id"])
        for message in messages
        if message.payload.get("signal") == "node_failure" and message.payload.get("node_id")
    }
    source_nodes = {message.source_node for message in messages}
    targeted_nodes = {
        message.target
        for message in messages
        if message.target not in {"broadcast", "coordinator", "all"} and not message.target.startswith("topic:")
    }
    nodes = source_nodes | targeted_nodes
    online_nodes = len(nodes - failed_nodes)
    latencies = [float(message.latency_ms) for message in messages if message.latency_ms is not None]
    p50 = round(median(latencies), 3) if latencies else None
    p95 = _percentile(latencies, 0.95)
    return AxlTranscriptStats(
        mode=mode,
        messages=len(messages),
        nodes_online=online_nodes,
        failed_nodes=tuple(sorted(failed_nodes)),
        last_message_type=messages[-1].type if messages else None,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        transcript_path=str(Path(path)),
        transcript=tuple(message.to_dict() for message in messages[-tail:]),
    )
