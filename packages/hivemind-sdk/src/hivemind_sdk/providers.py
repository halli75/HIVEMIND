from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from .axl import transcript_stats
from .models import Action, AgentArchetype, AgentState, LeaderboardEntry, Scenario
from .scoring import aiq_for, choose_action, confidence_for, pnl_bps_for, score_for


_VALID_ACTIONS: set[str] = {
    "buy",
    "sell",
    "hold",
    "provide_liquidity",
    "hedge",
    "rebalance",
    "arb",
    "vote",
    "front_run",
}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def use_mock_inference() -> bool:
    """Public helper: did the operator opt into archetype mock_decide?"""
    return _env_truthy("HIVEMIND_USE_MOCK_INFERENCE")


@dataclass(frozen=True)
class SeedReplay:
    """Replay source for deterministic partner integration proof snapshots."""

    payloads: dict[str, dict[str, Any]]

    @classmethod
    def from_directory(cls, directory: str | Path | None) -> "SeedReplay | None":
        if directory is None:
            return None

        root = Path(directory)
        if not root.exists():
            return None

        payloads: dict[str, dict[str, Any]] = {}
        for path in sorted(root.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payloads[path.name] = json.load(handle)

        if not payloads:
            return None
        return cls(payloads=payloads)

    @property
    def scenario_id(self) -> str | None:
        scenario = self.payloads.get("agents.seed.json", {}).get("scenario", {})
        value = scenario.get("id")
        return str(value) if value else None

    def agents(self) -> list[dict[str, Any]]:
        return list(self.payloads.get("agents.seed.json", {}).get("agents", []))

    def axl_messages(self) -> list[dict[str, Any]]:
        return list(self.payloads.get("gensyn-messages.seed.json", {}).get("messages", []))

    def storage_objects(self) -> list[dict[str, Any]]:
        return list(self.payloads.get("zerog-storage.seed.json", {}).get("objects", []))

    def uniswap_quote(self) -> dict[str, Any]:
        return dict(self.payloads.get("uniswap-quote.seed.json", {}))


class InferenceProvider(Protocol):
    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: AgentArchetype,
        scenario: Scenario,
        jitter: float,
    ) -> AgentState:
        """Evaluate a single agent for a scenario."""


class StorageProvider(Protocol):
    def write_state(
        self,
        *,
        sequence: int,
        scenario: Scenario,
        winner: LeaderboardEntry,
        state_digest: str,
    ) -> dict[str, Any]:
        """Persist or simulate persistence of swarm state and return proof data."""


class MessageBus(Protocol):
    def broadcast_scenario(
        self,
        *,
        scenario: Scenario,
        agent_count: int,
    ) -> dict[str, Any]:
        """Broadcast or simulate a typed scenario message."""


class ExecutionProvider(Protocol):
    def prepare_trade(
        self,
        *,
        scenario: Scenario,
        winner: LeaderboardEntry,
        state_digest: str,
    ) -> dict[str, Any]:
        """Prepare or simulate the execution path for a recommended trade."""


class LocalInferenceProvider:
    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: AgentArchetype,
        scenario: Scenario,
        jitter: float,
    ) -> AgentState:
        action = choose_action(archetype, scenario, jitter)
        confidence = confidence_for(archetype, scenario, jitter)
        aiq = aiq_for(archetype, scenario, confidence, jitter)
        pnl_bps = pnl_bps_for(action, archetype, scenario, jitter)
        score = score_for(confidence, pnl_bps, aiq, archetype.tier)
        rationale = (
            f"{archetype.name} selected {action} with sentiment={scenario.sentiment:.2f}, "
            f"volatility={scenario.volatility:.2f}, liquidity_delta={scenario.liquidity_delta:.2f}"
        )
        return AgentState(
            agent_id=agent_id,
            archetype=archetype.name,
            tier=archetype.tier,
            action=cast(Action, action),
            confidence=confidence,
            pnl_bps=pnl_bps,
            aiq=aiq,
            score=score,
            rationale=rationale,
        )


class MockInferenceProvider:
    """Inference path that calls archetype.mock_decide() instead of 0G Compute.

    Selected when HIVEMIND_USE_MOCK_INFERENCE=true. The market_state and memory
    arguments to mock_decide are derived from the scenario plus a small jitter
    so each agent still gets a deterministic per-call view.
    """

    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: AgentArchetype,
        scenario: Scenario,
        jitter: float,
    ) -> AgentState:
        price_delta = scenario.sentiment * scenario.signal_strength
        market_state: dict[str, Any] = {
            "scenario_id": scenario.scenario_id,
            "volatility": scenario.volatility,
            "liquidity_delta": scenario.liquidity_delta,
            "sentiment": scenario.sentiment,
            "gas_pressure": scenario.gas_pressure,
            "signal_strength": scenario.signal_strength,
            "price_delta": price_delta,
            "price_delta_pct": price_delta,
            "pool_spread_bps": max(0.0, scenario.volatility * 30.0 - 4.0),
            "peg_delta": scenario.liquidity_delta * 0.005,
        }
        memory: dict[str, Any] = {
            "axl_signals": [
                {
                    "id": f"sig-{agent_id}-mkt",
                    "type": "MARKET_SIGNAL",
                    "direction": "buy" if scenario.sentiment >= 0 else "sell",
                    "confidence": min(0.99, abs(scenario.sentiment) * scenario.signal_strength + jitter * 0.1),
                },
                {
                    "id": f"sig-{agent_id}-trade",
                    "type": "TRADE_INTENT",
                    "size_usd": 200_000 + scenario.volatility * 600_000,
                },
            ],
            "lp_position": {
                "in_range": scenario.liquidity_delta >= -0.4,
                "impermanent_loss_delta": max(0.0, scenario.volatility * 0.04 - 0.005),
                "range_lower": 1800 - scenario.volatility * 300,
                "range_upper": 2200 + scenario.volatility * 300,
            },
            "social_graph": [
                {"agent_id": "leader-001", "stake": 1_000_000, "vote": "for"},
                {"agent_id": "leader-002", "stake": 750_000, "vote": "abstain"},
            ],
            "min_spread_bps": 8,
            "portfolio": 100_000.0,
        }

        decision = archetype.mock_decide(market_state, memory)
        action = decision.get("action", "hold")
        if action not in _VALID_ACTIONS:
            action = "hold"
        confidence = float(decision.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        rationale = str(decision.get("rationale", f"{archetype.name}: mock_decide"))

        aiq = aiq_for(archetype, scenario, confidence, jitter)
        pnl_bps = pnl_bps_for(action, archetype, scenario, jitter)
        score = score_for(confidence, pnl_bps, aiq, archetype.tier)

        return AgentState(
            agent_id=agent_id,
            archetype=archetype.name,
            tier=archetype.tier,
            action=cast(Action, action),
            confidence=round(confidence, 4),
            pnl_bps=pnl_bps,
            aiq=aiq,
            score=score,
            rationale=rationale,
        )


class LocalStorageProvider:
    def __init__(self, *, replay: SeedReplay | None = None) -> None:
        self._replay = replay

    def write_state(
        self,
        *,
        sequence: int,
        scenario: Scenario,
        winner: LeaderboardEntry,
        state_digest: str,
    ) -> dict[str, Any]:
        replay_object = self._first_replay_object(winner.agent_id)
        uri = replay_object.get("uri", f"mock://0g-storage/swarm-state/{state_digest}")
        content_hash = replay_object.get("contentHash", f"0x{state_digest.ljust(64, '0')[:64]}")
        return {
            "mode": "seed_replay" if replay_object else "mock",
            "uri": uri,
            "hash": content_hash,
            "state_digest": state_digest,
            "readback": {
                "ok": True,
                "uri": uri,
                "hash": content_hash,
                "sequence": sequence,
                "scenario_id": scenario.scenario_id,
            },
        }

    def _first_replay_object(self, winner_id: str) -> dict[str, Any]:
        if self._replay is None:
            return {}

        for agent in self._replay.agents():
            if agent.get("id") == winner_id:
                return {
                    "uri": agent.get("storageUri"),
                    "contentHash": agent.get("storageHash"),
                }

        objects = self._replay.storage_objects()
        return dict(objects[0]) if objects else {}


class LocalMessageBus:
    def __init__(self, *, replay: SeedReplay | None = None) -> None:
        self._replay = replay

    def broadcast_scenario(
        self,
        *,
        scenario: Scenario,
        agent_count: int,
    ) -> dict[str, Any]:
        messages = self._replay.axl_messages() if self._replay else []
        return {
            "mode": "seed_replay" if messages else "mock",
            "topic": f"hivemind.scenario.{scenario.scenario_id}",
            "messages": len(messages) if messages else agent_count,
            "nodes_online": 2 if messages else 1,
            "last_message_type": messages[-1].get("type") if messages else "SCENARIO_SHOCK",
            "p50_latency_ms": None,
            "p95_latency_ms": None,
            "coordinator": "axl_coordinator",
            "transcript": messages,
        }


class LocalAxlMessageBus:
    def __init__(self, *, transcript_path: str | Path) -> None:
        self._transcript_path = Path(transcript_path)

    def broadcast_scenario(
        self,
        *,
        scenario: Scenario,
        agent_count: int,
    ) -> dict[str, Any]:
        stats = transcript_stats(self._transcript_path)
        payload = stats.to_dict()
        return {
            **payload,
            "topic": f"hivemind.scenario.{scenario.scenario_id}",
            "coordinator": "axl_coordinator",
        }


class LocalExecutionProvider:
    def __init__(self, *, replay: SeedReplay | None = None) -> None:
        self._replay = replay

    def prepare_trade(
        self,
        *,
        scenario: Scenario,
        winner: LeaderboardEntry,
        state_digest: str,
    ) -> dict[str, Any]:
        quote = self._replay.uniswap_quote() if self._replay else {}
        response = quote.get("response", {})
        quote_id = response.get("quoteId", f"uni-quote-{state_digest[:8]}")
        return {
            "mode": quote.get("mode", "mock"),
            "chain": "sepolia",
            "route": response.get("route", ["WETH", "USDC"]),
            "recommended_action": winner.action,
            "quote_id": quote_id,
            "quote": response
            or {
                "quoteId": quote_id,
                "amountOutDecimals": "0.00",
                "priceImpactBps": 0,
            },
            "swap_receipt": {
                "status": "placeholder",
                "transaction_hash": None,
                "scenario_id": scenario.scenario_id,
            },
        }


class UniswapExecutionProvider:
    """Live Sepolia execution backed by an injected Uniswap client.

    Quote-only by design: prepare_trade fetches a real /v1/quote response
    but does not sign or broadcast. Live submission stays in the manual
    apps/execution/run_swap.py path so a human always confirms the swap.
    The injected client is duck-typed (must expose async get_quote) so the
    SDK keeps zero runtime dependencies.
    """

    def __init__(
        self,
        *,
        client: Any,
        swapper_address: str,
        token_in: str,
        token_out: str,
        amount_in_wei: int,
        chain_id: int = 11155111,
    ) -> None:
        self._client = client
        self._swapper_address = swapper_address
        self._token_in = token_in
        self._token_out = token_out
        self._amount_in_wei = amount_in_wei
        self._chain_id = chain_id

    def prepare_trade(
        self,
        *,
        scenario: Scenario,
        winner: LeaderboardEntry,
        state_digest: str,
    ) -> dict[str, Any]:
        import asyncio

        quote = asyncio.run(
            self._client.get_quote(
                self._token_in,
                self._token_out,
                self._amount_in_wei,
                chain_id=self._chain_id,
                recipient=self._swapper_address,
            )
        )
        inner = quote.get("quote") or {}
        quote_id = inner.get("quoteId") or quote.get("quoteId") or f"uni-quote-{state_digest[:8]}"
        route = inner.get("route") or quote.get("route") or ["WETH", "USDC"]

        return {
            "mode": "live",
            "chain": "sepolia",
            "route": route,
            "recommended_action": winner.action,
            "quote_id": quote_id,
            "quote": inner or quote,
            "swap_receipt": {
                "status": "quoted",
                "transaction_hash": None,
                "scenario_id": scenario.scenario_id,
            },
        }
