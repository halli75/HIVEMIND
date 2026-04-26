from __future__ import annotations

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
    volatility_opportunity = scenario.volatility * archetype.risk_appetite * 28.0

    if action == "buy":
        pnl = directional_signal * 85.0 + volatility_opportunity - gas_drag
    elif action == "sell":
        pnl = -directional_signal * 80.0 + volatility_opportunity * 0.72 - gas_drag
    elif action == "provide_liquidity":
        pnl = scenario.liquidity_delta * 42.0 + archetype.liquidity_bias * 16.0 - scenario.volatility * 12.0
    elif action == "hedge":
        pnl = scenario.volatility * archetype.hedge_bias * 32.0 + liquidity_stress * 20.0 - gas_drag * 0.45
    else:
        pnl = 2.0 - scenario.volatility * 8.0 - gas_drag * 0.2

    return round(pnl + (jitter - 0.5) * 8.0, 4)


def score_for(confidence: float, pnl_bps: float, aiq: float, tier: int) -> float:
    tier_bonus = {1: 0.0, 2: 2.5, 3: 4.0}[tier]
    return round(pnl_bps * 0.52 + confidence * 32.0 + aiq * 18.0 + tier_bonus, 4)
