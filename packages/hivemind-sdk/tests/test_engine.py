import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from hivemind_sdk import AxlMessage, HybridInferenceProvider, Scenario, SwarmEngine, TokenBucket, ZeroGComputeInferenceProvider, append_jsonl


def test_engine_is_deterministic_for_same_seed_and_scenario() -> None:
    scenario = Scenario(
        scenario_id="eth-breakout",
        label="ETH upside breakout",
        volatility=0.72,
        liquidity_delta=-0.18,
        sentiment=0.8,
        gas_pressure=0.31,
        signal_strength=0.9,
    )

    first = SwarmEngine(agent_count=15, seed="fixed").inject_scenario(scenario).to_dict()
    second = SwarmEngine(agent_count=15, seed="fixed").inject_scenario(scenario).to_dict()

    assert first == second


def test_scenario_injection_builds_leaderboard_metrics_and_mock_integrations() -> None:
    engine = SwarmEngine(agent_count=10, seed="slice-test")
    scenario = Scenario(
        scenario_id="liquidity-crunch",
        label="Liquidity crunch",
        volatility=0.85,
        liquidity_delta=-0.74,
        sentiment=-0.42,
        gas_pressure=0.66,
        signal_strength=0.7,
    )

    snapshot = engine.inject_scenario(scenario)

    assert snapshot.sequence == 2
    assert len(snapshot.agents) == 10
    assert snapshot.leaderboard[0].rank == 1
    assert snapshot.leaderboard[0].score >= snapshot.leaderboard[-1].score
    assert {metric.tier for metric in snapshot.tier_metrics} == {1, 2, 3}
    assert sum(metric.inference_calls for metric in snapshot.tier_metrics) == 10
    assert snapshot.integrations.zero_g_compute["mode"] == "mock"
    assert snapshot.integrations.gensyn_axl["topic"] == "hivemind.scenario.liquidity-crunch"
    assert snapshot.integrations.uniswap["chain"] == "sepolia"
    assert snapshot.run_mode == "mock"
    assert snapshot.proof["latest_scenario"]["scenario_id"] == "liquidity-crunch"


def test_seed_replay_adds_partner_proof_fields_and_saves_transcript(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    engine = SwarmEngine(
        agent_count=6,
        seed="seed-replay",
        seed_snapshot_dir=root / "data" / "snapshots",
        transcript_root=tmp_path / "runs",
    )
    scenario = Scenario(
        scenario_id="sepolia-volatility-open-001",
        label="Seed replay shock",
        volatility=0.62,
        liquidity_delta=-0.2,
        sentiment=0.35,
        gas_pressure=0.25,
        signal_strength=0.75,
    )

    snapshot = engine.inject_scenario(scenario)

    assert snapshot.run_mode == "mock"
    assert snapshot.transcript["latest_scenario"]["scenario_id"] == "sepolia-volatility-open-001"
    assert snapshot.transcript["axl_message_count"] == 2
    assert snapshot.proof["zero_g_storage"]["uri"].startswith("0g://storage/hivemind/")
    assert snapshot.proof["zero_g_storage"]["hash"].startswith("0x")
    assert snapshot.proof["zero_g_storage"]["readback"]["ok"] is True
    assert snapshot.proof["inft"]["status"] in {"placeholder", "active"}
    assert snapshot.proof["inft"]["local_address"].startswith("local-inft://")
    assert snapshot.proof["uniswap"]["quote"]["quoteId"] == "mock-quote-alpha-001"
    assert snapshot.proof["uniswap"]["swap_receipt"]["status"] == "placeholder"

    transcript_path = Path(str(snapshot.transcript["path"]))
    assert transcript_path.exists()
    assert transcript_path.parent.parent == tmp_path / "runs"
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "hivemind.run.transcript.v0"
    assert payload["snapshot"]["run_mode"] == "mock"


def test_engine_uses_local_axl_transcript_metrics(tmp_path: Path) -> None:
    transcript = tmp_path / "axl.jsonl"
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-a",
            target="axl-node-b",
            message_type="SCENARIO_SHOCK",
            payload={"scenario_id": "local-axl-engine"},
        ),
    )
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-b",
            target="axl-node-a",
            message_type="TRADE_INTENT",
            payload={"received_message_id": "axl-1", "decision": "hedge"},
            latency_ms=12.5,
        ),
    )
    engine = SwarmEngine(agent_count=6, seed="local-axl", axl_transcript_path=transcript)

    snapshot = engine.inject_scenario(
        Scenario(
            scenario_id="local-axl-engine",
            label="Local AXL engine",
            volatility=0.5,
            liquidity_delta=-0.1,
            sentiment=0.2,
            gas_pressure=0.2,
            signal_strength=0.6,
        )
    )

    assert snapshot.run_mode == "local_axl"
    assert snapshot.integrations.gensyn_axl["mode"] == "local_axl"
    assert snapshot.integrations.gensyn_axl["messages"] == 2
    assert snapshot.integrations.gensyn_axl["nodes_online"] == 2
    assert snapshot.integrations.gensyn_axl["last_message_type"] == "TRADE_INTENT"
    assert snapshot.transcript["axl_p50_latency_ms"] == 12.5
    assert snapshot.proof["axl"]["transcript_path"] == str(transcript)


def test_token_bucket_drain_and_refill() -> None:
    fake_now = [1000.0]
    bucket = TokenBucket(capacity=3, refill_rate=2.0, clock=lambda: fake_now[0])

    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is False
    assert bucket.remaining == 0

    fake_now[0] += 1.0  # 1 second passes -> +2 tokens
    assert bucket.try_consume() is True
    assert bucket.try_consume() is True
    assert bucket.try_consume() is False


def test_engine_falls_back_to_heuristic_when_token_bucket_empty() -> None:
    bucket = TokenBucket(capacity=2, refill_rate=0.001)
    engine = SwarmEngine(agent_count=15, seed="rate-limit", token_bucket=bucket)

    snapshot = asyncio.run(engine.run_async(ticks=1))

    assert engine.last_rate_limited_count == 8
    assert len(engine.last_rate_limited_agents) == 8
    assert engine.token_bucket_remaining == 0
    assert len(snapshot.agents) == 15
    assert snapshot.transcript["rate_limited_count"] == 8
    assert snapshot.transcript["token_bucket_capacity"] == 2


def test_engine_records_zero_rate_limited_when_bucket_has_capacity() -> None:
    engine = SwarmEngine(agent_count=8, seed="bucket-ok")

    asyncio.run(engine.run_async(ticks=1))

    assert engine.last_rate_limited_count == 0
    assert engine.last_rate_limited_agents == ()


def test_engine_reports_live_0g_mode_and_metrics() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "buy", "confidence": 0.77})}}]
    }
    inference = HybridInferenceProvider(
        real=ZeroGComputeInferenceProvider(
            api_base_url="https://fake-0g.example.com",
            bearer_token="tok-test",
            model="qwen-test",
        ),
        top_n=2,
    )
    with patch("httpx.post", return_value=mock_resp):
        engine = SwarmEngine(agent_count=3, seed="live-0g-engine", inference_provider=inference)
        snapshot = engine.inject_scenario(
            Scenario(
                scenario_id="live-0g-engine",
                label="Live 0G engine",
                volatility=0.5,
                liquidity_delta=0.1,
                sentiment=0.3,
                gas_pressure=0.2,
                signal_strength=0.6,
            )
        )

    compute = snapshot.integrations.zero_g_compute
    assert snapshot.run_mode == "live_0g"
    assert compute["evaluated_agents"] == 3
    assert compute["inference_calls"] == 2
    assert compute["real_inference_count"] == 2
    assert compute["fallback_count"] == 0
    assert compute["model_tier"] == "qwen-test"
