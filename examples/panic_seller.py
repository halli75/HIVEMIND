from hivemind_sdk import AgentArchetype, SwarmEngine, ScenarioInjector


class PanicSeller(AgentArchetype):
    archetype_name = "panic_seller"

    def decide(self, market_state, memory) -> dict:
        if market_state["price_delta_pct"] < -0.05:
            return {
                "action": "sell",
                "amount": memory["portfolio"] * 0.5,
                "confidence": 0.82,
                "rationale": "panic_seller: fast drawdown, cut risk",
            }
        return {"action": "hold", "confidence": 0.55, "rationale": "panic_seller: no drawdown trigger"}

    def heuristic(self, market_state, memory) -> dict:
        if market_state["price_delta_pct"] < -0.10:
            return {
                "action": "sell",
                "amount": memory["portfolio"] * 0.3,
                "confidence": 0.74,
                "rationale": "panic_seller: heuristic drawdown trigger",
            }
        return {"action": "hold", "confidence": 0.5, "rationale": "panic_seller: hold band"}


engine = SwarmEngine(archetypes=[PanicSeller], count=100)
injector = ScenarioInjector(engine)
engine.run()
injector.inject("20% ETH price drop over 4 hours")
