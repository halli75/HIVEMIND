from __future__ import annotations

import asyncio
import hashlib
import json
import os as _os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence, Union

from .archetypes import DEFAULT_ARCHETYPES
from .axl_pool import AXLPoolManager
from .models import (
    AgentArchetype,
    AgentState,
    IntegrationEnvelope,
    LeaderboardEntry,
    RunMode,
    Scenario,
    SwarmSnapshot,
    TierMetric,
)
from .providers import (
    ExecutionProvider,
    HybridInferenceProvider,
    InferenceProvider,
    LocalExecutionProvider,
    LocalAxlMessageBus,
    LocalInferenceProvider,
    LocalMessageBus,
    LocalStorageProvider,
    MessageBus,
    MockInferenceProvider,
    SeedReplay,
    StorageProvider,
    use_mock_inference,
)


TIER1_SIZE = 10
TIER2_FRACTION = 0.18
TIER1_COOLDOWN_TICKS = 2
TIER1_SEMAPHORE = 10
TOKEN_BUCKET_CAPACITY = 10
TOKEN_BUCKET_REFILL_RATE = 10.0


class TokenBucket:
    """Token-bucket rate limiter for Tier 1 (0G Compute) inference calls.

    Default config (``capacity=10``, ``refill_rate=10`` tokens/sec) lets up to
    10 calls burst, then sustains ~10 calls per second. ``try_consume`` returns
    False when the bucket is empty so the caller can fall back to the cheaper
    Tier 2 heuristic path instead of stalling on the upstream API.
    """

    def __init__(
        self,
        capacity: int = TOKEN_BUCKET_CAPACITY,
        refill_rate: float = TOKEN_BUCKET_REFILL_RATE,
        *,
        clock: callable = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._clock = clock
        self._tokens = float(capacity)
        self._last_refill = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self._capacity, self._tokens + elapsed * self._refill_rate
            )
            self._last_refill = now

    def try_consume(self, n: int = 1) -> bool:
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    @property
    def remaining(self) -> int:
        self._refill()
        return int(self._tokens)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def refill_rate(self) -> float:
        return self._refill_rate


@dataclass(frozen=True)
class _AgentIdentity:
    agent_id: str
    archetype: AgentArchetype


class FileTranscriptRecorder:
    """Persists scenario run transcripts under an ignored runs/ root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def save(self, *, snapshot: SwarmSnapshot, event: dict[str, object]) -> dict[str, object]:
        now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        run_dir = self._root / stamp
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = run_dir / "transcript.json"
        index = 2
        while transcript_path.exists():
            transcript_path = run_dir / f"transcript-{index}.json"
            index += 1
        payload = {
            "schema": "hivemind.run.transcript.v0",
            "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "event": event,
            "snapshot": snapshot.to_dict(),
        }
        with transcript_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return {
            "run_id": stamp,
            "path": str(transcript_path),
        }


class SwarmEngine:
    """Deterministic local mock engine for hackathon development and tests."""

    def __init__(
        self,
        *,
        agent_count: int | None = None,
        count: int | None = None,
        seed: str = "hivemind-local",
        archetypes: Sequence[Union[AgentArchetype, type[AgentArchetype]]] = DEFAULT_ARCHETYPES,
        run_mode: RunMode | None = None,
        seed_snapshot_dir: str | Path | None = None,
        transcript_root: str | Path | None = None,
        axl_transcript_path: str | Path | None = None,
        inference_provider: InferenceProvider | None = None,
        storage_provider: StorageProvider | None = None,
        message_bus: MessageBus | None = None,
        execution_provider: ExecutionProvider | None = None,
        axl_node_urls: list[str] | None = None,
        axl_pool_id: str = "hivemind-main",
        axl_agent_id: str = "hivemind-engine",
        token_bucket: TokenBucket | None = None,
    ) -> None:
        if agent_count is not None and count is not None and agent_count != count:
            raise ValueError("pass either agent_count or count, not both")
        resolved_count = agent_count if agent_count is not None else count
        if resolved_count is None:
            resolved_count = 24
        if resolved_count <= 0:
            raise ValueError("agent_count must be positive")
        if not archetypes:
            raise ValueError("at least one archetype is required")
        normalized_archetypes: list[AgentArchetype] = []
        for arch in archetypes:
            if isinstance(arch, type) and issubclass(arch, AgentArchetype):
                normalized_archetypes.append(arch())
            elif isinstance(arch, AgentArchetype):
                normalized_archetypes.append(arch)
            else:
                raise TypeError(
                    f"archetypes must be AgentArchetype subclasses or instances, got {arch!r}"
                )
        archetypes = tuple(normalized_archetypes)

        self._seed = seed
        self._replay = SeedReplay.from_directory(seed_snapshot_dir)
        self._inference_provider = inference_provider or LocalInferenceProvider()
        local_axl_enabled = bool(axl_transcript_path) or isinstance(message_bus, LocalAxlMessageBus)
        live_0g_enabled = isinstance(self._inference_provider, HybridInferenceProvider)
        self._run_mode: RunMode = run_mode or self._compose_run_mode(
            local_axl=local_axl_enabled,
            live_0g=live_0g_enabled,
        )
        self._storage_provider = storage_provider or LocalStorageProvider(replay=self._replay)
        self._message_bus = message_bus or (
            LocalAxlMessageBus(transcript_path=axl_transcript_path)
            if axl_transcript_path
            else LocalMessageBus(replay=self._replay)
        )
        self._execution_provider = execution_provider or LocalExecutionProvider(replay=self._replay)
        self._transcript_recorder: FileTranscriptRecorder | None = None
        self._agents = tuple(
            _AgentIdentity(
                agent_id=f"agent-{index + 1:03d}",
                archetype=archetypes[index % len(archetypes)],
            )
            for index in range(resolved_count)
        )
        self._sequence = 0
        self._tick_index = 0
        self._last_inference_tick: dict[str, int] = {}
        self._cooldown_until: dict[str, int] = {}
        self._last_action: dict[str, str] = {}
        self._last_pnl_bps: dict[str, float] = {}
        self._axl_node_urls = list(axl_node_urls or [])
        self._axl_pool_id = axl_pool_id
        self._axl_agent_id = axl_agent_id
        self._axl_pool: AXLPoolManager | None = None
        self._axl_urgency_boost: dict[str, float] = {}
        self._token_bucket = token_bucket or TokenBucket()
        self._last_rate_limited_count: int = 0
        self._last_rate_limited_agents: tuple[str, ...] = ()
        self._snapshot = self.inject_scenario(Scenario.neutral())
        if transcript_root is not None:
            self._transcript_recorder = FileTranscriptRecorder(transcript_root)

    @property
    def latest_snapshot(self) -> SwarmSnapshot:
        return self._snapshot

    def record_inft_mint(
        self,
        *,
        token_id: int | None,
        tx_hash: str | None,
        contract_address: str,
        storage_uri: str | None,
        storage_hash: str | None,
        content_hash: str | None = None,
    ) -> SwarmSnapshot:
        """Attach the latest real iNFT mint proof to the current snapshot."""
        snapshot = self._snapshot
        previous_inft = dict(snapshot.proof.get("inft", {}))
        inft_proof = {
            **previous_inft,
            "status": "minted",
            "contract_address": contract_address,
            "chain": "0g-galileo",
            "chain_id": 16602,
            "token_id": token_id,
            "tx_hash": tx_hash,
            "storage_uri": storage_uri,
            "storage_hash": storage_hash,
            "content_hash": content_hash,
            "memory_uri": storage_uri or previous_inft.get("memory_uri"),
            "explorer": f"https://chainscan-galileo.0g.ai/address/{contract_address}",
            "tx_explorer": f"https://chainscan-galileo.0g.ai/tx/{tx_hash}" if tx_hash else None,
        }
        proof = {**snapshot.proof, "inft": inft_proof}
        self._snapshot = SwarmSnapshot(
            sequence=snapshot.sequence,
            run_mode=snapshot.run_mode,
            scenario=snapshot.scenario,
            agents=snapshot.agents,
            tier_metrics=snapshot.tier_metrics,
            leaderboard=snapshot.leaderboard,
            integrations=snapshot.integrations,
            transcript=snapshot.transcript,
            proof=proof,
            event_log=(*snapshot.event_log, f"inft:minted:{token_id}"),
        )
        return self._snapshot

    @property
    def run_mode(self) -> RunMode:
        return self._run_mode

    @property
    def token_bucket(self) -> TokenBucket:
        return self._token_bucket

    @property
    def token_bucket_remaining(self) -> int:
        return self._token_bucket.remaining

    @property
    def last_rate_limited_count(self) -> int:
        return self._last_rate_limited_count

    @property
    def last_rate_limited_agents(self) -> tuple[str, ...]:
        return self._last_rate_limited_agents

    @staticmethod
    def _compose_run_mode(*, local_axl: bool, live_0g: bool) -> RunMode:
        if local_axl and live_0g:
            return "local_axl+live_0g"
        if local_axl:
            return "local_axl"
        if live_0g:
            return "live_0g"
        return "mock"

    def inject_scenario(self, scenario: Scenario) -> SwarmSnapshot:
        self._sequence += 1
        agent_states = list(self._evaluate_agent(agent, scenario) for agent in self._agents)
        if isinstance(self._inference_provider, HybridInferenceProvider):
            archetype_map = {a.agent_id: a.archetype for a in self._agents}
            agent_states = self._inference_provider.refine_top_n(
                agent_states, scenario, archetype_map
            )
        agent_states = tuple(agent_states)
        leaderboard = self._build_leaderboard(agent_states)
        tier_metrics = self._build_tier_metrics(agent_states, scenario)
        integrations = self._integration_envelope(scenario, agent_states, leaderboard)
        transcript = self._build_transcript(scenario, integrations)
        proof = self._build_proof(scenario, leaderboard, integrations, transcript)
        event_log = (
            f"scenario:{scenario.scenario_id}",
            f"axl:{integrations.gensyn_axl['mode']}:messages:{integrations.gensyn_axl['messages']}",
            f"0g:{integrations.zero_g_storage['mode']}:{integrations.zero_g_storage['uri']}",
            f"uniswap:{integrations.uniswap['mode']}:quote:{integrations.uniswap['quote_id']}",
        )
        snapshot = SwarmSnapshot(
            sequence=self._sequence,
            run_mode=self._run_mode,
            scenario=scenario,
            agents=agent_states,
            tier_metrics=tier_metrics,
            leaderboard=leaderboard,
            integrations=integrations,
            transcript=transcript,
            proof=proof,
            event_log=event_log,
        )
        if self._transcript_recorder is not None:
            transcript_ref = self._transcript_recorder.save(
                snapshot=snapshot,
                event={"type": "scenario", "scenario": scenario.to_dict()},
            )
            transcript = {**transcript, **transcript_ref}
            proof = {**proof, "transcript": transcript_ref}
            snapshot = SwarmSnapshot(
                sequence=snapshot.sequence,
                run_mode=snapshot.run_mode,
                scenario=snapshot.scenario,
                agents=snapshot.agents,
                tier_metrics=snapshot.tier_metrics,
                leaderboard=snapshot.leaderboard,
                integrations=snapshot.integrations,
                transcript=transcript,
                proof=proof,
                event_log=snapshot.event_log,
            )
        self._snapshot = snapshot
        return self._snapshot

    def _evaluate_agent(self, agent: _AgentIdentity, scenario: Scenario) -> AgentState:
        jitter = self._jitter(agent.agent_id, scenario.scenario_id)
        return self._inference_provider.evaluate_agent(
            agent_id=agent.agent_id,
            archetype=agent.archetype,
            scenario=scenario,
            jitter=jitter,
        )

    def _jitter(self, agent_id: str, scenario_id: str) -> float:
        digest = hashlib.sha256(f"{self._seed}:{scenario_id}:{agent_id}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    @staticmethod
    def _build_leaderboard(agent_states: tuple[AgentState, ...]) -> tuple[LeaderboardEntry, ...]:
        ranked = sorted(agent_states, key=lambda agent: (-agent.score, agent.agent_id))
        return tuple(
            LeaderboardEntry(
                rank=index + 1,
                agent_id=agent.agent_id,
                archetype=agent.archetype,
                tier=agent.tier,
                action=agent.action,
                score=agent.score,
                confidence=agent.confidence,
                pnl_bps=agent.pnl_bps,
                aiq=agent.aiq,
            )
            for index, agent in enumerate(ranked)
        )

    @staticmethod
    def _build_tier_metrics(
        agent_states: tuple[AgentState, ...], scenario: Scenario
    ) -> tuple[TierMetric, ...]:
        by_tier: dict[int, list[AgentState]] = defaultdict(list)
        for agent in agent_states:
            by_tier[agent.tier].append(agent)

        metrics: list[TierMetric] = []
        for tier in sorted(by_tier):
            tier_agents = by_tier[tier]
            fallback_count = sum(1 for agent in tier_agents if agent.confidence < 0.5)
            avg_aiq = sum(agent.aiq for agent in tier_agents) / len(tier_agents)
            avg_latency = 18.0 + tier * 7.5 + scenario.volatility * 24.0 + fallback_count * 1.5
            metrics.append(
                TierMetric(
                    tier=tier,
                    agent_count=len(tier_agents),
                    inference_calls=len(tier_agents),
                    fallback_count=fallback_count,
                    avg_latency_ms=round(avg_latency, 3),
                    aiq_size=round(avg_aiq * len(tier_agents), 4),
                )
            )
        return tuple(metrics)

    def _integration_envelope(
        self,
        scenario: Scenario,
        agent_states: tuple[AgentState, ...],
        leaderboard: tuple[LeaderboardEntry, ...],
    ) -> IntegrationEnvelope:
        winner = leaderboard[0]
        state_digest = hashlib.sha256(
            f"{self._seed}:{scenario.scenario_id}:{winner.agent_id}:{self._sequence}".encode("utf-8")
        ).hexdigest()[:16]
        storage = self._storage_provider.write_state(
            sequence=self._sequence,
            scenario=scenario,
            winner=winner,
            state_digest=state_digest,
        )
        axl = self._message_bus.broadcast_scenario(
            scenario=scenario,
            agent_count=len(agent_states),
        )
        execution = self._execution_provider.prepare_trade(
            scenario=scenario,
            winner=winner,
            state_digest=state_digest,
        )
        _is_real = isinstance(self._inference_provider, HybridInferenceProvider)
        _metrics = self._inference_provider.metrics if _is_real else None
        _metric_payload = _metrics.to_dict() if _metrics else {}
        return IntegrationEnvelope(
            zero_g_compute={
                "mode": "0g_compute" if _is_real else "mock",
                "request_id": f"0g-compute-{self._sequence:04d}",
                "evaluated_agents": len(agent_states),
                "inference_calls": _metric_payload.get("attempted_real_count", 0),
                "model_tier": _metric_payload.get("model", "local-deterministic"),
                "real_inference_count": _metric_payload.get("successful_real_count", 0),
                "fallback_count": _metric_payload.get("fallback_count", 0),
                "top_n": _metric_payload.get("top_n", 0),
                "avg_latency_ms": _metric_payload.get("avg_latency_ms"),
                "last_error": _metric_payload.get("last_error"),
            },
            zero_g_storage=storage,
            gensyn_axl=axl,
            uniswap=execution,
        )

    @staticmethod
    def _build_transcript(
        scenario: Scenario, integrations: IntegrationEnvelope
    ) -> dict[str, object]:
        return {
            "latest_scenario": scenario.to_dict(),
            "axl_message_count": integrations.gensyn_axl["messages"],
            "axl_nodes_online": integrations.gensyn_axl.get("nodes_online", 0),
            "axl_failed_nodes": integrations.gensyn_axl.get("failed_nodes", []),
            "axl_last_message_type": integrations.gensyn_axl.get("last_message_type"),
            "axl_p50_latency_ms": integrations.gensyn_axl.get("p50_latency_ms"),
            "axl_p95_latency_ms": integrations.gensyn_axl.get("p95_latency_ms"),
            "axl_transcript_path": integrations.gensyn_axl.get("transcript_path"),
            "axl_messages": integrations.gensyn_axl.get("transcript", []),
        }

    @staticmethod
    def _build_proof(
        scenario: Scenario,
        leaderboard: tuple[LeaderboardEntry, ...],
        integrations: IntegrationEnvelope,
        transcript: dict[str, object],
    ) -> dict[str, object]:
        winner = leaderboard[0]
        return {
            "latest_scenario": scenario.to_dict(),
            "axl": {
                "message_count": transcript["axl_message_count"],
                "nodes_online": transcript["axl_nodes_online"],
                "failed_nodes": transcript["axl_failed_nodes"],
                "last_message_type": transcript["axl_last_message_type"],
                "p50_latency_ms": transcript["axl_p50_latency_ms"],
                "p95_latency_ms": transcript["axl_p95_latency_ms"],
                "transcript_path": transcript["axl_transcript_path"],
            },
            "zero_g_storage": {
                "uri": integrations.zero_g_storage["uri"],
                "hash": integrations.zero_g_storage["hash"],
                "readback": integrations.zero_g_storage["readback"],
            },
            "inft": {
                "status": "active" if _os.environ.get("INFT_CONTRACT_ADDRESS") else "placeholder",
                "contract_address": _os.environ.get("INFT_CONTRACT_ADDRESS"),
                "chain": "0g-galileo" if _os.environ.get("INFT_CONTRACT_ADDRESS") else None,
                "chain_id": 16602 if _os.environ.get("INFT_CONTRACT_ADDRESS") else None,
                "token_id": None,
                "local_address": f"local-inft://{winner.agent_id}",
                "memory_uri": integrations.zero_g_storage["uri"],
                "explorer": (
                    f"https://chainscan-galileo.0g.ai/address/{_os.environ['INFT_CONTRACT_ADDRESS']}"
                    if _os.environ.get("INFT_CONTRACT_ADDRESS") else None
                ),
            },
            "uniswap": {
                "quote": integrations.uniswap["quote"],
                "swap_receipt": integrations.uniswap["swap_receipt"],
            },
        }

    # ----- async 3-tier tick loop -------------------------------------------------

    def _urgency(self, agent: _AgentIdentity, scenario: Scenario) -> float:
        last_tick = self._last_inference_tick.get(agent.agent_id, -10)
        time_since = max(0, self._tick_index - last_tick)
        portfolio_delta = abs(self._last_pnl_bps.get(agent.agent_id, 0.0)) / 100.0
        axl_signal_strength = scenario.signal_strength * abs(scenario.sentiment)
        position_proximity = (
            scenario.volatility * agent.archetype.hedge_bias
            + max(0.0, -scenario.liquidity_delta) * agent.archetype.liquidity_bias
        )
        cooldown_left = max(0, self._cooldown_until.get(agent.agent_id, 0) - self._tick_index)
        pool_boost = self._axl_urgency_boost.get(agent.agent_id, 0.0)
        urgency = (
            time_since
            + portfolio_delta
            + axl_signal_strength
            + position_proximity
            + pool_boost
            - cooldown_left * 0.6
        )
        return urgency

    def _assign_tiers(
        self, scenario: Scenario
    ) -> tuple[list[_AgentIdentity], list[_AgentIdentity], list[_AgentIdentity]]:
        scored = sorted(
            self._agents,
            key=lambda a: (-self._urgency(a, scenario), a.agent_id),
        )
        n = len(scored)
        tier1_size = min(TIER1_SIZE, n)
        tier1 = scored[:tier1_size]
        tier2_size = max(0, int(round(n * TIER2_FRACTION)))
        tier2 = scored[tier1_size : tier1_size + tier2_size]
        tier3 = scored[tier1_size + tier2_size :]
        return tier1, tier2, tier3

    async def _tier1_evaluate(
        self,
        agent: _AgentIdentity,
        scenario: Scenario,
        semaphore: asyncio.Semaphore,
    ) -> AgentState:
        async with semaphore:
            jitter = self._jitter(agent.agent_id, scenario.scenario_id)
            return await asyncio.to_thread(
                self._inference_provider.evaluate_agent,
                agent_id=agent.agent_id,
                archetype=agent.archetype,
                scenario=scenario,
                jitter=jitter,
            )

    def _tier2_evaluate(self, agent: _AgentIdentity, scenario: Scenario) -> AgentState:
        jitter = self._jitter(agent.agent_id, scenario.scenario_id)
        market_state = _market_state_from_scenario(scenario)
        memory = _memory_from_scenario(scenario, agent.agent_id, jitter)
        decision = agent.archetype.heuristic(market_state, memory)
        return _agent_state_from_decision(agent, scenario, decision, jitter)

    def _tier3_evaluate(self, agent: _AgentIdentity, scenario: Scenario) -> AgentState:
        jitter = self._jitter(agent.agent_id, scenario.scenario_id)
        last_action = self._last_action.get(agent.agent_id, "hold")
        decision = {
            "action": last_action,
            "confidence": 0.3,
            "rationale": f"{agent.archetype.name}: tier-3 background carry of last action",
        }
        return _agent_state_from_decision(agent, scenario, decision, jitter)

    async def tick(self, scenario: Scenario | None = None) -> SwarmSnapshot:
        """Execute one async tick across the 3-tier state machine.

        Tier 1: top 10 by urgency, real inference, gated by Semaphore(10).
        Tier 2: next 18%, synchronous heuristic.
        Tier 3: rest, minimal carry of prior action.
        """

        self._tick_index += 1
        active_scenario = scenario or self._snapshot.scenario
        self._sequence += 1

        await self._axl_pool_drain()
        for agent_id in list(self._axl_urgency_boost):
            decayed = self._axl_urgency_boost[agent_id] * 0.5
            if decayed < 0.05:
                del self._axl_urgency_boost[agent_id]
            else:
                self._axl_urgency_boost[agent_id] = decayed

        tier1_proposed, tier2, tier3 = self._assign_tiers(active_scenario)

        # Token-bucket gate: agents that can't get a token fall through to the
        # cheaper Tier 2 heuristic path for this tick instead of blocking on
        # the upstream 0G Compute API.
        tier1_admitted: list[_AgentIdentity] = []
        tier1_rate_limited: list[_AgentIdentity] = []
        for agent in tier1_proposed:
            if self._token_bucket.try_consume():
                tier1_admitted.append(agent)
            else:
                tier1_rate_limited.append(agent)

        self._last_rate_limited_count = len(tier1_rate_limited)
        self._last_rate_limited_agents = tuple(a.agent_id for a in tier1_rate_limited)
        tier1 = tier1_admitted

        semaphore = asyncio.Semaphore(TIER1_SEMAPHORE)
        tier1_results = await asyncio.gather(
            *(self._tier1_evaluate(a, active_scenario, semaphore) for a in tier1)
        )
        rate_limited_results = [
            self._tier2_evaluate(a, active_scenario) for a in tier1_rate_limited
        ]
        tier2_results = [self._tier2_evaluate(a, active_scenario) for a in tier2]
        tier3_results = [self._tier3_evaluate(a, active_scenario) for a in tier3]

        for agent, state in zip(tier1, tier1_results):
            self._last_inference_tick[agent.agent_id] = self._tick_index
            self._cooldown_until[agent.agent_id] = self._tick_index + TIER1_COOLDOWN_TICKS
            self._last_action[agent.agent_id] = state.action
            self._last_pnl_bps[agent.agent_id] = state.pnl_bps
        for agent, state in (
            list(zip(tier1_rate_limited, rate_limited_results))
            + list(zip(tier2, tier2_results))
            + list(zip(tier3, tier3_results))
        ):
            self._last_action[agent.agent_id] = state.action
            self._last_pnl_bps[agent.agent_id] = state.pnl_bps

        agent_states_by_id: dict[str, AgentState] = {}
        for agent, state in zip(tier1, tier1_results):
            agent_states_by_id[agent.agent_id] = state
        for agent, state in zip(tier1_rate_limited, rate_limited_results):
            agent_states_by_id[agent.agent_id] = state
        for agent, state in zip(tier2, tier2_results):
            agent_states_by_id[agent.agent_id] = state
        for agent, state in zip(tier3, tier3_results):
            agent_states_by_id[agent.agent_id] = state

        agent_states = tuple(agent_states_by_id[a.agent_id] for a in self._agents)
        leaderboard = self._build_leaderboard(agent_states)
        tier_metrics = self._build_tier_metrics(agent_states, active_scenario)
        integrations = self._integration_envelope(active_scenario, agent_states, leaderboard)
        transcript = self._build_transcript(active_scenario, integrations)
        transcript = {
            **transcript,
            "rate_limited_count": self._last_rate_limited_count,
            "rate_limited_agents": list(self._last_rate_limited_agents),
            "token_bucket_remaining": self._token_bucket.remaining,
            "token_bucket_capacity": self._token_bucket.capacity,
        }
        proof = self._build_proof(active_scenario, leaderboard, integrations, transcript)
        event_log = (
            f"tick:{self._tick_index}",
            f"scenario:{active_scenario.scenario_id}",
            f"tier1:{len(tier1)} tier2:{len(tier2)} tier3:{len(tier3)} rate_limited:{self._last_rate_limited_count}",
            f"axl:{integrations.gensyn_axl['mode']}:messages:{integrations.gensyn_axl['messages']}",
        )

        snapshot = SwarmSnapshot(
            sequence=self._sequence,
            run_mode=self._run_mode,
            scenario=active_scenario,
            agents=agent_states,
            tier_metrics=tier_metrics,
            leaderboard=leaderboard,
            integrations=integrations,
            transcript=transcript,
            proof=proof,
            event_log=event_log,
        )
        self._snapshot = snapshot

        await self._axl_pool_publish_tier1(active_scenario, tier1, tier1_results)
        self._print_tick_summary(self._tick_index, tier1, tier1_results, tier2, tier2_results, tier3, tier3_results)
        return snapshot

    async def run_async(self, ticks: int = 1, scenario: Scenario | None = None) -> SwarmSnapshot:
        if ticks <= 0:
            raise ValueError("ticks must be positive")
        snapshot = self._snapshot
        for _ in range(ticks):
            snapshot = await self.tick(scenario)
        return snapshot

    def run(self, ticks: int = 1, scenario: Scenario | None = None) -> SwarmSnapshot:
        """Synchronous wrapper around ``run_async`` for quickstart usage."""
        return asyncio.run(self.run_async(ticks=ticks, scenario=scenario))

    async def _axl_pool_ensure(self) -> AXLPoolManager | None:
        if not self._axl_node_urls:
            return None
        if self._axl_pool is None:
            pool = AXLPoolManager(
                node_urls=self._axl_node_urls,
                pool_id=self._axl_pool_id,
                agent_id=self._axl_agent_id,
            )
            await pool.connect()
            self._axl_pool = pool
        return self._axl_pool

    async def _axl_pool_drain(self) -> None:
        pool = await self._axl_pool_ensure()
        if pool is None:
            return
        messages = await pool.receive(timeout=0.0)
        for message in messages:
            if message.type != "MARKET_SIGNAL":
                continue
            target = (
                message.payload.get("target_agent_id")
                or message.payload.get("agent_id")
            )
            strength = float(message.payload.get("signal_strength", 1.0) or 1.0)
            if target:
                self._axl_urgency_boost[str(target)] = (
                    self._axl_urgency_boost.get(str(target), 0.0) + strength
                )
            else:
                for agent in self._agents:
                    self._axl_urgency_boost[agent.agent_id] = (
                        self._axl_urgency_boost.get(agent.agent_id, 0.0) + strength * 0.1
                    )

    async def _axl_pool_publish_tier1(
        self,
        scenario: Scenario,
        tier1: list["_AgentIdentity"],
        tier1_results: list[AgentState],
    ) -> None:
        pool = await self._axl_pool_ensure()
        if pool is None:
            return
        for agent, state in zip(tier1, tier1_results):
            try:
                await pool.broadcast(
                    "TRADE_INTENT",
                    {
                        "agent_id": agent.agent_id,
                        "archetype": agent.archetype.name,
                        "scenario_id": scenario.scenario_id,
                        "action": state.action,
                        "confidence": state.confidence,
                        "size_usd_est": round(200_000 + scenario.volatility * 600_000, 2),
                    },
                )
                await pool.broadcast(
                    "INFERENCE_RESULT",
                    {
                        "agent_id": agent.agent_id,
                        "scenario_id": scenario.scenario_id,
                        "action": state.action,
                        "confidence": state.confidence,
                        "score": state.score,
                        "aiq": state.aiq,
                    },
                )
            except (ConnectionError, OSError):
                continue

    async def aclose(self) -> None:
        if self._axl_pool is not None:
            await self._axl_pool.disconnect()
            self._axl_pool = None

    @staticmethod
    def _print_tick_summary(
        tick_index: int,
        tier1: list[_AgentIdentity],
        tier1_results: list[AgentState],
        tier2: list[_AgentIdentity],
        tier2_results: list[AgentState],
        tier3: list[_AgentIdentity],
        tier3_results: list[AgentState],
    ) -> None:
        print(f"\n=== Tick {tick_index} ===")
        for label, agents, states in (
            ("Tier 1 (AIQ inference)", tier1, tier1_results),
            ("Tier 2 (heuristic)", tier2, tier2_results),
            ("Tier 3 (background)", tier3, tier3_results),
        ):
            print(f"-- {label}: {len(agents)} agents --")
            for agent, state in zip(agents, states):
                print(
                    f"  {agent.agent_id} [{agent.archetype.name}] -> {state.action} "
                    f"(conf={state.confidence:.2f}, score={state.score:.2f})"
                )


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


def _agent_state_from_decision(
    agent: _AgentIdentity,
    scenario: Scenario,
    decision: dict[str, Any],
    jitter: float,
) -> AgentState:
    from typing import cast

    from .models import Action
    from .scoring import aiq_for, pnl_bps_for, score_for

    valid_actions = {
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
    action = decision.get("action", "hold")
    if action not in valid_actions:
        action = "hold"
    confidence = float(decision.get("confidence", 0.4))
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(decision.get("rationale", f"{agent.archetype.name}: heuristic"))
    aiq = aiq_for(agent.archetype, scenario, confidence, jitter)
    pnl_bps = pnl_bps_for(action, agent.archetype, scenario, jitter)
    score = score_for(confidence, pnl_bps, aiq, agent.archetype.tier)
    return AgentState(
        agent_id=agent.agent_id,
        archetype=agent.archetype.name,
        tier=agent.archetype.tier,
        action=cast(Action, action),
        confidence=round(confidence, 4),
        pnl_bps=pnl_bps,
        aiq=aiq,
        score=score,
        rationale=rationale,
    )
