from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Action = Literal["buy", "sell", "hold", "provide_liquidity", "hedge"]
RunMode = Literal[
    "mock",
    "local_axl",
    "live_0g",
    "live_uniswap",
    "local_axl+live_0g",
    "local_axl+live_uniswap",
    "live_0g+live_uniswap",
    "local_axl+live_0g+live_uniswap",
]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class AgentArchetype:
    """Strategy profile used to instantiate deterministic mock agents."""

    name: str
    tier: int
    risk_appetite: float
    momentum_bias: float
    liquidity_bias: float
    hedge_bias: float
    aiq_base: float

    def __post_init__(self) -> None:
        if self.tier not in {1, 2, 3}:
            raise ValueError("tier must be 1, 2, or 3")
        for field_name in (
            "risk_appetite",
            "momentum_bias",
            "liquidity_bias",
            "hedge_bias",
            "aiq_base",
        ):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Scenario:
    """Market shock injected into the local swarm engine."""

    scenario_id: str
    label: str
    volatility: float
    liquidity_delta: float
    sentiment: float
    gas_pressure: float
    signal_strength: float = 0.5

    def __post_init__(self) -> None:
        for field_name in ("volatility", "gas_pressure", "signal_strength"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        if not -1.0 <= self.liquidity_delta <= 1.0:
            raise ValueError("liquidity_delta must be between -1.0 and 1.0")
        if not -1.0 <= self.sentiment <= 1.0:
            raise ValueError("sentiment must be between -1.0 and 1.0")

    @classmethod
    def neutral(cls) -> "Scenario":
        return cls(
            scenario_id="bootstrap-neutral",
            label="Bootstrap neutral market",
            volatility=0.2,
            liquidity_delta=0.0,
            sentiment=0.0,
            gas_pressure=0.1,
            signal_strength=0.4,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentState:
    agent_id: str
    archetype: str
    tier: int
    action: Action
    confidence: float
    pnl_bps: float
    aiq: float
    score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TierMetric:
    tier: int
    agent_count: int
    inference_calls: int
    fallback_count: int
    avg_latency_ms: float
    aiq_size: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int
    agent_id: str
    archetype: str
    tier: int
    action: Action
    score: float
    confidence: float
    pnl_bps: float
    aiq: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntegrationEnvelope:
    """Mock integration surface shaped for later 0G, AXL, and Uniswap adapters."""

    zero_g_compute: dict[str, Any]
    zero_g_storage: dict[str, Any]
    gensyn_axl: dict[str, Any]
    uniswap: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SwarmSnapshot:
    sequence: int
    run_mode: RunMode
    scenario: Scenario
    agents: tuple[AgentState, ...]
    tier_metrics: tuple[TierMetric, ...]
    leaderboard: tuple[LeaderboardEntry, ...]
    integrations: IntegrationEnvelope
    transcript: dict[str, Any] = field(default_factory=dict)
    proof: dict[str, Any] = field(default_factory=dict)
    event_log: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "run_mode": self.run_mode,
            "scenario": self.scenario.to_dict(),
            "agents": [agent.to_dict() for agent in self.agents],
            "tier_metrics": [metric.to_dict() for metric in self.tier_metrics],
            "leaderboard": [entry.to_dict() for entry in self.leaderboard],
            "integrations": self.integrations.to_dict(),
            "transcript": self.transcript,
            "proof": self.proof,
            "event_log": list(self.event_log),
        }


def clamp_unit(value: float) -> float:
    return _clamp(value, 0.0, 1.0)
