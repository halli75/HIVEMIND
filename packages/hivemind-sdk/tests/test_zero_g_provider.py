from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_async_post(content: str, status_code: int = 200) -> AsyncMock:
    """Build an `AsyncMock` suitable for patching `httpx.AsyncClient.post`."""
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return AsyncMock(return_value=response)


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

    async_post = _make_async_post(json.dumps({"action": "sell", "confidence": 0.9}))
    with patch("httpx.AsyncClient.post", async_post):
        refined = hybrid.refine_top_n(states, _SCENARIO, archetypes)

    assert len(refined) == 5
    real_count = sum(1 for s in refined if s.inference_source == "0g_compute")
    assert real_count == 3
    # All 3 top-N agents fan out concurrently in a single batch window.
    assert async_post.await_count == 3
    assert hybrid.metrics.attempted_real_count == 3
    assert hybrid.metrics.successful_real_count == 3
    assert hybrid.metrics.fallback_count == 0
    assert hybrid.metrics.avg_latency_ms is not None


def test_hybrid_provider_metrics_use_actual_refined_count_for_fallbacks() -> None:
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

    async_post = _make_async_post('{"action": "UNKNOWN", "confidence": 0.5}')
    with patch("httpx.AsyncClient.post", async_post):
        refined = hybrid.refine_top_n(states, _SCENARIO, archetypes)

    assert len(refined) == 2
    assert hybrid.metrics.attempted_real_count == 2
    assert hybrid.metrics.successful_real_count == 0
    assert hybrid.metrics.fallback_count == 2
    assert hybrid.metrics.last_error is not None


def test_evaluate_agents_batch_returns_concurrent_results() -> None:
    """Direct check that the async batch path fans out N requests concurrently
    and returns one AgentState per request, in input order."""
    provider = _make_provider()
    archetypes = [DEFAULT_ARCHETYPES[i % len(DEFAULT_ARCHETYPES)] for i in range(5)]
    requests = [
        (f"agent-{i:03d}", archetypes[i], _SCENARIO, 0.1 * i) for i in range(5)
    ]

    async_post = _make_async_post(json.dumps({"action": "buy", "confidence": 0.66}))
    with patch("httpx.AsyncClient.post", async_post):
        results = asyncio.run(provider.evaluate_agents_batch(requests=requests))

    assert [s.agent_id for s in results] == [f"agent-{i:03d}" for i in range(5)]
    assert all(s.inference_source == "0g_compute" for s in results)
    assert all(abs(s.confidence - 0.66) < 1e-6 for s in results)
    assert async_post.await_count == 5


def test_refine_top_n_batches_in_windows_of_five() -> None:
    """A 7-agent top-N pool should fan out across two batch windows
    (BATCH_SIZE=5 + 2), still using a single shared connection pool."""
    real = _make_provider()
    hybrid = HybridInferenceProvider(real=real, top_n=7)
    local = LocalInferenceProvider()
    archetypes = {f"agent-{i:03d}": DEFAULT_ARCHETYPES[i % len(DEFAULT_ARCHETYPES)] for i in range(1, 8)}
    states = [
        local.evaluate_agent(
            agent_id=f"agent-{i:03d}",
            archetype=archetypes[f"agent-{i:03d}"],
            scenario=_SCENARIO,
            jitter=float(i) / 10,
        )
        for i in range(1, 8)
    ]

    async_post = _make_async_post(json.dumps({"action": "buy", "confidence": 0.8}))
    with patch("httpx.AsyncClient.post", async_post):
        refined = hybrid.refine_top_n(states, _SCENARIO, archetypes)

    assert len(refined) == 7
    assert sum(1 for s in refined if s.inference_source == "0g_compute") == 7
    assert async_post.await_count == 7
    assert hybrid.metrics.successful_real_count == 7


def test_refine_top_n_works_inside_running_event_loop() -> None:
    """`engine.inject_scenario` runs inside the FastAPI event loop, so
    `refine_top_n` must not crash with `asyncio.run() cannot be called from a
    running event loop`. The provider should detect the running loop and
    dispatch the batch on a helper thread instead."""
    real = _make_provider()
    hybrid = HybridInferenceProvider(real=real, top_n=2)
    local = LocalInferenceProvider()
    archetypes = {f"agent-{i:03d}": DEFAULT_ARCHETYPES[i % len(DEFAULT_ARCHETYPES)] for i in range(1, 4)}
    states = [
        local.evaluate_agent(
            agent_id=f"agent-{i:03d}",
            archetype=archetypes[f"agent-{i:03d}"],
            scenario=_SCENARIO,
            jitter=float(i) / 10,
        )
        for i in range(1, 4)
    ]

    async def _drive() -> list:
        async_post = _make_async_post(json.dumps({"action": "hold", "confidence": 0.5}))
        with patch("httpx.AsyncClient.post", async_post):
            return hybrid.refine_top_n(states, _SCENARIO, archetypes)

    refined = asyncio.run(_drive())
    assert len(refined) == 3
    assert sum(1 for s in refined if s.inference_source == "0g_compute") == 2
