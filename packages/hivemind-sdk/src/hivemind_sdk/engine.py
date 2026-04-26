from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from .archetypes import DEFAULT_ARCHETYPES
from .models import (
    Action,
    AgentArchetype,
    AgentState,
    IntegrationEnvelope,
    LeaderboardEntry,
    Scenario,
    SwarmSnapshot,
    TierMetric,
)
from .scoring import aiq_for, choose_action, confidence_for, pnl_bps_for, score_for


@dataclass(frozen=True)
class _AgentIdentity:
    agent_id: str
    archetype: AgentArchetype


class SwarmEngine:
    """Deterministic local mock engine for hackathon development and tests."""

    def __init__(
        self,
        *,
        agent_count: int = 24,
        seed: str = "hivemind-local",
        archetypes: tuple[AgentArchetype, ...] = DEFAULT_ARCHETYPES,
    ) -> None:
        if agent_count <= 0:
            raise ValueError("agent_count must be positive")
        if not archetypes:
            raise ValueError("at least one archetype is required")

        self._seed = seed
        self._agents = tuple(
            _AgentIdentity(
                agent_id=f"agent-{index + 1:03d}",
                archetype=archetypes[index % len(archetypes)],
            )
            for index in range(agent_count)
        )
        self._sequence = 0
        self._snapshot = self.inject_scenario(Scenario.neutral())

    @property
    def latest_snapshot(self) -> SwarmSnapshot:
        return self._snapshot

    def inject_scenario(self, scenario: Scenario) -> SwarmSnapshot:
        self._sequence += 1
        agent_states = tuple(self._evaluate_agent(agent, scenario) for agent in self._agents)
        leaderboard = self._build_leaderboard(agent_states)
        tier_metrics = self._build_tier_metrics(agent_states, scenario)
        integrations = self._integration_envelope(scenario, agent_states, leaderboard)
        event_log = (
            f"scenario:{scenario.scenario_id}",
            f"axl:mock-broadcast:{len(agent_states)}-agents",
            f"0g:mock-state:{scenario.scenario_id}:{self._sequence}",
            f"uniswap:mock-quote:{leaderboard[0].action}",
        )
        self._snapshot = SwarmSnapshot(
            sequence=self._sequence,
            scenario=scenario,
            agents=agent_states,
            tier_metrics=tier_metrics,
            leaderboard=leaderboard,
            integrations=integrations,
            event_log=event_log,
        )
        return self._snapshot

    def _evaluate_agent(self, agent: _AgentIdentity, scenario: Scenario) -> AgentState:
        jitter = self._jitter(agent.agent_id, scenario.scenario_id)
        action = choose_action(agent.archetype, scenario, jitter)
        confidence = confidence_for(agent.archetype, scenario, jitter)
        aiq = aiq_for(agent.archetype, scenario, confidence, jitter)
        pnl_bps = pnl_bps_for(action, agent.archetype, scenario, jitter)
        score = score_for(confidence, pnl_bps, aiq, agent.archetype.tier)
        rationale = (
            f"{agent.archetype.name} selected {action} with sentiment={scenario.sentiment:.2f}, "
            f"volatility={scenario.volatility:.2f}, liquidity_delta={scenario.liquidity_delta:.2f}"
        )
        return AgentState(
            agent_id=agent.agent_id,
            archetype=agent.archetype.name,
            tier=agent.archetype.tier,
            action=cast(Action, action),
            confidence=confidence,
            pnl_bps=pnl_bps,
            aiq=aiq,
            score=score,
            rationale=rationale,
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
        return IntegrationEnvelope(
            zero_g_compute={
                "mode": "mock",
                "request_id": f"0g-compute-{self._sequence:04d}",
                "inference_calls": len(agent_states),
                "model_tier": "local-deterministic",
            },
            zero_g_storage={
                "mode": "mock",
                "uri": f"mock://0g-storage/swarm-state/{state_digest}",
                "state_digest": state_digest,
            },
            gensyn_axl={
                "mode": "mock",
                "topic": f"hivemind.scenario.{scenario.scenario_id}",
                "messages": len(agent_states),
                "coordinator": "axl_coordinator",
            },
            uniswap={
                "mode": "mock",
                "chain": "sepolia",
                "route": "WETH/USDC",
                "recommended_action": winner.action,
                "quote_id": f"uni-quote-{state_digest[:8]}",
            },
        )
