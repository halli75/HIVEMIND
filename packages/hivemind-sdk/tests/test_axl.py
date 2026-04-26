import pytest

from hivemind_sdk import AxlMessage, append_jsonl, payload_digest, read_transcript, transcript_stats


def test_payload_digest_is_deterministic() -> None:
    first = payload_digest({"b": 2, "a": 1})
    second = payload_digest({"a": 1, "b": 2})

    assert first == second
    assert first.startswith("sha256:")


def test_axl_message_round_trips_through_jsonl(tmp_path) -> None:
    transcript = tmp_path / "axl.jsonl"
    message = AxlMessage.create(
        source_node="axl-node-a",
        target="axl-node-b",
        message_type="SCENARIO_SHOCK",
        payload={"scenario_id": "shock-001", "sequence": 1},
        timestamp="2026-04-26T12:00:00.000Z",
    )

    append_jsonl(transcript, message)
    loaded = read_transcript(transcript)

    assert loaded == (message,)


def test_read_transcript_rejects_unknown_message_type(tmp_path) -> None:
    transcript = tmp_path / "bad.jsonl"
    transcript.write_text(
        '{"id":"bad","source_node":"a","target":"b","type":"UNKNOWN","timestamp":"now","payload":{}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid AXL transcript line 1"):
        read_transcript(transcript)


def test_transcript_stats_reports_nodes_latency_and_failures(tmp_path) -> None:
    transcript = tmp_path / "stats.jsonl"
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-a",
            target="axl-node-b",
            message_type="SCENARIO_SHOCK",
            payload={"sequence": 1},
        ),
    )
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-b",
            target="axl-node-a",
            message_type="INFERENCE_RESULT",
            payload={"sequence": 1},
            latency_ms=10.0,
        ),
    )
    append_jsonl(
        transcript,
        AxlMessage.create(
            source_node="axl-node-a",
            target="broadcast",
            message_type="MARKET_SIGNAL",
            payload={"signal": "node_failure", "node_id": "axl-node-b"},
            latency_ms=30.0,
        ),
    )

    stats = transcript_stats(transcript)

    assert stats.mode == "local_axl"
    assert stats.messages == 3
    assert stats.nodes_online == 1
    assert stats.failed_nodes == ("axl-node-b",)
    assert stats.last_message_type == "MARKET_SIGNAL"
    assert stats.p50_latency_ms == 20.0
    assert stats.p95_latency_ms == 29.0
    assert stats.transcript_path == str(transcript)
