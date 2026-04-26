from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
    LocalInferenceProvider,
    LocalMessageBus,
    LocalStorageProvider,
    MessageBus,
    SeedReplay,
    StorageProvider,
)


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
        agent_count: int = 24,
        seed: str = "hivemind-local",
        archetypes: tuple[AgentArchetype, ...] = DEFAULT_ARCHETYPES,
        run_mode: RunMode | None = None,
        seed_snapshot_dir: str | Path | None = None,
        transcript_root: str | Path | None = None,
        inference_provider: InferenceProvider | None = None,
        storage_provider: StorageProvider | None = None,
        message_bus: MessageBus | None = None,
        execution_provider: ExecutionProvider | None = None,
    ) -> None:
        if agent_count <= 0:
            raise ValueError("agent_count must be positive")
        if not archetypes:
            raise ValueError("at least one archetype is required")

        self._seed = seed
        self._replay = SeedReplay.from_directory(seed_snapshot_dir)
        self._run_mode: RunMode = run_mode or "mock"
        self._inference_provider = inference_provider or LocalInferenceProvider()
        self._storage_provider = storage_provider or LocalStorageProvider(replay=self._replay)
        self._message_bus = message_bus or LocalMessageBus(replay=self._replay)
        self._execution_provider = execution_provider or LocalExecutionProvider(replay=self._replay)
        self._transcript_recorder: FileTranscriptRecorder | None = None
        self._agents = tuple(
            _AgentIdentity(
                agent_id=f"agent-{index + 1:03d}",
                archetype=archetypes[index % len(archetypes)],
            )
            for index in range(agent_count)
        )
        self._sequence = 0
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
