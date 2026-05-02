"""Tests for the three AXL message types that the proposal claimed were
"live" but were never actually plumbed: POOL_STATE, COALITION_INVITE, and
GOVERNANCE_SIGNAL.

These tests exercise both halves of the contract:

- The publish path runs in `_axl_pool_publish_tier1` and emits messages onto
  the AXL pool. We swap in a `_FakePool` so we can record every broadcast/send
  without standing up real TCP nodes.
- The drain path runs in `_axl_pool_drain` and mutates engine side-state
  (`_axl_urgency_boost`, `_coalition_overrides`, `_governance_votes`,
  `_governance_events`). Each test pokes the side-state directly via the
  handler entry points, then asserts the observable engine effects.

The proposal's claim is "all 7 types are live"; these tests are the regression
fence that keeps that claim true.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from hivemind_sdk import (
    Scenario,
    SwarmEngine,
)
from hivemind_sdk.archetypes import (
    ArbitrageurArchetype,
    GovernanceVoterArchetype,
    LPProviderArchetype,
    WhaleArchetype,
)
from hivemind_sdk.models import AgentState


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _SentMessage:
    kind: str  # "broadcast" or "send"
    target: str  # "broadcast" or target agent_id
    type: str
    payload: dict[str, Any]


class _FakePool:
    """In-process stand-in for AXLPoolManager that records every emit and
    serves a scripted inbox to `receive()`."""

    def __init__(self) -> None:
        self.sent: list[_SentMessage] = []
        self.inbox: list[Any] = []

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def broadcast(self, message_type: str, payload: dict[str, Any]) -> None:
        self.sent.append(
            _SentMessage(kind="broadcast", target="broadcast", type=message_type, payload=dict(payload))
        )

    async def send(self, target_agent_id: str, message_type: str, payload: dict[str, Any]) -> None:
        self.sent.append(
            _SentMessage(kind="send", target=target_agent_id, type=message_type, payload=dict(payload))
        )

    async def receive(self, *, timeout: float = 1.0) -> list[Any]:
        drained, self.inbox = self.inbox, []
        return drained


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scenario(scenario_id: str = "axl-7-types") -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        label="AXL plumbing fixture",
        volatility=0.5,
        liquidity_delta=0.1,
        sentiment=0.4,
        gas_pressure=0.2,
        signal_strength=0.6,
    )


# ---------------------------------------------------------------------------
# POOL_STATE — drain handler effects
# ---------------------------------------------------------------------------


def test_pool_state_first_frame_is_baseline_and_does_not_emit_urgency() -> None:
    engine = SwarmEngine(agent_count=8, seed="pool-baseline")
    assert engine._last_pool_tvl_usd is None  # type: ignore[attr-defined]

    engine._handle_pool_state({"tvl_usd": 12_000_000.0})  # type: ignore[attr-defined]

    assert engine._last_pool_tvl_usd == 12_000_000.0  # type: ignore[attr-defined]
    assert engine._axl_urgency_boost == {}  # type: ignore[attr-defined]


def test_pool_state_tvl_drop_boosts_arb_and_lp_urgency() -> None:
    engine = SwarmEngine(
        agent_count=4,
        seed="pool-drop",
        archetypes=[
            ArbitrageurArchetype(),
            LPProviderArchetype(),
            WhaleArchetype(),
            GovernanceVoterArchetype(),
        ],
    )
    engine._handle_pool_state({"tvl_usd": 10_000_000.0})  # type: ignore[attr-defined]
    engine._handle_pool_state({"tvl_usd": 9_500_000.0})   # -5% drop

    boosts = engine._axl_urgency_boost  # type: ignore[attr-defined]
    arb_boost = boosts.get("agent-001", 0.0)  # ArbitrageurArchetype
    lp_boost = boosts.get("agent-002", 0.0)   # LPProviderArchetype
    whale_boost = boosts.get("agent-003", 0.0)
    gov_boost = boosts.get("agent-004", 0.0)

    assert arb_boost > 0, "Arbitrageur should react to TVL drop"
    assert lp_boost > 0, "LP Provider should react to TVL drop"
    assert whale_boost == 0, "Whale should not react to POOL_STATE"
    assert gov_boost == 0, "Governance voter should not react to POOL_STATE"
    # 5% drop * 2x scaling -> 0.1 boost expected
    assert arb_boost == pytest.approx(0.1, rel=1e-6)


def test_pool_state_small_rise_only_lifts_lp_provider() -> None:
    engine = SwarmEngine(
        agent_count=2,
        seed="pool-rise",
        archetypes=[ArbitrageurArchetype(), LPProviderArchetype()],
    )
    engine._handle_pool_state({"tvl_usd": 10_000_000.0})  # type: ignore[attr-defined]
    engine._handle_pool_state({"tvl_usd": 10_400_000.0})  # +4% rise

    boosts = engine._axl_urgency_boost  # type: ignore[attr-defined]
    assert boosts.get("agent-001", 0.0) == 0, "Arb does not react to TVL increase"
    assert boosts.get("agent-002", 0.0) > 0, "LP Provider gets a confidence-style nudge"


def test_pool_state_below_threshold_is_noise_and_skipped() -> None:
    engine = SwarmEngine(agent_count=4, seed="pool-noise")
    engine._handle_pool_state({"tvl_usd": 10_000_000.0})  # baseline
    engine._handle_pool_state({"tvl_usd": 10_050_000.0})  # +0.5% — below 1% floor

    assert engine._axl_urgency_boost == {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# COALITION_INVITE — drain handler effects
# ---------------------------------------------------------------------------


def test_coalition_invite_stages_action_override_for_target() -> None:
    engine = SwarmEngine(
        agent_count=4,
        seed="coalition-accept",
        archetypes=[WhaleArchetype()],  # all 4 agents become whales
    )
    engine._tick_index = 5

    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-test-1",
            "proposer_agent_id": "agent-001",
            "target_agent_id": "agent-002",
            "objective": "coordinated_buy",
            "expires_at_tick": 10,
        }
    )

    overrides = engine._coalition_overrides  # type: ignore[attr-defined]
    assert "agent-002" in overrides
    assert overrides["agent-002"]["action"] == "buy"
    # Inviting the target also pulls them up the urgency ranking:
    assert engine._axl_urgency_boost.get("agent-002", 0.0) > 0  # type: ignore[attr-defined]


def test_coalition_invite_rejected_when_archetypes_differ() -> None:
    engine = SwarmEngine(
        agent_count=2,
        seed="coalition-mismatch",
        archetypes=[WhaleArchetype(), LPProviderArchetype()],
    )
    engine._tick_index = 5

    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-mismatch",
            "proposer_agent_id": "agent-001",  # Whale
            "target_agent_id": "agent-002",    # LP Provider
            "objective": "coordinated_buy",
            "expires_at_tick": 10,
        }
    )

    assert engine._coalition_overrides == {}  # type: ignore[attr-defined]


def test_coalition_invite_rejected_when_already_expired() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="coalition-expired", archetypes=[WhaleArchetype()]
    )
    engine._tick_index = 20

    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-expired",
            "proposer_agent_id": "agent-001",
            "target_agent_id": "agent-002",
            "objective": "joint_lp",
            "expires_at_tick": 5,  # in the past
        }
    )
    assert engine._coalition_overrides == {}  # type: ignore[attr-defined]


def test_coalition_action_override_is_one_shot() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="coalition-one-shot", archetypes=[LPProviderArchetype()]
    )
    engine._tick_index = 1
    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-one-shot",
            "proposer_agent_id": "agent-001",
            "target_agent_id": "agent-002",
            "objective": "joint_lp",
            "expires_at_tick": 10,
        }
    )
    first = engine._coalition_action_override("agent-002")  # type: ignore[attr-defined]
    second = engine._coalition_action_override("agent-002")  # type: ignore[attr-defined]
    assert first == "provide_liquidity"
    assert second is None


# ---------------------------------------------------------------------------
# GOVERNANCE_SIGNAL — drain handler effects
# ---------------------------------------------------------------------------


def test_governance_signal_tallies_weighted_votes_and_logs_quorum() -> None:
    engine = SwarmEngine(
        agent_count=4,
        seed="gov-quorum",
        archetypes=[GovernanceVoterArchetype()],
    )
    # 4 governance_voter agents -> 50% quorum = 2 unique voters.
    engine._handle_governance_signal(  # type: ignore[attr-defined]
        {"proposal_id": "prop-A", "voter_agent_id": "agent-001", "vote": "for", "voting_power": 1.0}
    )
    assert engine._governance_events == []  # type: ignore[attr-defined] - no quorum yet
    engine._handle_governance_signal(
        {"proposal_id": "prop-A", "voter_agent_id": "agent-002", "vote": "against", "voting_power": 0.4}
    )

    events = engine._drain_governance_events()  # type: ignore[attr-defined]
    assert len(events) == 1
    assert events[0].startswith("governance:prop-A:for")
    assert "voters=2/4" in events[0]


def test_governance_signal_dedupes_repeat_votes_from_same_agent() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="gov-dedupe", archetypes=[GovernanceVoterArchetype()]
    )
    payload = {
        "proposal_id": "prop-B",
        "voter_agent_id": "agent-001",
        "vote": "for",
        "voting_power": 1.0,
    }
    engine._handle_governance_signal(payload)  # type: ignore[attr-defined]
    engine._handle_governance_signal(payload)  # duplicate — should be ignored

    bucket = engine._governance_votes["prop-B"]  # type: ignore[attr-defined]
    assert bucket["for"] == pytest.approx(1.0)
    assert len(bucket["voters"]) == 1


def test_governance_signal_quorum_logs_only_once() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="gov-once", archetypes=[GovernanceVoterArchetype()]
    )
    engine._handle_governance_signal(  # type: ignore[attr-defined]
        {"proposal_id": "prop-C", "voter_agent_id": "agent-001", "vote": "for", "voting_power": 1.0}
    )
    engine._handle_governance_signal(
        {"proposal_id": "prop-C", "voter_agent_id": "agent-002", "vote": "for", "voting_power": 1.0}
    )
    first_drain = engine._drain_governance_events()  # type: ignore[attr-defined]
    assert len(first_drain) == 1
    second_drain = engine._drain_governance_events()
    assert second_drain == ()


# ---------------------------------------------------------------------------
# Publish path — _axl_pool_publish_tier1 emits the right messages
# ---------------------------------------------------------------------------


def _agent_state(
    *,
    agent_id: str,
    archetype: str,
    action: str,
    confidence: float = 0.85,
    score: float = 90.0,
    aiq: float = 0.8,
) -> AgentState:
    return AgentState(
        agent_id=agent_id,
        archetype=archetype,
        tier=1,
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        pnl_bps=20.0,
        aiq=aiq,
        score=score,
        rationale=f"{archetype} test",
        inference_source="local",
        model="",
    )


def test_publish_emits_coalition_invite_for_high_confidence_whale_buy() -> None:
    engine = SwarmEngine(
        agent_count=3,
        seed="coalition-publish",
        archetypes=[WhaleArchetype()],  # 3 whales
    )
    fake = _FakePool()
    engine._axl_node_urls = ["tcp://fake:0"]  # type: ignore[attr-defined]
    engine._axl_pool = fake  # type: ignore[assignment]
    engine._tick_index = 7

    proposer = engine._agents[0]  # type: ignore[attr-defined]
    state = _agent_state(
        agent_id=proposer.agent_id, archetype="whale", action="buy", confidence=0.9
    )
    asyncio.run(
        engine._axl_pool_publish_tier1(_scenario(), [proposer], [state])  # type: ignore[attr-defined]
    )

    types = [m.type for m in fake.sent]
    assert "TRADE_INTENT" in types
    assert "INFERENCE_RESULT" in types
    coalitions = [m for m in fake.sent if m.type == "COALITION_INVITE"]
    assert len(coalitions) == 1
    invite = coalitions[0]
    assert invite.kind == "send"
    assert invite.target != proposer.agent_id
    assert invite.payload["objective"] == "coordinated_buy"
    assert invite.payload["proposer_agent_id"] == proposer.agent_id
    assert invite.payload["expires_at_tick"] > engine._tick_index  # type: ignore[attr-defined]


def test_publish_skips_coalition_invite_for_low_confidence() -> None:
    engine = SwarmEngine(
        agent_count=3, seed="coalition-low-conf", archetypes=[WhaleArchetype()]
    )
    fake = _FakePool()
    engine._axl_node_urls = ["tcp://fake:0"]  # type: ignore[attr-defined]
    engine._axl_pool = fake  # type: ignore[assignment]

    proposer = engine._agents[0]  # type: ignore[attr-defined]
    state = _agent_state(
        agent_id=proposer.agent_id, archetype="whale", action="buy", confidence=0.5
    )
    asyncio.run(
        engine._axl_pool_publish_tier1(_scenario(), [proposer], [state])  # type: ignore[attr-defined]
    )
    assert not [m for m in fake.sent if m.type == "COALITION_INVITE"]


def test_publish_emits_governance_signal_with_for_vote_when_confident() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="gov-publish", archetypes=[GovernanceVoterArchetype()]
    )
    fake = _FakePool()
    engine._axl_node_urls = ["tcp://fake:0"]  # type: ignore[attr-defined]
    engine._axl_pool = fake  # type: ignore[assignment]

    voter = engine._agents[0]  # type: ignore[attr-defined]
    state = _agent_state(
        agent_id=voter.agent_id, archetype="governance_voter", action="vote", confidence=0.82
    )
    asyncio.run(
        engine._axl_pool_publish_tier1(_scenario("prop-test"), [voter], [state])  # type: ignore[attr-defined]
    )

    governance = [m for m in fake.sent if m.type == "GOVERNANCE_SIGNAL"]
    assert len(governance) == 1
    payload = governance[0].payload
    assert payload["proposal_id"] == "prop-prop-test"
    assert payload["vote"] == "for"
    assert payload["voter_agent_id"] == voter.agent_id
    assert payload["voting_power"] > 0


def test_publish_emits_governance_signal_with_against_vote_when_unconfident() -> None:
    engine = SwarmEngine(
        agent_count=2, seed="gov-against", archetypes=[GovernanceVoterArchetype()]
    )
    fake = _FakePool()
    engine._axl_node_urls = ["tcp://fake:0"]  # type: ignore[attr-defined]
    engine._axl_pool = fake  # type: ignore[assignment]

    voter = engine._agents[0]  # type: ignore[attr-defined]
    state = _agent_state(
        agent_id=voter.agent_id, archetype="governance_voter", action="vote", confidence=0.4
    )
    asyncio.run(
        engine._axl_pool_publish_tier1(_scenario(), [voter], [state])  # type: ignore[attr-defined]
    )
    governance = [m for m in fake.sent if m.type == "GOVERNANCE_SIGNAL"]
    assert governance[0].payload["vote"] == "against"


# ---------------------------------------------------------------------------
# Drain → tier-2 follow-through
# ---------------------------------------------------------------------------


def test_coalition_override_changes_tier2_evaluation_action() -> None:
    """When the heuristic's default action differs from the coalition objective,
    the override substitutes the action and annotates the rationale. (When
    the heuristic already produced the same action the override is a no-op,
    which is exercised in
    `test_coalition_override_no_op_when_heuristic_already_aligns`.)"""
    engine = SwarmEngine(
        agent_count=3, seed="coalition-tier2", archetypes=[WhaleArchetype()]
    )
    engine._tick_index = 3
    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-t2",
            "proposer_agent_id": "agent-001",
            "target_agent_id": "agent-002",
            "objective": "joint_lp",  # Whale heuristic doesn't default to LP
            "expires_at_tick": 10,
        }
    )
    target = next(a for a in engine._agents if a.agent_id == "agent-002")  # type: ignore[attr-defined]

    # Sanity: the Whale heuristic's natural action under this scenario is not LP.
    baseline_engine = SwarmEngine(
        agent_count=3, seed="coalition-tier2", archetypes=[WhaleArchetype()]
    )
    baseline_engine._tick_index = 3
    baseline_target = next(
        a for a in baseline_engine._agents if a.agent_id == "agent-002"
    )
    baseline_state = baseline_engine._tier2_evaluate(baseline_target, _scenario())  # type: ignore[attr-defined]
    assert baseline_state.action != "provide_liquidity"

    state = engine._tier2_evaluate(target, _scenario())  # type: ignore[attr-defined]
    assert state.action == "provide_liquidity"
    assert "coalition override" in state.rationale


def test_coalition_override_no_op_when_heuristic_already_aligns() -> None:
    engine = SwarmEngine(
        agent_count=3, seed="coalition-noop", archetypes=[LPProviderArchetype()]
    )
    engine._tick_index = 3
    engine._handle_coalition_invite(  # type: ignore[attr-defined]
        {
            "coalition_id": "coal-noop",
            "proposer_agent_id": "agent-001",
            "target_agent_id": "agent-002",
            "objective": "joint_lp",
            "expires_at_tick": 10,
        }
    )
    target = next(a for a in engine._agents if a.agent_id == "agent-002")  # type: ignore[attr-defined]
    state = engine._tier2_evaluate(target, _scenario())  # type: ignore[attr-defined]
    # Action matches the heuristic's natural choice (LP Provider chooses LP),
    # so the rationale should NOT carry the override marker — but the override
    # is still consumed (one-shot) so it doesn't double-fire next call.
    assert state.action == "provide_liquidity"
    assert "coalition override" not in state.rationale
    assert engine._coalition_overrides == {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Coordinator runner — POOL_STATE rotation
# ---------------------------------------------------------------------------


def test_coordinator_rotation_cycles_through_three_message_types() -> None:
    from hivemind_axl_node.runner import _coordinator_message_type

    types = [_coordinator_message_type(i) for i in range(9)]
    assert types == [
        "SCENARIO_SHOCK",
        "MARKET_SIGNAL",
        "POOL_STATE",
        "SCENARIO_SHOCK",
        "MARKET_SIGNAL",
        "POOL_STATE",
        "SCENARIO_SHOCK",
        "MARKET_SIGNAL",
        "POOL_STATE",
    ]


def test_coordinator_pool_state_payload_matches_typeddict_shape() -> None:
    from hivemind_axl_node.runner import _coordinator_payload

    payload = _coordinator_payload("POOL_STATE", index=2)
    expected_keys = {
        "pool_address",
        "token0",
        "token1",
        "fee_tier",
        "tick",
        "sqrt_price_x96",
        "liquidity",
        "tvl_usd",
    }
    assert set(payload.keys()) == expected_keys
    assert payload["fee_tier"] == 3000
    assert isinstance(payload["sqrt_price_x96"], str)
    assert payload["tvl_usd"] > 0
