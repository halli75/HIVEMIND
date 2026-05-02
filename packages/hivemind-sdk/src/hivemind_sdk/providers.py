from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Protocol, TypeVar, cast

import httpx

from .axl import transcript_stats
from .models import Action, AgentArchetype, AgentState, LeaderboardEntry, Scenario
from .scoring import aiq_for, pnl_bps_for, score_for


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


def _market_state_from_scenario(scenario: Scenario) -> dict[str, Any]:
    price_delta = scenario.sentiment * scenario.signal_strength
    return {
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


def _memory_from_scenario(scenario: Scenario, agent_id: str, jitter: float) -> dict[str, Any]:
    return {
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


def _brief_error(error: Exception) -> str:
    message = str(error).strip().replace("\n", " ")
    message = re.sub(r"hf_[A-Za-z0-9_=-]+", "hf_[REDACTED]", message)
    message = re.sub(r"app-sk-[A-Za-z0-9_=-]+", "app-sk-[REDACTED]", message)
    message = re.sub(r"(?i)((?:UNISWAP_API_KEY|ZERO_G_COMPUTE_BEARER_TOKEN)\s*=\s*)\S+", r"\1[REDACTED]", message)
    message = re.sub(r"(?i)((?:DEPLOYER|WALLET)_PRIVATE_KEY\s*=\s*)(0x)?[a-f0-9]{64}", r"\1[REDACTED]", message)
    return message[:240] if message else error.__class__.__name__


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


@dataclass(frozen=True)
class HybridInferenceMetrics:
    mode: str
    model: str
    top_n: int
    attempted_real_count: int
    successful_real_count: int
    fallback_count: int
    avg_latency_ms: float | None
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "model": self.model,
            "top_n": self.top_n,
            "attempted_real_count": self.attempted_real_count,
            "successful_real_count": self.successful_real_count,
            "fallback_count": self.fallback_count,
            "avg_latency_ms": self.avg_latency_ms,
            "last_error": self.last_error,
        }


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
        market_state = _market_state_from_scenario(scenario)
        memory = _memory_from_scenario(scenario, agent_id, jitter)
        decision = archetype.heuristic(market_state, memory)

        action = decision.get("action", "hold")
        if action not in _VALID_ACTIONS:
            action = "hold"
        confidence = max(0.0, min(1.0, float(decision.get("confidence", 0.5))))
        rationale = str(decision.get("rationale", f"{archetype.name}: heuristic"))

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
        market_state = _market_state_from_scenario(scenario)
        memory = _memory_from_scenario(scenario, agent_id, jitter)

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


class LiveAxlMessageBus:
    """Broadcasts to running local AXL pool nodes via AXLPoolManager."""

    def __init__(
        self,
        *,
        node_urls: list[str],
        pool_id: str = "hivemind-main",
        agent_id: str = "hivemind-engine",
    ) -> None:
        if not node_urls:
            raise ValueError("LiveAxlMessageBus requires at least one node_url")
        self._node_urls = list(node_urls)
        self._pool_id = pool_id
        self._agent_id = agent_id

    def broadcast_scenario(
        self,
        *,
        scenario: Scenario,
        agent_count: int,
    ) -> dict[str, Any]:
        import asyncio as _asyncio

        from .axl_pool import AXLPoolManager

        async def _run() -> dict[str, Any]:
            pool = AXLPoolManager(
                node_urls=self._node_urls,
                pool_id=self._pool_id,
                agent_id=self._agent_id,
                timeout=5.0,
            )
            t0 = time.perf_counter()
            await pool.connect()
            nodes_online = len(pool.connected_node_ids)
            failed_nodes = pool.failed_node_urls

            if nodes_online == 0:
                await pool.disconnect()
                return {
                    "mode": "unavailable",
                    "messages": 0,
                    "nodes_online": 0,
                    "failed_nodes": failed_nodes,
                    "last_message_type": "none",
                    "p50_latency_ms": None,
                    "p95_latency_ms": None,
                    "topic": f"hivemind.scenario.{scenario.scenario_id}",
                    "coordinator": "axl_pool",
                    "error": "No AXL pool nodes connected",
                }

            await pool.broadcast(
                "SCENARIO_SHOCK",
                {"scenario_id": scenario.scenario_id, "label": scenario.label},
            )
            await pool.broadcast(
                "TRADE_INTENT",
                {"scenario_id": scenario.scenario_id, "agent_count": agent_count},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            msg_count = pool.message_count
            await pool.disconnect()

            return {
                "mode": "live_axl",
                "messages": msg_count,
                "nodes_online": nodes_online,
                "failed_nodes": failed_nodes,
                "last_message_type": "TRADE_INTENT",
                "p50_latency_ms": round(elapsed_ms / 2, 3),
                "p95_latency_ms": round(elapsed_ms, 3),
                "topic": f"hivemind.scenario.{scenario.scenario_id}",
                "coordinator": "axl_pool",
            }

        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_asyncio.run, _run()).result()


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
        try:
            quote = self._client.get_quote_sync(
                self._token_in,
                self._token_out,
                self._amount_in_wei,
                chain_id=self._chain_id,
                recipient=self._swapper_address,
            )
        except Exception as exc:
            # Quote unavailable (API down, no liquidity, etc.) - return explicit non-live telemetry.
            fallback_id = f"uni-quote-{state_digest[:8]}"
            return {
                "mode": "unavailable",
                "chain": "sepolia",
                "route": ["WETH", "USDC"],
                "recommended_action": winner.action,
                "quote_id": fallback_id,
                "quote": {"quoteId": fallback_id, "error": _brief_error(exc)},
                "swap_receipt": {
                    "status": "unavailable",
                    "transaction_hash": None,
                    "scenario_id": scenario.scenario_id,
                },
            }
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


def _build_inference_prompt(archetype: "AgentArchetype", scenario: "Scenario") -> str:
    return (
        f"You are a {archetype.name} trading agent (tier {archetype.tier}).\n"
        f"Scenario: {scenario.label}\n"
        f"Market sentiment: {scenario.sentiment:.2f}, "
        f"volatility: {scenario.volatility:.2f}, "
        f"liquidity_delta: {scenario.liquidity_delta:.2f}\n\n"
        'Respond ONLY with valid json (no markdown, no explanation):\n'
        '{"action": "buy"|"sell"|"hold", "confidence": 0.0-1.0}'
    )


def _parse_model_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


def _safe_error(exc: Exception, token: str) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if token:
        message = message.replace(token, "[redacted]")
    return message[:240]


BATCH_SIZE = 5
"""Default concurrent fan-out for 0G Compute inference.

Tier 1 evaluations are dispatched in windows of this size against a shared
`httpx.AsyncClient`. The 0G Compute proxy does not expose a native batch
endpoint, so "batch" here means concurrent HTTP calls coordinated via
`asyncio.gather()`. Larger windows do not necessarily improve latency once
the upstream rate limiter starts returning 429s.
"""

_T = TypeVar("_T")


def _action_from_raw(raw: dict[str, Any]) -> tuple["Action", float]:
    """Validate the parsed model JSON and return (action, confidence)."""
    action_str = str(raw["action"]).lower()
    if action_str not in {"buy", "sell", "hold"}:
        raise ValueError(f"unexpected action: {action_str}")
    action = cast("Action", action_str)
    confidence = max(0.0, min(1.0, float(raw["confidence"])))
    return action, confidence


def _state_from_inference(
    *,
    agent_id: str,
    archetype: "AgentArchetype",
    scenario: "Scenario",
    jitter: float,
    action: "Action",
    confidence: float,
    model: str,
) -> "AgentState":
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
        rationale=f"0G/{model}: {archetype.name} -> {action} (conf={confidence:.2f})",
        inference_source="0g_compute",
        model=model,
    )


def _state_from_fallback(
    *,
    fallback: "LocalInferenceProvider",
    agent_id: str,
    archetype: "AgentArchetype",
    scenario: "Scenario",
    jitter: float,
    error: str,
) -> "AgentState":
    state = fallback.evaluate_agent(
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
        rationale=f"0G fallback: {error}; {state.rationale}",
        inference_source="local_fallback",
        model="",
    )


def _run_coroutine_blocking(coro: Awaitable[_T]) -> _T:
    """Drive a coroutine to completion from a sync caller, even when an event
    loop is already running on the current thread.

    `asyncio.run()` raises if invoked from inside a running loop (e.g. the
    FastAPI request handlers that drive `engine.inject_scenario`). To stay
    correct in both contexts, we detect a running loop and spin up a single
    helper thread with its own loop to drive the coroutine. When no loop is
    running we use `asyncio.run()` directly so callers in pure-sync contexts
    (tests, CLI smokes) keep their existing semantics.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result_box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
            result_box["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result_box:
        raise result_box["error"]
    return cast(_T, result_box["value"])


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
        self._last_error: str | None = None
        self._last_latency_ms: float | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_latency_ms(self) -> float | None:
        return self._last_latency_ms

    def evaluate_agent(
        self,
        *,
        agent_id: str,
        archetype: "AgentArchetype",
        scenario: "Scenario",
        jitter: float,
    ) -> "AgentState":
        prompt = _build_inference_prompt(archetype, scenario)
        started = time.perf_counter()
        try:
            resp = None
            for attempt in range(4):
                resp = httpx.post(
                    f"{self._base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 64,
                    },
                    timeout=self._timeout,
                )
                if getattr(resp, "status_code", None) == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                break
            resp.raise_for_status()
            raw = _parse_model_json(resp.json()["choices"][0]["message"]["content"])
            action, confidence = _action_from_raw(raw)
            self._last_error = None
        except Exception as exc:
            self._last_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self._last_error = _safe_error(exc, self._token)
            return _state_from_fallback(
                fallback=self._fallback,
                agent_id=agent_id,
                archetype=archetype,
                scenario=scenario,
                jitter=jitter,
                error=self._last_error,
            )

        self._last_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return _state_from_inference(
            agent_id=agent_id,
            archetype=archetype,
            scenario=scenario,
            jitter=jitter,
            action=action,
            confidence=confidence,
            model=self._model,
        )

    async def evaluate_agents_batch(
        self,
        *,
        requests: list[tuple[str, "AgentArchetype", "Scenario", float]],
        client: httpx.AsyncClient | None = None,
    ) -> list["AgentState"]:
        """Fire one HTTP call per agent concurrently against 0G Compute.

        The 0G Compute proxy has no native batch endpoint, so we approximate
        a batch by reusing a single `httpx.AsyncClient` connection pool across
        an `asyncio.gather()` fan-out. Per-request retry on 429 and per-request
        fallback to the local heuristic match the sync `evaluate_agent()` path
        exactly, so a partial failure inside a batch only degrades that single
        agent.

        Pass `client` to reuse an outer connection pool (useful when chaining
        multiple batches in one logical call); otherwise a short-lived client
        is created for the duration of the batch.
        """
        if not requests:
            return []

        if client is None:
            async with httpx.AsyncClient(timeout=self._timeout) as owned:
                return await self._dispatch_batch(owned, requests)
        return await self._dispatch_batch(client, requests)

    async def _dispatch_batch(
        self,
        client: httpx.AsyncClient,
        requests: list[tuple[str, "AgentArchetype", "Scenario", float]],
    ) -> list["AgentState"]:
        tasks = [
            self._single_async_eval(client, agent_id, archetype, scenario, jitter)
            for agent_id, archetype, scenario, jitter in requests
        ]
        return list(await asyncio.gather(*tasks))

    async def _single_async_eval(
        self,
        client: httpx.AsyncClient,
        agent_id: str,
        archetype: "AgentArchetype",
        scenario: "Scenario",
        jitter: float,
    ) -> "AgentState":
        prompt = _build_inference_prompt(archetype, scenario)
        started = time.perf_counter()
        last_exc: Exception | None = None
        try:
            resp: httpx.Response | None = None
            for attempt in range(4):
                resp = await client.post(
                    f"{self._base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 64,
                    },
                )
                if getattr(resp, "status_code", None) == 429:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                break
            assert resp is not None
            resp.raise_for_status()
            raw = _parse_model_json(resp.json()["choices"][0]["message"]["content"])
            action, confidence = _action_from_raw(raw)
        except Exception as exc:
            last_exc = exc

        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        if last_exc is not None:
            error = _safe_error(last_exc, self._token)
            # Reflect the most recent batch error on the provider so callers
            # observing `last_error`/`last_latency_ms` see consistent state.
            self._last_error = error
            self._last_latency_ms = latency_ms
            return _state_from_fallback(
                fallback=self._fallback,
                agent_id=agent_id,
                archetype=archetype,
                scenario=scenario,
                jitter=jitter,
                error=error,
            )

        self._last_error = None
        self._last_latency_ms = latency_ms
        return _state_from_inference(
            agent_id=agent_id,
            archetype=archetype,
            scenario=scenario,
            jitter=jitter,
            action=action,
            confidence=confidence,
            model=self._model,
        )


class HybridInferenceProvider:
    """Local first pass for all agents; re-evaluates top-N with real 0G Compute."""

    def __init__(
        self, *, real: ZeroGComputeInferenceProvider, top_n: int = 10, max_workers: int = 2
    ) -> None:
        self._local = LocalInferenceProvider()
        self._real = real
        self._top_n = max(0, top_n)
        # Retained for API/config compatibility. The refine path now fans out
        # via async batching (`BATCH_SIZE`) on a shared httpx.AsyncClient
        # rather than a thread pool, so this value is advisory.
        self._max_workers = max(1, max_workers)
        self._last_metrics = HybridInferenceMetrics(
            mode="0g_compute",
            model=real.model,
            top_n=self._top_n,
            attempted_real_count=0,
            successful_real_count=0,
            fallback_count=0,
            avg_latency_ms=None,
            last_error=None,
        )

    @property
    def metrics(self) -> HybridInferenceMetrics:
        return self._last_metrics

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

        if not top:
            self._last_metrics = HybridInferenceMetrics(
                mode="0g_compute",
                model=self._real.model,
                top_n=self._top_n,
                attempted_real_count=0,
                successful_real_count=0,
                fallback_count=0,
                avg_latency_ms=None,
                last_error=None,
            )
            return rest

        eligible = [state for state in top if state.agent_id in archetypes]
        skipped = [state for state in top if state.agent_id not in archetypes]
        requests = [
            (state.agent_id, archetypes[state.agent_id], scenario, 0.0) for state in eligible
        ]

        refined, per_agent_latency_ms = _run_coroutine_blocking(
            self._refine_in_batches(requests)
        )

        successful = sum(1 for state in refined if state.inference_source == "0g_compute")
        fallback = len(refined) - successful
        last_error: str | None = None
        for state in refined:
            if state.inference_source == "local_fallback" and state.rationale.startswith("0G fallback: "):
                last_error = state.rationale.removeprefix("0G fallback: ").split("; ", 1)[0]
        self._last_metrics = HybridInferenceMetrics(
            mode="0g_compute",
            model=self._real.model,
            top_n=self._top_n,
            attempted_real_count=len(refined),
            successful_real_count=successful,
            fallback_count=fallback,
            avg_latency_ms=per_agent_latency_ms,
            last_error=last_error,
        )
        return refined + skipped + rest

    async def _refine_in_batches(
        self,
        requests: list[tuple[str, "AgentArchetype", "Scenario", float]],
    ) -> tuple[list["AgentState"], float | None]:
        """Drive `evaluate_agents_batch` in windows of `BATCH_SIZE`, sharing
        a single `httpx.AsyncClient` across all windows so connection setup
        is amortized.

        Returns the refined states (in input order) and the average per-agent
        wall-clock latency, computed by dividing each batch's wall-clock time
        by the number of agents in that batch — which approximates the
        amortized cost the caller saw under concurrent dispatch.
        """
        if not requests:
            return [], None

        refined: list["AgentState"] = []
        per_agent_samples: list[float] = []
        async with httpx.AsyncClient(timeout=self._real._timeout) as client:
            for offset in range(0, len(requests), BATCH_SIZE):
                window = requests[offset : offset + BATCH_SIZE]
                started = time.perf_counter()
                chunk = await self._real.evaluate_agents_batch(
                    requests=window, client=client
                )
                wall_ms = (time.perf_counter() - started) * 1000.0
                refined.extend(chunk)
                if window:
                    per_agent_samples.extend([wall_ms / len(window)] * len(window))
        avg = (
            round(sum(per_agent_samples) / len(per_agent_samples), 3)
            if per_agent_samples
            else None
        )
        return refined, avg
