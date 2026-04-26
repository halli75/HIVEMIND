import subprocess
import sys

from hivemind_sdk import transcript_stats


def test_axl_smoke_cli_exchanges_messages(tmp_path) -> None:
    transcript = tmp_path / "smoke.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hivemind_axl_node",
            "smoke",
            "--port",
            "8876",
            "--messages",
            "10",
            "--transcript",
            str(transcript),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    stats = transcript_stats(transcript)
    assert stats.messages >= 20
    assert stats.nodes_online == 2
    assert stats.last_message_type in {"TRADE_INTENT", "INFERENCE_RESULT"}


def test_axl_failure_smoke_records_failed_node(tmp_path) -> None:
    transcript = tmp_path / "failure.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hivemind_axl_node",
            "failure-smoke",
            "--port",
            "8877",
            "--transcript",
            str(transcript),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    stats = transcript_stats(transcript)
    assert stats.failed_nodes == ("axl-node-b",)
    assert stats.nodes_online == 1
