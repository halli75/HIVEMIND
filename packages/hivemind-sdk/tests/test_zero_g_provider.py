from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from hivemind_sdk import (
    HybridInferenceProvider,
    LocalInferenceProvider,
    Scenario,
    ZeroGComputeInferenceProvider,
)
from hivemind_sdk.archetypes import DEFAULT_ARCHETYPES


_SCENARIO = Scenario(
    scenario_id="test-bull",
    label="Bull market test",
    volatility=0.4,
    liquidity_delta=0.1,
    sentiment=0.7,
    gas_pressure=0.2,
)
_ARCHETYPE = DEFAULT_ARCHETYPES[0]


def _make_provider() -> ZeroGComputeInferenceProvider:
    return ZeroGComputeInferenceProvider(
        api_base_url="https://fake-0g.example.com",
        bearer_token="tok-test",
        model="qwen-test",
    )


def test_zero_g_provider_returns_real_inference_on_valid_response() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "buy", "confidence": 0.85})}}]
    }

    provider = _make_provider()
    with patch("httpx.post", return_value=mock_resp):
        state = provider.evaluate_agent(
            agent_id="agent-001",
            archetype=_ARCHETYPE,
            scenario=_SCENARIO,
            jitter=0.5,
        )

    assert state.action == "buy"
    assert abs(state.confidence - 0.85) < 1e-6
    assert state.inference_source == "0g_compute"
    assert state.model == "qwen-test"
    assert state.agent_id == "agent-001"
    assert provider.last_error is None
    assert provider.last_latency_ms is not None


def test_zero_g_provider_accepts_fenced_json_response() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '```json\n{"action": "hold", "confidence": 0.55}\n```'}}]
    }

    provider = _make_provider()
    with patch("httpx.post", return_value=mock_resp):
        state = provider.evaluate_agent(
            agent_id="agent-001",
            archetype=_ARCHETYPE,
            scenario=_SCENARIO,
            jitter=0.5,
        )

    assert state.action == "hold"
    assert abs(state.confidence - 0.55) < 1e-6
    assert state.inference_source == "0g_compute"


def test_zero_g_provider_falls_back_on_http_error() -> None:
    import httpx

    provider = _make_provider()
    with patch("httpx.post", side_effect=httpx.HTTPError("timeout")):
        state = provider.evaluate_agent(
            agent_id="agent-002",
            archetype=_ARCHETYPE,
            scenario=_SCENARIO,
            jitter=0.3,
        )

    assert state.inference_source == "local_fallback"
    assert state.action in {"buy", "sell", "hold"}
    assert provider.last_error is not None
    assert "tok-test" not in provider.last_error


def test_zero_g_provider_falls_back_on_malformed_response() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"action": "UNKNOWN", "confidence": 0.5}'}}]
    }

    provider = _make_provider()
    with patch("httpx.post", return_value=mock_resp):
        state = provider.evaluate_agent(
            agent_id="agent-003",
            archetype=_ARCHETYPE,
            scenario=_SCENARIO,
            jitter=0.5,
        )

    assert state.inference_source == "local_fallback"
    assert provider.last_error is not None
    assert "unexpected action" in provider.last_error


def test_zero_g_provider_retries_rate_limit_before_success() -> None:
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status = MagicMock()
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    ok.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "buy", "confidence": 0.72})}}]
    }

    provider = _make_provider()
    with patch("time.sleep"), patch("httpx.post", side_effect=[rate_limited, ok]) as post:
        state = provider.evaluate_agent(
            agent_id="agent-004",
            archetype=_ARCHETYPE,
            scenario=_SCENARIO,
            jitter=0.5,
        )

    assert post.call_count == 2
    assert state.inference_source == "0g_compute"
    assert state.confidence == 0.72


def test_hybrid_provider_refines_top_n() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "sell", "confidence": 0.9})}}]
    }

    real = _make_provider()
    hybrid = HybridInferenceProvider(real=real, top_n=3)

    local = LocalInferenceProvider()
    archetypes = {f"agent-{i:03d}": DEFAULT_ARCHETYPES[i % len(DEFAULT_ARCHETYPES)] for i in range(1, 6)}
    states = [
        local.evaluate_agent(
            agent_id=f"agent-{i:03d}",
            archetype=archetypes[f"agent-{i:03d}"],
            scenario=_SCENARIO,
            jitter=float(i) / 10,
        )
        for i in range(1, 6)
    ]

    with patch("httpx.post", return_value=mock_resp):
        refined = hybrid.refine_top_n(states, _SCENARIO, archetypes)

    assert len(refined) == 5
    real_count = sum(1 for s in refined if s.inference_source == "0g_compute")
    assert real_count == 3
    assert hybrid.metrics.attempted_real_count == 3
    assert hybrid.metrics.successful_real_count == 3
    assert hybrid.metrics.fallback_count == 0
    assert hybrid.metrics.avg_latency_ms is not None


def test_hybrid_provider_metrics_use_actual_refined_count_for_fallbacks() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"action": "UNKNOWN", "confidence": 0.5}'}}]
    }

    real = _make_provider()
    hybrid = HybridInferenceProvider(real=real, top_n=10)
    local = LocalInferenceProvider()
    archetypes = {f"agent-{i:03d}": DEFAULT_ARCHETYPES[i % len(DEFAULT_ARCHETYPES)] for i in range(1, 3)}
    states = [
        local.evaluate_agent(
            agent_id=f"agent-{i:03d}",
            archetype=archetypes[f"agent-{i:03d}"],
            scenario=_SCENARIO,
            jitter=float(i) / 10,
        )
        for i in range(1, 3)
    ]

    with patch("httpx.post", return_value=mock_resp):
        refined = hybrid.refine_top_n(states, _SCENARIO, archetypes)

    assert len(refined) == 2
    assert hybrid.metrics.attempted_real_count == 2
    assert hybrid.metrics.successful_real_count == 0
    assert hybrid.metrics.fallback_count == 2
    assert hybrid.metrics.last_error is not None
