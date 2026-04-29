from __future__ import annotations

import re
from dataclasses import dataclass

from .engine import SwarmEngine
from .models import Scenario, SwarmSnapshot

_DROP_WORDS = ("drop", "crash", "down", "decline", "dump", "selloff", "sell-off", "fall", "plunge")
_RALLY_WORDS = ("rally", "rise", "pump", "surge", "spike", "rip", "moon")
_DURATION_SCALE = {
    "second": 1.0,
    "minute": 60.0,
    "hour": 3600.0,
    "day": 86400.0,
    "week": 604800.0,
}


@dataclass(frozen=True)
class ParsedPrompt:
    asset: str
    direction: int  # -1 down, 0 neutral, 1 up
    magnitude: float  # fraction (0.20 == 20%)
    duration_seconds: float
    raw: str


def _parse_prompt(prompt: str) -> ParsedPrompt:
    text = prompt.lower().strip()
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    magnitude = float(pct.group(1)) / 100.0 if pct else 0.10
    magnitude = max(0.0, min(1.0, magnitude))

    direction = 0
    if any(word in text for word in _DROP_WORDS):
        direction = -1
    elif any(word in text for word in _RALLY_WORDS):
        direction = 1

    asset_match = re.search(r"\b([A-Z]{2,6})\b", prompt)
    asset = asset_match.group(1) if asset_match else "ETH"

    duration_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?|days?|weeks?)",
        text,
    )
    if duration_match:
        amount = float(duration_match.group(1))
        unit = duration_match.group(2).rstrip("s")
        duration_seconds = amount * _DURATION_SCALE[unit]
    else:
        duration_seconds = 3600.0

    return ParsedPrompt(
        asset=asset,
        direction=direction,
        magnitude=magnitude,
        duration_seconds=duration_seconds,
        raw=prompt,
    )


def _scenario_from_prompt(parsed: ParsedPrompt) -> Scenario:
    sentiment = max(-1.0, min(1.0, parsed.direction * parsed.magnitude * 5.0))
    volatility = max(0.0, min(1.0, parsed.magnitude * 5.0))
    liquidity_delta = max(-1.0, min(1.0, parsed.direction * parsed.magnitude * 3.0))
    speed = 3600.0 / max(parsed.duration_seconds, 1.0)
    gas_pressure = max(0.0, min(1.0, 0.4 + min(speed, 1.0) * 0.4))
    signal_strength = 0.7

    label = parsed.raw.strip()
    if len(label) > 80:
        label = label[:77] + "..."

    scenario_id = (
        f"injected-{parsed.asset.lower()}-"
        f"{('drop' if parsed.direction < 0 else 'rally' if parsed.direction > 0 else 'flat')}-"
        f"{int(round(parsed.magnitude * 100)):03d}"
    )
    return Scenario(
        scenario_id=scenario_id,
        label=label or "Injected scenario",
        volatility=volatility,
        liquidity_delta=liquidity_delta,
        sentiment=sentiment,
        gas_pressure=gas_pressure,
        signal_strength=signal_strength,
    )


class ScenarioInjector:
    """Natural-language adapter for ``SwarmEngine.inject_scenario``.

    Parses simple English prompts like ``"20% ETH price drop over 4 hours"``
    into the structured :class:`Scenario` shape the engine expects, and
    forwards them to the wrapped engine.
    """

    def __init__(self, engine: SwarmEngine) -> None:
        self._engine = engine

    @property
    def engine(self) -> SwarmEngine:
        return self._engine

    def parse(self, prompt: str) -> Scenario:
        return _scenario_from_prompt(_parse_prompt(prompt))

    def inject(self, prompt: str, *, verbose: bool = True) -> SwarmSnapshot:
        scenario = self.parse(prompt)
        snapshot = self._engine.inject_scenario(scenario)
        if verbose:
            self._print(snapshot, prompt)
        return snapshot

    @staticmethod
    def _print(snapshot: SwarmSnapshot, prompt: str) -> None:
        scenario = snapshot.scenario
        print(f"\n=== ScenarioInjector: '{prompt}' ===")
        print(
            f"scenario_id={scenario.scenario_id} "
            f"sentiment={scenario.sentiment:+.2f} "
            f"volatility={scenario.volatility:.2f} "
            f"liquidity_delta={scenario.liquidity_delta:+.2f}"
        )
        print("-- Top 5 leaderboard --")
        for entry in snapshot.leaderboard[:5]:
            print(
                f"  #{entry.rank} {entry.agent_id} [{entry.archetype}] "
                f"-> {entry.action} (score={entry.score:.2f}, conf={entry.confidence:.2f})"
            )
