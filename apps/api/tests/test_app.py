import json
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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


def test_default_app_wires_seed_replay_and_transcript_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HIVEMIND_USE_MOCK_0G", "true")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_GENSYN", "true")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_UNISWAP", "true")
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
    monkeypatch.setenv("HIVEMIND_USE_MOCK_0G", "true")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_UNISWAP", "true")
    monkeypatch.delenv("AXL_NODE_URLS", raising=False)
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


def test_default_app_requires_0g_credentials_when_live_enabled(monkeypatch) -> None:
    monkeypatch.setenv("HIVEMIND_USE_MOCK_0G", "false")
    monkeypatch.delenv("ZERO_G_COMPUTE_API_BASE_URL", raising=False)
    monkeypatch.delenv("ZERO_G_COMPUTE_BEARER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="Live 0G Compute requires"):
        create_app()


def test_default_app_reports_live_0g_run_mode(monkeypatch, tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "buy", "confidence": 0.7})}}]
    }
    monkeypatch.setenv("HIVEMIND_USE_MOCK_0G", "false")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_GENSYN", "true")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_UNISWAP", "true")
    monkeypatch.setenv("ZERO_G_COMPUTE_API_BASE_URL", "https://fake-0g.example.com")
    monkeypatch.setenv("ZERO_G_COMPUTE_BEARER_TOKEN", "tok-test")
    monkeypatch.setenv("ZERO_G_COMPUTE_TOP_N", "2")

    with patch("httpx.post", return_value=mock_resp):
        client = TestClient(
            create_app(
                seed_snapshot_dir=tmp_path / "missing-seeds",
                transcript_root=tmp_path / "runs",
            )
        )
        snapshot = client.post("/scenario", json=_scenario_payload("live-0g")).json()["snapshot"]

    compute = snapshot["integrations"]["zero_g_compute"]
    assert snapshot["run_mode"] == "live_0g"
    assert compute["mode"] == "0g_compute"
    assert compute["evaluated_agents"] == 24
    assert compute["inference_calls"] == 2
    assert compute["real_inference_count"] == 2
    assert compute["fallback_count"] == 0
    assert compute["avg_latency_ms"] is not None


def test_default_app_composes_local_axl_and_live_0g_run_mode(tmp_path: Path, monkeypatch) -> None:
    transcript = tmp_path / "axl.jsonl"
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-a",
            target="axl-node-b",
            message_type="SCENARIO_SHOCK",
            payload={"scenario_id": "api-combined"},
        ),
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "hold", "confidence": 0.8})}}]
    }
    monkeypatch.setenv("HIVEMIND_USE_MOCK_GENSYN", "false")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_0G", "false")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_UNISWAP", "true")
    monkeypatch.setenv("ZERO_G_COMPUTE_API_BASE_URL", "https://fake-0g.example.com")
    monkeypatch.setenv("ZERO_G_COMPUTE_BEARER_TOKEN", "tok-test")
    monkeypatch.setenv("ZERO_G_COMPUTE_TOP_N", "1")
    monkeypatch.delenv("AXL_NODE_URLS", raising=False)

    with patch("httpx.post", return_value=mock_resp):
        client = TestClient(
            create_app(
                seed_snapshot_dir=tmp_path / "missing-seeds",
                transcript_root=tmp_path / "runs",
                axl_transcript_path=transcript,
            )
        )
        snapshot = client.post("/scenario", json=_scenario_payload("api-combined")).json()["snapshot"]

    assert snapshot["run_mode"] == "local_axl+live_0g"
    assert snapshot["integrations"]["gensyn_axl"]["mode"] == "local_axl"
    assert snapshot["integrations"]["zero_g_compute"]["mode"] == "0g_compute"


def test_legacy_mock_inference_flag_still_enables_live_0g(monkeypatch, tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"action": "sell", "confidence": 0.6})}}]
    }
    monkeypatch.delenv("HIVEMIND_USE_MOCK_0G", raising=False)
    monkeypatch.setenv("HIVEMIND_MOCK_INFERENCE", "false")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_GENSYN", "true")
    monkeypatch.setenv("HIVEMIND_USE_MOCK_UNISWAP", "true")
    monkeypatch.setenv("ZERO_G_COMPUTE_API_BASE_URL", "https://fake-0g.example.com")
    monkeypatch.setenv("ZERO_G_COMPUTE_BEARER_TOKEN", "tok-test")
    monkeypatch.setenv("ZERO_G_COMPUTE_TOP_N", "1")

    with patch("httpx.post", return_value=mock_resp):
        client = TestClient(
            create_app(
                seed_snapshot_dir=tmp_path / "missing-seeds",
                transcript_root=tmp_path / "runs",
            )
        )

    assert client.get("/health").json()["run_mode"] == "live_0g"


def test_mint_reports_storage_unavailable_without_generic_500(monkeypatch) -> None:
    class FailedMintProcess:
        returncode = 1

        async def communicate(self):
            return (
                b"[3/4] Uploading to 0G Storage ...\n"
                b"DEPLOYER_PRIVATE_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                b"storage_unavailable: 0G Storage upload failed after 4 attempts: 503 Service Unavailable",
                b"",
            )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FailedMintProcess()

    monkeypatch.setenv("INFT_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = _client()
    response = client.post("/mint")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "storage_unavailable"
    assert "minting did not start" in detail["message"]
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in detail["output_tail"]
    assert "[REDACTED]" in detail["output_tail"]


def test_mint_reports_storage_upload_failed_for_flow_revert(monkeypatch) -> None:
    class FailedMintProcess:
        returncode = 1

        async def communicate(self):
            return (
                b"Storage upload attempt 1/8 ...\n"
                b"First selected node status : { timeout: 30000 }\n"
                b"Error: 0G Storage upload failed: Error: storage_upload_failed: "
                b"Failed to submit transaction: ProviderError: execution reverted",
                b"",
            )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FailedMintProcess()

    monkeypatch.setenv("INFT_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = _client()
    response = client.post("/mint")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["status"] == "storage_upload_failed"
    assert "storage fee transaction failed" in detail["message"]


def test_mint_success_updates_state_inft_proof(monkeypatch) -> None:
    class MintedProcess:
        returncode = 0

        async def communicate(self):
            return (
                b"Content hash (sha256): "
                b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                b"rootHash:  0xroot\n"
                b"Storage URI: 0g://storage/hivemind/0xroot\n"
                b"=== MINT COMPLETE ===\n"
                b"Token ID:  7\n"
                b"Tx:        https://chainscan-galileo.0g.ai/tx/0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
                b"Storage:   https://storagescan-galileo.0g.ai/tx/0xcccc\n",
                b"",
            )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return MintedProcess()

    contract = "0x0000000000000000000000000000000000000001"
    monkeypatch.setenv("INFT_CONTRACT_ADDRESS", contract)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = _client()
    response = client.post("/mint")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "minted"
    assert body["token_id"] == 7
    assert body["storage_uri"] == "0g://storage/hivemind/0xroot"
    assert "output" not in body
    assert "output_tail" in body
    proof = client.get("/state").json()["proof"]["inft"]
    assert proof["status"] == "minted"
    assert proof["token_id"] == 7
    assert proof["contract_address"] == contract
    assert proof["storage_uri"] == "0g://storage/hivemind/0xroot"
