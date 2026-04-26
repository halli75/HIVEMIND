from __future__ import annotations

from .models import AgentArchetype

DEFAULT_ARCHETYPES: tuple[AgentArchetype, ...] = (
    AgentArchetype("momentum_hunter", 1, 0.82, 0.9, 0.28, 0.12, 0.64),
    AgentArchetype("liquidity_sentinel", 1, 0.42, 0.24, 0.9, 0.32, 0.69),
    AgentArchetype("risk_balancer", 2, 0.54, 0.46, 0.54, 0.74, 0.78),
    AgentArchetype("gas_aware_arbitrageur", 2, 0.68, 0.62, 0.48, 0.52, 0.73),
    AgentArchetype("axl_coordinator", 3, 0.36, 0.38, 0.68, 0.82, 0.86),
)


def archetype_by_name(name: str) -> AgentArchetype:
    for archetype in DEFAULT_ARCHETYPES:
        if archetype.name == name:
            return archetype
    raise KeyError(f"unknown archetype: {name}")
