from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Action = Literal[
    "buy",
    "sell",
    "hold",
    "provide_liquidity",
    "hedge",
    "rebalance",
    "arb",
    "vote",
    "front_run",
]
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


class AgentArchetype:
    """Strategy profile + decision surface for swarm agents.

    Subclasses override `mock_decide` and `heuristic` with strategy-specific
    logic. `decide` is the single entrypoint the engine calls; default routes
    to `heuristic`. `on_signal` is called when an AXL message is delivered.

    The default constructor argument set is permissive enough that minimal
    quickstart subclasses can omit ``__init__`` entirely; set
    ``archetype_name`` as a class attribute to control the agent's name.
    """

    archetype_name: str | None = None

    def __init__(
        self,
        name: str | None = None,
        tier: int = 2,
        risk_appetite: float = 0.5,
        momentum_bias: float = 0.5,
        liquidity_bias: float = 0.5,
        hedge_bias: float = 0.5,
        aiq_base: float = 0.7,
    ) -> None:
        if name is None:
            name = type(self).archetype_name or type(self).__name__.lower()
        if tier not in {1, 2, 3}:
            raise ValueError("tier must be 1, 2, or 3")
        for field_name, value in (
            ("risk_appetite", risk_appetite),
            ("momentum_bias", momentum_bias),
            ("liquidity_bias", liquidity_bias),
            ("hedge_bias", hedge_bias),
            ("aiq_base", aiq_base),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")

        self.name = name
        self.tier = tier
        self.risk_appetite = risk_appetite
        self.momentum_bias = momentum_bias
        self.liquidity_bias = liquidity_bias
        self.hedge_bias = hedge_bias
        self.aiq_base = aiq_base

    def decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "hold",
            "confidence": 0.5,
            "rationale": f"{self.name}: base heuristic (no override)",
        }

    def on_signal(self, message: dict[str, Any]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "risk_appetite": self.risk_appetite,
            "momentum_bias": self.momentum_bias,
            "liquidity_bias": self.liquidity_bias,
            "hedge_bias": self.hedge_bias,
            "aiq_base": self.aiq_base,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AgentArchetype):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(("AgentArchetype", self.name, self.tier))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, tier={self.tier})"


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
    inference_source: str = "local"
    model: str = ""

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
    rationale: str = ""
    inference_source: str = "local"
    model: str = ""

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
