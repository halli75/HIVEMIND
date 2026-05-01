from __future__ import annotations

import math
from typing import Any

from .models import AgentArchetype, Scenario, clamp_unit


def choose_action(archetype: AgentArchetype, scenario: Scenario, jitter: float) -> str:
    directional_signal = scenario.sentiment * scenario.signal_strength
    liquidity_stress = max(0.0, -scenario.liquidity_delta)
    hedge_pressure = (
        scenario.volatility * archetype.hedge_bias
        + scenario.gas_pressure * 0.35
        + liquidity_stress * 0.25
    )
    lp_score = archetype.liquidity_bias * (1.0 - scenario.volatility) + scenario.liquidity_delta * 0.3
    momentum_score = archetype.momentum_bias * abs(directional_signal) + archetype.risk_appetite * 0.2

    if hedge_pressure + jitter * 0.08 > 0.78:
        return "hedge"
    if lp_score + jitter * 0.05 > 0.62:
        return "provide_liquidity"
    if momentum_score < 0.22:
        return "hold"
    if directional_signal < -0.06:
        return "sell"
    if directional_signal > 0.06:
        return "buy"
    return "hold"


def confidence_for(archetype: AgentArchetype, scenario: Scenario, jitter: float) -> float:
    signal_fit = (
        abs(scenario.sentiment) * archetype.momentum_bias
        + max(0.0, scenario.liquidity_delta) * archetype.liquidity_bias
        + scenario.volatility * archetype.hedge_bias
    )
    uncertainty = scenario.volatility * (1.0 - archetype.risk_appetite) + scenario.gas_pressure * 0.25
    return round(clamp_unit(0.42 + signal_fit * 0.34 - uncertainty * 0.18 + jitter * 0.12), 4)


def aiq_for(archetype: AgentArchetype, scenario: Scenario, confidence: float, jitter: float) -> float:
    scenario_complexity = scenario.volatility * 0.18 + abs(scenario.liquidity_delta) * 0.08
    return round(clamp_unit(archetype.aiq_base + confidence * 0.12 + scenario_complexity + jitter * 0.04), 4)


def pnl_bps_for(action: str, archetype: AgentArchetype, scenario: Scenario, jitter: float) -> float:
    directional_signal = scenario.sentiment * scenario.signal_strength
    liquidity_stress = max(0.0, -scenario.liquidity_delta)
    gas_drag = scenario.gas_pressure * 18.0
    volatility_opportunity = scenario.volatility * archetype.risk_appetite * 60.0

    if action == "buy":
        pnl = directional_signal * 150.0 + volatility_opportunity - gas_drag
    elif action == "sell":
        pnl = -directional_signal * 140.0 + volatility_opportunity * 0.72 - gas_drag
    elif action == "arb":
        spread_bps = max(0.0, scenario.volatility * 30.0 - 4.0)
        pnl = spread_bps * archetype.risk_appetite * 0.8 + volatility_opportunity * 0.5 - gas_drag * 0.6
    elif action == "front_run":
        pnl = volatility_opportunity * 0.9 + abs(directional_signal) * 60.0 - gas_drag * 1.5
    elif action == "rebalance":
        pnl = archetype.liquidity_bias * 30.0 - scenario.volatility * 20.0 - gas_drag * 0.3
    elif action == "provide_liquidity":
        pnl = scenario.liquidity_delta * 42.0 + archetype.liquidity_bias * 16.0 - scenario.volatility * 12.0
    elif action == "hedge":
        pnl = scenario.volatility * archetype.hedge_bias * 32.0 + liquidity_stress * 20.0 - gas_drag * 0.45
    elif action == "vote":
        pnl = archetype.aiq_base * 12.0 - gas_drag * 0.1
    else:  # hold
        pnl = 2.0 - scenario.volatility * 8.0 - gas_drag * 0.2

    return round(pnl + (jitter - 0.5) * 40.0, 4)


def score_for(confidence: float, pnl_bps: float, aiq: float, tier: int) -> float:
    tier_bonus = {1: 0.0, 2: 2.5, 3: 4.0}[tier]
    return round(pnl_bps * 0.20 + confidence * 22.0 + aiq * 14.0 + tier_bonus, 4)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


class ScoringEngine:
    """Computes performance metrics over an agent's simulated history.

    A history entry is a dict with at least a ``pnl_bps`` field per tick. The
    optional ``runs`` field at the top level controls how many simulation
    samples we expect when computing consistency.
    """

    TRADING_DAYS = 252

    def __init__(self, runs: int = 50) -> None:
        if runs <= 0:
            raise ValueError("runs must be positive")
        self.runs = runs

    def score(self, agent_history: list[dict[str, Any]]) -> dict[str, float]:
        returns = [float(tick.get("pnl_bps", 0.0)) for tick in agent_history]

        sharpe_ratio = self._sharpe(returns)
        max_drawdown = self._max_drawdown(returns)
        consistency = self._consistency(agent_history)

        composite = 0.5 * self._normalize_sharpe(sharpe_ratio) \
            + 0.3 * consistency \
            - 0.2 * self._normalize_drawdown(max_drawdown)
        composite_score = max(0.0, min(1.0, composite))

        return {
            "sharpe_ratio": round(sharpe_ratio, 6),
            "max_drawdown": round(max_drawdown, 6),
            "consistency": round(consistency, 6),
            "composite_score": round(composite_score, 6),
        }

    def rank(self, all_agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            all_agents,
            key=lambda a: float(a.get("composite_score", 0.0)),
            reverse=True,
        )
        return [{**agent, "rank": idx + 1} for idx, agent in enumerate(ranked)]

    def _sharpe(self, returns: list[float]) -> float:
        if not returns:
            return 0.0
        mu = _mean(returns)
        sigma = _stdev(returns)
        if sigma == 0.0:
            return 0.0
        return (mu / sigma) * math.sqrt(self.TRADING_DAYS)

    @staticmethod
    def _max_drawdown(returns: list[float]) -> float:
        if not returns:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _consistency(self, agent_history: list[dict[str, Any]]) -> float:
        if not agent_history:
            return 0.0
        run_pnls: dict[Any, float] = {}
        for tick in agent_history:
            run_id = tick.get("run_id", 0)
            run_pnls[run_id] = run_pnls.get(run_id, 0.0) + float(tick.get("pnl_bps", 0.0))
        if not run_pnls:
            return 0.0
        positive = sum(1 for v in run_pnls.values() if v > 0)
        return positive / len(run_pnls)

    @staticmethod
    def _normalize_sharpe(sharpe: float) -> float:
        # squashes (-inf, inf) into [0, 1] via logistic; sharpe of 0 => 0.5
        return 1.0 / (1.0 + math.exp(-sharpe / 4.0))

    @staticmethod
    def _normalize_drawdown(drawdown: float) -> float:
        # treat 200 bps drawdown as a "full" 1.0 penalty
        return max(0.0, min(1.0, drawdown / 200.0))
