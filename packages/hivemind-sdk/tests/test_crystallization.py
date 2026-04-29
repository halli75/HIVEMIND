import asyncio
import math

from hivemind_sdk import (
    CrystallizationPipeline,
    LocalStorageUploadProvider,
    MockWeb3Provider,
    ScoringEngine,
)


def test_scoring_engine_score_known_input() -> None:
    engine = ScoringEngine()
    history = [
        {"pnl_bps": 10.0, "run_id": 0},
        {"pnl_bps": -4.0, "run_id": 0},
        {"pnl_bps": 6.0, "run_id": 0},
        {"pnl_bps": 8.0, "run_id": 1},
    ]

    result = engine.score(history)

    returns = [10.0, -4.0, 6.0, 8.0]
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    expected_sharpe = (mu / math.sqrt(var)) * math.sqrt(252)
    assert math.isclose(result["sharpe_ratio"], round(expected_sharpe, 6), rel_tol=1e-5)

    # cumulative pnl: 10, 6, 12, 20 — peak 12 then 20, drawdown is 10→6 (4 bps)
    assert result["max_drawdown"] == 4.0
    # both runs end positive (run 0 = 12, run 1 = 8) → consistency 1.0
    assert result["consistency"] == 1.0
    assert 0.0 <= result["composite_score"] <= 1.0


def test_scoring_engine_rank_orders_by_composite_descending() -> None:
    engine = ScoringEngine()
    agents = [
        {"agent_id": "low", "composite_score": 0.2},
        {"agent_id": "high", "composite_score": 0.9},
        {"agent_id": "mid", "composite_score": 0.55},
    ]

    ranked = engine.rank(agents)

    assert [a["agent_id"] for a in ranked] == ["high", "mid", "low"]
    assert [a["rank"] for a in ranked] == [1, 2, 3]


def test_crystallization_pipeline_returns_full_dict_with_mock_providers() -> None:
    pipeline = CrystallizationPipeline(
        storage_provider=LocalStorageUploadProvider(),
        web3_provider=MockWeb3Provider(),
        owner_address="0x000000000000000000000000000000000000dEaD",
    )
    winner = {
        "agent_id": "agent-7",
        "archetype": "MomentumScout",
        "tier": 1,
        "composite_score": 0.88,
        "sharpe_ratio": 2.1,
        "max_drawdown": 12.5,
        "consistency": 0.75,
    }

    result = asyncio.run(pipeline.crystallize(winner, simulation_run_id="sim-001"))

    assert set(result.keys()) >= {
        "token_id",
        "tx_hash",
        "storage_ref",
        "metadata_uri",
        "intelligence_ref",
        "owner",
        "composite_score",
        "archetype",
    }
    assert result["token_id"] == 1
    assert result["tx_hash"].startswith("0x") and len(result["tx_hash"]) == 66
    assert result["storage_ref"].startswith("mock://0g-storage/")
    assert result["metadata_uri"].startswith("data:application/json;base64,")
    assert result["intelligence_ref"] == result["storage_ref"]
    assert result["composite_score"] == 0.88
    assert result["archetype"] == "MomentumScout"
