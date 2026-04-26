import json
from pathlib import Path

from hivemind_sdk import Scenario, SwarmEngine


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
    assert snapshot.proof["inft"]["status"] == "placeholder"
    assert snapshot.proof["inft"]["local_address"].startswith("local-inft://")
    assert snapshot.proof["uniswap"]["quote"]["quoteId"] == "mock-quote-alpha-001"
    assert snapshot.proof["uniswap"]["swap_receipt"]["status"] == "placeholder"

    transcript_path = Path(str(snapshot.transcript["path"]))
    assert transcript_path.exists()
    assert transcript_path.parent.parent == tmp_path / "runs"
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "hivemind.run.transcript.v0"
    assert payload["snapshot"]["run_mode"] == "mock"
