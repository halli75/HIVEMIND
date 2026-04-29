"""Concrete agent archetypes.

Each archetype extends AgentArchetype with realistic mock_decide / heuristic
logic. mock_decide is what the engine calls when HIVEMIND_USE_MOCK_INFERENCE
is on; heuristic is the cheap rule-based fallback used by Tier 2 agents and
also the default body of mock_decide for archetypes that don't need a
separate offline simulator.
"""

from __future__ import annotations

from typing import Any

from .models import AgentArchetype

_DEGEN_CONFIDENCE_THRESHOLD = 0.7
_LP_IL_THRESHOLD = 0.02
_ARB_MIN_SPREAD_BPS = 8
_PEG_DEVIATION_THRESHOLD = 0.003
_MEV_SIZE_THRESHOLD_USD = 250_000


def _decision(action: str, confidence: float, rationale: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "action": action,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "rationale": rationale,
    }
    if extra:
        out.update(extra)
    return out


class WhaleArchetype(AgentArchetype):
    """Slow-moving accumulator. Buys deep dips, distributes into rallies."""

    def __init__(self) -> None:
        super().__init__(
            name="whale",
            tier=1,
            risk_appetite=0.45,
            momentum_bias=0.30,
            liquidity_bias=0.55,
            hedge_bias=0.40,
            aiq_base=0.82,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        delta = float(market_state.get("price_delta", 0.0))
        if delta < -0.10:
            return _decision("buy", 0.86, f"whale: price_delta {delta:+.2%} < -10%, accumulate")
        if delta > 0.15:
            return _decision("sell", 0.84, f"whale: price_delta {delta:+.2%} > +15%, distribute")
        return _decision("hold", 0.55, f"whale: price_delta {delta:+.2%} within band")

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class DegenArchetype(AgentArchetype):
    """Copies the strongest MARKET_SIGNAL it has seen recently."""

    def __init__(self) -> None:
        super().__init__(
            name="degen",
            tier=1,
            risk_appetite=0.95,
            momentum_bias=0.92,
            liquidity_bias=0.18,
            hedge_bias=0.10,
            aiq_base=0.55,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        signals = memory.get("axl_signals") or []
        market_signals = [s for s in signals if s.get("type") == "MARKET_SIGNAL"]
        if not market_signals:
            return _decision("hold", 0.30, "degen: no MARKET_SIGNAL, fade")

        strongest = max(market_signals, key=lambda s: float(s.get("confidence", 0.0)))
        confidence = float(strongest.get("confidence", 0.0))
        if confidence <= _DEGEN_CONFIDENCE_THRESHOLD:
            return _decision(
                "hold",
                confidence * 0.5,
                f"degen: strongest signal conf={confidence:.2f} below threshold",
            )
        action = strongest.get("direction") or "buy"
        return _decision(
            action,
            min(0.99, confidence + 0.05),
            f"degen: copying MARKET_SIGNAL {strongest.get('id', '?')} conf={confidence:.2f}",
            copied_signal_id=strongest.get("id"),
        )

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class LPProviderArchetype(AgentArchetype):
    """Maintains a concentrated liquidity range. Rebalances on drift / IL."""

    def __init__(self) -> None:
        super().__init__(
            name="lp_provider",
            tier=2,
            risk_appetite=0.32,
            momentum_bias=0.20,
            liquidity_bias=0.95,
            hedge_bias=0.55,
            aiq_base=0.71,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        position = memory.get("lp_position") or {}
        in_range = bool(position.get("in_range", True))
        il_delta = float(position.get("impermanent_loss_delta", 0.0))

        if not in_range:
            return _decision(
                "rebalance",
                0.78,
                f"lp_provider: position out of range (lower={position.get('range_lower')}, upper={position.get('range_upper')})",
                trigger="out_of_range",
            )
        if il_delta > _LP_IL_THRESHOLD:
            return _decision(
                "rebalance",
                0.7,
                f"lp_provider: IL delta {il_delta:+.2%} > {_LP_IL_THRESHOLD:.2%}",
                trigger="impermanent_loss",
            )
        return _decision("provide_liquidity", 0.6, "lp_provider: in range, IL acceptable")

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class ArbitrageurArchetype(AgentArchetype):
    """Cross-pool arbitrage. Queues an arb when spread exceeds the floor."""

    def __init__(self) -> None:
        super().__init__(
            name="arbitrageur",
            tier=2,
            risk_appetite=0.6,
            momentum_bias=0.4,
            liquidity_bias=0.5,
            hedge_bias=0.45,
            aiq_base=0.74,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        spread_bps = float(market_state.get("pool_spread_bps", 0.0))
        min_spread = float(memory.get("min_spread_bps", _ARB_MIN_SPREAD_BPS))
        if spread_bps > min_spread:
            return _decision(
                "arb",
                min(0.95, 0.5 + spread_bps / 200.0),
                f"arbitrageur: spread {spread_bps:.1f}bps > min {min_spread:.1f}bps, queue arb",
                spread_bps=spread_bps,
            )
        return _decision(
            "hold",
            0.4,
            f"arbitrageur: spread {spread_bps:.1f}bps below {min_spread:.1f}bps floor",
        )

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class GovernanceVoterArchetype(AgentArchetype):
    """Copies the vote of the highest-stake agent in its social graph."""

    def __init__(self) -> None:
        super().__init__(
            name="governance_voter",
            tier=3,
            risk_appetite=0.18,
            momentum_bias=0.15,
            liquidity_bias=0.30,
            hedge_bias=0.40,
            aiq_base=0.62,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        graph = memory.get("social_graph") or []
        if not graph:
            return _decision("hold", 0.25, "governance_voter: no social graph, abstain")
        leader = max(graph, key=lambda n: float(n.get("stake", 0.0)))
        return _decision(
            "vote",
            0.65,
            f"governance_voter: copying vote of {leader.get('agent_id', '?')} (stake={leader.get('stake', 0.0):.2f})",
            vote=leader.get("vote"),
            followed_agent=leader.get("agent_id"),
        )

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class StablecoinArbArchetype(AgentArchetype):
    """Trades the peg when the deviation crosses a threshold."""

    def __init__(self) -> None:
        super().__init__(
            name="stablecoin_arb",
            tier=2,
            risk_appetite=0.35,
            momentum_bias=0.30,
            liquidity_bias=0.6,
            hedge_bias=0.7,
            aiq_base=0.69,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        peg_delta = float(market_state.get("peg_delta", 0.0))
        if abs(peg_delta) > _PEG_DEVIATION_THRESHOLD:
            direction = "buy" if peg_delta < 0 else "sell"
            return _decision(
                "arb",
                min(0.95, 0.6 + abs(peg_delta) * 50),
                f"stablecoin_arb: peg_delta {peg_delta:+.4f} > {_PEG_DEVIATION_THRESHOLD}, peg arb",
                peg_direction=direction,
                peg_delta=peg_delta,
            )
        return _decision(
            "hold",
            0.45,
            f"stablecoin_arb: peg_delta {peg_delta:+.4f} within band",
        )

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


class MEVSearcherArchetype(AgentArchetype):
    """Watches TRADE_INTENT messages and front-runs sufficiently large ones."""

    def __init__(self) -> None:
        super().__init__(
            name="mev_searcher",
            tier=1,
            risk_appetite=0.85,
            momentum_bias=0.78,
            liquidity_bias=0.35,
            hedge_bias=0.25,
            aiq_base=0.78,
        )

    def heuristic(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        intents = memory.get("axl_signals") or []
        trade_intents = [
            s for s in intents
            if s.get("type") == "TRADE_INTENT" and float(s.get("size_usd", 0.0)) > _MEV_SIZE_THRESHOLD_USD
        ]
        if not trade_intents:
            return _decision("hold", 0.3, "mev_searcher: no qualifying TRADE_INTENT")
        biggest = max(trade_intents, key=lambda s: float(s.get("size_usd", 0.0)))
        return _decision(
            "front_run",
            0.82,
            f"mev_searcher: front-run {biggest.get('id', '?')} size=${float(biggest['size_usd']):,.0f}",
            target_intent_id=biggest.get("id"),
            target_size_usd=biggest.get("size_usd"),
        )

    def mock_decide(self, market_state: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        return self.heuristic(market_state, memory)


DEFAULT_ARCHETYPES: tuple[AgentArchetype, ...] = (
    WhaleArchetype(),
    DegenArchetype(),
    LPProviderArchetype(),
    ArbitrageurArchetype(),
    GovernanceVoterArchetype(),
    StablecoinArbArchetype(),
    MEVSearcherArchetype(),
)


def archetype_by_name(name: str) -> AgentArchetype:
    for archetype in DEFAULT_ARCHETYPES:
        if archetype.name == name:
            return archetype
    raise KeyError(f"unknown archetype: {name}")
