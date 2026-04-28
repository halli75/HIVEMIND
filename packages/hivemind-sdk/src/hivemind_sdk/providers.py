from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from .axl import transcript_stats
from .models import Action, AgentArchetype, AgentState, LeaderboardEntry, Scenario
from .scoring import aiq_for, choose_action, confidence_for, pnl_bps_for, score_for


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


def _build_inference_prompt(archetype: "AgentArchetype", scenario: "Scenario") -> str:
    return (
        f"You are a {archetype.name} trading agent (tier {archetype.tier}).\n"
        f"Scenario: {scenario.label}\n"
        f"Market sentiment: {scenario.sentiment:.2f}, "
        f"volatility: {scenario.volatility:.2f}, "
        f"liquidity_delta: {scenario.liquidity_delta:.2f}\n\n"
        'Respond ONLY with valid JSON (no markdown, no explanation):\n'
        '{"action": "buy"|"sell"|"hold", "confidence": 0.0-1.0}'
    )


class ZeroGComputeInferenceProvider:
    def __init__(
        self,
        *,
        api_base_url: str,
        bearer_token: str,
        model: str,
        timeout: float = 15.0,
    ) -> None:
        self._base = api_base_url.rstrip("/")
        self._token = bearer_token
        self._model = model
        self._timeout = timeout
        self._fallback = LocalInferenceProvider()

    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: "AgentArchetype",
        scenario: "Scenario",
        jitter: float,
    ) -> "AgentState":
        prompt = _build_inference_prompt(archetype, scenario)
        try:
            resp = httpx.post(
                f"{self._base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 64,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            raw = json.loads(resp.json()["choices"][0]["message"]["content"])
            action_str = str(raw["action"]).lower()
            if action_str not in {"buy", "sell", "hold"}:
                raise ValueError(f"unexpected action: {action_str}")
            action = cast("Action", action_str)
            confidence = float(raw["confidence"])
            confidence = max(0.0, min(1.0, confidence))
        except Exception:
            state = self._fallback.evaluate_agent(
                agent_id=agent_id, archetype=archetype, scenario=scenario, jitter=jitter
            )
            return AgentState(
                agent_id=state.agent_id,
                archetype=state.archetype,
                tier=state.tier,
                action=state.action,
                confidence=state.confidence,
                pnl_bps=state.pnl_bps,
                aiq=state.aiq,
                score=state.score,
                rationale=state.rationale,
                inference_source="local_fallback",
                model="",
            )

        aiq = aiq_for(archetype, scenario, confidence, jitter)
        pnl_bps = pnl_bps_for(action, archetype, scenario, jitter)
        score = score_for(confidence, pnl_bps, aiq, archetype.tier)
        return AgentState(
            agent_id=agent_id,
            archetype=archetype.name,
            tier=archetype.tier,
            action=action,
            confidence=confidence,
            pnl_bps=pnl_bps,
            aiq=aiq,
            score=score,
            rationale=f"0G/{self._model}: {archetype.name} → {action} (conf={confidence:.2f})",
            inference_source="0g_compute",
            model=self._model,
        )


class HybridInferenceProvider:
    """Local first pass for all agents; re-evaluates top-N with real 0G Compute."""

    def __init__(self, *, real: ZeroGComputeInferenceProvider, top_n: int = 10) -> None:
        self._local = LocalInferenceProvider()
        self._real = real
        self._top_n = top_n

    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: "AgentArchetype",
        scenario: "Scenario",
        jitter: float,
    ) -> "AgentState":
        return self._local.evaluate_agent(
            agent_id=agent_id, archetype=archetype, scenario=scenario, jitter=jitter
        )

    def refine_top_n(
        self,
        states: list["AgentState"],
        scenario: "Scenario",
        archetypes: dict[str, "AgentArchetype"],
    ) -> list["AgentState"]:
        sorted_states = sorted(states, key=lambda s: s.score, reverse=True)
        top = sorted_states[: self._top_n]
        rest = sorted_states[self._top_n :]

        def refine_one(state: "AgentState") -> "AgentState":
            archetype = archetypes[state.agent_id]
            return self._real.evaluate_agent(
                agent_id=state.agent_id,
                archetype=archetype,
                scenario=scenario,
                jitter=0.0,
            )

        with ThreadPoolExecutor(max_workers=max(1, len(top))) as executor:
            refined = list(executor.map(refine_one, top))

        return refined + rest
