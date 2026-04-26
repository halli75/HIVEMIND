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
