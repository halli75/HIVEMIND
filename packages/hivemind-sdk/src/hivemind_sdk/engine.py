from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .archetypes import DEFAULT_ARCHETYPES
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
        archetypes: tuple[AgentArchetype, ...] = DEFAULT_ARCHETYPES,
        run_mode: RunMode | None = None,
        seed_snapshot_dir: str | Path | None = None,
        transcript_root: str | Path | None = None,
        axl_transcript_path: str | Path | None = None,
        inference_provider: InferenceProvider | None = None,
        storage_provider: StorageProvider | None = None,
        message_bus: MessageBus | None = None,
        execution_provider: ExecutionProvider | None = None,
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

        self._seed = seed
        self._replay = SeedReplay.from_directory(seed_snapshot_dir)
        self._run_mode: RunMode = run_mode or ("local_axl" if axl_transcript_path else "mock")
        if inference_provider is not None:
            self._inference_provider = inference_provider
        elif use_mock_inference():
            self._inference_provider = MockInferenceProvider()
        else:
            self._inference_provider = LocalInferenceProvider()
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
        self._snapshot = self.inject_scenario(Scenario.neutral())
        if transcript_root is not None:
            self._transcript_recorder = FileTranscriptRecorder(transcript_root)

    @property
    def latest_snapshot(self) -> SwarmSnapshot:
        return self._snapshot

    @property
    def run_mode(self) -> RunMode:
        return self._run_mode

    def inject_scenario(self, scenario: Scenario) -> SwarmSnapshot:
        self._sequence += 1
        agent_states = tuple(self._evaluate_agent(agent, scenario) for agent in self._agents)
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
        return IntegrationEnvelope(
            zero_g_compute={
                "mode": "seed_replay" if self._run_mode == "seed_replay" else "mock",
                "request_id": f"0g-compute-{self._sequence:04d}",
                "inference_calls": len(agent_states),
                "model_tier": "local-deterministic",
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
                "status": "placeholder",
                "token_id": None,
                "local_address": f"local-inft://{winner.agent_id}",
                "memory_uri": integrations.zero_g_storage["uri"],
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
        urgency = (
            time_since
            + portfolio_delta
            + axl_signal_strength
            + position_proximity
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

        tier1, tier2, tier3 = self._assign_tiers(active_scenario)

        semaphore = asyncio.Semaphore(TIER1_SEMAPHORE)
        tier1_results = await asyncio.gather(
            *(self._tier1_evaluate(a, active_scenario, semaphore) for a in tier1)
        )
        tier2_results = [self._tier2_evaluate(a, active_scenario) for a in tier2]
        tier3_results = [self._tier3_evaluate(a, active_scenario) for a in tier3]

        for agent, state in zip(tier1, tier1_results):
            self._last_inference_tick[agent.agent_id] = self._tick_index
            self._cooldown_until[agent.agent_id] = self._tick_index + TIER1_COOLDOWN_TICKS
            self._last_action[agent.agent_id] = state.action
            self._last_pnl_bps[agent.agent_id] = state.pnl_bps
        for agent, state in list(zip(tier2, tier2_results)) + list(zip(tier3, tier3_results)):
            self._last_action[agent.agent_id] = state.action
            self._last_pnl_bps[agent.agent_id] = state.pnl_bps

        agent_states_by_id: dict[str, AgentState] = {}
        for agent, state in zip(tier1, tier1_results):
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
        proof = self._build_proof(active_scenario, leaderboard, integrations, transcript)
        event_log = (
            f"tick:{self._tick_index}",
            f"scenario:{active_scenario.scenario_id}",
            f"tier1:{len(tier1)} tier2:{len(tier2)} tier3:{len(tier3)}",
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

        self._print_tick_summary(self._tick_index, tier1, tier1_results, tier2, tier2_results, tier3, tier3_results)
        return snapshot

    async def run(self, ticks: int = 1, scenario: Scenario | None = None) -> SwarmSnapshot:
        if ticks <= 0:
            raise ValueError("ticks must be positive")
        snapshot = self._snapshot
        for _ in range(ticks):
            snapshot = await self.tick(scenario)
        return snapshot

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
    return {
        "scenario_id": scenario.scenario_id,
        "volatility": scenario.volatility,
        "liquidity_delta": scenario.liquidity_delta,
        "sentiment": scenario.sentiment,
        "gas_pressure": scenario.gas_pressure,
        "signal_strength": scenario.signal_strength,
        "price_delta": scenario.sentiment * scenario.signal_strength,
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
