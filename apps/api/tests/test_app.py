from pathlib import Path

from fastapi.testclient import TestClient

from hivemind_api import create_app
from hivemind_sdk import AxlMessage, SwarmEngine, append_jsonl


def _client() -> TestClient:
    app = create_app(engine=SwarmEngine(agent_count=8, seed="api-test"))
    return TestClient(app)


def _scenario_payload(scenario_id: str = "macro-shock") -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "label": "Macro shock",
        "volatility": 0.77,
        "liquidity_delta": -0.35,
        "sentiment": -0.48,
        "gas_pressure": 0.42,
        "signal_strength": 0.8,
    }


def test_rest_scenario_updates_state_leaderboard_and_tier_metrics() -> None:
    client = _client()

    response = client.post("/scenario", json=_scenario_payload())

    assert response.status_code == 200
    event = response.json()
    snapshot = event["snapshot"]
    assert event["type"] == "snapshot"
    assert snapshot["scenario"]["scenario_id"] == "macro-shock"
    assert len(snapshot["agents"]) == 8
    assert snapshot["integrations"]["zero_g_compute"]["mode"] == "mock"

    leaderboard = client.get("/leaderboard").json()
    assert leaderboard["sequence"] == snapshot["sequence"]
    assert leaderboard["leaderboard"][0]["rank"] == 1

    metrics = client.get("/metrics/tiers").json()
    assert sum(metric["inference_calls"] for metric in metrics["tier_metrics"]) == 8
    # Token-bucket fields surfaced for the dashboard rate-limit warning.
    assert metrics["token_bucket_capacity"] == 10
    assert metrics["token_bucket_refill_rate"] == 10.0
    assert isinstance(metrics["token_bucket_remaining"], int)
    assert 0 <= metrics["token_bucket_remaining"] <= 10
    assert metrics["rate_limited"] is False
    assert metrics["rate_limited_count"] == 0
    assert metrics["rate_limited_agents"] == []


def test_websocket_streams_initial_state_and_accepts_scenario_injection() -> None:
    client = _client()

    with client.websocket_connect("/ws/state") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "snapshot"
        assert initial["snapshot"]["scenario"]["scenario_id"] == "bootstrap-neutral"

        websocket.send_json(
            {
                "type": "inject_scenario",
                "scenario": _scenario_payload("ws-shock"),
            }
        )
        event = websocket.receive_json()

    assert event["type"] == "snapshot"
    assert event["snapshot"]["scenario"]["scenario_id"] == "ws-shock"
    assert event["snapshot"]["integrations"]["gensyn_axl"]["mode"] == "mock"


def test_health_reports_current_run_mode() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json()["mode"] == "local-mock"
    assert response.json()["run_mode"] == "mock"


def test_default_app_wires_seed_replay_and_transcript_output(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    client = TestClient(
        create_app(
            seed_snapshot_dir=root / "data" / "snapshots",
            transcript_root=tmp_path / "runs",
        )
    )

    response = client.post("/scenario", json=_scenario_payload("seeded-api-shock"))

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["run_mode"] == "mock"
    assert snapshot["transcript"]["axl_message_count"] == 2
    assert snapshot["proof"]["zero_g_storage"]["readback"]["ok"] is True
    assert snapshot["proof"]["uniswap"]["quote"]["quoteId"] == "mock-quote-alpha-001"
    assert Path(snapshot["transcript"]["path"]).exists()


def test_default_app_can_read_local_axl_transcript(tmp_path: Path, monkeypatch) -> None:
    transcript = tmp_path / "axl.jsonl"
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-a",
            target="axl-node-b",
            message_type="SCENARIO_SHOCK",
            payload={"scenario_id": "api-local-axl"},
        ),
    )
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-b",
            target="axl-node-a",
            message_type="INFERENCE_RESULT",
            payload={"decision": "rank_adjustment"},
            latency_ms=8.0,
        ),
    )
    monkeypatch.setenv("HIVEMIND_USE_MOCK_GENSYN", "false")
    client = TestClient(
        create_app(
            seed_snapshot_dir=tmp_path / "missing-seeds",
            transcript_root=tmp_path / "runs",
            axl_transcript_path=transcript,
        )
    )

    health = client.get("/health").json()
    response = client.post("/scenario", json=_scenario_payload("api-local-axl"))

    assert health["run_mode"] == "local_axl"
    snapshot = response.json()["snapshot"]
    assert snapshot["run_mode"] == "local_axl"
    assert snapshot["integrations"]["gensyn_axl"]["mode"] == "local_axl"
    assert snapshot["integrations"]["gensyn_axl"]["messages"] == 2
    assert snapshot["proof"]["axl"]["nodes_online"] == 2
